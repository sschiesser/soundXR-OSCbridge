"""Mapping engine: input OSC value -> one or more Sound xR parameter values.

The pipeline for every *leg* of a mapping is:

    raw value
      -> clamp to input range
      -> normalise to 0..1
      -> invert
      -> deadzone (around the centre of the input range)
      -> curve (linear / exponential / logarithmic / s-curve / breakpoints)
      -> scale to output range
      -> quantise
      -> smooth (one pole, per incoming message)
      -> clamp + coerce to the target argument's type

A *route* binds one incoming OSC address (wildcards allowed) and one of its
arguments to a list of legs, so a single input can drive several Sound xR
parameters at once, each with its own curve and range.
"""

from __future__ import annotations

import fnmatch
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from .catalog import Catalog, Target

CURVE_KINDS = ("linear", "exponential", "logarithmic", "scurve", "breakpoints")


# --------------------------------------------------------------------------
# curves
# --------------------------------------------------------------------------
@dataclass
class Curve:
    kind: str = "linear"
    amount: float = 2.0
    points: list[tuple[float, float]] = field(default_factory=list)

    def normalised_points(self) -> list[tuple[float, float]]:
        pts = sorted((float(x), float(y)) for x, y in self.points)
        if len(pts) < 2:
            pts = [(0.0, 0.0), (1.0, 1.0)]
        return pts

    def apply(self, u: float) -> float:
        u = min(1.0, max(0.0, u))
        kind = self.kind
        if kind == "linear":
            return u
        if kind == "exponential":
            g = max(0.01, self.amount)
            return u ** g
        if kind == "logarithmic":
            g = max(0.01, self.amount)
            return u ** (1.0 / g)
        if kind == "scurve":
            g = max(0.01, self.amount)
            if u <= 0.5:
                return 0.5 * ((2.0 * u) ** g)
            return 1.0 - 0.5 * ((2.0 * (1.0 - u)) ** g)
        if kind == "breakpoints":
            return _interp(self.normalised_points(), u)
        return u

    def sample(self, n: int = 128) -> list[tuple[float, float]]:
        return [(i / (n - 1), self.apply(i / (n - 1))) for i in range(n)]

    def to_dict(self) -> dict:
        return {"kind": self.kind, "amount": self.amount,
                "points": [list(p) for p in self.points]}

    @classmethod
    def from_dict(cls, d: dict) -> "Curve":
        return cls(kind=d.get("kind", "linear"),
                   amount=float(d.get("amount", 2.0)),
                   points=[tuple(p) for p in d.get("points", [])])


def _interp(points: list[tuple[float, float]], x: float) -> float:
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y1
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return points[-1][1]


# --------------------------------------------------------------------------
# legs and routes
# --------------------------------------------------------------------------
@dataclass
class Leg:
    """One output binding of a route."""
    target_id: str
    arg: str
    indices: dict[str, int] = field(default_factory=dict)
    in_min: float = 0.0
    in_max: float = 1.0
    out_min: float = 0.0
    out_max: float = 1.0
    curve: Curve = field(default_factory=Curve)
    invert: bool = False
    deadzone: float = 0.0          # 0..1, fraction of the input span, centred
    smoothing: float = 0.0         # 0 = off, ->1 = heavy
    quantize: float = 0.0          # output step, 0 = off
    clamp_input: bool = True
    enabled: bool = True
    _last: float | None = field(default=None, repr=False, compare=False)

    # -- maths -----------------------------------------------------------
    def normalise(self, value: float) -> float:
        lo, hi = self.in_min, self.in_max
        if self.clamp_input:
            value = min(max(value, min(lo, hi)), max(lo, hi))
        span = hi - lo
        if span == 0:
            return 0.0
        return (value - lo) / span

    def apply_deadzone(self, u: float) -> float:
        dz = min(0.999, max(0.0, self.deadzone))
        if dz <= 0.0:
            return u
        half = dz / 2.0
        d = u - 0.5
        if abs(d) <= half:
            return 0.5
        # rescale the two live regions back onto 0..0.5 and 0.5..1
        sign = 1.0 if d > 0 else -1.0
        return 0.5 + sign * (abs(d) - half) / (0.5 - half) * 0.5

    def compute(self, value: float) -> float:
        u = self.normalise(float(value))
        if self.invert:
            u = 1.0 - u
        u = self.apply_deadzone(u)
        u = self.curve.apply(u)
        out = self.out_min + u * (self.out_max - self.out_min)
        if self.quantize > 0:
            out = round(out / self.quantize) * self.quantize
        s = min(0.99, max(0.0, self.smoothing))
        if s > 0 and self._last is not None:
            out = self._last + (1.0 - s) * (out - self._last)
        self._last = out
        return out

    def reset(self) -> None:
        self._last = None

    def key(self) -> tuple:
        return (self.target_id, tuple(sorted(self.indices.items())))

    # -- serialisation ---------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "target_id": self.target_id, "arg": self.arg, "indices": dict(self.indices),
            "in_min": self.in_min, "in_max": self.in_max,
            "out_min": self.out_min, "out_max": self.out_max,
            "curve": self.curve.to_dict(), "invert": self.invert,
            "deadzone": self.deadzone, "smoothing": self.smoothing,
            "quantize": self.quantize, "clamp_input": self.clamp_input,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Leg":
        return cls(
            target_id=d["target_id"], arg=d["arg"],
            indices={k: int(v) for k, v in d.get("indices", {}).items()},
            in_min=float(d.get("in_min", 0.0)), in_max=float(d.get("in_max", 1.0)),
            out_min=float(d.get("out_min", 0.0)), out_max=float(d.get("out_max", 1.0)),
            curve=Curve.from_dict(d.get("curve", {})),
            invert=bool(d.get("invert", False)),
            deadzone=float(d.get("deadzone", 0.0)),
            smoothing=float(d.get("smoothing", 0.0)),
            quantize=float(d.get("quantize", 0.0)),
            clamp_input=bool(d.get("clamp_input", True)),
            enabled=bool(d.get("enabled", True)),
        )


