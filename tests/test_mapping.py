import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soundxr_bridge.catalog import Catalog
from soundxr_bridge.mapping import Curve, Leg, MappingEngine, Route

CAT = Catalog.load()


def test_catalog_loads():
    assert "adm.obj.xyz" in CAT.targets
    t = CAT.get("adm.obj.xyz")
    assert t.format_address({"obj": 7}) == "/adm/obj/7/xyz"
    assert [a.name for a in t.args] == ["x", "y", "z"]
    y = CAT.get("yosc.oba.object.fader.level")
    assert y.format_address({"component": 40000, "obj": 3}) == \
        "/yosc:req/set/PROC:Component/40000/OBA/Object/Fader/Level/3"


def test_linear_range():
    leg = Leg("adm.obj.xyz", "x", {"obj": 1}, in_min=0, in_max=127, out_min=-1, out_max=1)
    assert leg.compute(0) == -1.0
    assert leg.compute(127) == 1.0
    assert abs(leg.compute(63.5)) < 1e-9


def test_clamping_and_invert():
    leg = Leg("adm.obj.xyz", "x", in_min=0, in_max=1, out_min=0, out_max=10)
    assert leg.compute(5.0) == 10.0          # clamped
    leg.invert = True
    leg.reset()
    assert leg.compute(0.0) == 10.0


def test_exponential_and_log_curves():
    leg = Leg("adm.obj.gain", "gain", in_min=0, in_max=1, out_min=0, out_max=1,
              curve=Curve("exponential", 2.0))
    assert abs(leg.compute(0.5) - 0.25) < 1e-9
    leg.curve = Curve("logarithmic", 2.0)
    leg.reset()
    assert abs(leg.compute(0.25) - 0.5) < 1e-9


def test_scurve_is_monotonic_and_bounded():
    c = Curve("scurve", 2.5)
    vals = [c.apply(i / 50) for i in range(51)]
    assert vals[0] == 0.0 and abs(vals[-1] - 1.0) < 1e-9
    assert all(b >= a - 1e-12 for a, b in zip(vals, vals[1:]))
    assert abs(c.apply(0.5) - 0.5) < 1e-9


def test_breakpoints():
    c = Curve("breakpoints", points=[(0.0, 0.0), (0.5, 0.9), (1.0, 1.0)])
    assert abs(c.apply(0.25) - 0.45) < 1e-9
    assert abs(c.apply(0.75) - 0.95) < 1e-9
    assert c.apply(-2) == 0.0 and c.apply(2) == 1.0


def test_deadzone():
    leg = Leg("adm.obj.xyz", "x", in_min=-1, in_max=1, out_min=-1, out_max=1,
              deadzone=0.2)
    assert abs(leg.compute(0.0)) < 1e-9
    leg.reset()
    assert abs(leg.compute(0.1)) < 1e-9        # inside the deadzone
    leg.reset()
    assert leg.compute(1.0) == 1.0             # ends still reach full scale


def test_smoothing_converges():
    leg = Leg("adm.obj.xyz", "x", in_min=0, in_max=1, out_min=0, out_max=1,
              smoothing=0.5)
    out = [leg.compute(1.0) for _ in range(10)]
    assert out[0] == 1.0                        # first value passes through
    leg.reset()
    leg.compute(0.0)
    vals = [leg.compute(1.0) for _ in range(8)]
    assert 0.4 < vals[0] < 0.6 and vals[-1] > 0.99
    assert all(b >= a for a, b in zip(vals, vals[1:]))


def test_quantize():
    leg = Leg("yosc.oba.object.sizeh", "size", in_min=0, in_max=1,
              out_min=0, out_max=10000, quantize=500)
    assert leg.compute(0.31) == 3000.0


def test_int_coercion_and_clamp_on_bus():
    engine = MappingEngine(CAT, [Route(source="/fader", arg_index=0, legs=[
        Leg("yosc.oba.object.fader.level", "level", {"component": 40000, "obj": 2},
            in_min=0, in_max=1, out_min=-13801, out_max=1000)])])
    out = engine.process("/fader", [1.0])
    assert out == [("/yosc:req/set/PROC:Component/40000/OBA/Object/Fader/Level/2",
                    [1000], "yosc")]
    out = engine.process("/fader", [0.0])
    assert out[0][1] == [-13801]
    assert isinstance(out[0][1][0], int)


def test_fan_out_one_to_many():
    """One incoming address drives x, z and the fader, each with its own curve."""
    route = Route(source="/tracker/1/pos", arg_index=0, legs=[
        Leg("adm.obj.xyz", "x", {"obj": 1}, in_min=0, in_max=10, out_min=-1, out_max=1),
        Leg("adm.obj.xyz", "z", {"obj": 1}, in_min=0, in_max=10, out_min=0, out_max=1,
            curve=Curve("exponential", 2.0)),
        Leg("yosc.oba.object.fader.level", "level", {"component": 40000, "obj": 1},
            in_min=0, in_max=10, out_min=-2000, out_max=0,
            curve=Curve("breakpoints", points=[(0, 0), (0.5, 0.8), (1, 1)])),
    ])
    engine = MappingEngine(CAT, [route])
    out = dict((a, v) for a, v, _ in engine.process("/tracker/1/pos", [5.0]))
    assert out["/adm/obj/1/xyz"] == [0.0, 0.0, 0.25]     # y untouched, keeps default
    assert out["/yosc:req/set/PROC:Component/40000/OBA/Object/Fader/Level/1"] == [-400]


