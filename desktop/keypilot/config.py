from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TriggerConfig:
    virtual_key: str
    require_windows: bool
    require_shift: bool


@dataclass(frozen=True)
class GestureConfig:
    double_tap_ms: int
    hold_ms: int
    immediate_tap: bool = False


@dataclass(frozen=True)
class AppConfig:
    trigger: TriggerConfig
    gestures: GestureConfig
    actions: dict[str, dict[str, Any]]


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def load_config(path: Path) -> AppConfig:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    trigger = raw.get("trigger", {})
    gestures = raw.get("gestures", {})
    actions = raw.get("actions", {})

    for gesture_name in ("tap", "double_tap", "hold"):
        if gesture_name not in actions or not isinstance(actions[gesture_name], dict):
            raise ValueError(f"actions.{gesture_name} must be configured")

    virtual_key = trigger.get("virtual_key", "F23")
    if not isinstance(virtual_key, str) or not virtual_key:
        raise ValueError("trigger.virtual_key must be a non-empty string")

    return AppConfig(
        trigger=TriggerConfig(
            virtual_key=virtual_key.upper(),
            require_windows=bool(trigger.get("require_windows", True)),
            require_shift=bool(trigger.get("require_shift", True)),
        ),
        gestures=GestureConfig(
            double_tap_ms=_positive_int(gestures.get("double_tap_ms", 320), "gestures.double_tap_ms"),
            hold_ms=_positive_int(gestures.get("hold_ms", 550), "gestures.hold_ms"),
            immediate_tap=bool(gestures.get("immediate_tap", False)),
        ),
        actions=actions,
    )
