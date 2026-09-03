#!/usr/bin/env bash
# macOS / Linux equivalent of setup.ps1
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
./.venv/bin/python -m pytest tests -q
echo "Done.  ./.venv/bin/python -m soundxr_bridge"
