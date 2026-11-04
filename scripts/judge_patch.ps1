<#
.SYNOPSIS
  Audit every patch of a VC3D project folder and print the summary table.
.DESCRIPTION
  Uses C:\VesuviusUNET\venv\Scripts\python.exe if it exists, else the python on PATH. If the vun tools are not
  installed in that Python, installs this repository there in editable mode (pip install -e). Then runs
  vun-audit --vc3d-folder: verdict.json and verdict.txt are written INTO each patch folder (x/y/z.tif and meta.json
  are never touched) and verdict_summary.txt / .csv at the project root. Exit code: 0 all PASS, 1 any FAIL,
  4 something NOT JUDGED, 2 bad input.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\judge_patch.ps1 D:\scroll1\project -Volume D:\scroll1\vol.zarr
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\judge_patch.ps1 D:\scroll1\project --heights 2073,2600
#>
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Folder,
    [string]$Volume = "",
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Extra = @()
)
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$venvPython = "C:\VesuviusUNET\venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) { $py = $venvPython } else { $py = "python" }
$repo = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path -LiteralPath $Folder -PathType Container)) {
    Write-Host "error: folder not found: $Folder"
    exit 2
}

& $py -c "import vun_tools.cli" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "vun-audit is not installed for $py - installing $repo (pip install -e)"
    & $py -m pip install -e $repo
    if ($LASTEXITCODE -ne 0) {
        Write-Host "error: pip install -e failed"
        exit 2
    }
}

$argList = @("--vc3d-folder", $Folder)
if ($Volume -ne "") { $argList += @("--volume", $Volume) }
$argList += $Extra
& $py -c "import sys; from vun_tools.cli import audit; sys.exit(audit())" @argList
$code = $LASTEXITCODE

$summary = Join-Path $Folder "verdict_summary.txt"
if (Test-Path -LiteralPath $summary) {
    Write-Host ""
    Write-Host "Summary ($summary):"
    Get-Content -LiteralPath $summary
}
exit $code
