import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# presets must never touch the developer's real folder during tests
os.environ.setdefault("SOUNDXR_DATA_DIR", tempfile.mkdtemp(prefix="soundxr-tests-"))

pytest_plugins = ["nicegui.testing.user_plugin"]   # user fixture only; no selenium
