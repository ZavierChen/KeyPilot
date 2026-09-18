"""Voice metadata survives transient directory-read errors without loading models."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .user_settings import save_settings


def scan_voice_packs(directory: Path) -> dict[str, Path]:
    cache_path = directory.parent / "voice-catalog-cache.json"
    diagnostics = {"directory": str(directory), "entries": []}
    cached = {}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict) and payload.get("directory") == str(directory):
            for entry in payload.get("voices", []):
                identity, label = entry["id"], entry["label"]
                if (isinstance(identity, str) and identity not in ("", ".", "..")
                        and not any(c in identity for c in "/\\:") and isinstance(label, str)):
                    cached[identity] = label
    except (OSError, ValueError, KeyError, TypeError):
        pass
    found = {}
    try:
        with os.scandir(directory) as scan:
            folders = sorted(entry.name for entry in scan if entry.is_dir())
    except OSError as error:
        diagnostics["scan_error"] = str(error)
        diagnostics["using_cached_catalog"] = True
        found = cached.copy()
    else:
        for identity in folders:
            path = directory / identity / "voice.json"
            try:
                config = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(config, dict):
                    raise ValueError("voice.json must contain an object")
                diagnostics["entries"].append({"file": str(path), "ready": config.get("ready")})
                if config.get("ready"):
                    found[identity] = str(config.get("name") or identity)
            except (OSError, ValueError) as error:
                diagnostics["entries"].append({"file": str(path), "error": str(error)})
                if identity in cached:
                    found[identity] = cached[identity]
        try:
            save_settings(cache_path, {"directory": str(directory),
                "voices": [{"id": identity, "label": label} for identity, label in found.items()]})
        except OSError:
            pass
    packs = {}
    labels = list(found.values())
    for identity, label in found.items():
        if label == "关闭" or labels.count(label) > 1:
            label = f"{label}（{identity}）"
        packs[label] = directory / identity / "voice.json"
    try:
        save_settings(directory.parent / "voice-catalog-diagnostic.json", diagnostics)
    except OSError:
        pass
    return packs
