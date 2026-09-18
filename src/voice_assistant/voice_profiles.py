from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class VoiceProfile:
    name: str
    speaker_id: str
    resource_id: str = "seed-icl-2.0"
    consent_confirmed: bool = False
    created_at: str = ""


class VoiceProfileStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def save(self, profile: VoiceProfile) -> Path:
        if not _SAFE_NAME.fullmatch(profile.name):
            raise ValueError("音色配置名只能包含字母、数字、下划线和连字符，最长 64 个字符。")
        self.directory.mkdir(parents=True, exist_ok=True)
        created_at = profile.created_at or datetime.now(timezone.utc).isoformat()
        stored = VoiceProfile(**{**asdict(profile), "created_at": created_at})
        path = self.directory / f"{profile.name}.json"
        path.write_text(json.dumps(asdict(stored), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, name: str) -> VoiceProfile:
        if not _SAFE_NAME.fullmatch(name):
            raise ValueError("无效的音色配置名。")
        path = self.directory / f"{name}.json"
        if not path.is_file():
            raise FileNotFoundError(f"找不到音色配置：{name}")
        return VoiceProfile(**json.loads(path.read_text(encoding="utf-8")))

    def delete(self, name: str) -> None:
        if not _SAFE_NAME.fullmatch(name):
            raise ValueError("无效的音色配置名。")
        path = self.directory / f"{name}.json"
        if path.exists():
            path.unlink()
