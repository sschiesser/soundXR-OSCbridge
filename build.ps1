# Build the standalone Windows application into dist\SoundxR-OSC-Bridge\
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
if (-not (Test-Path ".venv")) { throw "Run .\setup.ps1 first." }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pyinstaller
& $py -m PyInstaller packaging\soundxr_bridge.spec --noconfirm --clean
Write-Host ""
Write-Host "Built: dist\SoundxR-OSC-Bridge\SoundxR-OSC-Bridge.exe"
Write-Host "Copy the whole dist\SoundxR-OSC-Bridge folder to run it on another PC."
