"""NiceGUI spike — one UI for desktop window and tablet browser.

Deliberately a spike, not a replacement: it drives the real engine
(soundxr_bridge.bridge.Bridge) so what you see is the actual behaviour, but it
covers only the parts worth judging — live discovery, building a mapping from a
multi-argument address, editing a leg, and the breakpoint curve, which is the
one thing Qt did that a browser has to earn.

    python spike_nicegui/app.py              # browser at http://localhost:8090
    python spike_nicegui/app.py --native     # desktop window (needs pywebview)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nicegui import app as nicegui_app
from nicegui import ui

from soundxr_bridge import __version__
from soundxr_bridge.bridge import Bridge
from soundxr_bridge.mapping import CURVE_KINDS, Leg, Route
from soundxr_bridge.project import Project

BRIDGE = Bridge(Project(input_port=10020))
CATALOG = BRIDGE.catalog
STATE: dict = {"leg": None, "route": None, "sel": None, "drag": False}

TARGET_OPTIONS = {t.id: f"{t.group} · {t.label}"
                  for t in sorted(CATALOG.targets.values(),
                                  key=lambda t: (t.group, t.label))}


# ---------------------------------------------------------------- engine glue
def start_stop() -> None:
    if BRIDGE.receiver.running:
        BRIDGE.stop()
        ui.notify("Stopped")
    else:
        try:
            BRIDGE.start()
            ui.notify(f"Listening on {BRIDGE.project.input_host}:"
                      f"{BRIDGE.project.input_port}")
        except OSError as exc:
            ui.notify(f"Cannot listen: {exc}", type="negative", timeout=8000)


def set_input(host: str | None = None, port: float | None = None) -> None:
    project = BRIDGE.project
    if host is not None:
        project.input_host = host.strip() or "0.0.0.0"
    if port is not None:
        project.input_port = int(port)
    if BRIDGE.receiver.running:
        try:
            BRIDGE.receiver.restart(project.input_host, project.input_port)
            ui.notify(f"Now listening on {project.input_host}:{project.input_port}")
        except OSError as exc:
            ui.notify(f"Cannot listen: {exc}", type="negative", timeout=8000)


def set_dest(protocol: str, host: str | None = None, port: float | None = None,
             enabled: bool | None = None) -> None:
    d = BRIDGE.project.destinations.setdefault(
        protocol, {"host": "127.0.0.1", "port": 9000, "enabled": False})
    if host is not None:
        d["host"] = host.strip() or "127.0.0.1"
    if port is not None:
        d["port"] = int(port)
    if enabled is not None:
        d["enabled"] = bool(enabled)
    BRIDGE.sender.load_dict(BRIDGE.project.destinations)


def simulate() -> None:
    """Inject traffic so the UI can be judged without an OSC source."""
    import math
    import time
    t = time.time()
    BRIDGE.discovery.observe("/mocap/head",
                             (2.0 * math.sin(t), 1.2 * math.cos(t * 0.7), 1.0 + math.sin(t * 0.3)),
                             "10.21.137.9:10020")
    BRIDGE.discovery.observe("/ctl/fader/1", (0.5 + 0.5 * math.sin(t * 0.4),),
                             "10.21.137.9:10020")


def add_route(address: str) -> None:
    info = BRIDGE.discovery.get(address)
    route = Route(source=address)
    numeric = [n for n, a in enumerate(info.last_args)
               if isinstance(a, (int, float)) and not isinstance(a, bool)] if info else []
    target = CATALOG.get("adm.obj.xyz")
    if len(numeric) > 1 and len(target.args) >= len(numeric):
        for slot, index in enumerate(numeric):
            rng = info.observed_range(index)
            lo, hi = rng if rng and rng[0] != rng[1] else (0.0, 1.0)
            spec = target.args[slot]
            route.legs.append(Leg(target.id, spec.name,
                                  {i.name: i.default for i in target.indices},
                                  source_arg=index, in_min=lo, in_max=hi,
                                  out_min=spec.min, out_max=spec.max))
    else:
        spec = target.args[0]
        route.legs.append(Leg(target.id, spec.name,
                              {i.name: i.default for i in target.indices},
                              out_min=spec.min, out_max=spec.max))
    BRIDGE.engine.routes.append(route)
    select_leg(route, route.legs[0])
    ui.notify(f"{address} → {len(route.legs)} leg(s)")
    mappings.refresh()


def select_leg(route: Route, leg: Leg) -> None:
    STATE["route"], STATE["leg"] = route, leg
    editor.refresh()


def delete_route(route: Route) -> None:
    BRIDGE.engine.routes.remove(route)
    BRIDGE.engine.bus.clear()
    if STATE["route"] is route:
        STATE["route"] = STATE["leg"] = None
    mappings.refresh()
    editor.refresh()


# ------------------------------------------------------------- curve as SVG
# interactive_image sizes itself from its source, so it needs a transparent
# placeholder of the right aspect ratio for the SVG overlay to have room.
BLANK = ("data:image/svg+xml;utf8,"
         "%3Csvg xmlns='http://www.w3.org/2000/svg' width='320' height='200'%3E%3C/svg%3E")


def curve_svg(leg: Leg, w: int = 320, h: int = 200) -> str:
    """The transfer curve, drawn as inline SVG with draggable breakpoints."""
    pad = 8
    iw, ih = w - 2 * pad, h - 2 * pad

    def px(x: float, y: float) -> tuple[float, float]:
        return (pad + x * iw, pad + (1 - y) * ih)

    grid = "".join(
        f'<line x1="{pad + iw * i / 4:.1f}" y1="{pad}" x2="{pad + iw * i / 4:.1f}" '
        f'y2="{h - pad}" stroke="#8884" stroke-width="1"/>'
        f'<line x1="{pad}" y1="{pad + ih * i / 4:.1f}" x2="{w - pad}" '
        f'y2="{pad + ih * i / 4:.1f}" stroke="#8884" stroke-width="1"/>'
        for i in range(1, 4))
    pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in
                   (px(x, y) for x, y in leg.curve.sample(120)))
    handles = ""
    if leg.curve.kind == "breakpoints":
        parts = []
        for n, (x, y) in enumerate(leg.curve.normalised_points()):
            cx, cy = px(x, y)
            chosen = n == STATE["sel"]
            parts.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{9 if chosen else 6}" '
                f'fill="{"#ffca6a" if chosen else "#fff"}" stroke="#007acc" '
                f'stroke-width="{3 if chosen else 2}"/>')
        handles = "".join(parts)
    live = ""
    info = BRIDGE.discovery.get(STATE["route"].source) if STATE["route"] else None
    if info and STATE["route"]:
        index = STATE["route"].index_for(leg)
        if index < len(info.last_args) and isinstance(info.last_args[index], (int, float)):
            u = leg.apply_deadzone(leg.normalise(float(info.last_args[index])))
            if leg.invert:
                u = 1.0 - u
            x, y = px(u, leg.curve.apply(u))
            live = (f'<line x1="{x:.1f}" y1="{h - pad}" x2="{x:.1f}" y2="{y:.1f}" '
                    f'stroke="#dc5a3c" stroke-dasharray="3 3"/>'
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#dc5a3c"/>')
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" style="touch-action:none">'
            f'<rect x="{pad}" y="{pad}" width="{iw}" height="{ih}" fill="#0002" '
            f'stroke="#888"/>{grid}'
            f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{pad}" '
            f'stroke="#8886" stroke-dasharray="4 4"/>'
            f'<polyline points="{pts}" fill="none" stroke="#007acc" stroke-width="2"/>'
            f'{handles}{live}</svg>')


def _unit(e) -> tuple[float, float]:
    w, h, pad = 320, 200, 8
    x = min(1.0, max(0.0, (e.image_x - pad) / (w - 2 * pad)))
    y = min(1.0, max(0.0, 1 - (e.image_y - pad) / (h - 2 * pad)))
    return x, y


def _nearest(leg, x: float, y: float) -> int | None:
    best, best_d = None, 0.07
    for n, (px_, py_) in enumerate(leg.curve.points):
        d = max(abs(px_ - x), abs(py_ - y))
        if d < best_d:
            best, best_d = n, d
    return best


def curve_mouse(e) -> None:
    """Press a handle and drag it; press empty space to add one and drag that."""
    leg = STATE["leg"]
    if leg is None or leg.curve.kind != "breakpoints":
        return
    x, y = _unit(e)

    if e.type == "mousedown":
        hit = _nearest(leg, x, y)
        if hit is None:
            leg.curve.points.append((x, y))
            leg.curve.points.sort()
            hit = leg.curve.points.index((x, y))
        STATE["sel"], STATE["drag"] = hit, True
        _redraw(leg)
        point_fields.refresh()

    elif e.type == "mousemove" and STATE["drag"] and STATE["sel"] is not None:
        moving = (x, y)
        leg.curve.points[STATE["sel"]] = moving
        leg.curve.points.sort()
        STATE["sel"] = leg.curve.points.index(moving)
        leg.reset()
        _redraw(leg)                      # redraw only, no widget rebuild

    elif e.type == "mouseup":
        STATE["drag"] = False
        point_fields.refresh()


def _redraw(leg) -> None:
    if curve_view is not None:
        curve_view.set_content(curve_svg(leg))


def move_selected(dx: float = 0.0, dy: float = 0.0, to=None) -> None:
    """Nudge or set the selected point — precise editing, and it works on touch."""
    leg = STATE["leg"]
    if leg is None or STATE["sel"] is None:
        return
    x, y = leg.curve.points[STATE["sel"]]
    nx, ny = (to if to else (x + dx, y + dy))
    moving = (min(1.0, max(0.0, nx)), min(1.0, max(0.0, ny)))
    leg.curve.points[STATE["sel"]] = moving
    leg.curve.points.sort()
    STATE["sel"] = leg.curve.points.index(moving)
    leg.reset()
    _redraw(leg)
    point_fields.refresh()


def remove_selected() -> None:
    leg = STATE["leg"]
    if leg is None or STATE["sel"] is None or len(leg.curve.points) <= 2:
        return
    leg.curve.points.pop(STATE["sel"])
    STATE["sel"] = None
    leg.reset()
    _redraw(leg)
    point_fields.refresh()


# ------------------------------------------------------------------ the page
@ui.page("/")
def main_page() -> None:
    ui.dark_mode(True)
    ui.query("body").style("font-family: system-ui")

    with ui.header().classes("items-center gap-4 py-2"):
        status = ui.icon("circle", size="14px")
        ui.label(f"Sound xR OSC Bridge {__version__}").classes("text-lg font-medium")
        ui.label("NiceGUI spike").classes("text-xs opacity-60")
        run_btn = ui.button("Start", on_click=start_stop).props("unelevated")
        counters = ui.label("").classes("ml-auto text-sm opacity-80")

    with ui.row().classes("w-full gap-4 p-4 items-start"):
        # ---- incoming -------------------------------------------------
        with ui.card().classes("w-full lg:w-[48%]"):
            with ui.row().classes("items-center w-full"):
                ui.label("Incoming OSC").classes("text-base font-medium")
                ui.space()
                ui.button("Simulate", on_click=simulate).props("flat dense")
                ui.button("Clear", on_click=BRIDGE.discovery.clear).props("flat dense")
            table = ui.table(
                columns=[{"name": "address", "label": "Address", "field": "address",
                          "align": "left"},
                         {"name": "types", "label": "Types", "field": "types"},
                         {"name": "rate", "label": "Hz", "field": "rate"},
                         {"name": "last", "label": "Last values", "field": "last",
                          "align": "left"}],
                rows=[], row_key="address").classes("w-full")
            table.on("rowClick", lambda e: add_route(e.args[1]["address"]))
            ui.label("Tap a row to build a mapping from it").classes("text-xs opacity-60")

            transport()

        # ---- mappings and editor -------------------------------------
        with ui.column().classes("w-full lg:w-[48%] gap-4"):
            mappings()
            editor()

    def refresh() -> None:
        running = BRIDGE.receiver.running
        status.classes(replace="text-green-400" if running else "text-red-400")
        run_btn.text = "Stop" if running else "Start"
        counters.text = (f"{BRIDGE.discovery.total_messages} in · "
                         f"{BRIDGE.sender.sent} out")
        table.rows = [{"address": d.address, "types": d.arg_types,
                       "rate": f"{d.rate_hz:.1f}",
                       "last": "  ".join(f"{v:.3f}" if isinstance(v, float) else str(v)
                                         for v in d.last_args)}
                      for d in BRIDGE.discovery.snapshot()]
        table.update()
        BRIDGE.tick()
        if STATE["leg"] is not None:
            curve_view.set_content(curve_svg(STATE["leg"]))

    ui.timer(0.25, refresh)


def transport() -> None:
    with ui.card().classes("w-full mt-4"):
        ui.label("Transport").classes("text-base font-medium")
        with ui.row().classes("w-full gap-2 items-end"):
            ui.input("Listen on", value=BRIDGE.project.input_host,
                     on_change=lambda e: set_input(host=e.value)) \
                .classes("flex-1") \
                .tooltip("0.0.0.0 listens on every adapter and is the only "
                         "setting that receives broadcasts")
            ui.number("Input port", value=BRIDGE.project.input_port, format="%d",
                      on_change=lambda e: set_input(port=e.value)).classes("w-32")
        for proto in ("adm", "yosc", "custom"):
            d = BRIDGE.project.destinations.get(
                proto, {"host": "127.0.0.1", "port": 9000, "enabled": False})
            with ui.row().classes("w-full gap-2 items-center"):
                ui.label(proto).classes("w-16 text-sm opacity-70")
                ui.input("Host", value=d["host"],
                         on_change=lambda e, p=proto: set_dest(p, host=e.value)) \
                    .classes("flex-1")
                ui.number("Port", value=d["port"], format="%d",
                          on_change=lambda e, p=proto: set_dest(p, port=e.value)) \
                    .classes("w-28")
                ui.switch(value=d["enabled"],
                          on_change=lambda e, p=proto: set_dest(p, enabled=e.value)) \
                    .tooltip("send to this destination")
        ui.label("Changes apply immediately; the input port restarts the "
                 "receiver while it is running.").classes("text-xs opacity-60")


@ui.refreshable
def mappings() -> None:
    with ui.card().classes("w-full"):
        ui.label("Mappings").classes("text-base font-medium")
        if not BRIDGE.engine.routes:
            ui.label("Nothing mapped yet.").classes("text-xs opacity-60")
        for route in BRIDGE.engine.routes:
            with ui.expansion(route.source, value=True).classes("w-full"):
                for leg in route.legs:
                    target = CATALOG.targets.get(leg.target_id)
                    src = "route" if leg.source_arg is None else f"arg {leg.source_arg}"
                    with ui.row().classes("items-center w-full gap-2"):
                        ui.button(icon="edit",
                                  on_click=lambda r=route, l=leg: select_leg(r, l)) \
                            .props("flat dense")
                        ui.label(f"{src} → {target.label if target else '?'} · {leg.arg}") \
                            .classes("text-sm")
                        ui.space()
                        ui.badge(target.protocol if target else "?").props("outline")
                ui.button("Remove route", on_click=lambda r=route: delete_route(r)) \
                    .props("flat dense color=negative")


@ui.refreshable
def editor() -> None:
    global curve_view
    leg, route = STATE["leg"], STATE["route"]
    with ui.card().classes("w-full"):
        ui.label("Leg").classes("text-base font-medium")
        if leg is None:
            ui.label("Pick a leg with the pencil icon.").classes("text-xs opacity-60")
            curve_view = ui.html("")
            return
        target = CATALOG.get(leg.target_id)

        def set_target(value) -> None:
            t = CATALOG.get(value)
            leg.target_id = t.id
            leg.arg = t.args[0].name
            leg.indices = {i.name: i.default for i in t.indices}
            leg.out_min, leg.out_max = t.args[0].min, t.args[0].max
            BRIDGE.engine.bus.clear()
            editor.refresh()
            mappings.refresh()

        ui.select(TARGET_OPTIONS, value=leg.target_id, label="Sound xR parameter",
                  with_input=True, on_change=lambda e: set_target(e.value)) \
            .classes("w-full")
        with ui.row().classes("w-full gap-2"):
            ui.select([a.name for a in target.args], value=leg.arg, label="Argument",
                      on_change=lambda e: (setattr(leg, "arg", e.value),
                                           mappings.refresh())).classes("flex-1")
            for spec in target.indices:
                ui.number(spec.label, value=leg.indices.get(spec.name, spec.default),
                          min=spec.min, max=spec.max, format="%d",
                          on_change=lambda e, n=spec.name: (
                              leg.indices.__setitem__(n, int(e.value or 0)),
                              BRIDGE.engine.bus.clear())).classes("flex-1")
        ui.label(target.format_address(leg.indices)).classes("text-xs font-mono opacity-70")

        with ui.row().classes("w-full gap-2"):
            ui.number("Source arg (-1 = route)",
                      value=-1 if leg.source_arg is None else leg.source_arg,
                      format="%d",
                      on_change=lambda e: setattr(
                          leg, "source_arg",
                          None if e.value is None or e.value < 0 else int(e.value))
                      ).classes("flex-1")
            ui.number("In min", value=leg.in_min, format="%.3f",
                      on_change=lambda e: setattr(leg, "in_min", float(e.value or 0))
                      ).classes("flex-1")
            ui.number("In max", value=leg.in_max, format="%.3f",
                      on_change=lambda e: setattr(leg, "in_max", float(e.value or 0))
                      ).classes("flex-1")
        with ui.row().classes("w-full gap-2"):
            ui.number("Out min", value=leg.out_min, format="%.3f",
                      on_change=lambda e: setattr(leg, "out_min", float(e.value or 0))
                      ).classes("flex-1")
            ui.number("Out max", value=leg.out_max, format="%.3f",
                      on_change=lambda e: setattr(leg, "out_max", float(e.value or 0))
                      ).classes("flex-1")
            def set_curve(kind: str) -> None:
                leg.curve.kind = kind
                if kind == "breakpoints" and len(leg.curve.points) < 2:
                    leg.curve.points = [(0.0, 0.0), (0.4, 0.75), (1.0, 1.0)]
                leg.reset()
                editor.refresh()

            ui.select(list(CURVE_KINDS), value=leg.curve.kind, label="Curve",
                      on_change=lambda e: set_curve(e.value)).classes("flex-1")

        curve_view = ui.interactive_image(
            BLANK, content=curve_svg(leg), on_mouse=curve_mouse,
            events=["mousedown", "mousemove", "mouseup"], cross=False).classes("w-full")
        if leg.curve.kind == "breakpoints":
            point_fields()
            ui.label("drag a handle to move it · press empty space to add one") \
                .classes("text-xs opacity-60")


@ui.refreshable
def point_fields() -> None:
    leg = STATE["leg"]
    with ui.row().classes("items-center gap-2 w-full"):
        if leg is None or STATE["sel"] is None:
            ui.label("no point selected — press one to select it") \
                .classes("text-xs opacity-60")
            return
        x, y = leg.curve.points[STATE["sel"]]
        ui.label(f"point {STATE['sel'] + 1}/{len(leg.curve.points)}").classes("text-xs")
        ui.number("x", value=round(x, 3), step=0.01, format="%.3f",
                  on_change=lambda e: move_selected(
                      to=(float(e.value or 0), leg.curve.points[STATE["sel"]][1]))
                  ).classes("w-24")
        ui.number("y", value=round(y, 3), step=0.01, format="%.3f",
                  on_change=lambda e: move_selected(
                      to=(leg.curve.points[STATE["sel"]][0], float(e.value or 0)))
                  ).classes("w-24")
        ui.button(icon="delete", on_click=remove_selected) \
            .props("flat dense color=negative") \
            .tooltip("remove the selected point")


curve_view = None

if __name__ in {"__main__", "__mp_main__"}:
    ap = argparse.ArgumentParser()
    ap.add_argument("--native", action="store_true", help="desktop window")
    ap.add_argument("--port", type=int, default=8090)
    args, _ = ap.parse_known_args()
    nicegui_app.on_shutdown(BRIDGE.stop)
    ui.run(title=f"Sound xR OSC Bridge {__version__} (NiceGUI spike)",
           port=args.port, native=args.native, reload=False, show=False,
           window_size=(1280, 900) if args.native else None)
