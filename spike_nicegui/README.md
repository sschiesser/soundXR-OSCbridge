# NiceGUI spike

A throwaway experiment, kept separate from `soundxr_bridge/` so nothing in the
working app depends on it. Delete the folder and everything still runs.

```bash
pip install nicegui
python spike_nicegui/app.py            # browser at http://localhost:8090
python spike_nicegui/app.py --native   # desktop window (pip install pywebview)
```

Press **Simulate** a few times to inject fake traffic — you can judge the UI
without an OSC source. Tap a row in *Incoming OSC* to build a mapping from it.

## What it proves

It drives the **real engine** — `soundxr_bridge.bridge.Bridge`, the same
catalogue, the same `Leg`/`Route`, the same output bus — so the behaviour is
not mocked. In ~330 lines of Python it covers:

- live discovery table, updating over a websocket rather than polling
- tap an address, get one leg per numeric argument with learned ranges
- leg editor: target, argument, index, source argument, ranges, curve
- curve amount for exponential / logarithmic / s-curve: number box,
  slider and preset buttons, with the plot following live
- the breakpoint curve as inline SVG with the live input cursor: press a
  handle and drag it, press empty space to add one, edit the selected point
  numerically (x/y fields), delete it with the bin button
- **Learn range**: press it, move the controller, press stop — min/max come
  from the message stream (every message, not a sample), and old outliers
  are forgotten first. *Learn whole route* does every leg in one pass,
  each on its own argument
- transport: listen address and port, and host/port/enable per output
- the same page on desktop and tablet — the columns stack below `lg`

That is roughly the feature set of `gui/main_window.py` (≈900 lines) *and*
`web_ui.py` (≈330 lines of hand-written HTML/JS) together, in one file.

## What it does not prove

- **Touch dragging is unproven.** Mouse dragging works (press a handle, drag,
  release). On a tablet the browser may deliver only taps rather than a
  continuous drag — that is what the x/y number fields are for, and the thing
  worth testing on the iPad.
- **Nothing is packaged.** Native mode and `nicegui-pack` bring their own
  requirements: `reload=False`, `freeze_support()` as the first statement in
  the main guard, `native.find_open_port()`, and the EdgeChromium WebView2
  runtime on Windows.
- **No project save/load and no monitor pane.**
- **State is global**, shared by every connected browser. Correct for a remote,
  but it means two people editing at once see each other's changes with no
  locking — the same caveat the current web remote has.

## The decision this is for

Adopting it would mean deleting `soundxr_bridge/gui/` and `web_ui.py` and
maintaining one UI instead of two. The cost is a rewrite of the desktop window,
a proper curve widget with dragging, and new packaging. The engine, the
catalogue, the tests and the CI stay exactly as they are.
