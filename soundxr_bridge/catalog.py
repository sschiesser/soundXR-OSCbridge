"""Sound xR OSC target catalogue.

A *target* is one addressable Sound xR parameter: an OSC address template with
zero or more index placeholders (object number, component ID, speaker number)
and one or more typed arguments.  Everything is loaded from ``targets.json`` so
the catalogue can be corrected or extended without touching code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CATALOG = Path(__file__).with_name("targets.json")


def user_catalog() -> Path | None:
    """A targets.json placed next to the executable (or the working directory).

    In a packaged build the bundled catalogue is read-only, so this is how a
    user corrects or extends the address list without a rebuild.
    """
    import sys
    base = (Path(sys.executable).parent if getattr(sys, "frozen", False)
            else Path.cwd())
    candidate = base / "targets.json"
    return candidate if candidate.is_file() else None


@dataclass(frozen=True)
class ArgSpec:
    name: str
    type: str = "float"           # float | int | string
    min: float = 0.0
    max: float = 1.0
    default: Any = 0.0
    unit: str = ""
    scale: float = 1.0            # wire value = engineering value * scale

    @property
    def numeric(self) -> bool:
        return self.type in ("float", "int")

    def coerce(self, value: Any) -> Any:
        if self.type == "int":
            return int(round(float(value)))
        if self.type == "float":
            return float(value)
        return str(value)

    def clamp(self, value: float) -> float:
        return min(self.max, max(self.min, value))

    def engineering(self, wire_value: float) -> float:
        """Wire value -> human units (e.g. -1000 -> -10.0 dB)."""
        return wire_value / self.scale if self.scale else wire_value

    def describe_range(self) -> str:
        if not self.numeric:
            return self.unit or "string"
        if self.scale and self.scale != 1.0:
            return (f"{self.engineering(self.min):g}..{self.engineering(self.max):g} "
                    f"{self.unit} (wire {self.min:g}..{self.max:g})")
        return f"{self.min:g}..{self.max:g}{(' ' + self.unit) if self.unit else ''}"


@dataclass(frozen=True)
class IndexSpec:
    name: str
    label: str = ""
    min: int = 1
    max: int = 128
    default: int = 1


@dataclass(frozen=True)
class Target:
    id: str
    protocol: str
    label: str
    address: str
    group: str = ""
    indices: tuple[IndexSpec, ...] = ()
    args: tuple[ArgSpec, ...] = ()
    verified: bool = True

    def format_address(self, index_values: dict[str, int] | None = None) -> str:
        values = {i.name: i.default for i in self.indices}
        if index_values:
            values.update({k: v for k, v in index_values.items() if k in values})
        try:
            return self.address.format(**values)
        except KeyError as exc:  # pragma: no cover - catalogue authoring error
            raise ValueError(f"target {self.id}: missing index {exc}") from exc

    def arg(self, name_or_index: str | int) -> ArgSpec:
        if isinstance(name_or_index, int):
            return self.args[name_or_index]
        for a in self.args:
            if a.name == name_or_index:
                return a
        raise KeyError(name_or_index)

    def arg_index(self, name: str) -> int:
        for n, a in enumerate(self.args):
            if a.name == name:
                return n
        raise KeyError(name)

    def default_args(self) -> list[Any]:
        return [a.coerce(a.default) for a in self.args]

    @property
    def display(self) -> str:
        mark = "" if self.verified else "  (unverified)"
        return f"{self.label}{mark}"


@dataclass
class Catalog:
    protocols: dict[str, dict] = field(default_factory=dict)
    targets: dict[str, Target] = field(default_factory=dict)
    note: str = ""
    source_path: Path | None = None

    # -- loading ---------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path | None = None) -> "Catalog":
        path = Path(path) if path else DEFAULT_CATALOG
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cat = cls(protocols=data.get("protocols", {}), source_path=Path(path))
        note = data.get("note", "")
        cat.note = "\n".join(note) if isinstance(note, list) else str(note)
        for raw in data.get("targets", []):
            cat.add(_target_from_dict(raw))
        return cat

    def merge(self, other: "Catalog") -> None:
        self.protocols.update(other.protocols)
        self.targets.update(other.targets)

    def add(self, target: Target) -> None:
        self.targets[target.id] = target

    # -- queries ---------------------------------------------------------
    def get(self, target_id: str) -> Target:
        return self.targets[target_id]

    def by_protocol(self, protocol: str) -> list[Target]:
        return [t for t in self.targets.values() if t.protocol == protocol]

    def groups(self) -> dict[str, list[Target]]:
        out: dict[str, list[Target]] = {}
        for t in self.targets.values():
            out.setdefault(t.group or "Other", []).append(t)
        for v in out.values():
            v.sort(key=lambda t: t.label)
        return dict(sorted(out.items()))

    def search(self, text: str) -> list[Target]:
        text = text.strip().lower()
        if not text:
            return list(self.targets.values())
        return [t for t in self.targets.values()
                if text in t.label.lower() or text in t.address.lower()
                or text in t.id.lower() or text in t.group.lower()]

    def default_port(self, protocol: str) -> int:
        return int(self.protocols.get(protocol, {}).get("default_port", 9000))

    def protocol_label(self, protocol: str) -> str:
        return self.protocols.get(protocol, {}).get("label", protocol)


def _target_from_dict(raw: dict) -> Target:
    indices = tuple(
        IndexSpec(
            name=i["name"],
            label=i.get("label", i["name"]),
            min=int(i.get("min", 1)),
            max=int(i.get("max", 128)),
            default=int(i.get("default", 1)),
        )
        for i in raw.get("indices", [])
    )
    args = tuple(
        ArgSpec(
            name=a["name"],
            type=a.get("type", "float"),
            min=float(a.get("min", 0.0)) if a.get("type", "float") != "string" else 0.0,
            max=float(a.get("max", 1.0)) if a.get("type", "float") != "string" else 0.0,
            default=a.get("default", 0.0),
            unit=a.get("unit", ""),
            scale=float(a.get("scale", 1.0)),
        )
        for a in raw.get("args", [])
    )
    return Target(
        id=raw["id"],
        protocol=raw.get("protocol", "adm"),
        label=raw.get("label", raw["id"]),
        address=raw["address"],
        group=raw.get("group", ""),
        indices=indices,
        args=args,
        verified=bool(raw.get("verified", True)),
    )


def custom_target(address: str, arg_types: list[str], label: str = "") -> Target:
    """Build an ad-hoc target for an address the catalogue does not cover."""
    args = tuple(
        ArgSpec(name=f"arg{n + 1}", type=t,
                min=0.0 if t != "float" else -1.0,
                max=1.0, default="" if t == "string" else 0.0)
        for n, t in enumerate(arg_types)
    )
    return Target(
        id=f"custom:{address}",
        protocol="custom",
        label=label or address,
        address=address,
        group="Custom",
        indices=(),
        args=args,
        verified=False,
    )
