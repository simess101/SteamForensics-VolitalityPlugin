from __future__ import annotations

import re
from typing import Iterable, Iterator, Tuple, Optional, List

from volatility3.framework import interfaces, exceptions, renderers
from volatility3.framework.configuration import requirements
from volatility3.framework.renderers import format_hints


# ---------- Helpers ----------

_ASCII_RE_TEMPLATE = rb"[ -~]{%d,}"
_UTF16LE_RE_TEMPLATE = rb"(?:[ -~]\x00){%d,}"

STEAMID_RE = re.compile(rb"(?P<steamid>7656119\d{10})")
UNIX13_RE = re.compile(rb"(?P<ts>\d{13})")
MSG_LINE_RE = re.compile(
    rb'(?P<msg>(?:"message"\s*:\s*"[^"]+"|A_TAG_\d{3,}[^"\r\n]*|im\s+going\s+to\s+use[^"\r\n]*))',
    re.IGNORECASE,
)
URL_RE = re.compile(
    rb"https?://(?:steamcommunity|steampowered|store\.steampowered|help\.steampowered|"
    rb"shared\.steamstatic|avatars\.steamstatic|steamcdn|steamuserimages|"
    rb"ext2-par1\.steamserver|steambroadcast|steamloopback)[^\s\"']+",
    re.IGNORECASE,
)


def iter_strings(buf: bytes, minlen: int, scan_unicode: bool) -> Iterable[Tuple[int, bytes]]:
    ascii_re = re.compile(_ASCII_RE_TEMPLATE % minlen)
    for m in ascii_re.finditer(buf):
        yield m.start(), m.group(0)
    if scan_unicode:
        u16 = re.compile(_UTF16LE_RE_TEMPLATE % minlen)
        for m in u16.finditer(buf):
            yield m.start(), m.group(0)


def maybe_decode(s: bytes) -> str:
    for enc in ("utf-16-le", "utf-8", "latin-1"):
        try:
            t = s.decode(enc, errors="ignore")
            return " ".join(t.replace("\x00", "").split())
        except Exception:
            continue
    return ""


def first_group(pattern: re.Pattern, data: bytes, name: str) -> Optional[str]:
    m = pattern.search(data)
    if not m:
        return None
    g = m.groupdict().get(name)
    if not g:
        return None
    try:
        return g.decode("ascii", "ignore")
    except Exception:
        return g.decode("latin-1", "ignore")


def int_unix_ms(data: bytes) -> Optional[int]:
    m = UNIX13_RE.search(data)
    if not m:
        return None
    try:
        return int(m.group("ts"))
    except Exception:
        return None


def match_kind(data: bytes) -> str:
    if URL_RE.search(data):
        return "url"
    if STEAMID_RE.search(data):
        return "steamid"
    if MSG_LINE_RE.search(data):
        return "chat"
    return "string"


class SteamCarver(interfaces.plugins.PluginInterface):
    """Carves Steam-related remnants (SteamIDs, chat lines, URLs) from memory."""

    _required_framework_version = (2, 26, 0)

    @classmethod
    def get_requirements(cls):
        # Use a translation-layer requirement so --single-location works with automagic
        return [
            requirements.TranslationLayerRequirement(
                name="primary",
                description="Memory layer to scan",
            ),
            requirements.IntRequirement(
                name="chunk_size",
                description="Read size per iteration (bytes)",
                default=16 * 1024 * 1024,
                optional=True,
            ),
            requirements.IntRequirement(
                name="overlap",
                description="Overlap between consecutive chunks (bytes)",
                default=1024,
                optional=True,
            ),
            requirements.IntRequirement(
                name="minlen",
                description="Minimum printable length for carving",
                default=6,
                optional=True,
            ),
            requirements.BooleanRequirement(
                name="scan_unicode",
                description="Also carve UTF-16LE strings",
                default=True,
                optional=True,
            ),
        ]

    def _columns(self) -> List[Tuple[str, type]]:
        # Column names and their renderer types
        return [
            ("kind",    str),
            ("offset",  format_hints.Hex),
            ("preview", str),
            ("steamid", str),
            ("unix_ts", int),
            ("message", str),
            ("value",   str),
        ]

    @staticmethod
    def _layer_read_chunks(
        layer: interfaces.layers.DataLayerInterface,
        chunk_size: int,
        overlap: int,
    ) -> Iterator[Tuple[int, bytes]]:
        """
        Iterate virtual ranges of `layer` in a version-agnostic way.
        Supports mapping() tuples shaped like:
          - (virt_start, virt_end, ...)
          - (virt_start, mapped_offset, length, ...)
          - (virt_start, length)
          - (virt_start, virt_end)
        """
        for tpl in layer.mapping(0, layer.maximum_address, ignore_errors=True):
            t = tuple(tpl)
            virt_start = t[0]

            virt_end = None
            if len(t) >= 2:
                second = t[1]
                # if second is an end (>= start), use it
                if isinstance(second, int) and second >= virt_start:
                    virt_end = second
                # else if there's a length in third slot, use it
                elif len(t) >= 3 and isinstance(t[2], int) and t[2] > 0:
                    virt_end = virt_start + t[2]

            if virt_end is None:
                virt_end = min(virt_start + chunk_size, layer.maximum_address)

            cursor = virt_start
            step = max(1, chunk_size - overlap)

            while cursor < virt_end:
                read_len = min(chunk_size, virt_end - cursor)
                try:
                    data = layer.read(cursor, read_len, pad=True)
                except exceptions.InvalidAddressException:
                    cursor += step
                    continue

                yield cursor, data
                cursor += step

    def _generator(self):
        # Resolve a layer to scan
        layer_name = self.config.get("primary", None)
        if not layer_name:
            try:
                layer_name = next(iter(self.context.layers))
            except StopIteration:
                raise exceptions.LayerException("No layers available to scan")

        layer = self.context.layers[layer_name]

        # Pull + clamp user options (since IntRequirement min/max aren't used here)
        chunk_size = int(self.config.get("chunk_size", 16 * 1024 * 1024))
        overlap    = int(self.config.get("overlap", 1024))
        minlen     = int(self.config.get("minlen", 6))
        scan_uni   = bool(self.config.get("scan_unicode", True))

        if chunk_size < 1024:
            chunk_size = 1024
        if overlap < 0:
            overlap = 0
        if overlap >= chunk_size:
            overlap = max(0, chunk_size // 2)
        if minlen < 3:
            minlen = 3
        if minlen > 4096:
            minlen = 4096

        # Emit rows
        for base, buf in self._layer_read_chunks(layer, chunk_size, overlap):
            for rel_off, match_bytes in iter_strings(buf, minlen=minlen, scan_unicode=scan_uni):
                abs_off = int(base + rel_off)
                knd = match_kind(match_bytes)

                sid = first_group(STEAMID_RE, match_bytes, "steamid") or ""
                ts  = int_unix_ms(match_bytes) or 0
                msg = first_group(MSG_LINE_RE, match_bytes, "msg") or ""

                val = ""
                if knd == "url":
                    um = URL_RE.search(match_bytes)
                    if um:
                        try:
                            val = um.group(0).decode("utf-8", "ignore")
                        except Exception:
                            val = um.group(0).decode("latin-1", "ignore")

                preview = maybe_decode(match_bytes)[:200]
                yield (0, [knd, format_hints.Hex(abs_off), preview, sid, ts, msg, val])

    def run(self):
        # Build and return the TreeGrid so renderers (including CSV) can consume it
        return renderers.TreeGrid(self._columns(), self._generator())
