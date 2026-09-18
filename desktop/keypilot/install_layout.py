"""Persistent install locations; updates never relocate user voice data."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from .data_paths import user_data_dir


def installed_layout() -> dict:
    path = Path(__file__).resolve().parent.parent / "install-layout.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}  # Development checkout, not an installed application.
    if not isinstance(value, dict):
        raise ValueError(f"Invalid install layout: {path}")
    return value


def voice_directory() -> Path:
    fixed = installed_layout().get("voice_pack_dir")
    if fixed:
        result = Path(fixed)
        if not result.is_absolute():
            raise ValueError("Installed voice directory must be absolute")
        return result
    return user_data_dir() / "voice-packs"


def application_python() -> str:
    # Never choose a different Python from the launcher's inherited PATH.
    fixed = installed_layout().get("pythonw")
    if fixed:
        if not Path(fixed).is_absolute():
            raise ValueError("Installed Python executable must be absolute")
        return fixed
    return sys.executable
