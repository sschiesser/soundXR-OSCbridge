"""Offscreen smoke test: build the window, drive the editors, save a project."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from soundxr_bridge.gui.curve_editor import CurveEditor  # noqa: E402
from soundxr_bridge.gui.main_window import MainWindow  # noqa: E402
from soundxr_bridge.gui.target_picker import TargetPickerDialog  # noqa: E402
from soundxr_bridge.mapping import Curve  # noqa: E402
from soundxr_bridge.project import Project  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_window_builds_and_edits(app, tmp_path):
    win = MainWindow(Project(input_port=59999))
    win.show()

    # discovery table fills from observed traffic
    win.bridge.discovery.observe("/tracker/1/x", (0.25,), "10.0.0.5:9000")
    win.bridge.discovery.observe("/tracker/1/x", (0.75,), "10.0.0.5:9000")
    win._refresh_discovery()
    assert win.disc_table.rowCount() == 1
    assert win.disc_table.item(0, 0).text() == "/tracker/1/x"

    # "map selected" builds a route with a sensible default leg
    win.disc_table.selectRow(0)
    win._new_route_from_discovery()
    assert len(win.bridge.engine.routes) == 1
    route = win.bridge.engine.routes[0]
    assert route.source == "/tracker/1/x"
    assert route.legs and route.legs[0].in_min == 0.25 and route.legs[0].in_max == 0.75

    # select the leg -> editor page, then change fields through the widgets
    leg_item = win.tree.topLevelItem(0).child(0)
    win.tree.setCurrentItem(leg_item)
    assert win.editor_stack.currentIndex() == 2
    win.l_curve_kind.setCurrentText("exponential")
    win.l_amount.setValue(3.0)
    win.l_out_min.setValue(-1.0)
    win.l_out_max.setValue(1.0)
    leg = route.legs[0]
    assert leg.curve.kind == "exponential" and leg.curve.amount == 3.0
    assert abs(leg.compute(0.75) - 1.0) < 1e-9

    # fan-out: add a second leg to the same route
    win.tree.setCurrentItem(win.tree.topLevelItem(0))
    win._add_leg()
    assert len(route.legs) == 2

    # live readout does not explode
    win._refresh_live()

    # engine actually produces output for that route
    msgs = win.bridge.engine.process("/tracker/1/x", [0.5])
    assert msgs and msgs[0][0].startswith("/adm/obj/")

    # save + reload
    path = tmp_path / "p.json"
    win.bridge.sync_project().save(path)
    reloaded = Project.load(path)
    assert len(reloaded.routes) == 1 and len(reloaded.routes[0].legs) == 2
    win.close()


def test_target_picker_lists_catalogue(app):
    from soundxr_bridge.catalog import Catalog
    dlg = TargetPickerDialog(Catalog.load(), "adm.obj.xyz")
    assert dlg.tree.topLevelItemCount() >= 2
    dlg.search.setText("fader")
    assert dlg.tree.topLevelItemCount() >= 1
    dlg.close()


def test_curve_editor_breakpoint_editing(app):
    ed = CurveEditor()
    ed.resize(200, 200)
    curve = Curve("breakpoints", points=[(0.0, 0.0), (1.0, 1.0)])
    ed.set_curve(curve)
    pos = QPointF(100, 100)
    ed.mouseDoubleClickEvent(QMouseEvent(QMouseEvent.MouseButtonDblClick, pos,
                                         Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert len(curve.points) == 3
    ed.set_live_input(0.5)
    ed.grab()          # forces a paintEvent


def test_switching_a_leg_to_a_yosc_target_sticks(app):
    """Regression: PySide6 >= 6.9 removed instance access to enum members, so
    `dlg.Accepted` raised AttributeError and the target switch was abandoned
    half-way — the leg silently stayed on its ADM-OSC target."""
    from PySide6.QtWidgets import QDialog

    from soundxr_bridge.gui import main_window as mw
    from soundxr_bridge.gui.target_picker import ID_ROLE, TargetPickerDialog

    win = MainWindow(Project(input_port=59998))
    win.bridge.discovery.observe("/ctl/fader/1", (0.5,))
    win._refresh_discovery()
    win.disc_table.selectRow(0)
    win._new_route_from_discovery()
    route = win.bridge.engine.routes[0]
    leg = route.legs[0]
    assert leg.target_id.startswith("adm.")

    class PickYoscFader(TargetPickerDialog):
        def exec(self):
            for i in range(self.tree.topLevelItemCount()):
                head = self.tree.topLevelItem(i)
                for j in range(head.childCount()):
                    child = head.child(j)
                    if child.data(0, ID_ROLE) == "yosc.oba.object.fader.level":
                        self.tree.setCurrentItem(child)
                        return QDialog.DialogCode.Accepted
            raise AssertionError("yosc fader missing from the picker")

    original = mw.TargetPickerDialog
    mw.TargetPickerDialog = PickYoscFader
    try:
        win.tree.setCurrentItem(win.tree.topLevelItem(0).child(0))
        win._pick_target()
    finally:
        mw.TargetPickerDialog = original

    assert leg.target_id == "yosc.oba.object.fader.level"
    assert leg.indices == {"component": 40000, "obj": 1}
    win.l_in_max.setValue(2.0)                       # editing must not revert it
    assert leg.target_id == "yosc.oba.object.fader.level"

    address, values, protocol = win.bridge.engine.process("/ctl/fader/1", [1.0])[0]
    assert protocol == "yosc"
    assert address == "/yosc:req/set/PROC:Component/40000/OBA/Object/Fader/Level/1"
    win.close()
