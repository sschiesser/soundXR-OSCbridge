"""Entry point: ``python -m soundxr_bridge``.

Starts the bridge's interface and opens it in the default browser. The same
address works from a tablet or another machine on the network.
"""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="soundxr_bridge",
                                 description="OSC -> Sound xR Image bridge")
    ap.add_argument("preset", nargs="?",
                    help="a preset .json to open instead of the last session")
    ap.add_argument("--port", type=int, default=8080,
                    help="port for the interface (default 8080)")
    ap.add_argument("--host", default="0.0.0.0",
                    help="interface to serve on (default: all)")
    ap.add_argument("--no-browser", action="store_true",
                    help="do not open a browser window")
    ap.add_argument("--start", action="store_true",
                    help="start listening straight away, without pressing Start")
    ap.add_argument("--headless", action="store_true",
                    help="run a preset with no interface at all")
    args = ap.parse_args(argv)

    from .project import Project

    project = Project.load(args.preset) if args.preset else None

    if args.headless:
        if not args.preset:
            ap.error("--headless needs a preset file")
        from .bridge import run_headless
        run_headless(args.preset)
        return 0

    from .webui import run
    run(port=args.port, host=args.host, show=not args.no_browser,
        project=project, start=args.start)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
