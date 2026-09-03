# Creates .venv next to this file and installs everything the bridge needs.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (Test-Path ".venv") {
    Write-Host "Using the existing .venv"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    Write-Host "Creating .venv with the Python launcher..."
    & py -3 -m venv .venv
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    Write-Host "Creating .venv with python..."
    & python -m venv .venv
} else {
    throw "No Python found. Install Python 3.10+ from python.org (tick 'Add to PATH') and run this again."
}

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $py -c "import sys; assert sys.version_info >= (3,10), f'Python 3.10+ required, this venv is {sys.version.split()[0]}'"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt
& $py -m pip install -r requirements-dev.txt
Write-Host ""
Write-Host "Running the test suite..."
& $py -m pytest tests -q
Write-Host ""
Write-Host "Done. Press F5 in VS Code, or run:  .\.venv\Scripts\python.exe -m soundxr_bridge"
