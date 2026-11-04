# Windows: judge a VC3D project folder in three steps

You need Windows 10/11 and Python 3.10 or newer (3.12 is what CI uses). Nothing here needs a GPU.

1. **Make the Python environment (once).** In PowerShell:

       py -3.12 -m venv C:\VesuviusUNET\venv

   (If you skip this, `scripts\judge_patch.ps1` falls back to the `python` on your PATH.)
2. **Get the repository (once).** `git clone https://github.com/pwrobinson70-netizen/vesuviusunet-pherc0139` and open that
   folder. You do not have to install anything by hand: the script runs `pip install -e` itself the first time
   it finds `vun-audit` missing.
3. **Judge a project.** Point the script at the VC3D project folder (the one that holds the `*.tifxyz` patch folders):

       powershell -ExecutionPolicy Bypass -File scripts\judge_patch.ps1 D:\scroll1\project -Volume D:\scroll1\volume.zarr

   `-Volume` is optional if the patches' `meta.json` name a volume or `project\volumes\` holds exactly one.
   Any other `vun-audit` flag can follow, e.g. `--heights 2073,2600 --umbilicus D:\scroll1\umbilicus.json`.
   For a folder of PNG slices add `--png-pixel-um` (see `tools/trace_auditor/README.md`).

What you get: `verdict.json` and `verdict.txt` inside every patch folder, and `verdict_summary.txt` / `verdict_summary.csv`
in the project folder; the script also prints the table. Re-running overwrites only those files; `x.tif`, `y.tif`, `z.tif`,
`mask.tif` and `meta.json` are never modified. Exit code: 0 all PASS, 1 any FAIL, 4 something NOT JUDGED, 2 bad input.

Notes: the script is CRLF with a UTF-8 BOM (Windows PowerShell 5.1 needs the BOM to read it as UTF-8). CI parses it with
PowerShell on `windows-latest`. Paths with spaces are fine; give them to the script in quotes.
