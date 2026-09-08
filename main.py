"""Entry point for the packaged application and for NiceGUI's tooling."""

from soundxr_bridge.webui.app import run

if __name__ in {"__main__", "__mp_main__"}:
    run()
