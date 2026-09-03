"""Entry point: ``python -m soundxr_bridge`` (GUI) or ``--headless project.json``."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="soundxr_bridge",
                                 description="OSC -> Sound xR Image bridge")
    ap.add_argument("project", nargs="?", help="project .json to open")
    ap.add_argument("--headless", action="store_true",
                    help="run a saved project without the GUI")
    ap.add_argument("--catalog", help="extra target catalogue .json to merge")
    ap.add_argument("--port", type=int, help="override the input port")
    args = ap.parse_args(argv)

    from .catalog import Catalog
    from .project import Project

    project = Project.load(args.project) if args.project else Project()
    if args.port:
        project.input_port = args.port

    if args.headless:
        if not args.project:
            ap.error("--headless needs a project file")
        from .bridge import run_headless
        run_headless(args.project)
        return 0

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 is not installed.  pip install PySide6 python-osc\n"
              "(or run with --headless to use a saved project without a GUI)")
        return 1

    catalog = Catalog.load()
    if args.catalog:
        catalog.merge(Catalog.load(args.catalog))

    from .gui.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName("Sound xR OSC Bridge")
    win = MainWindow(project, catalog)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
