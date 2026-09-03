"""Fake Sound xR device: prints every OSC message it receives.

Point the bridge's output at 127.0.0.1 and run this on the same port to watch
exactly what would go to the DME.

    python tools/listen_osc.py --port 4002       # ADM-OSC
    python tools/listen_osc.py --port 50528      # native yosc
"""

from __future__ import annotations

import argparse
import time

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--quiet", action="store_true", help="only count, do not print")
    args = ap.parse_args()

    state = {"n": 0, "t": time.time()}

    def handler(address, *values):
        state["n"] += 1
        if args.quiet:
            if time.time() - state["t"] > 1.0:
                print(f"{state['n']} messages", flush=True)
                state["t"] = time.time()
            return
        pretty = " ".join(f"{v:g}" if isinstance(v, float) else str(v) for v in values)
        print(f"{address}  {pretty}", flush=True)

    disp = Dispatcher()
    disp.set_default_handler(handler)
    server = BlockingOSCUDPServer((args.host, args.port), disp)
    print(f"Listening on {args.host}:{args.port} — Ctrl-C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\nstopped after {state['n']} messages", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
