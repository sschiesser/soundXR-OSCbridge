"""Project file: everything the bridge needs to run, as plain JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .mapping import Route

FORMAT = "soundxr-osc-bridge"
FORMAT_VERSION = 1


@dataclass
class Project:
    input_host: str = "0.0.0.0"
    input_port: int = 9000
    destinations: dict = field(default_factory=lambda: {
        "adm": {"host": "127.0.0.1", "port": 4002, "enabled": True},
        "yosc": {"host": "127.0.0.1", "port": 50528, "enabled": True},
        "custom": {"host": "127.0.0.1", "port": 9001, "enabled": False},
    })
    send_rate_hz: float = 100.0
    extra_catalogs: list[str] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "input": {"host": self.input_host, "port": self.input_port},
            "destinations": self.destinations,
            "send_rate_hz": self.send_rate_hz,
            "extra_catalogs": list(self.extra_catalogs),
            "routes": [r.to_dict() for r in self.routes],
        }

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        self.path = path
        return path

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") not in (None, FORMAT):
            raise ValueError(f"{path.name} is not a {FORMAT} project")
        inp = data.get("input", {})
        p = cls(
            input_host=inp.get("host", "0.0.0.0"),
            input_port=int(inp.get("port", 9000)),
            destinations=data.get("destinations", cls().destinations),
            send_rate_hz=float(data.get("send_rate_hz", 100.0)),
            extra_catalogs=list(data.get("extra_catalogs", [])),
            routes=[Route.from_dict(r) for r in data.get("routes", [])],
        )
        p.path = path
        return p
