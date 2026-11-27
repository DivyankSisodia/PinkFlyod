# One-time setup on Windows: Python environment, frontend build, tool checks.
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd was not found. $hint" }
}
Need python "Install Python 3.11 or newer from python.org (tick 'Add to PATH')."
Need node "Install Node.js 18 or newer from nodejs.org."
Need ffmpeg "Install FFmpeg: winget install Gyan.FFmpeg"
Need ffprobe "Install FFmpeg (includes ffprobe): winget install Gyan.FFmpeg"

$ver = python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$ver -lt [version]"3.11") { throw "Python $ver found; Shorts Studio needs 3.11 or newer." }

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv"
    python -m venv .venv
}
Write-Host "Installing the backend"
& .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .venv\Scripts\python.exe -m pip install --quiet -e ".[dev]"

Write-Host "Building the frontend"
Push-Location frontend
npm ci --no-fund --no-audit
npm run build
Pop-Location

Write-Host ""
Write-Host "Done. Start Shorts Studio with:"
Write-Host "  .venv\Scripts\python -m shorts_studio"
