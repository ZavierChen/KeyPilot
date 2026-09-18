from __future__ import annotations

from .data_paths import user_data_dir

import json
import os
from pathlib import Path


def shortcuts_path() -> Path:
    base = user_data_dir()
    return base / "path-shortcuts.json"


def normalize_system_path(value: str, *, require_exists: bool = False) -> str | None:
    candidate = os.path.expandvars(value.strip().strip('"'))
    if not candidate:
        return None
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        return None
    if require_exists and not path.exists():
        return None
    return str(path)


def load_path_shortcuts(path: Path | None = None) -> dict[str, str]:
    target = path or shortcuts_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    shortcuts: dict[str, str] = {}
    for keyword, raw_path in payload.items():
        if not isinstance(keyword, str) or not keyword.strip() or not isinstance(raw_path, str):
            continue
        normalized = normalize_system_path(raw_path)
        if normalized:
            shortcuts[keyword.strip()] = normalized
    return shortcuts


def set_path_shortcut(keyword: str, system_path: str, path: Path | None = None) -> bool:
    target = path or shortcuts_path()
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("关键词不能为空。")
    shortcuts = load_path_shortcuts(target)
    if not system_path.strip():
        removed = shortcuts.pop(keyword, None) is not None
        _write_shortcuts(target, shortcuts)
        return removed
    normalized = normalize_system_path(system_path, require_exists=True)
    if not normalized:
        raise ValueError("路径无效或目标不存在，请输入完整的文件、文件夹或应用路径。")
    shortcuts[keyword] = normalized
    _write_shortcuts(target, shortcuts)
    return True


def _write_shortcuts(target: Path, shortcuts: dict[str, str]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(shortcuts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


__all__ = [
    "load_path_shortcuts",
    "normalize_system_path",
    "set_path_shortcut",
    "shortcuts_path",
]
