from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class LatencyMetrics:
    request_id: str
    text_chars: int
    connect_ms: float | None = None
    session_start_ms: float | None = None
    first_audio_ms: float | None = None
    total_ms: float | None = None
    audio_bytes: int = 0
    audio_seconds: float | None = None
    realtime_factor: float | None = None

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"timestamp": time.time(), **asdict(self)}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
