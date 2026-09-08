"""The interface, driven headlessly through NiceGUI's own test harness.

No browser, no display — so it runs in CI exactly as it does here.
"""

import pytest
from nicegui.testing import User

# The module is imported lazily. Importing it at module level would register the
# page before NiceGUI resets its globals for each test; the later import from
# main.py would then be a no-op out of sys.modules and the page would be missing.


def ui_module():
    from soundxr_bridge.webui import app as webui
    return webui




def _pin(route) -> None:
    """Give the legs ranges whose output differs from the target's defaults.

    The bus never re-sends an unchanged value, so a leg that happens to compute
    the parameter's default emits nothing — fine in use, useless in a test.
    """
    for leg in route.legs:
        leg.in_min, leg.in_max = 0.0, 1.0
        leg.out_min, leg.out_max = -1.0, 1.0
        leg.reset()


@pytest.fixture(autouse=True)
def clean_bridge():
    from soundxr_bridge import presets
    # the page's run() restores the last session on start; each test must begin
    # from nothing or leftovers from the previous one leak in
    presets.autosave_path().unlink(missing_ok=True)
    webui = ui_module()
    webui.BRIDGE.engine.routes.clear()
    webui.BRIDGE.engine.bus.clear()
    webui.STATE.update(leg=None, route=None, sel=None, learn=None, preset=None)
    webui.BRIDGE.discovery.clear()
    webui.set_monitor(True)
    webui.PENDING.clear()
    yield
    webui.BRIDGE.stop()


async def test_page_shows_its_sections(user: User) -> None:
    webui = ui_module()
    await user.open("/")
    await user.should_see("Incoming OSC")
    await user.should_see("Mappings")
    await user.should_see("Transport")
    await user.should_see("Presets")
    await user.should_see("Output monitor")


async def test_simulate_then_map_builds_one_leg_per_argument(user: User) -> None:
    webui = ui_module()
    await user.open("/")
    user.find("Simulate").click()
    user.find("Simulate").click()
    # the discovery table's rows are client-side data, so assert on the model
    assert "/mocap/head" in {d.address for d in webui.BRIDGE.discovery.snapshot()}

    webui.add_route("/mocap/head")             # what tapping the row calls
    route = webui.BRIDGE.engine.routes[0]
    assert [leg.source_arg for leg in route.legs] == [0, 1, 2]
    assert [leg.arg for leg in route.legs] == ["x", "y", "z"]
    await user.should_see("arg 2 → Position X/Y/Z (normalised) · z")


async def test_engine_receives_what_the_page_configured(user: User) -> None:
    webui = ui_module()
    await user.open("/")
    user.find("Simulate").click()
    webui.add_route("/mocap/head")
    route = webui.BRIDGE.engine.routes[0]
    for leg in route.legs:
        leg.in_min, leg.in_max = -1.0, 1.0
        leg.out_min, leg.out_max = -1.0, 1.0

    out = webui.BRIDGE.engine.process("/mocap/head", [1.0, 0.0, -1.0])
    assert out == [("/adm/obj/1/xyz", [1.0, 0.0, -1.0], "adm")]


async def test_leg_operations(user: User) -> None:
    webui = ui_module()
    await user.open("/")
    user.find("Simulate").click()
    webui.add_route("/ctl/fader/1")
    route = webui.BRIDGE.engine.routes[0]
    assert len(route.legs) == 1

    webui.add_leg(route)
    assert len(route.legs) == 2
    webui.duplicate_leg(route, route.legs[0])
    assert len(route.legs) == 3
    webui.remove_leg(route, route.legs[0])
    assert len(route.legs) == 2
    webui.delete_route(route)
    assert webui.BRIDGE.engine.routes == []


async def test_presets_round_trip_through_the_page(user: User) -> None:
    webui = ui_module()
    await user.open("/")
    user.find("Simulate").click()
    webui.add_route("/mocap/head")
    webui.BRIDGE.engine.routes[0].legs[0].curve.kind = "logarithmic"
    webui.BRIDGE.engine.routes[0].legs[0].curve.amount = 2.75

    webui.save_preset("regression")
    webui.delete_route(webui.BRIDGE.engine.routes[0])
    assert webui.BRIDGE.engine.routes == []

    webui.load_preset("regression")
    leg = webui.BRIDGE.engine.routes[0].legs[0]
    assert leg.curve.kind == "logarithmic" and leg.curve.amount == 2.75
    assert webui.STATE["preset"] == "regression"


async def test_monitor_records_what_was_sent(user: User) -> None:
    webui = ui_module()
    await user.open("/")
    user.find("Simulate").click()
    webui.add_route("/mocap/head")
    webui.PENDING.clear()
    webui.BRIDGE.engine.handle("/mocap/head", [0.9, 0.1, 0.4])
    webui.BRIDGE.tick()
    assert any("/adm/obj/1/xyz" in line for line in webui.PENDING), list(webui.PENDING)


async def test_transport_edits_reach_the_project(user: User) -> None:
    webui = ui_module()
    await user.open("/")
    webui.set_input(host="127.0.0.1", port=10123)
    assert webui.BRIDGE.project.input_port == 10123
    webui.set_dest("yosc", host="10.1.2.3", port=50528, enabled=True)
    assert webui.BRIDGE.sender.destinations["yosc"].host == "10.1.2.3"
    assert webui.BRIDGE.sender.destinations["yosc"].enabled is True


async def test_monitor_can_be_switched_off(user: User) -> None:
    webui = ui_module()
    await user.open("/")
    user.find("Simulate").click()
    webui.add_route("/mocap/head")

    _pin(webui.BRIDGE.engine.routes[0])
    webui.set_monitor(False)
    webui.PENDING.clear()
    webui.BRIDGE.engine.handle("/mocap/head", [0.7, 0.2, 0.9])
    webui.BRIDGE.tick()
    assert not webui.PENDING, "monitor was off but still logged"

    webui.set_monitor(True)
    webui.BRIDGE.engine.handle("/mocap/head", [0.1, 0.8, 0.3])
    webui.BRIDGE.tick()
    assert webui.PENDING, "monitor was on but logged nothing"


async def test_switching_the_monitor_off_drops_the_backlog(user: User) -> None:
    webui = ui_module()
    await user.open("/")
    user.find("Simulate").click()
    webui.add_route("/mocap/head")
    _pin(webui.BRIDGE.engine.routes[0])
    webui.BRIDGE.engine.handle("/mocap/head", [1.0, 1.0, 1.0])
    webui.BRIDGE.tick()
    assert webui.PENDING

    webui.set_monitor(False)
    assert not webui.PENDING, "turning it off should not leave a burst waiting"
    webui.set_monitor(True)


async def test_simulate_drives_the_mappings_not_just_the_table(user: User) -> None:
    """Pressing Simulate must exercise the whole chain, so a mapping can be
    checked with no hardware present."""
    webui = ui_module()
    await user.open("/")
    user.find("Simulate").click()
    webui.add_route("/mocap/head")
    _pin(webui.BRIDGE.engine.routes[0])
    webui.PENDING.clear()

    user.find("Simulate").click()          # this one should reach the engine
    webui.BRIDGE.tick()
    assert any("/adm/obj/1/xyz" in line for line in webui.PENDING), list(webui.PENDING)
