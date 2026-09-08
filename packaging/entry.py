"""Entry script for the packaged application.

Separate from main.py (which NiceGUI's test harness executes) because this one
parses the command line and needs freeze_support for the frozen build.
"""

import multiprocessing
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soundxr_bridge.__main__ import main  # noqa: E402

if __name__ == "__main__":
    multiprocessing.freeze_support()   # keep a frozen app from re-spawning itself
    sys.exit(main())
