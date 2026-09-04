# Sound xR OSC Bridge

Receives arbitrary OSC, learns every address it sees, and maps it onto Yamaha
**Sound xR Image** parameters — ADM-OSC and the native `/yosc:req` protocol —
with non-linear, one-to-many mappings you build in a GUI.

![workflow](docs/screenshot.png)

## Install

```bash
pip install -r requirements.txt      # python-osc + PySide6
python -m soundxr_bridge             # start the GUI
python -m soundxr_bridge examples/example_tracker.json
```

Python 3.10 or newer. Run it on any machine on the same network as the DME
(Sound xR Image accepts up to 8 remote controllers).

## The four requirements, and where they live

**1 · Auto-discovery of incoming OSC**
The receiver installs a catch-all handler, so nothing has to be declared in
advance. The left table fills as messages arrive and shows, per address: the
OSC type tags, message rate, count, the last argument values and the **min/max
range observed so far** — that observed range is what the *Learn input range*
button in the editor uses, so you can just wave the controller around and let
the app work out its endpoints. `Freeze` stops the table updating while you
work; `Clear list` forgets everything.

**2 · Selection list of available Sound xR addresses**
`Choose address…` opens a searchable, grouped list of every target in
`soundxr_bridge/targets.json`, with its address template, argument types,
ranges and units. Index placeholders (object number, component ID, speaker
number) become spin boxes, and the resolved address is shown live.

**3 · GUI mapping from input to output**
A **route** is one incoming address (wildcards allowed: `/track/*/xyz`) plus one
argument index. Each route holds one or more **legs**, and each leg writes one
argument of one Sound xR parameter. Double-click a discovered address, or press
`Map selected →`, and a route with a sensible default leg appears.

**Multi-argument messages**
A leg reads whichever argument of the incoming message you point it at:
*Source argument* in the leg editor, `route default` meaning the index set on
the route. So a single `/mocap/head 1.2 0.4 2.1` can drive x, y and z — one leg
per argument. Pressing *Map selected →* on an address that carries several
numbers builds those legs for you, in order, with each argument's observed
range already filled in.

**4 · Mappings are not only linear or 1-to-1**
Per leg: independent input and output ranges, invert, centre deadzone,
one-pole smoothing, output quantisation, and a transfer curve — `linear`,
`exponential`, `logarithmic`, `scurve` (all with an adjustable amount) or
`breakpoints`, an editable point table you drag directly on the curve display
(double-click adds a point, right-click removes one). The red cursor on the
curve shows where the live input currently sits.

Fan-out is the default shape, not an afterthought: one input can drive x, width
and level at once, each with its own range and curve. The reverse also works —
several different incoming addresses can write x, y and z of the same object;
the output bus keeps the other arguments at their last value and coalesces
them into a single `/adm/obj/n/xyz` message per send tick.

## Signal path of one leg

```
raw argument
  → clamp to input range          (optional)
  → normalise to 0…1
  → invert                        (optional)
  → deadzone around the centre    (optional)
  → curve                         linear | exponential | logarithmic | scurve | breakpoints
  → scale to output range
  → quantise                      (optional)
  → smooth (one pole, per message)
  → clamp + cast to the parameter's own type and range
```

Outgoing messages are collected and sent on a timer (default 100 Hz) rather
than per input message, which coalesces multi-argument targets and keeps a
fast tracker feed from flooding the DME. Nothing is sent when nothing changed.

## Transport

| | default | notes |
|---|---|---|
| Input | UDP 9000, all interfaces | any OSC source |
| ADM-OSC out | UDP 4002 | normalised object control |
| Native yosc out | UDP 50528 | `/yosc:req/set/PROC:Component/…` |
| Custom out | UDP 9001, off | for targets you add yourself |

Set the DME's IP as the host for both outputs; enable only the protocol you
actually use.

## The target catalogue

`soundxr_bridge/targets.json` is plain JSON and is meant to be edited. Each
entry is an address template with index placeholders and typed arguments:

```json
{
  "id": "adm.obj.xyz",
  "protocol": "adm",
  "group": "ADM-OSC / Object",
  "label": "Position X/Y/Z (normalised)",
  "address": "/adm/obj/{obj}/xyz",
  "indices": [{"name": "obj", "label": "Object", "min": 1, "max": 128, "default": 1}],
  "args": [{"name": "x", "type": "float", "min": -1.0, "max": 1.0, "default": 0.0}]
}
```

