"""Keep the shareable research edition separate from an existing installation."""
from __future__ import annotations

import os
from pathlib import Path


def user_data_dir() -> Path:
    override = os.environ.get("KEYPILOT_DATA_DIR")
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError("KEYPILOT_DATA_DIR must be an absolute path")
        return path
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "KeyPilot-Repro"
