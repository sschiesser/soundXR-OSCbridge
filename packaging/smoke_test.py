"""Prove the packaged app actually works, on every platform, in CI.

Starts the built binary, waits for the page, and pushes a real OSC message
through it — catching the failures a build log never shows: a missing NiceGUI
asset, a hidden import PyInstaller dropped, or a broken entry point.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "SoundxR-OSC-Bridge"


def binary() -> Path:
    if sys.platform == "darwin":
        app = ROOT / "dist" / f"{NAME}.app" / "Contents" / "MacOS" / NAME
        if app.is_file():
            return app
    exe = ROOT / "dist" / NAME / (NAME + (".exe" if os.name == "nt" else ""))
    if not exe.is_file():
        raise SystemExit(f"packaged binary not found at {exe}")
    return exe


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> int:
    from pythonosc.dispatcher import Dispatcher
    from pythonosc.osc_server import ThreadingOSCUDPServer
    from pythonosc.udp_client import SimpleUDPClient

    ui_port, in_port, out_port = free_port(), free_port(), free_port()
    data_dir = Path(tempfile.mkdtemp(prefix="soundxr-smoke-"))

    # a mapping that turns one incoming message into a known ADM-OSC message
    project = {
        "format": "soundxr-osc-bridge", "version": 1,
        "input": {"host": "127.0.0.1", "port": in_port},
        "destinations": {"adm": {"host": "127.0.0.1", "port": out_port,
                                 "enabled": True}},
        "send_rate_hz": 100, "extra_catalogs": [],
        "routes": [{"source": "/smoke", "arg_index": 0, "name": "", "enabled": True,
                    "legs": [{"target_id": "adm.obj.xyz", "arg": "x",
                              "indices": {"obj": 1}, "source_arg": 0,
                              "in_min": 0.0, "in_max": 1.0,
                              "out_min": -1.0, "out_max": 1.0,
                              "curve": {"kind": "linear", "amount": 2.0, "points": []},
                              "invert": False, "deadzone": 0.0, "smoothing": 0.0,
                              "quantize": 0.0, "clamp_input": True, "enabled": True}]}],
    }
    preset = data_dir / "smoke.json"
    preset.write_text(json.dumps(project))

    received: list = []
    disp = Dispatcher()
    disp.set_default_handler(lambda addr, *a: received.append((addr, list(a))))
    sink = ThreadingOSCUDPServer(("127.0.0.1", out_port), disp)
    threading.Thread(target=sink.serve_forever, daemon=True).start()

    env = dict(os.environ, SOUNDXR_DATA_DIR=str(data_dir))
    proc = subprocess.Popen(
        [str(binary()), str(preset), "--port", str(ui_port),
         "--no-browser", "--start"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)

    try:
        page = ""
        for _ in range(90):
            if proc.poll() is not None:
                raise SystemExit(f"the app exited early:\n{proc.stdout.read()}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{ui_port}/",
                                            timeout=2) as r:
                    page = r.read().decode("utf-8", "replace")
                break
            except Exception:
                time.sleep(1)
        else:
            raise SystemExit("the packaged app never served its page")

        assert "Sound xR OSC Bridge" in page, "the page is not the bridge's"
        print("page served OK")

        # --start means it is already listening; push a value through the
        # mapping and require it to come out the other side
        client = SimpleUDPClient("127.0.0.1", in_port)
        for _ in range(20):
            client.send_message("/smoke", [1.0])
            time.sleep(0.05)
        time.sleep(1.5)
        assert received, "the packaged app received OSC but never sent any"
        address, args = received[-1]
        assert address == "/adm/obj/1/xyz", f"unexpected output address {address}"
        assert abs(args[0] - 1.0) < 1e-6, f"unexpected value {args}"
        print(f"OSC bridged OK: {address} {args} ({len(received)} message(s))")
        return 0
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        sink.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
