"""Main window: discovery, routing tree, leg editor, monitor."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QDockWidget, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSpinBox, QSplitter,
                               QStackedWidget, QTableWidget, QTableWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from .. import __version__
from ..bridge import Bridge
from ..catalog import Catalog
from ..osc_io import local_addresses, port_conflict
from ..mapping import CURVE_KINDS, Curve, Leg, Route
from ..project import Project
from .curve_editor import CurveEditor
from .target_picker import TargetPickerDialog

ROLE_KIND = Qt.UserRole + 1     # "route" | "leg"
ROLE_ROUTE = Qt.UserRole + 2
ROLE_LEG = Qt.UserRole + 3


def dspin(minimum=-1e9, maximum=1e9, decimals=4, step=0.1) -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setRange(minimum, maximum)
    w.setDecimals(decimals)
    w.setSingleStep(step)
    w.setKeyboardTracking(False)
    return w


class MainWindow(QMainWindow):
    def __init__(self, project: Project | None = None, catalog: Catalog | None = None):
        super().__init__()
        self.setWindowTitle(f"Sound xR OSC Bridge {__version__}")
        self.resize(1360, 880)

        self.bridge = Bridge(project or Project(), catalog)
        self.bridge.on_output = self._log_output
        self._loading = False

        self._build_ui()
        self._build_menu()
        self._apply_project_to_ui()

        self.tx_timer = QTimer(self)
        self.tx_timer.timeout.connect(self._tick)
        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._refresh_ui)
        self.ui_timer.start(200)

        self._note(f"Sound xR OSC Bridge {__version__} ready. "
                   f"Set the input port, then press Start.")
        self.statusBar().showMessage("Idle - press Start to listen.")

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QSplitter(Qt.Horizontal)

        # ---- left: discovery ----
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(6, 6, 6, 6)
        lv.addWidget(QLabel("<b>Incoming OSC (auto-discovered)</b>"))
        self.disc_table = QTableWidget(0, 6)
        self.disc_table.setHorizontalHeaderLabels(
            ["Address", "Types", "Hz", "Count", "Last values", "Observed range"])
        self.disc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.disc_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.disc_table.verticalHeader().setVisible(False)
        self.disc_table.setWordWrap(False)
        header = self.disc_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        self.disc_table.setColumnWidth(0, 200)
        for c in (1, 2, 3):
            header.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.disc_table.itemDoubleClicked.connect(lambda *_: self._new_route_from_discovery())
        lv.addWidget(self.disc_table, 1)
        row = QHBoxLayout()
        b_map = QPushButton("Map selected →")
        b_map.clicked.connect(self._new_route_from_discovery)
        b_clear = QPushButton("Clear list")
        b_clear.clicked.connect(self.bridge.discovery.clear)
        self.chk_freeze = QCheckBox("Freeze")
        row.addWidget(b_map)
        row.addWidget(b_clear)
        row.addWidget(self.chk_freeze)
        row.addStretch(1)
        lv.addLayout(row)
        left.setMinimumWidth(380)

        # ---- middle: routes ----
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(6, 6, 6, 6)
        mv.addWidget(QLabel("<b>Mappings</b>  <span style='color:gray'>"
                            "(route = one input · leg = one Sound xR parameter)</span>"))
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Source / Target", "Detail", "Mapping"])
        self.tree.setColumnWidth(0, 230)
        self.tree.setColumnWidth(1, 210)
        self.tree.header().setStretchLastSection(True)
        self.tree.currentItemChanged.connect(self._on_tree_selection)
        self.tree.itemChanged.connect(self._on_tree_item_changed)
        mv.addWidget(self.tree, 1)
        row = QHBoxLayout()
        for text, slot in (("Add route", self._add_route),
                           ("Add leg", self._add_leg),
                           ("Duplicate", self._duplicate),
                           ("Remove", self._remove_selected)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        mv.addLayout(row)

        # ---- right: editor ----
        self.editor_stack = QStackedWidget()
        self.editor_stack.addWidget(QLabel("  Select a route or a leg."))
        self.route_editor = self._build_route_editor()
        self.leg_editor = self._build_leg_editor()
        self.editor_stack.addWidget(self.route_editor)
        self.editor_stack.addWidget(self._scroll(self.leg_editor))

        central.addWidget(left)
        central.addWidget(mid)
        central.addWidget(self.editor_stack)
        central.setStretchFactor(0, 3)
        central.setStretchFactor(1, 4)
        central.setStretchFactor(2, 4)
        central.setSizes([380, 430, 520])
        self.setCentralWidget(central)

        # ---- docks ----
        self.setDockNestingEnabled(True)
        self.addDockWidget(Qt.TopDockWidgetArea, self._build_transport_dock())
        monitor_dock = self._build_monitor_dock()
        self.addDockWidget(Qt.BottomDockWidgetArea, monitor_dock)
        self.resizeDocks([monitor_dock], [150], Qt.Vertical)

    def _scroll(self, w: QWidget) -> QScrollArea:
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setWidget(w)
        return s

    def _build_transport_dock(self) -> QDockWidget:
        dock = QDockWidget("Transport")
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        w = QWidget()
        h = QHBoxLayout(w)

        g_in = QGroupBox("Input")
        f = QFormLayout(g_in)
        self.in_host = QLineEdit("0.0.0.0")
        self.in_host.setToolTip(
            "Which network adapter to listen on.\n"
            "0.0.0.0 = all of them, and the only setting that receives broadcasts.\n"
            "Put your own IP here only if you deliberately want one adapter.")
        self.in_port = QSpinBox()
        self.in_port.setRange(1, 65535)
        f.addRow("Listen on", self.in_host)
        f.addRow("Port", self.in_port)
        h.addWidget(g_in)

        self.dest_widgets: dict[str, tuple[QLineEdit, QSpinBox, QCheckBox]] = {}
        for proto in ("adm", "yosc", "custom"):
            g = QGroupBox(f"Output · {self.bridge.catalog.protocol_label(proto)}")
            f = QFormLayout(g)
            host = QLineEdit("127.0.0.1")
            port = QSpinBox()
            port.setRange(1, 65535)
            chk = QCheckBox("enabled")
            f.addRow("Host", host)
            f.addRow("Port", port)
            f.addRow("", chk)
            self.dest_widgets[proto] = (host, port, chk)
            h.addWidget(g)

        g_run = QGroupBox("Run")
        f = QFormLayout(g_run)
        self.rate = QSpinBox()
        self.rate.setRange(1, 500)
        self.rate.setSuffix(" Hz")
        self.btn_start = QPushButton("Start")
        self.btn_start.setCheckable(True)
        self.btn_start.toggled.connect(self._toggle_run)
        b_force = QPushButton("Send all now")
        b_force.clicked.connect(lambda: self._tick(force=True))
        f.addRow("Send rate", self.rate)
        f.addRow(self.btn_start)
        f.addRow(b_force)
        h.addWidget(g_run)
        h.addStretch(1)

        for widget in (self.in_host, self.in_port, self.rate):
            (widget.editingFinished if hasattr(widget, "editingFinished")
             else widget.valueChanged).connect(self._transport_changed)
        for host, port, chk in self.dest_widgets.values():
            host.editingFinished.connect(self._transport_changed)
            port.valueChanged.connect(self._transport_changed)
            chk.toggled.connect(self._transport_changed)

        dock.setWidget(w)
        return dock

    def _build_monitor_dock(self) -> QDockWidget:
        dock = QDockWidget("Output monitor")
        w = QWidget()
        v = QVBoxLayout(w)
        self.monitor = QPlainTextEdit()
        self.monitor.setReadOnly(True)
        self.monitor.setMaximumBlockCount(500)
        self.monitor.setStyleSheet("font-family: monospace;")
        v.addWidget(self.monitor)
        row = QHBoxLayout()
        self.chk_monitor = QCheckBox("Log outgoing messages")
        self.chk_monitor.setChecked(True)
        b = QPushButton("Clear")
        b.clicked.connect(self.monitor.clear)
        row.addWidget(self.chk_monitor)
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        dock.setWidget(w)
        return dock

    # -- route editor ---------------------------------------------------
    def _build_route_editor(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.r_name = QLineEdit()
        self.r_source = QComboBox()
        self.r_source.setEditable(True)
        self.r_source.setMinimumWidth(260)
        self.r_arg = QSpinBox()
        self.r_arg.setRange(0, 63)
        self.r_enabled = QCheckBox("route enabled")
        self.r_info = QLabel("")
        self.r_info.setWordWrap(True)
        f.addRow("Name", self.r_name)
        f.addRow("Source address", self.r_source)
        f.addRow("Argument index", self.r_arg)
        f.addRow("", self.r_enabled)
        f.addRow("Observed", self.r_info)
        hint = QLabel("Wildcards allowed: <tt>/track/*/xyz</tt>, <tt>/obj/?/gain</tt>.")
        hint.setStyleSheet("color: palette(mid);")
        f.addRow("", hint)

        self.r_name.editingFinished.connect(self._route_fields_changed)
        self.r_source.currentTextChanged.connect(self._route_fields_changed)
        self.r_arg.valueChanged.connect(self._route_fields_changed)
        self.r_enabled.toggled.connect(self._route_fields_changed)
        return w

    # -- leg editor -----------------------------------------------------
    def _build_leg_editor(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        g_t = QGroupBox("Sound xR target")
        f = QFormLayout(g_t)
        self.l_target = QLineEdit()
        self.l_target.setReadOnly(True)
        b_pick = QPushButton("Choose address…")
        b_pick.clicked.connect(self._pick_target)
        self.l_arg = QComboBox()
        self.l_addr_preview = QLabel("")
        self.l_addr_preview.setWordWrap(True)
        self.l_addr_preview.setStyleSheet("font-family: monospace; color: palette(mid);")
        self.index_form = QFormLayout()
        f.addRow("Parameter", self.l_target)
        f.addRow("", b_pick)
        f.addRow(self.index_form)
        f.addRow("Argument", self.l_arg)
        f.addRow("Address", self.l_addr_preview)
        v.addWidget(g_t)

        g_r = QGroupBox("Ranges")
        f = QFormLayout(g_r)
        self.l_in_min, self.l_in_max = dspin(), dspin()
        self.l_out_min, self.l_out_max = dspin(), dspin()
        b_learn = QPushButton("Learn input range from incoming data")
        b_learn.clicked.connect(self._learn_range)
        b_full = QPushButton("Output = full parameter range")
        b_full.clicked.connect(self._full_output_range)
        row_in = QHBoxLayout()
        row_in.addWidget(self.l_in_min)
        row_in.addWidget(QLabel("→"))
        row_in.addWidget(self.l_in_max)
        row_out = QHBoxLayout()
        row_out.addWidget(self.l_out_min)
        row_out.addWidget(QLabel("→"))
        row_out.addWidget(self.l_out_max)
        f.addRow("Input", row_in)
        f.addRow("", b_learn)
        f.addRow("Output", row_out)
        f.addRow("", b_full)
        self.l_out_hint = QLabel("")
        self.l_out_hint.setStyleSheet("color: palette(mid);")
        f.addRow("", self.l_out_hint)
        v.addWidget(g_r)

        g_c = QGroupBox("Transfer curve")
        f = QFormLayout(g_c)
        self.l_curve_kind = QComboBox()
        self.l_curve_kind.addItems(CURVE_KINDS)
        self.l_amount = dspin(0.05, 12.0, 2, 0.1)
        self.curve_view = CurveEditor()
        self.curve_view.curveChanged.connect(self._curve_edited)
        f.addRow("Shape", self.l_curve_kind)
        f.addRow("Amount", self.l_amount)
        f.addRow(self.curve_view)
        v.addWidget(g_c)

        g_s = QGroupBox("Shaping")
        f = QFormLayout(g_s)
        self.l_invert = QCheckBox("invert")
        self.l_clamp = QCheckBox("clamp input")
        self.l_dead = dspin(0.0, 0.99, 3, 0.01)
        self.l_smooth = dspin(0.0, 0.99, 3, 0.01)
        self.l_quant = dspin(0.0, 1e6, 4, 0.01)
        self.l_enabled = QCheckBox("leg enabled")
        checks = QHBoxLayout()
        checks.addWidget(self.l_invert)
        checks.addWidget(self.l_clamp)
        checks.addWidget(self.l_enabled)
        checks.addStretch(1)
        numbers = QHBoxLayout()
        for label, widget in (("Deadzone", self.l_dead), ("Smoothing", self.l_smooth),
                              ("Step", self.l_quant)):
            numbers.addWidget(QLabel(label))
            numbers.addWidget(widget)
        f.addRow(checks)
        f.addRow(numbers)
        v.addWidget(g_s)

        self.l_live = QLabel("—")
        self.l_live.setStyleSheet("font-family: monospace;")
        v.addWidget(self.l_live)
        v.addStretch(1)

        for widget in (self.l_in_min, self.l_in_max, self.l_out_min, self.l_out_max,
                       self.l_amount, self.l_dead, self.l_smooth, self.l_quant):
            widget.valueChanged.connect(self._leg_fields_changed)
        self.l_curve_kind.currentTextChanged.connect(self._leg_fields_changed)
        self.l_arg.currentTextChanged.connect(self._leg_fields_changed)
        for chk in (self.l_invert, self.l_clamp, self.l_enabled):
            chk.toggled.connect(self._leg_fields_changed)
        return w

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("&File")
        for text, slot, shortcut in (
            ("&New project", self._new_project, "Ctrl+N"),
            ("&Open project…", self._open_project, "Ctrl+O"),
            ("&Save project", self._save_project, "Ctrl+S"),
            ("Save project &as…", self._save_project_as, "Ctrl+Shift+S"),
            ("Load extra target &catalogue…", self._load_catalog, ""),
        ):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(shortcut)
            a.triggered.connect(slot)
            m.addAction(a)
        m.addSeparator()
        a = QAction("&Quit", self)
        a.setShortcut("Ctrl+Q")
        a.triggered.connect(self.close)
        m.addAction(a)

        h = self.menuBar().addMenu("&Help")
        a = QAction("About", self)
        a.triggered.connect(self._about)
        h.addAction(a)

    # -------------------------------------------------------------- state
    @property
    def project(self) -> Project:
        return self.bridge.project

    def _apply_project_to_ui(self) -> None:
        self._loading = True
        p = self.project
        self.in_host.setText(p.input_host)
        self.in_port.setValue(p.input_port)
        self.rate.setValue(int(p.send_rate_hz))
        for proto, (host, port, chk) in self.dest_widgets.items():
            d = p.destinations.get(proto, {})
            host.setText(d.get("host", "127.0.0.1"))
            port.setValue(int(d.get("port", self.bridge.catalog.default_port(proto))))
            chk.setChecked(bool(d.get("enabled", proto != "custom")))
        self._loading = False
        self._rebuild_tree()

    def _transport_changed(self) -> None:
        if self._loading:
            return
        p = self.project
        p.input_host = self.in_host.text().strip() or "0.0.0.0"
        p.input_port = self.in_port.value()
        p.send_rate_hz = float(self.rate.value())
        for proto, (host, port, chk) in self.dest_widgets.items():
            p.destinations[proto] = {"host": host.text().strip() or "127.0.0.1",
                                     "port": port.value(), "enabled": chk.isChecked()}
        self.bridge.sender.load_dict(p.destinations)
        if self.btn_start.isChecked():
            self.bridge.receiver.restart(p.input_host, p.input_port)
            self.tx_timer.setInterval(int(1000 / max(1, self.rate.value())))

    def _toggle_run(self, on: bool) -> None:
        self._note(f"-- Start button toggled: {on}")
        if on:
            host, port = self.in_host.text().strip() or "0.0.0.0", self.in_port.value()
            busy = port_conflict(host, port)
            try:
                self._transport_changed()
                self.bridge.start(pump=False)
            except OSError as exc:
                self._note(f"!! cannot listen on {host}:{port} - {exc}")
                QMessageBox.critical(
                    self, "Cannot listen",
                    f"Port {port}: {exc}\n\nAnother program is probably using it. "
                    f"Close it, or choose a different input port.")
                self.btn_start.setChecked(False)
                return
            self.tx_timer.start(int(1000 / max(1, self.rate.value())))
            self.btn_start.setText("Stop")
            self._msgs_at_start = self.bridge.discovery.total_messages
            self._note(f"== listening on {host}:{port}")
            if busy:
                self._note(
                    "!! another program is already open on this port. On Windows only "
                    "one of them receives the packets - close the other listener.")
            if host not in ("0.0.0.0", ""):
                self._note(
                    f"   note: bound to {host} only. Broadcast traffic and other network "
                    f"adapters will NOT be seen - use 0.0.0.0 to listen everywhere.")
            QTimer.singleShot(5000, self._check_for_silence)
            self.statusBar().showMessage(f"Listening on {host}:{port}")
        else:
            self.tx_timer.stop()
            self.bridge.stop()
            self.btn_start.setText("Start")
            self.statusBar().showMessage("Stopped.")

    def _check_for_silence(self) -> None:
        """Five seconds after Start with nothing received: say what to check."""
        if not self.btn_start.isChecked():
            return
        if self.bridge.discovery.total_messages > getattr(self, "_msgs_at_start", 0):
            return
        host = self.bridge.receiver.host
        ips = ", ".join(local_addresses())
        self._note(
            "\n?? nothing received in 5 s. Usual causes, in order:\n"
            "   1. Windows Firewall is dropping it — allow python.exe on the private\n"
            "      network (the prompt only appears once, and 'Cancel' means blocked).\n"
            "   2. Another program holds this port and is eating the packets.\n"
            f"   3. Listening on {host} instead of 0.0.0.0 — a specific address misses\n"
            "      broadcasts and traffic to your other adapters.\n"
            f"   4. The sender is aimed at the wrong address/port. This machine: {ips}\n"
            "   Try tools/listen_osc.py on the same port to test outside this app.\n")

    def _tick(self, force: bool = False) -> None:
        msgs = self.bridge.engine.flush(force=force)
        if msgs:
            self.bridge.sender.send_many(msgs)
            self._log_output(msgs)

    def _note(self, text: str) -> None:
        """Write to the monitor pane and to stdout (visible in the terminal)."""
        try:
            self.monitor.appendPlainText(text)
        except Exception:
            pass
        print(text, flush=True)

    def _log_output(self, messages: list) -> None:
        if not self.chk_monitor.isChecked():
            return
        for address, args, proto in messages[-12:]:
            pretty = " ".join(f"{a:g}" if isinstance(a, float) else str(a) for a in args)
            dest = self.bridge.sender.destinations.get(proto)
            if dest is None or not dest.enabled:
                self.monitor.appendPlainText(
                    f"[{proto}] {address} {pretty}"
                    f"   <-- NOT SENT: '{proto}' output is disabled in Transport")
            else:
                self.monitor.appendPlainText(f"[{proto}] {address} {pretty}")

    # ---------------------------------------------------------- discovery
    def _refresh_ui(self) -> None:
        if not self.chk_freeze.isChecked():
            self._refresh_discovery()
        self._refresh_live()

    def _refresh_discovery(self) -> None:
        items = self.bridge.discovery.snapshot()
        table = self.disc_table
        selected = self._selected_discovery_address()
        if table.rowCount() != len(items):
            table.setRowCount(len(items))
        for r, item in enumerate(items):
            last = " ".join(f"{a:.3f}" if isinstance(a, float) else str(a)
                            for a in item.last_args)
            ranges = " ".join(
                f"[{mn:.2f},{mx:.2f}]" if mn is not None else "[-]"
                for mn, mx in zip(item.mins, item.maxs))
            values = [item.address, item.arg_types, f"{item.rate_hz:.1f}",
                      str(item.count), last, ranges]
            for c, text in enumerate(values):
                cell = table.item(r, c)
                if cell is None:
                    cell = QTableWidgetItem()
                    table.setItem(r, c, cell)
                if cell.text() != text:
                    cell.setText(text)
            if item.address == selected:
                table.selectRow(r)
        skipped = self.bridge.sender.skipped
        warn = ("  ⚠ " + ", ".join(f"{n} {p} message(s) not sent — output disabled"
                                   for p, n in skipped.items() if n)) if skipped else ""
        self.statusBar().showMessage(
            f"{'Listening' if self.btn_start.isChecked() else 'Stopped'} · "
            f"{len(items)} addresses · {self.bridge.discovery.total_messages} in · "
            f"{self.bridge.sender.sent} out{warn}", 0)

    def _selected_discovery_address(self) -> str | None:
        rows = self.disc_table.selectionModel().selectedRows() if self.disc_table.selectionModel() else []
        if not rows:
            return None
        item = self.disc_table.item(rows[0].row(), 0)
        return item.text() if item else None

    def _new_route_from_discovery(self) -> None:
        address = self._selected_discovery_address()
        if not address:
            QMessageBox.information(self, "No selection",
                                    "Select an incoming address first.")
            return
        info = self.bridge.discovery.get(address)
        route = Route(source=address, arg_index=0, name="")
        leg = self._make_default_leg(info, 0)
        if leg:
            route.legs.append(leg)
        self.bridge.engine.routes.append(route)
        self._rebuild_tree(select=route)

    def _make_default_leg(self, info, arg_index: int) -> Leg | None:
        targets = list(self.bridge.catalog.targets.values())
        if not targets:
            return None
        target = self.bridge.catalog.targets.get("adm.obj.xyz", targets[0])
        rng = info.observed_range(arg_index) if info else None
        in_min, in_max = rng if rng and rng[0] != rng[1] else (0.0, 1.0)
        arg = target.args[0]
        return Leg(target_id=target.id, arg=arg.name,
                   indices={i.name: i.default for i in target.indices},
                   in_min=in_min, in_max=in_max,
                   out_min=arg.min, out_max=arg.max)

    # --------------------------------------------------------------- tree
    def _rebuild_tree(self, select=None) -> None:
        self._loading = True
        self.tree.clear()
        for route in self.bridge.engine.routes:
            r_item = QTreeWidgetItem([route.label(), f"arg {route.arg_index}",
                                      f"{len(route.legs)} leg(s)"])
            r_item.setData(0, ROLE_KIND, "route")
            r_item.setData(0, ROLE_ROUTE, route)
            r_item.setFlags(r_item.flags() | Qt.ItemIsUserCheckable)
            r_item.setCheckState(0, Qt.Checked if route.enabled else Qt.Unchecked)
            self.tree.addTopLevelItem(r_item)
            for leg in route.legs:
                l_item = QTreeWidgetItem(self._leg_columns(leg))
                l_item.setData(0, ROLE_KIND, "leg")
                l_item.setData(0, ROLE_ROUTE, route)
                l_item.setData(0, ROLE_LEG, leg)
                l_item.setFlags(l_item.flags() | Qt.ItemIsUserCheckable)
                l_item.setCheckState(0, Qt.Checked if leg.enabled else Qt.Unchecked)
                r_item.addChild(l_item)
            r_item.setExpanded(True)
            if select is route:
                self.tree.setCurrentItem(r_item)
        self._loading = False
        self._on_tree_selection(self.tree.currentItem(), None)

    def _leg_columns(self, leg: Leg) -> list[str]:
        try:
            target = self.bridge.catalog.get(leg.target_id)
        except KeyError:
            return [leg.target_id, "missing target", ""]
        curve = leg.curve.kind + ("" if leg.curve.kind != "breakpoints"
                                  else f" ({len(leg.curve.points)} pts)")
        return [f"{target.label} · {leg.arg}",
                target.format_address(leg.indices),
                f"{leg.in_min:g}→{leg.in_max:g}  ⇒  {leg.out_min:g}→{leg.out_max:g}  [{curve}]"]

    def _current(self) -> tuple[str | None, Route | None, Leg | None]:
        item = self.tree.currentItem()
        if item is None:
            return (None, None, None)
        return (item.data(0, ROLE_KIND), item.data(0, ROLE_ROUTE), item.data(0, ROLE_LEG))

    def _on_tree_selection(self, current, previous) -> None:
        kind, route, leg = self._current()
        if kind == "route" and route is not None:
            self._load_route(route)
            self.editor_stack.setCurrentIndex(1)
        elif kind == "leg" and leg is not None:
            self._load_leg(leg)
            self.editor_stack.setCurrentIndex(2)
        else:
            self.editor_stack.setCurrentIndex(0)

    def _on_tree_item_changed(self, item, column) -> None:
        if self._loading or column != 0:
            return
        kind = item.data(0, ROLE_KIND)
        checked = item.checkState(0) == Qt.Checked
        if kind == "route":
            item.data(0, ROLE_ROUTE).enabled = checked
        elif kind == "leg":
            item.data(0, ROLE_LEG).enabled = checked

    def _add_route(self) -> None:
        route = Route(source="/*", arg_index=0)
        self.bridge.engine.routes.append(route)
        self._rebuild_tree(select=route)

    def _add_leg(self) -> None:
        kind, route, leg = self._current()
        if route is None:
            QMessageBox.information(self, "No route", "Select a route first.")
            return
        info = self.bridge.discovery.get(route.source)
        new = self._make_default_leg(info, route.arg_index)
        if not new:
            return
        # if the route already writes this target, offer its next free argument
        if route.legs:
            last = route.legs[-1]
            try:
                target = self.bridge.catalog.get(last.target_id)
            except KeyError:
                target = None
            if target:
                used = {l.arg for l in route.legs if l.target_id == target.id
                        and l.indices == last.indices}
                free = [a for a in target.args if a.name not in used]
                spec = free[0] if free else target.args[0]
                new = Leg(target_id=target.id, arg=spec.name, indices=dict(last.indices),
                          in_min=last.in_min, in_max=last.in_max,
                          out_min=spec.min, out_max=spec.max)
        route.legs.append(new)
        self._rebuild_tree(select=route)

    def _duplicate(self) -> None:
        kind, route, leg = self._current()
        if kind == "leg" and leg is not None and route is not None:
            clone = Leg.from_dict(leg.to_dict())
            route.legs.append(clone)
            self._rebuild_tree(select=route)
        elif kind == "route" and route is not None:
            clone = Route.from_dict(route.to_dict())
            self.bridge.engine.routes.append(clone)
            self._rebuild_tree(select=clone)

    def _remove_selected(self) -> None:
        kind, route, leg = self._current()
        if kind == "leg" and route is not None and leg in route.legs:
            route.legs.remove(leg)
        elif kind == "route" and route in self.bridge.engine.routes:
            self.bridge.engine.routes.remove(route)
        self.bridge.engine.bus.clear()
        self._rebuild_tree()

    # ------------------------------------------------------- route editor
    def _load_route(self, route: Route) -> None:
        self._loading = True
        self.r_name.setText(route.name)
        self.r_source.clear()
        self.r_source.addItems([d.address for d in self.bridge.discovery.snapshot()])
        self.r_source.setCurrentText(route.source)
        self.r_arg.setValue(route.arg_index)
        self.r_enabled.setChecked(route.enabled)
        info = self.bridge.discovery.get(route.source)
        if info:
            self.r_info.setText(f"types {info.arg_types or '-'} · {info.rate_hz:.1f} Hz · "
                                f"last {info.last_args}")
        else:
            self.r_info.setText("not seen yet")
        self._loading = False

    def _route_fields_changed(self) -> None:
        if self._loading:
            return
        kind, route, _ = self._current()
        if route is None:
            return
        route.name = self.r_name.text()
        route.source = self.r_source.currentText().strip() or "/*"
        route.arg_index = self.r_arg.value()
        route.enabled = self.r_enabled.isChecked()
        item = self.tree.currentItem()
        if item is not None:
            item.setText(0, route.label())
            item.setText(1, f"arg {route.arg_index}")

    # --------------------------------------------------------- leg editor
    def _load_leg(self, leg: Leg) -> None:
        self._loading = True
        try:
            target = self.bridge.catalog.get(leg.target_id)
        except KeyError:
            target = None
        self.l_target.setText(target.label if target else f"{leg.target_id} (missing)")
        while self.index_form.rowCount():
            self.index_form.removeRow(0)
        self.index_spins = {}
        if target:
            for spec in target.indices:
                spin = QSpinBox()
                spin.setRange(spec.min, spec.max)
                spin.setValue(int(leg.indices.get(spec.name, spec.default)))
                spin.valueChanged.connect(self._leg_fields_changed)
                self.index_form.addRow(spec.label or spec.name, spin)
                self.index_spins[spec.name] = spin
            self.l_arg.clear()
            self.l_arg.addItems([a.name for a in target.args])
            self.l_arg.setCurrentText(leg.arg)
        self.l_in_min.setValue(leg.in_min)
        self.l_in_max.setValue(leg.in_max)
        self.l_out_min.setValue(leg.out_min)
        self.l_out_max.setValue(leg.out_max)
        self.l_curve_kind.setCurrentText(leg.curve.kind)
        self.l_amount.setValue(leg.curve.amount)
        self.curve_view.set_curve(leg.curve)
        self.l_invert.setChecked(leg.invert)
        self.l_clamp.setChecked(leg.clamp_input)
        self.l_dead.setValue(leg.deadzone)
        self.l_smooth.setValue(leg.smoothing)
        self.l_quant.setValue(leg.quantize)
        self.l_enabled.setChecked(leg.enabled)
        self._loading = False
        self._update_leg_hints(leg)

    def _leg_fields_changed(self) -> None:
        if self._loading:
            return
        kind, route, leg = self._current()
        if leg is None:
            return
        leg.arg = self.l_arg.currentText() or leg.arg
        leg.indices = {name: spin.value() for name, spin in getattr(self, "index_spins", {}).items()}
        leg.in_min = self.l_in_min.value()
        leg.in_max = self.l_in_max.value()
        leg.out_min = self.l_out_min.value()
        leg.out_max = self.l_out_max.value()
        leg.curve.kind = self.l_curve_kind.currentText()
        leg.curve.amount = self.l_amount.value()
        if leg.curve.kind == "breakpoints" and len(leg.curve.points) < 2:
            leg.curve.points = [(0.0, 0.0), (0.35, 0.15), (1.0, 1.0)]
        leg.invert = self.l_invert.isChecked()
        leg.clamp_input = self.l_clamp.isChecked()
        leg.deadzone = self.l_dead.value()
        leg.smoothing = self.l_smooth.value()
        leg.quantize = self.l_quant.value()
        leg.enabled = self.l_enabled.isChecked()
        leg.reset()
        self.curve_view.set_curve(leg.curve)
        self.curve_view.update()
        item = self.tree.currentItem()
        if item is not None:
            for c, text in enumerate(self._leg_columns(leg)):
                item.setText(c, text)
        self._update_leg_hints(leg)

    def _curve_edited(self) -> None:
        kind, route, leg = self._current()
        if leg is not None:
            item = self.tree.currentItem()
            if item is not None:
                for c, text in enumerate(self._leg_columns(leg)):
                    item.setText(c, text)

    def _update_leg_hints(self, leg: Leg) -> None:
        try:
            target = self.bridge.catalog.get(leg.target_id)
            spec = target.arg(leg.arg)
        except (KeyError, IndexError):
            self.l_addr_preview.setText("")
            self.l_out_hint.setText("")
            return
        self.l_addr_preview.setText(target.format_address(leg.indices))
        text = f"parameter range {spec.describe_range()}"
        if spec.scale and spec.scale != 1.0:
            text += (f" · output {leg.out_min:g}→{leg.out_max:g} = "
                     f"{spec.engineering(leg.out_min):g}→{spec.engineering(leg.out_max):g} {spec.unit}")
        self.l_out_hint.setText(text)

    def _pick_target(self) -> None:
        kind, route, leg = self._current()
        if leg is None:
            return
        dlg = TargetPickerDialog(self.bridge.catalog, leg.target_id, self)
        if dlg.exec() != dlg.Accepted or not dlg.result_target():
            return
        target = self.bridge.catalog.get(dlg.result_target())
        leg.target_id = target.id
        leg.indices = {i.name: i.default for i in target.indices}
        leg.arg = target.args[0].name if target.args else ""
        if target.args:
            leg.out_min, leg.out_max = target.args[0].min, target.args[0].max
        self.bridge.engine.bus.clear()
        self._load_leg(leg)
        item = self.tree.currentItem()
        if item is not None:
            for c, text in enumerate(self._leg_columns(leg)):
                item.setText(c, text)

    def _learn_range(self) -> None:
        kind, route, leg = self._current()
        if leg is None or route is None:
            return
        info = self.bridge.discovery.get(route.source)
        rng = info.observed_range(route.arg_index) if info else None
        if not rng or rng[0] == rng[1]:
            QMessageBox.information(self, "Nothing learned",
                                    "No numeric range observed for that address yet.")
            return
        self.l_in_min.setValue(rng[0])
        self.l_in_max.setValue(rng[1])

    def _full_output_range(self) -> None:
        kind, route, leg = self._current()
        if leg is None:
            return
        try:
            spec = self.bridge.catalog.get(leg.target_id).arg(leg.arg)
        except KeyError:
            return
        self.l_out_min.setValue(spec.min)
        self.l_out_max.setValue(spec.max)

    def _refresh_live(self) -> None:
        if self.editor_stack.currentIndex() != 2:
            return
        kind, route, leg = self._current()
        if leg is None or route is None:
            return
        info = self.bridge.discovery.get(route.source)
        if info is None or route.arg_index >= len(info.last_args):
            self.curve_view.set_live_input(None)
            self.l_live.setText("—")
            return
        raw = info.last_args[route.arg_index]
        if not isinstance(raw, (int, float)):
            return
        u = leg.normalise(float(raw))
        if leg.invert:
            u = 1.0 - u
        u = leg.apply_deadzone(u)
        self.curve_view.set_live_input(u)
        try:
            spec = self.bridge.catalog.get(leg.target_id).arg(leg.arg)
            out = spec.clamp(leg.curve.apply(u) * (leg.out_max - leg.out_min) + leg.out_min)
            eng = (f"  (= {spec.engineering(out):g} {spec.unit})"
                   if spec.scale and spec.scale != 1.0 else "")
        except KeyError:
            out, eng = 0.0, ""
        self.l_live.setText(f"in {float(raw):+.4g}  →  out {out:.4g}{eng}")

    # ------------------------------------------------------------ project
    def _new_project(self) -> None:
        self.bridge.apply_project(Project())
        self._apply_project_to_ui()

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "",
                                              "Bridge project (*.json)")
        if not path:
            return
        try:
            project = Project.load(path)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot open", str(exc))
            return
        self.bridge.apply_project(project)
        self._apply_project_to_ui()
        self.setWindowTitle(f"Sound xR OSC Bridge — {Path(path).name}")

    def _save_project(self) -> None:
        if self.project.path is None:
            self._save_project_as()
            return
        self.bridge.sync_project().save(self.project.path)
        self.statusBar().showMessage(f"Saved {self.project.path}", 3000)

    def _save_project_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save project", "bridge.json",
                                              "Bridge project (*.json)")
        if not path:
            return
        self.bridge.sync_project().save(path)
        self.setWindowTitle(f"Sound xR OSC Bridge — {Path(path).name}")
        self.statusBar().showMessage(f"Saved {path}", 3000)

    def _load_catalog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load target catalogue", "",
                                              "Catalogue (*.json)")
        if not path:
            return
        try:
            self.bridge.catalog.merge(Catalog.load(path))
        except Exception as exc:
            QMessageBox.critical(self, "Cannot load", str(exc))
            return
        if path not in self.project.extra_catalogs:
            self.project.extra_catalogs.append(path)
        self.statusBar().showMessage(
            f"Catalogue now has {len(self.bridge.catalog.targets)} targets", 4000)

    def _about(self) -> None:
        QMessageBox.about(
            self, "Sound xR OSC Bridge",
            "<b>Sound xR OSC Bridge</b><br><br>"
            "Receives any OSC, learns the addresses, and maps them onto Sound xR "
            "Image parameters (ADM-OSC and native /yosc:req) with per-leg curves, "
            "ranges and fan-out.<br><br>"
            "Target addresses come from <tt>targets.json</tt> — edit that file to "
            "correct or extend them.")

    def closeEvent(self, event) -> None:
        self.bridge.stop()
        super().closeEvent(event)
