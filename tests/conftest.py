import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Without pytest-asyncio, NiceGUI's async `user` fixture is never awaited and
# every page test dies with a bare AssertionError out of pytest's own fixture
# code — ten failures that say nothing about the cause. Say it once instead.
_asyncio = importlib.util.find_spec("pytest_asyncio")
if _asyncio is None or _asyncio.loader is None:   # missing, or an empty leftover
    pytest.exit("pytest-asyncio is not installed — the page tests need it.\n"
                "    pip install -r requirements-dev.txt", returncode=4)

# presets must never touch the developer's real folder during tests
os.environ.setdefault("SOUNDXR_DATA_DIR", tempfile.mkdtemp(prefix="soundxr-tests-"))

pytest_plugins = ["nicegui.testing.user_plugin"]   # user fixture only; no selenium
