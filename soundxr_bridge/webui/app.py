"""The Sound xR OSC Bridge user interface.

One NiceGUI page, served over HTTP: the same screen works in a browser on
the machine running the bridge and on a tablet elsewhere on the network.
It drives soundxr_bridge.bridge.Bridge; nothing about the OSC engine, the
catalogue or the mapping maths lives here.
"""

from __future__ import annotations

import threading
from collections import deque

from nicegui import app as nicegui_app
from nicegui import ui

from .. import __version__, presets
from ..bridge import Bridge
from ..mapping import CURVE_KINDS, Leg, Route
from ..project import Project

BRIDGE = Bridge(Project(input_port=10020))
CATALOG = BRIDGE.catalog
STATE: dict = {"leg": None, "route": None, "sel": None, "drag": False,
               "learn": None, "preset": None}

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


# ------------------------------------------------------------------- quitting
# Closing the browser tab leaves the app running on purpose — you may want it
# back. Quit is the deliberate way out, so the console window closes itself
# instead of needing Ctrl-C.
def _shutdown() -> None:
    """Stop the web server. Replaced in tests, which must survive the call."""
    nicegui_app.shutdown()


GOODBYE = ("document.body.innerHTML ="
           "'<div style=\"font-family:system-ui;color:#ddd;background:#121212;"
           "height:100vh;display:flex;align-items:center;justify-content:center;"
           "flex-direction:column;gap:.5rem\">"
           "<div style=\"font-size:1.2rem\">The bridge has stopped.</div>"
           "<div style=\"opacity:.6\">You can close this tab.</div></div>'")


def quit_app(delay: float = 0.4) -> None:
    """Stop listening, tell the page, then end the process.

    The short delay lets the goodbye message reach the browser: shutting the
    server down first would kill the socket carrying it.
    """
    BRIDGE.stop()
    try:
        ui.run_javascript(GOODBYE)
    except Exception:
        pass
    print("Quit from the interface - closing.")
    if delay <= 0:
        _shutdown()
        return
    try:
        ui.timer(delay, lambda: _shutdown(), once=True)
    except RuntimeError:
        # no client context: called from a script rather than a button
        threading.Timer(delay, _shutdown).start()


