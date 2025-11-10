# Recovering Steam User Activity from Process Memory

Carve Steam artifacts (SteamID64, chat lines, URLs) from a Windows memory image, then clean results into a readable CSV.

This repo contains:

- `steam_forensics.py` - a Volatility 3 plugin that scans a memory layer for Steam artifacts

- `postprocess.py` - a small script that filters and summarizes the raw CSV

## Quick Start

1) Create a Windows 11 ARM64 VM  
2) Install Steam and log in with a test account  
3) Produce a memory dump during activity  
4) Run the Volatility plugin to generate a raw CSV  
5) Run the postprocess script to clean and summarize results

All commands below are PowerShell unless noted.

---

## Requirements

Guest VM: Windows 11 ARM64

Software inside the VM:

- Steam desktop client
- Python 3.11 ARM64
- Volatility 3
- Sysinternals Strings (64-bit)
- A memory dumper (choose one)
  - WinPMEM  
  - DumpIt  
  - Task Manager basic process dump is not sufficient for full RAM. Use a full memory acquisition tool.

Folder layout used in examples:
```
C:\Steam-Mem-Forensics\
  20_acq\
    scenarioA_friends\
      images\
      hashes\
    scenarioB_chat\
      images\
      hashes\
  30_analysis\
    scenarioA_friends\
    scenarioB_chat\
  40_plugin\
    steamcarve\
      steam_forensics.py
    postprocess.py
```

---

## Install tools

### Python and Volatility 3
```powershell
# Verify Python
python --version

# Install Volatility 3
pip install volatility3

# Confirm vol.exe is on PATH
Get-Command vol.exe
```

### Sysinternals Strings (optional but recommended)
Download Strings from Microsoft Sysinternals and place `strings64.exe` somewhere on PATH or reference it with a full path.

---

## Prepare Steam and safety

- Use a test account with no payment methods
- Disable Steam Cloud sync for consistency
- Generate realistic activity before capture
  - Scenario A: open profile and friends
  - Scenario B: send and receive chat messages with distinctive phrases
  - Scenario C: browse store and library, launch a couple of games

---

## Acquire a memory image

Use WinPMEM or DumpIt to capture a full memory image as a `.raw` or `.dmp` file. The exact tool steps vary, but the end result is a large file containing guest memory.

Move and hash the newest dump into a scenario folder:

```powershell
$root   = 'C:\Steam-Mem-Forensics'
$scen   = 'scenarioB_chat'  # change for A or C
$imgDir = Join-Path $root "20_acq\$scen\images"
$hashDir= Join-Path $root "20_acq\$scen\hashes"
New-Item -ItemType Directory -Force -Path $imgDir,$hashDir | Out-Null

# Find newest dump
$img = Get-ChildItem C:\ -Include *.dmp,*.raw -File -Recurse -ErrorAction SilentlyContinue |
       Sort-Object LastWriteTime -Descending |
       Select-Object -First 1

# Name the image for this scenario
$base = 'B0_chat_active'  # pick a name per scenario
$dst  = Join-Path $imgDir "$base$([IO.Path]::GetExtension($img.FullName))"
Move-Item -LiteralPath $img.FullName -Destination $dst -Force

# Hash the image
Get-FileHash $dst -Algorithm SHA256 | Tee-Object (Join-Path $hashDir "$base.sha256")

# Confirm size
Get-Item $dst | Select Name, Length
```

---

## Optional: produce strings dumps for quick ground truth

This step is useful to verify that useful text exists before running the plugin.

```powershell
$imgPath = 'C:\Steam-Mem-Forensics\20_acq\scenarioB_chat\images\B0_chat_active.dmp'
$outDir  = 'C:\Steam-Mem-Forensics\30_analysis\scenarioB_chat'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# ASCII strings
strings64.exe -accepteula -n 6 "$imgPath" > (Join-Path $outDir 'B0_chat_active_ascii.txt')

# UTF-16LE strings
strings64.exe -accepteula -n 6 -u "$imgPath" > (Join-Path $outDir 'B0_chat_active_unicode.txt')
```

