from __future__ import annotations

import os
from pathlib import Path
import sys


APP_DATA_DIR_NAME = "BeeLine Issue Tracker"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def source_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bundled_resource_root() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if is_frozen() and bundle_root:
        return Path(bundle_root).resolve()
    return source_project_root()


def default_runtime_root() -> Path:
    if not is_frozen():
        return source_project_root()

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data).expanduser() / APP_DATA_DIR_NAME
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / APP_DATA_DIR_NAME
    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / APP_DATA_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DATA_DIR_NAME


def environment_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, default)).expanduser().resolve()
