"""OSC transport: a learning receiver and per-protocol senders."""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------
@dataclass
class DiscoveredAddress:
    address: str
    count: int = 0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = 0.0
    arg_types: str = ""                       # e.g. "fff"
    last_args: tuple = ()
    mins: list[float | None] = field(default_factory=list)
    maxs: list[float | None] = field(default_factory=list)
    rate_hz: float = 0.0
    sources: set[str] = field(default_factory=set)

    def observed_range(self, index: int) -> tuple[float, float] | None:
        if index < len(self.mins) and self.mins[index] is not None:
            return (self.mins[index], self.maxs[index])
        return None

    def type_of(self, index: int) -> str:
        return self.arg_types[index] if index < len(self.arg_types) else "?"


def _type_char(v: Any) -> str:
    if isinstance(v, bool):
        return "T"
    if isinstance(v, int):
        return "i"
    if isinstance(v, float):
        return "f"
    if isinstance(v, str):
        return "s"
    if isinstance(v, (bytes, bytearray)):
        return "b"
    return "?"


def _numeric(v: Any) -> float | None:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return None


class Discovery:
    """Thread-safe store of every OSC address seen on the input port."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, DiscoveredAddress] = {}
        self.total_messages = 0

    def observe(self, address: str, args: tuple, source: str = "") -> DiscoveredAddress:
        now = time.time()
        with self._lock:
            self.total_messages += 1
            item = self._items.get(address)
            if item is None:
                item = DiscoveredAddress(address=address, first_seen=now)
                self._items[address] = item
            if item.last_seen:
                dt = now - item.last_seen
                if dt > 0:
                    inst = 1.0 / dt
                    item.rate_hz = inst if item.rate_hz == 0 else item.rate_hz * 0.8 + inst * 0.2
            item.count += 1
            item.last_seen = now
            item.last_args = tuple(args)
            item.arg_types = "".join(_type_char(a) for a in args)
            if len(item.mins) != len(args):
                item.mins = [None] * len(args)
                item.maxs = [None] * len(args)
            for n, a in enumerate(args):
                v = _numeric(a)
                if v is None:
                    continue
                item.mins[n] = v if item.mins[n] is None else min(item.mins[n], v)
                item.maxs[n] = v if item.maxs[n] is None else max(item.maxs[n], v)
            if source:
                item.sources.add(source)
            return item

    def snapshot(self) -> list[DiscoveredAddress]:
        with self._lock:
            return sorted(self._items.values(), key=lambda i: i.address)

    def get(self, address: str) -> DiscoveredAddress | None:
        with self._lock:
            return self._items.get(address)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self.total_messages = 0

    def forget(self, address: str) -> None:
        with self._lock:
            self._items.pop(address, None)


# --------------------------------------------------------------------------
# receiver
# --------------------------------------------------------------------------
def port_conflict(host: str, port: int) -> bool:
    """True if some other process already holds this UDP port.

    On Windows a second program bound to the same port can swallow the packets,
    so it is worth telling the user before they go hunting.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):        # Windows
            try:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        probe.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def local_addresses() -> list[str]:
    """Best effort list of this machine's IPv4 addresses, for the UI hint."""
    found = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    return sorted(found)


class OscReceiver:
    """UDP server with a catch-all handler; every address is auto-discovered."""

    def __init__(self, host: str = "0.0.0.0", port: int = 9000,
                 discovery: Discovery | None = None,
                 on_message: Callable[[str, list], None] | None = None) -> None:
        self.host = host
        self.port = port
        self.discovery = discovery or Discovery()
        self.on_message = on_message
        self._server: ThreadingOSCUDPServer | None = None
        self._thread: threading.Thread | None = None
        self.bound: tuple[str, int] | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        if self._server is not None:
            return
        dispatcher = Dispatcher()
        dispatcher.set_default_handler(self._handle, needs_reply_address=True)
        self._server = ThreadingOSCUDPServer((self.host, self.port), dispatcher)
        self.bound = self._server.server_address
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="osc-rx", daemon=True)
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

    def restart(self, host: str | None = None, port: int | None = None) -> None:
        self.stop()
        if host is not None:
            self.host = host
        if port is not None:
            self.port = port
        self.start()

    # python-osc calls: handler(client_address, osc_address, *args)
    def _handle(self, client_address, address, *args) -> None:
        try:
            src = f"{client_address[0]}:{client_address[1]}" if client_address else ""
        except Exception:
            src = ""
        self.discovery.observe(address, tuple(args), src)
        if self.on_message:
            try:
                self.on_message(address, list(args))
            except Exception:
                pass


# --------------------------------------------------------------------------
# sender
# --------------------------------------------------------------------------
@dataclass
class Destination:
    host: str = "127.0.0.1"
    port: int = 4002
    enabled: bool = True


class OscSender:
    """One UDP client per protocol (adm / yosc / custom)."""

    def __init__(self, destinations: dict[str, Destination] | None = None) -> None:
        self.destinations: dict[str, Destination] = destinations or {}
        self._clients: dict[tuple[str, int], SimpleUDPClient] = {}
        self.sent = 0
        self.skipped: dict[str, int] = {}
        self.last_error: str = ""

    def set_destination(self, protocol: str, host: str, port: int,
                        enabled: bool = True) -> None:
        self.destinations[protocol] = Destination(host, port, enabled)

    def _client(self, host: str, port: int) -> SimpleUDPClient:
        key = (host, port)
        c = self._clients.get(key)
        if c is None:
            c = SimpleUDPClient(host, port)
            self._clients[key] = c
        return c

    def send(self, address: str, args: list[Any], protocol: str) -> bool:
        dest = self.destinations.get(protocol)
        if dest is None or not dest.enabled:
            self.skipped[protocol] = self.skipped.get(protocol, 0) + 1
            return False
        try:
            self._client(dest.host, dest.port).send_message(address, list(args))
            self.sent += 1
            return True
        except Exception as exc:  # network hiccup, bad host, ...
            self.last_error = f"{address}: {exc}"
            return False

    def send_many(self, messages: list[tuple[str, list[Any], str]]) -> int:
        return sum(1 for a, v, p in messages if self.send(a, v, p))

    def to_dict(self) -> dict:
        return {p: {"host": d.host, "port": d.port, "enabled": d.enabled}
                for p, d in self.destinations.items()}

    def load_dict(self, data: dict) -> None:
        for proto, d in (data or {}).items():
            self.set_destination(proto, d.get("host", "127.0.0.1"),
                                 int(d.get("port", 4002)),
                                 bool(d.get("enabled", True)))