def test_many_inputs_one_target_coalesce():
    """Separate addresses writing x and y produce one message per flush."""
    engine = MappingEngine(CAT, [
        Route(source="/x", legs=[Leg("adm.obj.xyz", "x", {"obj": 3},
                                     in_min=0, in_max=1, out_min=-1, out_max=1)]),
        Route(source="/y", legs=[Leg("adm.obj.xyz", "y", {"obj": 3},
                                     in_min=0, in_max=1, out_min=-1, out_max=1)]),
    ])
    engine.handle("/x", [1.0])
    engine.handle("/y", [0.0])
    out = engine.flush()
    assert out == [("/adm/obj/3/xyz", [1.0, -1.0, 0.0], "adm")]
    assert engine.flush() == []                 # nothing changed -> nothing sent


def test_wildcards():
    r = Route(source="/track/*/xyz")
    assert r.matches("/track/12/xyz")
    assert not r.matches("/track/12/gain")


def test_route_serialisation_roundtrip():
    r = Route(source="/a", arg_index=1, name="n", legs=[
        Leg("adm.obj.w", "w", {"obj": 5}, curve=Curve("breakpoints",
                                                      points=[(0, 0), (1, 1)]))])
    r2 = Route.from_dict(r.to_dict())
    assert r2.to_dict() == r.to_dict()


def test_string_and_bool_inputs():
    engine = MappingEngine(CAT, [Route(source="/mute", legs=[
        Leg("adm.obj.mute", "mute", {"obj": 1}, in_min=0, in_max=1,
            out_min=0, out_max=1)])])
    assert engine.process("/mute", [True])[0][1] == [1]
    assert engine.process("/mute", ["0"])[0][1] == [0]
    assert engine.process("/mute", ["nope"]) == []


def test_three_arguments_from_one_message():
    """One incoming address with three floats -> x, y and z of one object."""
    route = Route(source="/mocap/head", arg_index=0, legs=[
        Leg("adm.obj.xyz", "x", {"obj": 1}, source_arg=0,
            in_min=-2, in_max=2, out_min=-1, out_max=1),
        Leg("adm.obj.xyz", "y", {"obj": 1}, source_arg=1,
            in_min=-2, in_max=2, out_min=-1, out_max=1),
        Leg("adm.obj.xyz", "z", {"obj": 1}, source_arg=2,
            in_min=-2, in_max=2, out_min=-1, out_max=1),
    ])
    engine = MappingEngine(CAT, [route])
    out = engine.process("/mocap/head", [2.0, 0.0, -2.0])
    assert out == [("/adm/obj/1/xyz", [1.0, 0.0, -1.0], "adm")]


def test_source_arg_falls_back_to_the_route():
    route = Route(source="/a", arg_index=2, legs=[
        Leg("adm.obj.gain", "gain", {"obj": 1}, in_min=0, in_max=10,
            out_min=0, out_max=1),                      # source_arg=None
        Leg("adm.obj.w", "w", {"obj": 1}, source_arg=0, in_min=0, in_max=10,
            out_min=0, out_max=1),                      # explicit override
    ])
    engine = MappingEngine(CAT, [route])
    # values chosen to differ from each parameter's default, otherwise the bus
    # correctly suppresses the message as "nothing changed"
    out = dict((a, v) for a, v, _ in engine.process("/a", [10.0, 0.0, 5.0]))
    assert out["/adm/obj/1/gain"] == [0.5]              # took arg 2
    assert out["/adm/obj/1/w"] == [1.0]                 # took arg 0


def test_missing_argument_is_skipped_not_zeroed():
    engine = MappingEngine(CAT, [Route(source="/short", legs=[
        Leg("adm.obj.xyz", "x", {"obj": 1}, source_arg=0, in_min=0, in_max=1,
            out_min=-1, out_max=1),
        Leg("adm.obj.xyz", "y", {"obj": 1}, source_arg=5, in_min=0, in_max=1,
            out_min=-1, out_max=1),
    ])])
    out = engine.process("/short", [1.0])
    assert out == [("/adm/obj/1/xyz", [1.0, 0.0, 0.0], "adm")]


def test_component_id_zero_is_allowed():
    t = CAT.get("yosc.oba.object.fader.level")
    component = next(i for i in t.indices if i.name == "component")
    assert component.min == 0
    assert t.format_address({"component": 0, "obj": 3}) == \
        "/yosc:req/set/PROC:Component/0/OBA/Object/Fader/Level/3"


def test_source_arg_survives_save_and_load():
    r = Route(source="/a", legs=[Leg("adm.obj.xyz", "z", source_arg=2)])
    assert Route.from_dict(r.to_dict()).legs[0].source_arg == 2
