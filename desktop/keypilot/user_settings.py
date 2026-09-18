"""Personal settings live outside update-managed files in installed applications."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .install_layout import installed_layout, voice_directory
from .data_paths import user_data_dir


def assistant_settings_path(project_dir: Path) -> Path:
    legacy = project_dir / "assistant-settings.json"
    layout = installed_layout()
    if not layout:
        return user_data_dir() / "assistant-settings.json"
    data_dir = Path(layout.get("user_data_dir") or voice_directory().parent)
    if not data_dir.is_absolute():
        raise ValueError("User settings directory must be absolute")
    target = data_dir / "assistant-settings.json"
    if not target.exists() and legacy.exists():
        # Validate before migrating. A broken old file is never overwritten.
        payload = json.loads(legacy.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("Existing personal settings must be a JSON object")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
        except FileExistsError:
            pass  # Another launch already migrated; don't overwrite its choices.
    return target


def save_settings(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A crash during serialization/write must not truncate existing preferences.
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
