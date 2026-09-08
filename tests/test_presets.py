"""Presets: naming, round trip, and the load-must-not-start-listening rule."""

import os
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("SOUNDXR_DATA_DIR", str(tmp_path))
    from soundxr_bridge import presets
    return presets


def _project(**kw):
    from soundxr_bridge.mapping import Curve, Leg, Route
    from soundxr_bridge.project import Project
    return Project(routes=[Route(source="/mocap/head", legs=[
        Leg("adm.obj.xyz", "x", {"obj": 2}, source_arg=0, in_min=-3, in_max=3,
            out_min=-1, out_max=1, curve=Curve("logarithmic", 2.75)),
        Leg("adm.obj.xyz", "y", {"obj": 2}, source_arg=1),
    ])], **kw)


def test_round_trip_keeps_every_setting(store):
    store.save(_project(input_port=10020), "Show A")
    loaded = store.load("Show A")
    leg = loaded.routes[0].legs[0]
    assert loaded.input_port == 10020
    assert leg.source_arg == 0 and leg.indices == {"obj": 2}
    assert leg.curve.kind == "logarithmic" and leg.curve.amount == 2.75
    assert (leg.in_min, leg.in_max) == (-3.0, 3.0)


def test_names_hides_autosave_and_lists_alphabetically(store):
    store.save(_project(), "beta")
    store.save(_project(), "alpha")
    _project().save(store.autosave_path())
    assert store.names() == ["alpha", "beta"]


@pytest.mark.parametrize("given,expected", [
    ("../../etc/passwd", "etcpasswd"),
    ("show/1", "show1"),
    ("  spaced name  ", "spaced name"),
    ("", "untitled"),
    ("...", "untitled"),
])
def test_names_cannot_escape_the_folder(store, given, expected):
    assert store.safe_name(given) == expected
    assert store.path_for(given).parent == store.preset_dir()


def test_delete(store):
    store.save(_project(), "gone")
    assert store.delete("gone") is True
    assert store.delete("gone") is False
    assert store.names() == []


def test_loading_a_project_does_not_start_listening(store):
    """Regression: apply_project used to restart the receiver unconditionally,
    grabbing the port even when the bridge was stopped."""
    from soundxr_bridge.bridge import Bridge
    from soundxr_bridge.project import Project

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    bridge = Bridge(Project(input_host="127.0.0.1", input_port=port))
    assert bridge.receiver.running is False
    bridge.apply_project(_project(input_host="127.0.0.1", input_port=port))
    assert bridge.receiver.running is False, "loading a project started the receiver"
    assert bridge.receiver.port == port      # but it remembered where to listen

    bridge.start()
    assert bridge.receiver.running is True
    bridge.apply_project(_project(input_host="127.0.0.1", input_port=port))
    assert bridge.receiver.running is True, "loading stopped a running receiver"
    bridge.stop()


def test_data_dir_is_writable_and_honours_the_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SOUNDXR_DATA_DIR", str(tmp_path / "elsewhere"))
    from soundxr_bridge import presets
    assert presets.data_dir() == tmp_path / "elsewhere"
    assert presets.preset_dir().is_dir()
    (presets.preset_dir() / "probe.txt").write_text("ok")
