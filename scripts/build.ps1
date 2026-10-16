# Build the portable Flow Local folder: dist\FlowLocal\FlowLocal.exe
# Usage:  .\scripts\build.ps1            (includes CUDA libraries, about 3 GB)
#         .\scripts\build.ps1 -NoCuda    (CPU-only, much smaller)
param([switch]$NoCuda)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$py = ".\.venv\Scripts\python.exe"

if ($NoCuda) { $env:FLOW_NO_CUDA = "1" } else { Remove-Item Env:FLOW_NO_CUDA -ErrorAction SilentlyContinue }

& $py packaging\make_icon.py
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }
& $py -m PyInstaller --noconfirm --clean packaging\flow_local.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$size = (Get-ChildItem dist\FlowLocal -Recurse | Measure-Object Length -Sum).Sum / 1MB
"Built dist\FlowLocal\FlowLocal.exe ({0:N0} MB). Run dist\FlowLocal\flow-cli.exe doctor to check it." -f $size
