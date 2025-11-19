# Steam Activity Carver (Volatility 3)
Recover Steam user activity from a Windows memory image using a Volatility 3 plugin.  
The plugin carves:

- SteamID64 values
- Chat fragments with 13-digit Unix millisecond timestamps
- Steam and Valve related URLs (Store, Community, CDN, loopback)
    
Works with a single memory image. No Windows kernel symbols required.

---

## Repository contents
- `steam_forensics.py` — Volatility 3 plugin that scans a memory layer and emits structured rows
- `postprocess.py` (Highly recommend using in my test cases the csv was too large and wouldn't load without running the postprocess) — trims noise and produces a short findings report
    

---

## Quick start
- Install Python 3.11+ and Volatility 3
- Capture a full memory image while Steam is active
- Put `steam_forensics.py` on disk
- Run Volatility with the plugin to write a CSV
- (Optional) Run `postprocess.py` to clean and summarize

---

## Requirements
- Python 3.11 or newer
- Volatility 3
```powershell
    pip install volatility3
```
- A Windows memory image created with DumpIt or WinPMEM  
    Example: `C:\evidence\image.dmp`
- Optional: Sysinternals `strings64.exe` for quick spot checks
    

No symbols are needed. The plugin carves printable strings and classifies hits.

---

## Install Volatility 3
```powershell
python --version pip install --upgrade pip pip install volatility3  
# confirm vol.exe is on PATH 
Get-Command vol.exe`
```

---

## Place the plugin
Put the files in any folder, for example:
`C:\tools\steamcarve\steam_forensics.py & postprocess.py`

---

## Acquire a memory image
Generate realistic Steam activity before capture:
- Open profile and friends
- Send a few chat lines with a distinctive phrase
- Browse Store or Community
- Optionally launch a game

Create the image with DumpIt or WinPMEM. Example output: `C:\evidence\image.dmp`

Optional integrity check:
`Get-FileHash C:\evidence\image.dmp -Algorithm SHA256`

---

## Run the plugin and write CSV
Use UTF-8 and let Volatility’s CSV renderer write directly to a file.

```powershell 
# UTF-8 
chcp 65001 > $null 
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONIOENCODING = 'utf-8'  

# Paths 
$vol = (Get-Command vol.exe -ErrorAction Stop).Source 
$plugDir = 'C:\tools\steamcarve'               

# folder that contains steam_forensics.py 
$dmpUri  = 'file:///C:/evidence/image.dmp'     
# use file:/// and forward slashes 
$outDir  = 'C:\evidence' $fname   = 'steam_activity_raw.csv'  
# Run plugin. CSV renderer writes directly to a file. 
& $vol -q --plugin-dirs $plugDir --single-location $dmpUri ` -r csv -o $outDir -f $fname `steamcarve.steam_forensics.SteamCarver ` --chunk-size 33554432 --overlap 512 --minlen 12 --scan-unicode False  Get-Item (Join-Path $outDir $fname) | Select Name,Length,LastWriteTime
```

This creates `C:\evidence\steam_activity_raw.csv`.

If you prefer stdout capture, omit `-o` and `-f` and pipe to:

`| Out-File -FilePath C:\evidence\steam_activity_raw.csv -Encoding utf8 -Width 4096`

---

## CSV columns
- `kind` - url, steamid, chat, or string
- `offset` — virtual offset in the memory layer
- `preview` — short human readable snippet
- `steamid` — SteamID64 if present
- `unix_ts` — 13-digit Unix time in milliseconds if present
- `message` — chat message fragment if matched
- `value` — exact URL for `kind=url`

---

## Tuning for speed and signal
Start fast, then increase coverage if needed.
- `--chunk-size` controls bytes per read. Larger is faster. Try 32 MiB or 64 MiB.
- `--overlap` keeps cross-boundary strings. 256 to 1024 works well.
- `--minlen` reduces noise. Raising to 12 or 16 speeds up runs.
- `--scan-unicode` toggles UTF-16LE scanning. False is faster. True improves coverage.

Presets:

- Faster runs:
    `--chunk-size 33554432 --overlap 512 --minlen 12 --scan-unicode False`
    
- Deeper coverage:
    `--chunk-size 16777216 --overlap 1024 --minlen 6 --scan-unicode True`
    
---

## Optional cleaning and summary
`postprocess.py` trims noise and generates a short report.

`python C:\tools\steamcarve\postprocess.py C:\evidence\steam_activity_raw.csv`

Outputs next to the input CSV:
- `steam_activity_raw_clean.csv` — filtered rows with ISO timestamps and URL domains
- `steam_activity_raw_findings.csv` — top URL domains, SteamIDs found, and a sample of chat lines
    

---

## Example end to end
```powershell
# 1) Run the plugin 
& $vol -q --plugin-dirs C:\tools\steamcarve --single-location file:///C:/evidence/image.dmp ` -r csv -o C:\evidence -f steam_activity_raw.csv ` steamcarve.steam_forensics.SteamCarver ` --chunk-size 33554432 --overlap 512 --minlen 12 --scan-unicode False  
# 2) Clean and summarize 
python C:\tools\steamcarve\postprocess.py C:\evidence\steam_activity_raw.csv
```

Open `steam_activity_raw_clean.csv` and `steam_activity_raw_findings.csv`.

---

## Troubleshooting
Printed to console instead of a file  
Use `-r csv -o <dir> -f <name>` with no pipe. The renderer writes the file directly.

Encoding errors  
Keep the UTF-8 setup lines. Avoid `Out-File` unless you must pipe.

Slow runs  
Increase `--minlen`, set `--scan-unicode False`, and try a larger `--chunk-size`.

ARM64 Windows plugins fail  
This plugin does not rely on symbols. It works with `--single-location` on the image.

---

## License and attribution
Own the rights to your code and capture your own test data.  
Respect privacy and legal constraints in your jurisdiction.