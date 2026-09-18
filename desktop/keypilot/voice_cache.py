"""Shared cache keys without importing the inference runtime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def audio_cache_path(pack: Path, config: dict, text: str) -> Path:
    if config.get("engine") == "edge-rvc":
        # No reference recording is needed for an already trained RVC pack.
        # Include conversion settings and weight revisions, not only the text.
        identity = {key: config.get(key) for key in (
            "engine", "device", "source_voice", "index_rate", "protect", "rms_mix_rate",
            "pitch_semitones", "speech_rate", "f0_method", "cache_version", "loudness_lufs",
            "edge_fade_ms", "leading_silence_ms", "trailing_silence_ms",
        )}
        for key in ("model", "index"):
            path = Path(config[key])
            stat = path.stat()
            identity[key] = [str(path.resolve()), stat.st_size, stat.st_mtime_ns]
        key = hashlib.sha256((json.dumps(identity, sort_keys=True, ensure_ascii=False)
                              + text.strip()[:500]).encode("utf-8")).hexdigest()
        return pack.parent / "cache" / (key + ".wav")
    identity = json.dumps({key: config.get(key) for key in (
        "engine", "model", "vocoder", "reference_audio", "reference_text",
        "num_steps", "min_char_in_sentence", "pitch_semitones", "speech_rate",
        "loudness_lufs", "cache_version", "language_models", "edge_fade_ms",
        "leading_silence_ms", "trailing_silence_ms", "language_references",
    )}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    reference_bytes = bytearray(Path(config["reference_audio"]).read_bytes())
    routes = config.get("language_references")
    if isinstance(routes, dict):
        for language in sorted(routes):
            route = routes[language]
            if isinstance(route, dict) and route.get("audio"):
                reference_bytes.extend(Path(route["audio"]).read_bytes())
    fingerprint = hashlib.sha256(identity + reference_bytes).hexdigest()
    key = hashlib.sha256((fingerprint + text.strip()[:500]).encode("utf-8")).hexdigest()
    return pack.parent / "cache" / (key + ".wav")
