#!/usr/bin/env bash
# Build the standalone app on macOS or Linux into dist/
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip pyinstaller
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m PyInstaller packaging/soundxr_bridge.spec --noconfirm --clean
./.venv/bin/python packaging/smoke_test.py
echo
if [ "$(uname)" = "Darwin" ]; then
  echo "Built: dist/SoundxR-OSC-Bridge.app"
  echo "To sign and notarise it, see docs/SIGNING.md then run packaging/sign_macos.sh"
else
  echo "Built: dist/SoundxR-OSC-Bridge/SoundxR-OSC-Bridge"
fi
