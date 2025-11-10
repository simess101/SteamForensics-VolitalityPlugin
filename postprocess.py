import sys, re, csv, pathlib
from datetime import datetime, timezone

csv.field_size_limit(10_000_000)

def ts_iso(ms: str) -> str:
    try:
        v = int(ms)
        if v <= 0: return ""
        return datetime.fromtimestamp(v/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except:
        return ""

def hex_off(v: str) -> str:
    try:
        if isinstance(v, str) and v.startswith("0x"): return v
        return f"0x{int(v):X}"
    except:
        return v or ""

DOM_RE = re.compile(r"^https?://([^/]+)")

def domain_of(url: str) -> str:
    if not url: return ""
    m = DOM_RE.match(url.strip())
    return m.group(1).lower() if m else ""

def main(src_path: str):
    src = pathlib.Path(src_path).resolve()
    dst_clean = src.with_name(src.stem + "_clean.csv")
    dst_find  = src.with_name(src.stem + "_findings.csv")

    keep_kinds = {"url", "steamid", "chat"}
    seen = set()
    cleaned_rows = []

    with src.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        # normalize fieldnames
        fields = [c.strip() for c in r.fieldnames or []]
        for row in r:
            row = {k.strip(): (row.get(k,"") or "") for k in fields}
            kind     = row.get("kind","").strip().lower()
            preview  = row.get("preview","")
            message  = row.get("message","")
            value    = row.get("value","")
            steamid  = row.get("steamid","")
            unix_ts  = row.get("unix_ts","")
            offset   = row.get("offset","")

            if kind not in keep_kinds:
                continue
            if not message and not value:
                # no payload => drop
                if len(preview) < 8:
                    continue
            # normalize + enrich
            row["timestamp"] = ts_iso(unix_ts)
            row["offset"]    = hex_off(offset)
            if kind == "url":
                row["domain"] = domain_of(value)
            else:
                row["domain"] = ""

            # de-dup key (kind-specific payload)
            key = f"{kind}|{steamid}|{message}|{value}"
            if key in seen:
                continue
            seen.add(key)
            cleaned_rows.append(row)

    # sort by time then kind
    def sort_key(r):
        return (r.get("timestamp",""), r.get("kind",""), r.get("offset",""))
    cleaned_rows.sort(key=sort_key)

    # write clean csv
    out_fields = ["kind","timestamp","unix_ts","offset","steamid","message","value","preview","domain"]
    with dst_clean.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        for row in cleaned_rows:
            w.writerow(row)

    # findings: top domains, steamids, sample chats
    domain_counts = {}
    steamids = {}
    chats = []

    for r in cleaned_rows:
        if r["kind"] == "url" and r["domain"]:
            domain_counts[r["domain"]] = domain_counts.get(r["domain"], 0) + 1
        if r["kind"] == "steamid" and r.get("steamid"):
            steamids.setdefault(r["steamid"], {"first_seen": r["timestamp"], "offset": r["offset"]})
        if r["kind"] == "chat" and r.get("message"):
            chats.append({"timestamp": r["timestamp"], "message": r["message"], "offset": r["offset"]})

    top_domains = sorted(domain_counts.items(), key=lambda kv: kv[1], reverse=True)[:25]
    steamid_rows = [{"steamid": sid, "first_seen": meta["first_seen"], "offset": meta["offset"]}
                    for sid, meta in steamids.items()]
    steamid_rows.sort(key=lambda r: (r["first_seen"] or "", r["steamid"]))
    chats = sorted(chats, key=lambda r: (r["timestamp"] or "", r["offset"]))[:100]

    with dst_find.open("w", encoding="utf-8", newline="") as f:
        f.write("# Summary (top findings)\n\n")
        # Top domains
        f.write("## Top URL domains\n")
        w = csv.writer(f)
        w.writerow(["domain","url_count"])
        for d,c in top_domains:
            w.writerow([d,c])
        f.write("\n## SteamIDs found\n")
        w.writerow(["steamid","first_seen","offset"])
        for row in steamid_rows:
            w.writerow([row["steamid"], row["first_seen"], row["offset"]])
        f.write("\n## Sample chat lines (up to 100)\n")
        w.writerow(["timestamp","message","offset"])
        for row in chats:
            w.writerow([row["timestamp"], row["message"], row["offset"]])

    print("Wrote:", dst_clean)
    print("Wrote:", dst_find)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python postprocess.py <path_to_csv>")
        sys.exit(2)
    main(sys.argv[1])
