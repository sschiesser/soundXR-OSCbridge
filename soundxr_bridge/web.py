"""Browser remote: a small HTTP server exposing the bridge over JSON.

Any device with a browser — iPad, Android tablet, phone, another laptop — can
open it and watch the discovered traffic, edit the mappings and start or stop
the bridge.  No dependencies beyond the standard library, and the page is
served from memory so it works with no internet connection.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import __version__
from .catalog import Catalog
from .mapping import Curve, Leg, Route
from .web_ui import PAGE


class Controller:
    """All mutations the remote can perform, guarded by one lock.

    The desktop window and the browser can both be open at once; every change
    bumps ``revision`` so the GUI knows to rebuild its tree.
    """

    def __init__(self, bridge, log_size: int = 200):
        self.bridge = bridge
        self.lock = threading.RLock()
        self.revision = 0
        self.log: deque[str] = deque(maxlen=log_size)

    # -- helpers ---------------------------------------------------------
    @property
    def catalog(self) -> Catalog:
        return self.bridge.catalog

    def note(self, text: str) -> None:
        self.log.append(text)

    def touch(self) -> None:
        self.revision += 1

    def _route(self, index: int) -> Route:
        return self.bridge.engine.routes[index]

    # -- state -----------------------------------------------------------
    def state(self) -> dict:
        with self.lock:
            b = self.bridge
            discovery = []
            for d in b.discovery.snapshot():
                discovery.append({
                    "address": d.address,
                    "types": d.arg_types,
                    "rate": round(d.rate_hz, 1),
                    "count": d.count,
                    "last": [round(v, 4) if isinstance(v, float) else v
                             for v in d.last_args],
                    "ranges": [[mn, mx] if mn is not None else None
                               for mn, mx in zip(d.mins, d.maxs)],
                    "sources": sorted(d.sources),
                })
            routes = []
            for ri, r in enumerate(b.engine.routes):
                legs = []
                for li, leg in enumerate(r.legs):
                    target = self.catalog.targets.get(leg.target_id)
                    legs.append({
                        "index": li,
                        "target_id": leg.target_id,
                        "target_label": target.label if target else "(missing)",
                        "protocol": target.protocol if target else "?",
                        "address": target.format_address(leg.indices) if target else "",
                        "arg": leg.arg,
                        "args": [a.name for a in target.args] if target else [],
                        "indices": dict(leg.indices),
                        "index_specs": [{"name": i.name, "label": i.label,
                                         "min": i.min, "max": i.max}
                                        for i in target.indices] if target else [],
                        "source_arg": leg.source_arg,
                        "in_min": leg.in_min, "in_max": leg.in_max,
                        "out_min": leg.out_min, "out_max": leg.out_max,
                        "curve": leg.curve.kind, "amount": leg.curve.amount,
                        "invert": leg.invert, "smoothing": leg.smoothing,
                        "deadzone": leg.deadzone, "quantize": leg.quantize,
                        "enabled": leg.enabled,
                    })
                routes.append({"index": ri, "source": r.source, "name": r.name,
                               "arg_index": r.arg_index, "enabled": r.enabled,
                               "legs": legs})
            targets = [{"id": t.id, "label": t.label, "group": t.group,
                        "protocol": t.protocol, "address": t.address,
                        "verified": t.verified}
                       for t in sorted(self.catalog.targets.values(),
                                       key=lambda t: (t.group, t.label))]
            return {
                "version": __version__,
                "revision": self.revision,
                "running": b.receiver.running,
                "input": {"host": b.project.input_host, "port": b.project.input_port},
                "destinations": b.sender.to_dict(),
                "counters": {"in": b.discovery.total_messages,
                             "out": b.sender.sent,
                             "skipped": dict(b.sender.skipped)},
                "discovery": discovery,
                "routes": routes,
                "targets": targets,
                "log": list(self.log)[-40:],
            }

    # -- commands --------------------------------------------------------
    def command(self, cmd: str, data: dict) -> dict:
        with self.lock:
            handler = getattr(self, f"_cmd_{cmd}", None)
            if handler is None:
                return {"ok": False, "error": f"unknown command {cmd!r}"}
            result = handler(data) or {}
            self.touch()
            return {"ok": True, **result}

    def _cmd_start(self, data: dict) -> dict:
        host, port = self.bridge.project.input_host, self.bridge.project.input_port
        try:
            self.bridge.start()
        except OSError as exc:
            self.note(f"cannot listen on {host}:{port} - {exc}")
            raise RuntimeError(
                f"Cannot listen on {host}:{port} - {exc}. "
                f"Another program is probably using that port.") from exc
        self.note(f"started on {host}:{port}")
        return {}

    def _cmd_stop(self, data: dict) -> dict:
        self.bridge.stop()
        self.note("stopped")
        return {}

    def _cmd_set_input(self, data: dict) -> dict:
        p = self.bridge.project
        p.input_host = str(data.get("host", p.input_host)) or "0.0.0.0"
        p.input_port = int(data.get("port", p.input_port))
        if self.bridge.receiver.running:
            self.bridge.receiver.restart(p.input_host, p.input_port)
        self.note(f"input -> {p.input_host}:{p.input_port}")
        return {}

    def _cmd_set_dest(self, data: dict) -> dict:
        proto = data["protocol"]
        d = self.bridge.project.destinations.setdefault(proto, {})
        d["host"] = str(data.get("host", d.get("host", "127.0.0.1")))
        d["port"] = int(data.get("port", d.get("port", 4002)))
        d["enabled"] = bool(data.get("enabled", d.get("enabled", True)))
        self.bridge.sender.load_dict(self.bridge.project.destinations)
        self.note(f"{proto} -> {d['host']}:{d['port']} "
                  f"({'on' if d['enabled'] else 'off'})")
        return {}

    def _cmd_add_route(self, data: dict) -> dict:
        address = data["address"]
        info = self.bridge.discovery.get(address)
        route = Route(source=address, arg_index=0)
        numeric = [n for n, a in enumerate(info.last_args)
                   if isinstance(a, (int, float)) and not isinstance(a, bool)] if info else []
        target = self.catalog.targets.get("adm.obj.xyz")
        if len(numeric) > 1 and target and len(target.args) >= len(numeric):
            for slot, idx in enumerate(numeric):
                rng = info.observed_range(idx)
                lo, hi = rng if rng and rng[0] != rng[1] else (0.0, 1.0)
                spec = target.args[slot]
                route.legs.append(Leg(
                    target_id=target.id, arg=spec.name,
                    indices={i.name: i.default for i in target.indices},
                    source_arg=idx, in_min=lo, in_max=hi,
                    out_min=spec.min, out_max=spec.max))
        elif target:
            rng = info.observed_range(0) if info else None
            lo, hi = rng if rng and rng[0] != rng[1] else (0.0, 1.0)
            spec = target.args[0]
            route.legs.append(Leg(
                target_id=target.id, arg=spec.name,
                indices={i.name: i.default for i in target.indices},
                in_min=lo, in_max=hi, out_min=spec.min, out_max=spec.max))
        self.bridge.engine.routes.append(route)
        self.note(f"route added: {address} ({len(route.legs)} leg(s))")
        return {"route": len(self.bridge.engine.routes) - 1}

    def _cmd_del_route(self, data: dict) -> dict:
        routes = self.bridge.engine.routes
        i = int(data["route"])
        if 0 <= i < len(routes):
            self.note(f"route removed: {routes[i].source}")
            routes.pop(i)
            self.bridge.engine.bus.clear()
        return {}

    def _cmd_add_leg(self, data: dict) -> dict:
        route = self._route(int(data["route"]))
        target = self.catalog.targets.get("adm.obj.xyz")
        if route.legs:
            last = route.legs[-1]
            target = self.catalog.targets.get(last.target_id, target)
        spec = target.args[0]
        route.legs.append(Leg(
            target_id=target.id, arg=spec.name,
            indices={i.name: i.default for i in target.indices},
            out_min=spec.min, out_max=spec.max))
        return {}

    def _cmd_del_leg(self, data: dict) -> dict:
        route = self._route(int(data["route"]))
        i = int(data["leg"])
        if 0 <= i < len(route.legs):
            route.legs.pop(i)
            self.bridge.engine.bus.clear()
        return {}

    def _cmd_set_route(self, data: dict) -> dict:
        route = self._route(int(data["route"]))
        for key, value in data.get("fields", {}).items():
            if key == "source":
                route.source = str(value) or "/*"
            elif key == "arg_index":
                route.arg_index = int(value)
            elif key == "name":
                route.name = str(value)
            elif key == "enabled":
                route.enabled = bool(value)
        return {}

    def _cmd_set_leg(self, data: dict) -> dict:
        route = self._route(int(data["route"]))
        leg = route.legs[int(data["leg"])]
        fields = data.get("fields", {})
        if "target_id" in fields and fields["target_id"] in self.catalog.targets:
            target = self.catalog.get(fields["target_id"])
            leg.target_id = target.id
            leg.indices = {i.name: i.default for i in target.indices}
            leg.arg = target.args[0].name
            leg.out_min, leg.out_max = target.args[0].min, target.args[0].max
            self.bridge.engine.bus.clear()
        target = self.catalog.targets.get(leg.target_id)
        for key, value in fields.items():
            if key == "target_id":
                continue
            if key == "arg" and target and value in [a.name for a in target.args]:
                leg.arg = value
                spec = target.arg(value)
                leg.out_min, leg.out_max = spec.min, spec.max
            elif key == "source_arg":
                leg.source_arg = None if value in ("", None, -1, "-1") else int(value)
            elif key in ("in_min", "in_max", "out_min", "out_max",
                         "smoothing", "deadzone", "quantize"):
                setattr(leg, key, float(value))
            elif key in ("invert", "clamp_input", "enabled"):
                setattr(leg, key, bool(value))
            elif key == "curve":
                leg.curve.kind = str(value)
                if leg.curve.kind == "breakpoints" and len(leg.curve.points) < 2:
                    leg.curve.points = [(0.0, 0.0), (0.35, 0.15), (1.0, 1.0)]
            elif key == "amount":
                leg.curve.amount = float(value)
            elif key == "points":
                leg.curve.points = [(float(x), float(y)) for x, y in value]
            elif key == "indices" and isinstance(value, dict):
                leg.indices.update({k: int(v) for k, v in value.items()})
                self.bridge.engine.bus.clear()
        leg.reset()
        return {}

    def _cmd_learn(self, data: dict) -> dict:
        route = self._route(int(data["route"]))
        leg = route.legs[int(data["leg"])]
        info = self.bridge.discovery.get(route.source)
        rng = info.observed_range(route.index_for(leg)) if info else None
        if rng and rng[0] != rng[1]:
            leg.in_min, leg.in_max = rng
            return {}
        return {"warning": "no numeric range observed yet"}

    def _cmd_clear_discovery(self, data: dict) -> dict:
        self.bridge.discovery.clear()
        return {}

    def _cmd_send_all(self, data: dict) -> dict:
        messages = self.bridge.engine.flush(force=True)
        self.bridge.sender.send_many(messages)
        self.note(f"forced {len(messages)} message(s)")
        return {"sent": len(messages)}

    def _cmd_save(self, data: dict) -> dict:
        path = data.get("path") or self.bridge.project.path
        if not path:
            return {"warning": "no project path yet — use Save as in the desktop app"}
        self.bridge.sync_project().save(path)
        self.note(f"project saved to {path}")
        return {"path": str(path)}


class WebRemote:
    """Serves the remote UI and its JSON API on a background thread."""

    def __init__(self, bridge, host: str = "0.0.0.0", port: int = 8080):
        self.controller = Controller(bridge)
        self.host = host
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self) -> None:
        if self._server is not None:
            return
        controller = self.controller

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):        # keep the console quiet
                pass

            def _send(self, code: int, body: bytes, content_type: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, payload: Any, code: int = 200) -> None:
                self._send(code, json.dumps(payload).encode("utf-8"),
                           "application/json; charset=utf-8")

            def do_GET(self):
                if self.path.startswith("/api/state"):
                    self._json(controller.state())
                elif self.path in ("/", "/index.html"):
                    self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    data = json.loads(raw or b"{}")
                except ValueError:
                    self._json({"ok": False, "error": "bad JSON"}, 400)
                    return
                if not self.path.startswith("/api/command"):
                    self._json({"ok": False, "error": "not found"}, 404)
                    return
                cmd = data.pop("cmd", "")
                try:
                    self._json(controller.command(cmd, data))
                except Exception as exc:                       # never kill the server
                    self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 200)

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="web-remote", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
