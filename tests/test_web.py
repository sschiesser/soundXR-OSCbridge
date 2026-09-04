"""The browser remote: page, state API and every command."""

import json
import socket
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soundxr_bridge.bridge import Bridge
from soundxr_bridge.project import Project
from soundxr_bridge.web import WebRemote


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return json.loads(r.read()) if path.startswith("/api") else r.read().decode()


def post(base, payload):
    req = urllib.request.Request(base + "/api/command",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def test_remote_end_to_end():
    port = free_port()
    bridge = Bridge(Project(input_port=free_port()))
    remote = WebRemote(bridge, "127.0.0.1", port)
    remote.start()
    base = f"http://127.0.0.1:{port}"
    try:
        page = get(base, "/")
        assert "Sound xR OSC Bridge" in page and "<script>" in page
        assert "http://" not in page.split("<script>")[0].replace("http://www.w3", "")

        # a three-float message shows up and maps to three legs in one tap
        bridge.discovery.observe("/mocap/head", (1.0, 2.0, 3.0), "10.0.0.5:9000")
        bridge.discovery.observe("/mocap/head", (-1.0, 0.0, 1.0), "10.0.0.5:9000")
        state = get(base, "/api/state")
        assert state["discovery"][0]["address"] == "/mocap/head"
        assert state["discovery"][0]["types"] == "fff"

        assert post(base, {"cmd": "add_route", "address": "/mocap/head"})["ok"]
        state = get(base, "/api/state")
        legs = state["routes"][0]["legs"]
        assert [l["source_arg"] for l in legs] == [0, 1, 2]
        assert [l["arg"] for l in legs] == ["x", "y", "z"]

        # retarget a leg at a yosc parameter and set its range
        assert post(base, {"cmd": "set_leg", "route": 0, "leg": 2,
                           "fields": {"target_id": "yosc.oba.object.fader.level"}})["ok"]
        post(base, {"cmd": "set_leg", "route": 0, "leg": 2,
                    "fields": {"in_min": 0, "in_max": 1, "out_min": -6000,
                               "out_max": 0, "curve": "logarithmic",
                               "indices": {"component": 0}}})
        leg = get(base, "/api/state")["routes"][0]["legs"][2]
        assert leg["protocol"] == "yosc" and leg["curve"] == "logarithmic"
        assert leg["address"] == \
            "/yosc:req/set/PROC:Component/0/OBA/Object/Fader/Level/1"

        # the engine really uses what the browser configured
        # arg 2 = 0.0 -> bottom of the output range (0 dB would equal the
        # parameter's default and be suppressed as "unchanged")
        out = dict((a, v) for a, v, _ in bridge.engine.process("/mocap/head", [1.0, 1.0, 0.0]))
        assert out["/yosc:req/set/PROC:Component/0/OBA/Object/Fader/Level/1"] == [-6000]

        # transport edits
        post(base, {"cmd": "set_dest", "protocol": "yosc", "host": "10.1.2.3",
                    "port": 50528, "enabled": True})
        assert bridge.sender.destinations["yosc"].host == "10.1.2.3"
        spare = free_port()          # never hard-code: 10020 may be a real show port
        post(base, {"cmd": "set_input", "port": spare})
        assert bridge.project.input_port == spare

        # start/stop through the remote
        started = post(base, {"cmd": "start"})
        assert started["ok"], started.get("error")
        assert get(base, "/api/state")["running"] is True
        assert post(base, {"cmd": "stop"})["ok"]
        assert get(base, "/api/state")["running"] is False

        # learn, add/remove, and a bad command
        post(base, {"cmd": "learn", "route": 0, "leg": 0})
        assert get(base, "/api/state")["routes"][0]["legs"][0]["in_min"] == -1.0
        post(base, {"cmd": "add_leg", "route": 0})
        assert len(get(base, "/api/state")["routes"][0]["legs"]) == 4
        post(base, {"cmd": "del_leg", "route": 0, "leg": 3})
        assert len(get(base, "/api/state")["routes"][0]["legs"]) == 3
        assert post(base, {"cmd": "nonsense"})["ok"] is False

        post(base, {"cmd": "del_route", "route": 0})
        assert get(base, "/api/state")["routes"] == []
    finally:
        remote.stop()
        bridge.stop()


def test_page_has_no_external_resources():
    """It must work on a tablet with no internet."""
    from soundxr_bridge.web_ui import PAGE
    for bad in ("src=\"http", "href=\"http", "cdn.", "googleapis"):
        assert bad not in PAGE


def test_start_on_a_busy_port_explains_itself():
    """A port another program already holds must report, not crash."""
    import socket
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", 0))
    busy = blocker.getsockname()[1]

    port = free_port()
    bridge = Bridge(Project(input_host="127.0.0.1", input_port=busy))
    remote = WebRemote(bridge, "127.0.0.1", port)
    remote.start()
    base = f"http://127.0.0.1:{port}"
    try:
        res = post(base, {"cmd": "start"})
        assert res["ok"] is False
        assert "Cannot listen" in res["error"] and str(busy) in res["error"]
        assert get(base, "/api/state")["running"] is False
    finally:
        remote.stop()
        bridge.stop()
        blocker.close()
