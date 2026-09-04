"""Entry point for the packaged application (PyInstaller builds this file)."""

from soundxr_bridge.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
