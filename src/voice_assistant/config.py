from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_key: str
    tts_resource_id: str = "seed-icl-2.0"
    tts_ws_url: str = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
    voice_clone_url: str = "https://openspeech.bytedance.com/api/v3/tts/voice_clone"
    voice_query_url: str = "https://openspeech.bytedance.com/api/v3/tts/get_voice"
    sample_rate: int = 24000
    audio_format: str = "pcm"
    speech_rate: int = 0
    loudness_rate: int = 0
    profile_dir: Path = Path("data/profiles")
    metrics_file: Path = Path("outputs/latency.jsonl")

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> "Settings":
        if env_file:
            load_dotenv(env_file)
        api_key = os.getenv("VOLCENGINE_SPEECH_API_KEY", "").strip()
        return cls(
            api_key=api_key,
            tts_resource_id=os.getenv("VOLCENGINE_TTS_RESOURCE_ID", "seed-icl-2.0"),
            tts_ws_url=os.getenv(
                "VOLCENGINE_TTS_WS_URL",
                "wss://openspeech.bytedance.com/api/v3/tts/bidirection",
            ),
            voice_clone_url=os.getenv(
                "VOLCENGINE_VOICE_CLONE_URL",
                "https://openspeech.bytedance.com/api/v3/tts/voice_clone",
            ),
            voice_query_url=os.getenv(
                "VOLCENGINE_VOICE_QUERY_URL",
                "https://openspeech.bytedance.com/api/v3/tts/get_voice",
            ),
            sample_rate=int(os.getenv("TTS_SAMPLE_RATE", "24000")),
            audio_format=os.getenv("TTS_FORMAT", "pcm"),
            speech_rate=int(os.getenv("TTS_SPEECH_RATE", "0")),
            loudness_rate=int(os.getenv("TTS_LOUDNESS_RATE", "0")),
            profile_dir=Path(os.getenv("VOICE_PROFILE_DIR", "data/profiles")),
            metrics_file=Path(os.getenv("METRICS_FILE", "outputs/latency.jsonl")),
        )

    def require_api_key(self) -> None:
        if not self.api_key or self.api_key == "replace_me":
            raise RuntimeError(
                "缺少 VOLCENGINE_SPEECH_API_KEY。请复制 .env.example 为 .env 后填写新版豆包语音 API Key。"
            )
