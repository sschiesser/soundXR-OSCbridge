"""Where presets live, and how they are named.

A packaged app cannot write inside its own bundle, so presets go to a folder in
the user's home that they can find, copy and back up.
"""

from __future__ import annotations

import os
from pathlib import Path

from .project import Project

APP_FOLDER = "SoundxR OSC Bridge"


def data_dir() -> Path:
    """A writable, discoverable place for presets."""
    override = os.environ.get("SOUNDXR_DATA_DIR")
    if override:
        path = Path(override)
    else:
        home = Path.home()
        documents = home / "Documents"
        path = (documents if documents.is_dir() else home) / APP_FOLDER
    path.mkdir(parents=True, exist_ok=True)
    return path


def preset_dir() -> Path:
    path = data_dir() / "presets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def autosave_path() -> Path:
    return preset_dir() / "_autosave.json"


def safe_name(name: str) -> str:
    keep = "-_. "
    cleaned = "".join(c for c in (name or "").strip() if c.isalnum() or c in keep)
    return cleaned.strip().lstrip(".") or "untitled"


def names() -> list[str]:
    return sorted(f.stem for f in preset_dir().glob("*.json")
                  if not f.stem.startswith("_"))


def path_for(name: str) -> Path:
    return preset_dir() / f"{safe_name(name)}.json"


def save(project: Project, name: str) -> Path:
    return project.save(path_for(name))


def load(name: str) -> Project:
    return Project.load(path_for(name))


def delete(name: str) -> bool:
    path = path_for(name)
    if path.is_file():
        path.unlink()
        return True
    return False