@dataclass
class Route:
    """One incoming address/argument fanned out to N Sound xR parameters."""
    source: str = "/*"
    arg_index: int = 0
    name: str = ""
    enabled: bool = True
    legs: list[Leg] = field(default_factory=list)

    def matches(self, address: str) -> bool:
        if self.source == address:
            return True
        if any(ch in self.source for ch in "*?["):
            return fnmatch.fnmatchcase(address, self.source)
        return False

    def label(self) -> str:
        return self.name or f"{self.source} [{self.arg_index}]"

    def to_dict(self) -> dict:
        return {"source": self.source, "arg_index": self.arg_index, "name": self.name,
                "enabled": self.enabled, "legs": [l.to_dict() for l in self.legs]}

    @classmethod
    def from_dict(cls, d: dict) -> "Route":
        return cls(source=d.get("source", "/*"), arg_index=int(d.get("arg_index", 0)),
                   name=d.get("name", ""), enabled=bool(d.get("enabled", True)),
                   legs=[Leg.from_dict(x) for x in d.get("legs", [])])


# --------------------------------------------------------------------------
# output bus: coalesces multi-argument targets (e.g. /adm/obj/1/xyz)
# --------------------------------------------------------------------------
@dataclass
class _BusEntry:
    target: Target
    indices: dict[str, int]
    args: list[Any]
    dirty: bool = False
    last_sent: list[Any] | None = None


class TargetBus:
    """Holds the current argument set of every touched target.

    A leg only ever writes one argument (x of xyz, say); the bus keeps the other
    arguments at their last value so the message stays valid, and ``flush``
    returns one OSC message per changed target.
    """

    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self._entries: dict[tuple, _BusEntry] = {}

    def entry(self, target: Target, indices: dict[str, int]) -> _BusEntry:
        key = (target.id, tuple(sorted(indices.items())))
        e = self._entries.get(key)
        if e is None:
            e = _BusEntry(target=target, indices=dict(indices), args=target.default_args())
            self._entries[key] = e
        return e

    def set_arg(self, target: Target, indices: dict[str, int], arg_name: str,
                value: Any) -> None:
        spec = target.arg(arg_name)
        idx = target.arg_index(arg_name)
        if spec.numeric:
            value = spec.coerce(spec.clamp(float(value)))
        else:
            value = spec.coerce(value)
        e = self.entry(target, indices)
        if e.args[idx] != value:
            e.args[idx] = value
            e.dirty = True

    def flush(self, force: bool = False) -> list[tuple[str, list[Any], str]]:
        """Return [(address, args, protocol)] for every changed target."""
        out: list[tuple[str, list[Any], str]] = []
        for e in self._entries.values():
            if not (e.dirty or force):
                continue
            if not force and e.last_sent == e.args:
                e.dirty = False
                continue
            address = e.target.format_address(e.indices)
            args = list(e.args)
            out.append((address, args, e.target.protocol))
            e.last_sent = args
            e.dirty = False
        return out

    def clear(self) -> None:
        self._entries.clear()


# --------------------------------------------------------------------------
# engine
# --------------------------------------------------------------------------
class MappingEngine:
    def __init__(self, catalog: Catalog, routes: Iterable[Route] | None = None):
        self.catalog = catalog
        self.routes: list[Route] = list(routes or [])
        self.bus = TargetBus(catalog)
        self.enabled = True

    def reset(self) -> None:
        self.bus.clear()
        for r in self.routes:
            for l in r.legs:
                l.reset()

    def handle(self, address: str, args: list[Any]) -> None:
        """Feed one incoming OSC message through every matching route."""
        if not self.enabled:
            return
        for route in self.routes:
            if not route.enabled or not route.matches(address):
                continue
            if route.arg_index >= len(args):
                continue
            raw = args[route.arg_index]
            value = _to_float(raw)
            if value is None:
                continue
            for leg in route.legs:
                if not leg.enabled:
                    continue
                try:
                    target = self.catalog.get(leg.target_id)
                except KeyError:
                    continue
                try:
                    self.bus.set_arg(target, leg.indices, leg.arg, leg.compute(value))
                except (KeyError, ValueError):
                    continue

    def flush(self, force: bool = False) -> list[tuple[str, list[Any], str]]:
        return self.bus.flush(force=force)

    def process(self, address: str, args: list[Any]) -> list[tuple[str, list[Any], str]]:
        """Convenience for tests: handle + flush in one call."""
        self.handle(address, args)
        return self.flush()


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
