"""Wires receiver -> mapping engine -> sender. Used by both GUI and headless mode."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from .catalog import Catalog, user_catalog
from .mapping import MappingEngine
from .osc_io import Discovery, OscReceiver, OscSender
from .project import Project


class Bridge:
    def __init__(self, project: Project | None = None,
                 catalog: Catalog | None = None) -> None:
        self.project = project or Project()
        self.catalog = catalog or Catalog.load()
        extra_user = user_catalog()
        if extra_user and extra_user != self.catalog.source_path:
            try:
                self.catalog.merge(Catalog.load(extra_user))
            except Exception:
                pass
        for extra in self.project.extra_catalogs:
            try:
                self.catalog.merge(Catalog.load(extra))
            except Exception:
                pass
        self.discovery = Discovery()
        self.engine = MappingEngine(self.catalog, self.project.routes)
        self.sender = OscSender()
        self.sender.load_dict(self.project.destinations)
        self.receiver = OscReceiver(self.project.input_host, self.project.input_port,
                                    discovery=self.discovery,
                                    on_message=self.engine.handle)
        self.on_output: Callable[[list], None] | None = None
        self._pump: threading.Thread | None = None
        self._stop = threading.Event()

    # -- lifecycle -------------------------------------------------------
    def start(self, pump: bool = True) -> None:
        self.receiver.restart(self.project.input_host, self.project.input_port)
        self.sender.load_dict(self.project.destinations)
        if pump and self._pump is None:
            self._stop.clear()
            self._pump = threading.Thread(target=self._loop, name="osc-tx", daemon=True)
            self._pump.start()

    def stop(self) -> None:
        self._stop.set()
        if self._pump:
            self._pump.join(timeout=2.0)
            self._pump = None
        self.receiver.stop()

    def _loop(self) -> None:
        period = 1.0 / max(1.0, self.project.send_rate_hz)
        while not self._stop.is_set():
            self.tick()
            time.sleep(period)

    # -- one iteration (GUI drives this from a QTimer) -------------------
    def tick(self) -> list:
        messages = self.engine.flush()
        if not messages:
            return []
        self.sender.send_many(messages)
        if self.on_output:
            self.on_output(messages)
        return messages

    # -- project ---------------------------------------------------------
    def apply_project(self, project: Project) -> None:
        """Swap in a project, leaving the listening state exactly as it was.

        Restarting unconditionally used to start the receiver even when the
        bridge was stopped, quietly taking the port.
        """
        was_running = self.receiver.running
        self.project = project
        self.engine.routes = project.routes
        self.engine.reset()
        self.sender.load_dict(project.destinations)
        if was_running:
            self.receiver.restart(project.input_host, project.input_port)
        else:
            self.receiver.host = project.input_host
            self.receiver.port = project.input_port

    def sync_project(self) -> Project:
        self.project.destinations = self.sender.to_dict()
        self.project.routes = self.engine.routes
        return self.project


def run_headless(project_path: str | Path, verbose: bool = True) -> None:
    project = Project.load(project_path)
    bridge = Bridge(project)
    if verbose:
        def log(messages):
            for address, args, proto in messages:
                print(f"  -> [{proto}] {address} {args}")
        bridge.on_output = log
    bridge.start()
    print(f"Listening on {project.input_host}:{project.input_port}")
    for proto, d in bridge.sender.destinations.items():
        state = "on" if d.enabled else "off"
        print(f"Sending {proto} -> {d.host}:{d.port} ({state})")
    print(f"{len(project.routes)} route(s) active. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
