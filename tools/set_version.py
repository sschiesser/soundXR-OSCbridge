"""Set — or check — the one version number the project has.

    python tools/set_version.py 1.1.0        # write it
    python tools/set_version.py --check 1.1.0

soundxr_bridge/__init__.py holds the only literal: pyproject.toml reads it
through setuptools' dynamic version, and the PyInstaller spec imports it, so
the app header, the wheel and the macOS bundle version can never drift apart.

CI runs this on a tag push so a release binary always reports the tag it was
built from, even when the bump was forgotten before tagging.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

INIT = Path(__file__).resolve().parents[1] / "soundxr_bridge" / "__init__.py"
PATTERN = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)
# not full semver: a release candidate or a date-stamped build is fine too
VALID = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+([-.+][0-9A-Za-z.-]+)?$")


def current() -> str:
    match = PATTERN.search(INIT.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"no __version__ line found in {INIT}")
    return match.group(1)


def write(version: str) -> None:
    text = INIT.read_text(encoding="utf-8")
    INIT.write_text(PATTERN.sub(f'__version__ = "{version}"', text, count=1),
                    encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="set the project version")
    ap.add_argument("version", nargs="?", help="e.g. 1.1.0 (a leading v is dropped)")
    ap.add_argument("--check", metavar="VERSION",
                    help="exit non-zero unless the project already says this")
    args = ap.parse_args(argv)

    if args.check:
        wanted = args.check.lstrip("vV")
        have = current()
        if have != wanted:
            print(f"version mismatch: the tag says {wanted}, "
                  f"soundxr_bridge/__init__.py says {have}", file=sys.stderr)
            return 1
        print(f"version {have} matches")
        return 0

    if not args.version:
        print(current())
        return 0

    version = args.version.lstrip("vV")
    if not VALID.match(version):
        print(f"'{version}' does not look like a version number", file=sys.stderr)
        return 2
    write(version)
    print(f"version set to {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