`"scale"` on an argument only affects the display (the native fader level is
sent as dB × 100, so the editor shows you `-4000 = -40 dB` while the wire value
stays an integer). Add your own entries, or keep them in a separate file and
merge it at runtime with *File → Load extra target catalogue…* (the path is
remembered in the project).

> **Check the addresses before a show.** The catalogue was built from Yamaha's
> published *Sound xR Image on DME OSC Specifications v1.0.0*. Entries flagged
> `"verified": false` — the two reverb parameters and scene recall — were
> reconstructed from summary tables and are almost certainly not spelled right
> for your firmware. Fix them in the JSON once and they are correct for good.

## Projects and headless operation

Everything — ports, destinations, routes, legs, curves — saves to one JSON
file. Once a show is built you can run it without the GUI:

```bash
python -m soundxr_bridge examples/example_tracker.json --headless
```

## Tests

```bash
python -m pytest tests -q      # 20 tests: curve maths, fan-out, coalescing,
                               # UDP loopback, offscreen GUI smoke test
```

`tests/test_loopback.py` runs the whole chain over real sockets: it sends OSC
into the bridge and asserts on the transformed OSC that comes out the other
side.

## Layout

```
soundxr_bridge/
  targets.json      the Sound xR address catalogue (edit me)
  catalog.py        catalogue loading, address templating, units
  osc_io.py         learning receiver, per-protocol senders
  mapping.py        curves, legs, routes, the output bus
  bridge.py         receiver → engine → sender, plus headless runner
  project.py        save/load
  gui/              main window, target picker, curve editor
```

## Running it in VS Code

The workspace is preconfigured — `.vscode/` holds the launch, task and editor
settings, and `setup.ps1` builds the environment.

1. **Set up the environment, once.**
   `Ctrl+Shift+B` (or *Terminal → Run Build Task…*) runs
   *Setup: create .venv and install dependencies*: it creates `.venv` beside
   this file, installs `python-osc`, `PySide6` and `pytest`, and finishes by
   running the test suite. Equivalent by hand, in the VS Code terminal:

   ```powershell
   .\setup.ps1
   ```

   If PowerShell refuses the script, run
   `powershell -ExecutionPolicy Bypass -File .\setup.ps1`.

2. **Pick the interpreter.** `Ctrl+Shift+P` → *Python: Select Interpreter* →
   `.\.venv\Scripts\python.exe`. VS Code usually offers it automatically once
   the venv exists; it is already the default in `.vscode/settings.json`.

3. **Run.** `F5` starts the GUI (*1 · Bridge GUI*). The dropdown at the top of
   the Run and Debug panel also offers the example project, headless mode, the
   test suite, and the two helper tools below.

### Trying it without any hardware

`tools/` holds a fake source and a fake device so the whole chain can be
exercised on one laptop:

```powershell
.\.venv\Scripts\python.exe tools\listen_osc.py --port 4002     # pretend to be the DME
.\.venv\Scripts\python.exe tools\send_test_osc.py --port 9000  # pretend to be a tracker
```

Then start the GUI, set both output hosts to `127.0.0.1`, press **Start**, and
you will see `/tracker/1/x`, `/tracker/1/y`, `/ctl/fader/1` and `/track/5/mute`
appear in the discovery table, and the mapped `/adm/obj/…` messages arrive in
the listener window. The **Loopback demo** compound in the Run panel launches
all three at once.

### If something goes wrong

| Symptom | Fix |
|---|---|
| `python`/`py` not found in `setup.ps1` | Install Python 3.10+ from python.org with *Add python.exe to PATH* ticked, reopen VS Code. |
| `ModuleNotFoundError: PySide6` | Wrong interpreter selected — pick `.venv\Scripts\python.exe`. |
| Nothing appears in the discovery table | Windows Firewall prompt on first run: allow Python on the private network. Check the sender is aimed at this machine's IP and the port in *Input*. |
| A leg reads the wrong value of a multi-argument message | Set *Source argument* on the leg (0, 1, 2 ...) instead of leaving it on `route default`. |
| Nothing arrives on the yosc side | Two separate destinations: ADM-OSC goes to 4002, native yosc to 50528. Check *Output · Native (yosc)* is **enabled** in the Transport bar, and listen on 50528 — port 4002 will never show yosc traffic. The monitor now marks messages it could not send. |
| `[WinError 10048]` on Start | Another program already listens on that input port; change it. |
| Debug config errors on an old VS Code | Update the Python extension, or change `"type": "debugpy"` to `"type": "python"` in `.vscode/launch.json`. |
