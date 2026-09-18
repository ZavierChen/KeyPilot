"""Keep a voice selection stable across display-name changes and unavailable packs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .user_settings import save_settings


ZIPVOICE_QUALITY_STEPS = {
    "快速（4步）": 4,
    "均衡（8步）": 8,
    "精细（16步）": 16,
}
ZIPVOICE_QUALITY_OPTIONS = tuple(ZIPVOICE_QUALITY_STEPS)
ZIPVOICE_PRESET_FIELDS = (
    "model",
    "language_models",
    "language_references",
    "vocoder",
    "tokens",
    "encoder",
    "decoder",
    "data_dir",
    "lexicon",
    "num_steps",
    "cache_version",
)


def _load_zipvoice_config(pack: Path) -> dict | None:
    try:
        config = json.loads(pack.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(config, dict) or config.get("engine") != "zipvoice":
        return None
    return config


def zipvoice_quality_options(pack: Path | None) -> tuple[str, ...]:
    """Return model-aware presets when a pack defines them, else legacy step presets."""
    if pack is None:
        return ()
    config = _load_zipvoice_config(pack)
    if config is None:
        return ()
    presets = config.get("quality_presets")
    if isinstance(presets, dict) and presets:
        labels = tuple(
            label for label, preset in presets.items()
            if isinstance(label, str) and label and isinstance(preset, dict)
        )
        if labels:
            return labels
    return ZIPVOICE_QUALITY_OPTIONS


def restore_voice_selection(settings: Mapping, packs: Mapping[str, Path]) -> tuple[str, str]:
    label = str(settings.get("custom_voice_pack", "关闭"))
    identity = str(settings.get("custom_voice_pack_id", ""))
    if identity:
        for current_label, path in packs.items():
            if path.parent.name == identity:
                return current_label, identity
        # Do not choose a different pack based on a recycled display name.
        return label, identity
    if label == "关闭":
        return label, ""
    path = packs.get(label)
    return label, path.parent.name if path else ""


def selected_voice_path(label: str, identity: str, packs: Mapping[str, Path]) -> Path | None:
    if identity:
        return next((path for path in packs.values() if path.parent.name == identity), None)
    return packs.get(label) if label != "关闭" else None


def voice_selection_values(label: str, packs: Mapping[str, Path]) -> list[str]:
    # A temporarily unavailable selection stays in the UI instead of being reset.
    values = ["关闭", *packs]
    if label not in values:
        values.append(label)
    return values


def zipvoice_quality_label(pack: Path | None) -> str | None:
    """Return the visible quality preset for a ZipVoice pack."""
    if pack is None:
        return None
    config = _load_zipvoice_config(pack)
    if config is None:
        return None
    presets = config.get("quality_presets")
    if isinstance(presets, dict) and presets:
        selected = config.get("quality_preset")
        if selected in presets and isinstance(presets[selected], dict):
            return selected
        for label, preset in presets.items():
            if not isinstance(label, str) or not isinstance(preset, dict):
                continue
            comparable = [key for key in ZIPVOICE_PRESET_FIELDS if key in preset]
            if comparable and all(config.get(key) == preset[key] for key in comparable):
                return label
        return None
    try:
        steps = int(config.get("num_steps", 4))
    except (ValueError, TypeError):
        return None
    return next(
        (label for label, preset_steps in ZIPVOICE_QUALITY_STEPS.items() if preset_steps == steps),
        None,
    )


def set_zipvoice_quality(pack: Path, label: str) -> int:
    """Persist a supported ZipVoice generation preset without touching model files."""
    try:
        config = json.loads(pack.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError("无法读取 CPU 语音包配置") from exc
    if not isinstance(config, dict) or config.get("engine") != "zipvoice":
        raise ValueError("当前语音包不支持生成精度设置")
    presets = config.get("quality_presets")
    if isinstance(presets, dict) and presets:
        preset = presets.get(label)
        if not isinstance(preset, dict):
            raise ValueError("未知的 CPU 声音模式")
        try:
            steps = int(preset["num_steps"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("CPU 声音模式缺少有效步数") from exc
        if not 1 <= steps <= 16:
            raise ValueError("CPU 声音模式步数必须在 1 到 16 之间")
        for key in ZIPVOICE_PRESET_FIELDS:
            if key in preset:
                config[key] = preset[key]
            elif key in {"language_models", "language_references"}:
                config.pop(key, None)
        config["num_steps"] = steps
        config["quality_preset"] = label
        save_settings(pack, config)
        return steps
    if label not in ZIPVOICE_QUALITY_STEPS:
        raise ValueError("未知的 CPU 生成精度")
    steps = ZIPVOICE_QUALITY_STEPS[label]
    config["num_steps"] = steps
    save_settings(pack, config)
    return steps
