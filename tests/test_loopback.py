"""End-to-end: real UDP in, real UDP out."""

import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

from soundxr_bridge.bridge import Bridge
from soundxr_bridge.mapping import Curve, Leg, Route
from soundxr_bridge.project import Project


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_end_to_end():
    in_port, adm_port = free_port(), free_port()
    received = []

    disp = Dispatcher()
    disp.set_default_handler(lambda addr, *a: received.append((addr, list(a))))
    sink = ThreadingOSCUDPServer(("127.0.0.1", adm_port), disp)
    import threading
    threading.Thread(target=sink.serve_forever, daemon=True).start()

    project = Project(
        input_host="127.0.0.1", input_port=in_port, send_rate_hz=200,
        destinations={"adm": {"host": "127.0.0.1", "port": adm_port, "enabled": True},
                      "yosc": {"host": "127.0.0.1", "port": free_port(), "enabled": False}},
        routes=[Route(source="/head/*/azimuth", arg_index=0, legs=[
            Leg("adm.obj.xyz", "x", {"obj": 4}, in_min=-180, in_max=180,
                out_min=-1, out_max=1),
            Leg("adm.obj.xyz", "z", {"obj": 4}, in_min=-180, in_max=180,
                out_min=0, out_max=1,
                curve=Curve("breakpoints", points=[(0, 1), (0.5, 0), (1, 1)])),
        ])],
    )
    bridge = Bridge(project)
    bridge.start()
    time.sleep(0.3)

    client = SimpleUDPClient("127.0.0.1", in_port)
    client.send_message("/head/1/azimuth", 180.0)
    client.send_message("/some/other/thing", [1, 2.0, "three"])
    time.sleep(0.5)
    bridge.stop()
    sink.shutdown()

    assert ("/adm/obj/4/xyz", [1.0, 0.0, 1.0]) in received, received
    # auto-discovery saw both addresses, including the unmapped one
    seen = {d.address for d in bridge.discovery.snapshot()}
    assert seen == {"/head/1/azimuth", "/some/other/thing"}
    info = bridge.discovery.get("/some/other/thing")
    assert info.arg_types == "ifs"
    assert info.observed_range(1) == (2.0, 2.0)


def test_project_roundtrip(tmp_path):
    p = Project(routes=[Route(source="/a", legs=[Leg("adm.obj.gain", "gain")])])
    path = p.save(tmp_path / "proj.json")
    q = Project.load(path)
    assert q.to_dict() == p.to_dict()