def confirm_quit() -> None:
    with ui.dialog() as dialog, ui.card():
        ui.label("Quit the bridge?").classes("text-base font-medium")
        ui.label("Listening stops and the application closes on the machine "
                 "running it — including when you press this from a tablet. "
                 "Your settings are saved automatically.") \
            .classes("text-xs opacity-70 max-w-xs")
        with ui.row().classes("ml-auto"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Quit now", on_click=lambda: (dialog.close(), quit_app())) \
                .props("unelevated color=negative")
    dialog.open()


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


PENDING: "deque[str]" = deque(maxlen=500)      # lines waiting to reach the log
MONITOR_ON: dict = {"enabled": True}


def set_monitor(enabled: bool) -> None:
    """Turn the output log on or off.

    A fast tracker feed can push thousands of lines a minute over the websocket
    to every connected browser; switching it off costs nothing and keeps a
    tablet responsive during a show.
    """
    MONITOR_ON["enabled"] = bool(enabled)
    if not enabled:
        PENDING.clear()        # do not flush a backlog when it is turned back on


def _log_output(messages: list) -> None:
    if not MONITOR_ON["enabled"]:
        return
    for address, args, proto in messages:
        pretty = " ".join(f"{a:g}" if isinstance(a, float) else str(a) for a in args)
        dest = BRIDGE.sender.destinations.get(proto)
        note = "" if (dest and dest.enabled) else f"   <-- NOT SENT: {proto} output is off"
        PENDING.append(f"[{proto}] {address} {pretty}{note}")


BRIDGE.on_output = _log_output


def send_all() -> None:
    messages = BRIDGE.engine.flush(force=True)
    BRIDGE.sender.send_many(messages)
    _log_output(messages)
    ui.notify(f"Forced {len(messages)} message(s)")


def simulate() -> None:
    """Inject traffic, exactly as the receiver would, so the whole chain can be
    exercised without an OSC source: the discovery table fills, mappings
    compute, and the monitor shows what would go to the DME."""
    import math
    import time
    t = time.time()
    fake = [
        ("/mocap/head", (2.0 * math.sin(t), 1.2 * math.cos(t * 0.7),
                         1.0 + math.sin(t * 0.3))),
        ("/ctl/fader/1", (0.5 + 0.5 * math.sin(t * 0.4),)),
    ]
    for address, args in fake:
        BRIDGE.discovery.observe(address, args, "simulated")
        BRIDGE.engine.handle(address, list(args))   # drive the mappings too


preset_names = presets.names


def save_preset(name: str | None = None) -> None:
    name = presets.safe_name(name or STATE.get("preset") or "untitled")
    presets.save(BRIDGE.sync_project(), name)
    STATE["preset"] = name
    ui.notify(f"Saved preset '{name}'", type="positive")
    preset_bar.refresh()
    presets_card.refresh()


def load_preset(name: str | None) -> None:
    """Apply a saved preset without touching whether we are listening.

    Deliberately not Bridge.apply_project(): that restarts the receiver, which
    would start listening even when the bridge is stopped.
    """
    if not name:
        return
    path = presets.path_for(name)
    if not path.is_file():
        ui.notify(f"No preset '{name}'", type="warning")
        return
    project = Project.load(path)
    was_running = BRIDGE.receiver.running
    BRIDGE.project = project
    BRIDGE.engine.routes = project.routes
    BRIDGE.engine.reset()
    BRIDGE.engine.bus.clear()
    BRIDGE.sender.load_dict(project.destinations)
    if was_running:
        try:
            BRIDGE.receiver.restart(project.input_host, project.input_port)
        except OSError as exc:
            ui.notify(f"Loaded, but cannot listen: {exc}", type="negative", timeout=8000)
    STATE.update(preset=name, leg=None, route=None, sel=None, learn=None)
    ui.notify(f"Loaded '{name}' — {len(project.routes)} route(s)")
    for part in (preset_bar, presets_card, transport, mappings, editor):
        part.refresh()


def delete_preset(name: str | None) -> None:
    if not name:
        return
    if presets.delete(name):
        ui.notify(f"Deleted '{name}'")
    if STATE.get("preset") == name:
        STATE["preset"] = None
    preset_bar.refresh()
    presets_card.refresh()


LEARN_SECONDS = 20.0


def start_learning(whole_route: bool) -> None:
    """Watch the incoming values and take their min/max from the message stream.

    Clearing the stored statistics first means the range comes from what
    happens *now* — every message counted, not a 4 Hz sample of it — so a quick
    flick to the extremes is enough and old outliers are forgotten.
    """
    import time
    route, leg = STATE["route"], STATE["leg"]
    if route is None or leg is None:
        return
    BRIDGE.discovery.forget(route.source)
    STATE["learn"] = {"route": route, "legs": list(route.legs) if whole_route else [leg],
                      "until": time.time() + LEARN_SECONDS}
    ui.notify("Move the controller through its full range…")
    editor.refresh()


def finish_learning(apply: bool = True) -> None:
    job = STATE["learn"]
    STATE["learn"] = None
    if not job:
        return
    info = BRIDGE.discovery.get(job["route"].source)
    applied = 0
    for leg in job["legs"]:
        rng = info.observed_range(job["route"].index_for(leg)) if info else None
        if apply and rng and rng[0] != rng[1]:
            leg.in_min, leg.in_max = rng
            leg.reset()
            applied += 1
    ui.notify(f"Learned {applied} range(s)" if applied else
              "Nothing learned — no values moved", type="positive" if applied else "warning")
    editor.refresh()
    mappings.refresh()


def learn_tick() -> str:
    """Called by the UI timer; returns the status line and auto-stops."""
    import time
    job = STATE["learn"]
    if not job:
        return ""
    if time.time() > job["until"]:
        finish_learning()
        return ""
    info = BRIDGE.discovery.get(job["route"].source)
    parts = []
    for leg in job["legs"]:
        rng = info.observed_range(job["route"].index_for(leg)) if info else None
        index = job["route"].index_for(leg)
        parts.append(f"arg {index}: {rng[0]:+.3f} … {rng[1]:+.3f}" if rng
                     else f"arg {index}: —")
    left = job["until"] - time.time()
    return f"learning {left:.0f}s   " + "   ".join(parts)


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


def add_leg(route: Route) -> None:
    """A new leg on the same target, taking the next free argument slot."""
    target = CATALOG.get("adm.obj.xyz")
    source_arg = None
    in_min, in_max = 0.0, 1.0
    if route.legs:
        last = route.legs[-1]
        target = CATALOG.targets.get(last.target_id, target)
        in_min, in_max = last.in_min, last.in_max
        source_arg = None if last.source_arg is None else last.source_arg + 1
    used = {l.arg for l in route.legs if l.target_id == target.id}
    free = [a for a in target.args if a.name not in used] or list(target.args)
    spec = free[0]
    leg = Leg(target.id, spec.name, {i.name: i.default for i in target.indices},
              source_arg=source_arg, in_min=in_min, in_max=in_max,
              out_min=spec.min, out_max=spec.max)
    route.legs.append(leg)
    select_leg(route, leg)
    mappings.refresh()


def duplicate_leg(route: Route, leg: Leg) -> None:
    clone = Leg.from_dict(leg.to_dict())
    route.legs.insert(route.legs.index(leg) + 1, clone)
    select_leg(route, clone)
    mappings.refresh()


def remove_leg(route: Route, leg: Leg) -> None:
    if leg in route.legs:
        route.legs.remove(leg)
        BRIDGE.engine.bus.clear()
    if STATE["leg"] is leg:
        STATE["leg"] = route.legs[0] if route.legs else None
    mappings.refresh()
    editor.refresh()


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


AMOUNT_W: dict = {"number": None, "slider": None}
LEARN_LABEL: dict = {"w": None}


def set_amount(value, source: str = "") -> None:
    """Steepness of the exponential / logarithmic / s curves.

    Never rebuilds the widgets: refreshing them mid-drag destroys the slider
    the pointer is holding, which is why dragging did nothing before.
    """
    leg = STATE["leg"]
    if leg is None or value is None or STATE.get("syncing"):
        return
    leg.curve.amount = max(0.05, min(12.0, float(value)))
    leg.reset()
    _redraw(leg)
    STATE["syncing"] = True                 # keep the twin widget in step
    try:
        if source != "number" and AMOUNT_W["number"] is not None:
            AMOUNT_W["number"].value = round(leg.curve.amount, 2)
        if source != "slider" and AMOUNT_W["slider"] is not None:
            AMOUNT_W["slider"].value = min(6.0, leg.curve.amount)
    finally:
        STATE["syncing"] = False


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
def main_page() -> None:
    ui.dark_mode(True)
    ui.query("body").style("font-family: system-ui")

    with ui.header().classes("items-center gap-4 py-2"):
        status = ui.icon("circle", size="14px")
        ui.label(f"Sound xR OSC Bridge {__version__}").classes("text-lg font-medium")
        ui.label("OSC → Sound xR Image").classes("text-xs opacity-60")
        run_btn = ui.button("Start", on_click=start_stop).props("unelevated")
        preset_bar()
        counters = ui.label("").classes("ml-auto text-sm opacity-80")
        ui.button("Quit", on_click=confirm_quit) \
            .props("flat dense color=white") \
            .tooltip("stop the bridge and close the application")

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
            presets_card()
            monitor_card()

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
        if LEARN_LABEL["w"] is not None:
            LEARN_LABEL["w"].text = learn_tick()
        log = MONITOR_LOG["w"]
        if log is not None and PENDING:
            while PENDING:
                log.push(PENDING.popleft())

    ui.timer(0.25, refresh)


def monitor_card() -> None:
    with ui.card().classes("w-full mt-4"):
        with ui.row().classes("items-center w-full"):
            ui.label("Output monitor").classes("text-base font-medium")
            ui.switch(value=MONITOR_ON["enabled"],
                      on_change=lambda e: set_monitor(e.value)) \
                .tooltip("log every outgoing message — turn it off at high "
                         "message rates")
            ui.space()
            ui.button("Clear", on_click=lambda: (PENDING.clear(), _clear_log())) \
                .props("flat dense size=sm")
        MONITOR_LOG["w"] = ui.log(max_lines=300).classes("w-full h-40 text-xs")


MONITOR_LOG: dict = {"w": None}


def _clear_log() -> None:
    if MONITOR_LOG["w"] is not None:
        MONITOR_LOG["w"].clear()


@ui.refreshable
def preset_bar() -> None:
    """Always-visible preset switcher: pick one and it loads immediately."""
    names = preset_names()
    ui.select(names or [], value=STATE.get("preset"), label="Preset",
              on_change=lambda e: load_preset(e.value)) \
        .props("dense options-dense dark").classes("w-56") \
        .tooltip("choosing a preset applies it straight away")
    ui.button(icon="save", on_click=lambda: save_preset()) \
        .props("flat dense").tooltip("save over the current preset")


@ui.refreshable
def presets_card() -> None:
    with ui.card().classes("w-full mt-4"):
        with ui.row().classes("items-center w-full"):
            ui.label("Presets").classes("text-base font-medium")
            ui.space()
            ui.label(f"current: {STATE.get('preset') or '—'}").classes("text-xs opacity-60")
        with ui.row().classes("w-full gap-2 items-end"):
            # mirror every keystroke: reading .value at click time can race the
            # browser->server update and silently save as "untitled"
            typed = {"name": ""}

            def do_save() -> None:
                save_preset(typed["name"] or name_box.value)
                typed["name"] = ""
                name_box.set_value("")

            name_box = ui.input(
                "Save as", placeholder="show name",
                on_change=lambda e: typed.__setitem__("name", e.value or "")) \
                .classes("flex-1")
            name_box.on("keydown.enter", do_save)
            ui.button("Save", icon="save", on_click=do_save).props("unelevated dense")
        names = preset_names()
        if not names:
            ui.label("No presets yet — build a mapping and save it.") \
                .classes("text-xs opacity-60")
        for name in names:
            with ui.row().classes("w-full items-center gap-2"):
                ui.icon("bookmark", size="16px").classes(
                    "text-blue-400" if name == STATE.get("preset") else "opacity-40")
                ui.label(name).classes("text-sm flex-1")
                ui.button("Load", on_click=lambda n=name: load_preset(n)) \
                    .props("flat dense size=sm")
                ui.button(icon="delete", on_click=lambda n=name: delete_preset(n)) \
                    .props("flat dense size=sm color=negative")
        ui.label("Settings are also written to _autosave.json when the app closes "
                 "and restored on the next start.").classes("text-xs opacity-60")


@ui.refreshable
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
        with ui.row().classes("w-full gap-2 items-center"):
            ui.number("Send rate", value=int(BRIDGE.project.send_rate_hz), format="%d",
                      min=1, max=500, suffix="Hz",
                      on_change=lambda e: setattr(BRIDGE.project, "send_rate_hz",
                                                  float(e.value or 100))).classes("w-32") \
                .tooltip("how often changed values are flushed to the outputs")
            ui.button("Send all now", icon="send", on_click=send_all).props("flat dense") \
                .tooltip("force every mapped parameter out, even if unchanged")
        ui.label("Changes apply immediately; the input port restarts the "
                 "receiver while it is running.").classes("text-xs opacity-60")


@ui.refreshable
def mappings() -> None:
    with ui.card().classes("w-full"):
        ui.label("Mappings").classes("text-base font-medium")
        if not BRIDGE.engine.routes:
            ui.label("Nothing mapped yet.").classes("text-xs opacity-60")
        for route in BRIDGE.engine.routes:
            with ui.expansion(route.label(), value=True).classes("w-full"):
                with ui.row().classes("w-full gap-2 items-end"):
                    ui.input("Source address", value=route.source,
                             on_change=lambda e, r=route: (
                                 setattr(r, "source", e.value.strip() or "/*"),
                                 BRIDGE.engine.bus.clear())) \
                        .classes("flex-1").tooltip(
                            "wildcards allowed: /track/*/xyz or /obj/?/gain")
                    ui.number("Default arg", value=route.arg_index, format="%d",
                              on_change=lambda e, r=route: setattr(
                                  r, "arg_index", int(e.value or 0))).classes("w-28") \
                        .tooltip("used by legs whose source argument is -1")
                    ui.switch(value=route.enabled,
                              on_change=lambda e, r=route: setattr(r, "enabled", e.value)) \
                        .tooltip("route enabled")
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
                        ui.button(icon="content_copy",
                                  on_click=lambda r=route, l=leg: duplicate_leg(r, l)) \
                            .props("flat dense size=sm").tooltip("duplicate this leg")
                        ui.button(icon="close",
                                  on_click=lambda r=route, l=leg: remove_leg(r, l)) \
                            .props("flat dense size=sm color=negative")
                with ui.row().classes("gap-2"):
                    ui.button("Add leg", icon="add",
                              on_click=lambda r=route: add_leg(r)).props("flat dense")
                    ui.button("Remove route", icon="delete",
                              on_click=lambda r=route: delete_route(r)) \
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
        with ui.row().classes("w-full gap-2 items-center"):
            if STATE["learn"] is None:
                ui.button("Learn this leg", icon="radio_button_checked",
                          on_click=lambda: start_learning(False)) \
                    .props("flat dense").tooltip(
                        "watch the incoming values and take min/max from them")
                ui.button("Learn whole route", icon="playlist_add_check",
                          on_click=lambda: start_learning(True)) \
                    .props("flat dense").tooltip(
                        "one pass sets the range of every leg, each on its own argument")
            else:
                ui.button("Stop and apply", icon="stop",
                          on_click=lambda: finish_learning(True)).props("unelevated dense")
                ui.button("Cancel", on_click=lambda: finish_learning(False)) \
                    .props("flat dense")
        learn_status = ui.label("").classes("text-xs font-mono opacity-80")
        LEARN_LABEL["w"] = learn_status

        with ui.row().classes("w-full gap-3 items-center"):
            ui.switch("enabled", value=leg.enabled,
                      on_change=lambda e: (setattr(leg, "enabled", e.value),
                                           mappings.refresh()))
            ui.switch("invert", value=leg.invert,
                      on_change=lambda e: (setattr(leg, "invert", e.value), leg.reset(),
                                           _redraw(leg)))
            ui.switch("clamp input", value=leg.clamp_input,
                      on_change=lambda e: setattr(leg, "clamp_input", e.value))
        with ui.row().classes("w-full gap-2"):
            ui.number("Deadzone", value=leg.deadzone, step=0.01, min=0.0, max=0.99,
                      format="%.3f",
                      on_change=lambda e: (setattr(leg, "deadzone", float(e.value or 0)),
                                           leg.reset(), _redraw(leg))).classes("flex-1") \
                .tooltip("ignore this fraction of the input span around its centre")
            ui.number("Smoothing", value=leg.smoothing, step=0.05, min=0.0, max=0.99,
                      format="%.3f",
                      on_change=lambda e: (setattr(leg, "smoothing", float(e.value or 0)),
                                           leg.reset())).classes("flex-1") \
                .tooltip("one pole filter applied per incoming message")
            ui.number("Quantise", value=leg.quantize, step=0.01, min=0.0,
                      format="%.3f",
                      on_change=lambda e: setattr(leg, "quantize", float(e.value or 0))) \
                .classes("flex-1").tooltip("round the output to this step, 0 = off")

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
        else:
            amount_controls()


HINTS = {
    "exponential": "1 = linear · higher = slow start, fast finish",
    "logarithmic": "1 = linear · higher = fast start, slow finish",
    "scurve": "1 = linear · higher = flatter middle, steeper ends",
}


@ui.refreshable
def amount_controls() -> None:
    leg = STATE["leg"]
    AMOUNT_W["number"] = AMOUNT_W["slider"] = None
    if leg is None or leg.curve.kind not in HINTS:
        return
    with ui.row().classes("items-center gap-3 w-full"):
        AMOUNT_W["number"] = ui.number(
            "Amount", value=round(leg.curve.amount, 2), step=0.1,
            min=0.05, max=12.0, format="%.2f",
            on_change=lambda e: set_amount(e.value, "number")).classes("w-28")
        AMOUNT_W["slider"] = ui.slider(
            min=0.1, max=6.0, step=0.05, value=min(6.0, leg.curve.amount),
            on_change=lambda e: set_amount(e.value, "slider")) \
            .props("label-always").classes("flex-1")
    with ui.row().classes("gap-1"):
        for preset in (0.5, 1.0, 2.0, 3.0, 4.0):
            ui.button(f"{preset:g}", on_click=lambda p=preset: set_amount(p, "preset")) \
                .props("flat dense size=sm")
        ui.label(HINTS[leg.curve.kind]).classes("text-xs opacity-60 self-center ml-2")


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

def _autosave() -> None:
    try:
        BRIDGE.sync_project().save(presets.autosave_path())
    except Exception:
        pass
    BRIDGE.stop()


def _restore_autosave() -> int:
    path = presets.autosave_path()
    if not path.is_file():
        return 0
    try:
        restored = Project.load(path)
    except Exception:
        return 0
    BRIDGE.project = restored
    BRIDGE.engine.routes = restored.routes
    BRIDGE.sender.load_dict(restored.destinations)
    return len(restored.routes)


def create_ui() -> None:
    """Register the page. Safe to call on every start, including under test."""
    ui.page("/")(main_page)


def run(port: int = 8080, host: str = "0.0.0.0", show: bool = True,
        project: Project | None = None, start: bool = False) -> None:
    """Serve the interface. Called by ``python -m soundxr_bridge``."""
    from ..osc_io import local_addresses

    if project is not None:
        BRIDGE.project = project
        BRIDGE.engine.routes = project.routes
        BRIDGE.sender.load_dict(project.destinations)
    else:
        count = _restore_autosave()
        if count:
            print(f"Restored {count} route(s) from your last session")

    if start:
        try:
            BRIDGE.start()
            print(f"Listening on {BRIDGE.project.input_host}:"
                  f"{BRIDGE.project.input_port}")
        except OSError as exc:
            print(f"Cannot listen on {BRIDGE.project.input_host}:"
                  f"{BRIDGE.project.input_port} - {exc}")

    print(f"Presets and autosave live in {presets.preset_dir()}")
    for ip in local_addresses():
        print(f"  open on this machine or a tablet:  http://{ip}:{port}")

    create_ui()
    nicegui_app.on_shutdown(_autosave)
    ui.run(title=f"Sound xR OSC Bridge {__version__}", port=port, host=host,
           show=show, reload=False, favicon="\N{SPEAKER WITH THREE SOUND WAVES}",
           dark=True)
