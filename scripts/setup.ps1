# Sets up Flow Local on this PC. Safe to run again.
#
#   .\scripts\setup.ps1                  install everything, pull the cleanup model if Ollama is present
#   .\scripts\setup.ps1 -NoCuda          skip the NVIDIA GPU libraries (detected automatically otherwise)
#   .\scripts\setup.ps1 -SkipOllama      do not touch Ollama
#   .\scripts\setup.ps1 -DownloadModel   also download the speech model now (one-time, about 1.6 GB, uses the internet)
#   .\scripts\setup.ps1 -Check           install nothing, only report what this computer has
param(
    [switch]$NoCuda,
    [switch]$SkipOllama,
    [switch]$DownloadModel,
    [switch]$Check
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Note($text) { Write-Host "   $text" }
function Fail($text) { Write-Host "`nERROR: $text" -ForegroundColor Red; exit 1 }

$venv = ".\.venv\Scripts\python.exe"

if (-not $Check) {
    Step "Python"
    $launcher = $null
    foreach ($v in "3.12", "3.11") {
        & py "-$v" --version *> $null
        if ($LASTEXITCODE -eq 0) { $launcher = "-$v"; break }
    }
    if (-not $launcher) { Fail "Python 3.11 or 3.12 was not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run this again." }
    Note "using Python $($launcher.TrimStart('-'))"
    if (-not (Test-Path $venv)) {
        Step "Creating the virtual environment (.venv)"
        & py $launcher -m venv .venv
        if ($LASTEXITCODE -ne 0) { Fail "could not create the virtual environment" }
    }

    Step "NVIDIA graphics card"
    $gpu = $false
    if (-not $NoCuda) {
        try { & nvidia-smi --query-gpu=name --format=csv, noheader 2>$null | Select-Object -First 1 | ForEach-Object { $gpu = $true; Note "found: $_" } } catch { }
    }
    if ($gpu) { $extra = ".[cuda]"; Note "installing the GPU libraries too (about 1 GB)" }
    else { $extra = "."; Note "none found (or -NoCuda): the CPU speech model will be used" }

    Step "Installing Flow Local and its dependencies (this takes a few minutes)"
    & $venv -m pip install --upgrade pip --quiet
    & $venv -m pip install -e $extra
    if ($LASTEXITCODE -ne 0) { Fail "pip could not install the dependencies. Scroll up for the reason." }
}
elseif (-not (Test-Path $venv)) {
    Fail "No .venv yet. Run .\scripts\setup.ps1 without -Check first."
}

if (-not $SkipOllama) {
    Step "Ollama (the optional local AI used for smarter cleanup and Command Mode)"
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollama) {
        $local = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
        if (Test-Path $local) { $ollama = Get-Item $local }
    }
    if (-not $ollama) {
        Note "Ollama is not installed. Dictation still works with built-in cleanup rules."
        Note "To add the smarter cleanup:  winget install Ollama.Ollama   then run this script again."
    }
    else {
        $model = (& $venv -c "from flow.hardware import detect, recommend; print(recommend(detect()).llm_model)").Trim()
        Note "recommended cleanup model for this computer: $model"
        if (-not $Check) {
            Note "downloading it with Ollama (one-time, uses the internet)..."
            & $ollama.Source pull $model
        }
    }
}

if ($DownloadModel -and -not $Check) {
    Step "Speech model (one-time download, uses the internet)"
    & $venv -c "from flow.stt.engine import SttEngine; SttEngine().load(allow_download=True); print('speech model ready')"
}

Step "What this computer looks like"
& $venv -m flow doctor

Write-Host "`nDone. Start Flow Local with:  .\.venv\Scripts\python.exe -m flow" -ForegroundColor Green
Write-Host "On first run open Settings > Models and press 'Download now' if the speech model is not downloaded yet." -ForegroundColor Green