Open the text files and spot check for Steam URLs, chat fragments, or IDs.

---

## Run the Volatility plugin

Place `steam_forensics.py` here:
```
C:\Steam-Mem-Forensics\40_plugin\steamcarve\steam_forensics.py
```

Command to run and write CSV:

```powershell
$vol     = (Get-Command vol.exe -ErrorAction Stop).Source
$plugDir = 'C:\Steam-Mem-Forensics\40_plugin'
$dmpUrl  = 'file:///C:/Steam-Mem-Forensics/20_acq/scenarioB_chat/images/B0_chat_active.dmp'
$outDir  = 'C:\Steam-Mem-Forensics\30_analysis\scenarioB_chat'
$csvName = 'personal_volatility_program_chat.csv'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

& $vol --plugin-dirs $plugDir -r csv --single-location $dmpUrl `
  steamcarve.steam_forensics.SteamCarver `
  --chunk-size 16777216 --overlap 1024 --minlen 6 --scan-unicode `
  | Out-File -FilePath (Join-Path $outDir $csvName) -Encoding utf8 -Width 4096
```

Notes
- The plugin scans the memory layer and emits rows with columns: kind, offset, preview, steamid, unix_ts, message, value
- If you see a lot of noise, raise `--minlen` to 8 or 10
- Keep `--scan-unicode` on to catch UTF-16LE remnants

---

## Clean and summarize the raw CSV

Run the postprocess script to reduce noise and create a summary.

Place `postprocess.py` here:
```
C:\Steam-Mem-Forensics\40_plugin\postprocess.py
```

Command:
```powershell
python C:\Steam-Mem-Forensics\40_plugin\postprocess.py `
  "C:\Steam-Mem-Forensics\30_analysis\scenarioB_chat\personal_volatility_program_chat.csv"
```

Outputs in the same folder:

- `personal_volatility_program_chat_clean.csv`  
  Filtered rows. Focuses on kinds url, steamid, chat. Adds ISO timestamp and domain for URLs.
- `personal_volatility_program_chat_findings.csv`  
  A small findings file with top URL domains, SteamIDs discovered, and a sample of chat lines.

Open the clean CSV in Excel or a text editor for review.

---

## Expected results

- Scenario A: profile and friend traces  
  SteamID64, vanity URLs, store URLs with app IDs
- Scenario B: chat traces  
  Message fragments with nearby 13-digit unix ms timestamps
- Scenario C: browsing and launch context  
  store.steampowered.com, steamcommunity.com, steamstatic, steamloopback URLs and assets

---

## Troubleshooting

- Volatility cannot satisfy Windows requirements on ARM64  
  The plugin uses a carving approach and does not require Windows kernel symbols. If core Windows plugins (pslist, etc.) do not work on your ARM64 dump, this plugin can still run with `--single-location` pointing at the image file. As an alternative, consider capturing on an x86_64 Windows VM for full Volatility support.

- CSV characters fail to render or save  
  Always pipe to `Out-File -Encoding utf8 -Width 4096` to avoid codepage and wrapping issues.

- Too much noise  
  Increase `--minlen` and keep `--scan-unicode` enabled. You can also restrict URL regexes or filter further in `postprocess.py`.

- Very large output  
  That is normal for a carve. Use `postprocess.py` to create a smaller, clean CSV and a short findings file.

---

## Reproduce in minutes

1) Do some activity in Steam  
   - Open profile and friends  
   - Send a few chat lines with a distinctive phrase  
   - Browse a couple of store pages

2) Capture memory with WinPMEM or DumpIt

3) Move and hash the dump into `C:\Steam-Mem-Forensics\20_acq\<scenario>\images`

4) Run the plugin command above to write `personal_volatility_program_chat.csv`

5) Run `postprocess.py` on that CSV to produce `_clean.csv` and `_findings.csv`

6) Review the clean CSV and findings file

---
