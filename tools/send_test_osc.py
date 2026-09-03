"""Fake OSC source, so you can try the bridge without any hardware.

Sends a slowly circling tracker position, a fader ramp and a mute toggle to the
bridge's input port.  The addresses match examples/example_tracker.json.

    python tools/send_test_osc.py --port 9000
"""

from __future__ import annotations

import argparse
import math
import time

from pythonosc.udp_client import SimpleUDPClient


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9000, help="the bridge's input port")
    ap.add_argument("--rate", type=float, default=30.0, help="messages per second")
    ap.add_argument("--radius", type=float, default=5.0, help="metres, +/- around 0")
    args = ap.parse_args()

    client = SimpleUDPClient(args.host, args.port)
    print(f"Sending to {args.host}:{args.port} at {args.rate:g} Hz — Ctrl-C to stop", flush=True)
    t0 = time.time()
    period = 1.0 / max(1.0, args.rate)
    n = 0
    try:
        while True:
            t = time.time() - t0
            client.send_message("/tracker/1/x", args.radius * math.sin(t * 0.4))
            client.send_message("/tracker/1/y", args.radius * math.cos(t * 0.4))
            client.send_message("/ctl/fader/1", 0.5 + 0.5 * math.sin(t * 0.13))
            if n % 90 == 0:
                client.send_message("/track/5/mute", int((t // 6) % 2))
            n += 1
            if n % 60 == 0:
                print(f"  t={t:6.1f}s  x={args.radius * math.sin(t * 0.4):+.2f}  "
                      f"sent={n * 3}")
            time.sleep(period)
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
