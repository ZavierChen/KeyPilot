from __future__ import annotations

import json
import os
import urllib.parse
from pathlib import Path


def shortcuts_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "KeyPilot"
    return base / "website-shortcuts.json"


def normalize_safe_url(value: str) -> str | None:
    candidate = value.strip()
    if not candidate:
        return None
    parsed_input = urllib.parse.urlsplit(candidate)
    if parsed_input.scheme and parsed_input.scheme.lower() not in {"http", "https"}:
        return None
    if not parsed_input.scheme:
        candidate = "https://" + candidate
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    return candidate


def load_website_shortcuts(path: Path | None = None) -> dict[str, str]:
    target = path or shortcuts_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    shortcuts: dict[str, str] = {}
    for keyword, url in payload.items():
        if not isinstance(keyword, str) or not keyword.strip() or not isinstance(url, str):
            continue
        normalized = normalize_safe_url(url)
        if normalized:
            shortcuts[keyword.strip()] = normalized
    return shortcuts


def set_website_shortcut(keyword: str, url: str, path: Path | None = None) -> bool:
    target = path or shortcuts_path()
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("关键词不能为空。")
    shortcuts = load_website_shortcuts(target)
    if not url.strip():
        removed = shortcuts.pop(keyword, None) is not None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(shortcuts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return removed
    normalized = normalize_safe_url(url)
    if not normalized:
        raise ValueError("网址无效；只允许 http 或 https 地址。")
    shortcuts[keyword] = normalized
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(shortcuts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return True


__all__ = [
    "load_website_shortcuts",
    "normalize_safe_url",
    "set_website_shortcut",
    "shortcuts_path",
]
