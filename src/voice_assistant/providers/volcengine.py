from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path
from typing import Any

import requests
import websockets

from voice_assistant.config import Settings
from voice_assistant.metrics import LatencyMetrics
from voice_assistant.providers.volcengine_protocol import Event, Message, MsgType, event_message


class VolcengineAPIError(RuntimeError):
    pass


class VolcengineVoiceCloneClient:
    def __init__(self, settings: Settings, timeout: float = 60.0):
        settings.require_api_key()
        self.settings = settings
        self.timeout = timeout

    def train(
        self,
        audio_path: Path,
        *,
        speaker_id: str,
        text: str | None = None,
        language: int = 0,
        demo_text: str | None = None,
        denoise: bool = False,
        disable_volume_normalization: bool = False,
        audio_format: str | None = None,
        custom_speaker_id: str | None = None,
    ) -> dict[str, Any]:
        if not audio_path.is_file():
            raise FileNotFoundError(audio_path)
        if audio_path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("训练音频超过火山引擎当前 10 MB 上限。")
        fmt = (audio_format or audio_path.suffix.lstrip(".")).lower()
        audio = base64.b64encode(audio_path.read_bytes()).decode("ascii")
        body: dict[str, Any] = {
            "speaker_id": speaker_id,
            "audio": {"data": audio, "format": fmt},
            "language": language,
            "extra_params": {
                "enable_audio_denoise": denoise,
                "disable_volume_normalization": disable_volume_normalization,
            },
        }
        if custom_speaker_id:
            body["custom_speaker_id"] = custom_speaker_id
        if text:
            body["text"] = text
        if demo_text:
            body["extra_params"]["demo_text"] = demo_text
        return self._post(self.settings.voice_clone_url, body)

    def status(self, *, speaker_id: str, custom_speaker_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"speaker_id": speaker_id}
        if custom_speaker_id:
            body["custom_speaker_id"] = custom_speaker_id
        return self._post(self.settings.voice_query_url, body)

    def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        response = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": self.settings.api_key,
                "X-Api-Resource-Id": self.settings.tts_resource_id,
                "X-Api-Request-Id": request_id,
            },
            json=body,
            timeout=self.timeout,
        )
        log_id = response.headers.get("X-Tt-Logid", "")
        try:
            data = response.json()
        except requests.JSONDecodeError as exc:
            raise VolcengineAPIError(
                f"火山引擎返回非 JSON 响应：HTTP {response.status_code}，logid={log_id}"
            ) from exc
        if not response.ok or data.get("code", 0) != 0:
            raise VolcengineAPIError(
                f"火山引擎请求失败：HTTP {response.status_code}，logid={log_id}，response={data}"
            )
        return data


class VolcengineStreamingTTS:
    def __init__(self, settings: Settings):
        settings.require_api_key()
        if settings.audio_format != "pcm":
            raise ValueError("当前实时播放器仅支持 pcm；保存文件可自行扩展 mp3/ogg_opus。")
        self.settings = settings
        self.last_metrics: LatencyMetrics | None = None

    async def synthesize(
        self, text_chunks: AsyncIterable[str], speaker_id: str
    ) -> AsyncIterator[bytes]:
        request_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        started = time.perf_counter()
        metrics = LatencyMetrics(request_id=request_id, text_chars=0)
        headers = {
            "X-Api-Key": self.settings.api_key,
            "X-Api-Resource-Id": self.settings.tts_resource_id,
            "X-Api-Connect-Id": request_id,
            "X-Control-Require-Usage-Tokens-Return": "*",
        }
        async with websockets.connect(
            self.settings.tts_ws_url,
            additional_headers=headers,
            max_size=10 * 1024 * 1024,
            ping_interval=None,
        ) as websocket:
            metrics.connect_ms = (time.perf_counter() - started) * 1000
            await websocket.send(event_message(Event.START_CONNECTION))
            await self._wait_for(websocket, Event.CONNECTION_STARTED)

            request_base = {
                "req_params": {
                    "model": "seed-tts-2.0-standard",
                    "speaker": speaker_id,
                    "audio_params": {
                        "format": self.settings.audio_format,
                        "sample_rate": self.settings.sample_rate,
                        "speech_rate": self.settings.speech_rate,
                        "loudness_rate": self.settings.loudness_rate,
                    },
                    "additions": json.dumps(
                        {"disable_markdown_filter": True, "disable_emoji_filter": True}
                    ),
                }
            }
            session_payload = {**request_base, "event": int(Event.START_SESSION)}
            await websocket.send(
                event_message(
                    Event.START_SESSION,
                    json.dumps(session_payload, ensure_ascii=False).encode("utf-8"),
                    session_id,
                )
            )
            await self._wait_for(websocket, Event.SESSION_STARTED)
            metrics.session_start_ms = (time.perf_counter() - started) * 1000

            sender = asyncio.create_task(
                self._send_text(websocket, text_chunks, request_base, session_id, metrics)
            )
            first_audio = True
            try:
                while True:
                    msg = Message.decode(await websocket.recv())
                    self._raise_if_error(msg)
                    if msg.msg_type == MsgType.AUDIO_ONLY_SERVER:
                        if first_audio:
                            metrics.first_audio_ms = (time.perf_counter() - started) * 1000
                            first_audio = False
                        metrics.audio_bytes += len(msg.payload)
                        yield msg.payload
                    elif msg.event == Event.SESSION_FINISHED:
                        break
                await sender
            finally:
                if not sender.done():
                    sender.cancel()
                await websocket.send(event_message(Event.FINISH_CONNECTION))
                try:
                    await self._wait_for(websocket, Event.CONNECTION_FINISHED)
                except Exception:
                    pass

        metrics.total_ms = (time.perf_counter() - started) * 1000
        metrics.audio_seconds = metrics.audio_bytes / (self.settings.sample_rate * 2)
        if metrics.audio_seconds:
            metrics.realtime_factor = (metrics.total_ms / 1000) / metrics.audio_seconds
        metrics.write_jsonl(self.settings.metrics_file)
        self.last_metrics = metrics

    async def _send_text(
        self,
        websocket: Any,
        text_chunks: AsyncIterable[str],
        request_base: dict[str, Any],
        session_id: str,
        metrics: LatencyMetrics,
    ) -> None:
        async for text in text_chunks:
            if not text:
                continue
            metrics.text_chars += len(text)
            payload = json.loads(json.dumps(request_base))
            payload["event"] = int(Event.TASK_REQUEST)
            payload["req_params"]["text"] = text
            await websocket.send(
                event_message(
                    Event.TASK_REQUEST,
                    json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    session_id,
                )
            )
        await websocket.send(event_message(Event.FINISH_SESSION, session_id=session_id))

    async def _wait_for(self, websocket: Any, expected: Event) -> Message:
        msg = Message.decode(await websocket.recv())
        self._raise_if_error(msg)
        if msg.event != expected:
            raise VolcengineAPIError(f"协议事件不符合预期：需要 {expected.name}，收到 {msg.event}")
        return msg

    @staticmethod
    def _raise_if_error(msg: Message) -> None:
        if msg.msg_type == MsgType.ERROR or msg.event in {
            Event.CONNECTION_FAILED,
            Event.SESSION_FAILED,
        }:
            detail = msg.payload.decode("utf-8", errors="replace")
            raise VolcengineAPIError(
                f"火山引擎流式合成失败：code={msg.error_code}, event={msg.event}, detail={detail}"
            )


async def text_once(text: str) -> AsyncIterator[str]:
    yield text


async def chunk_text(text: str, size: int = 12, delay_ms: int = 0) -> AsyncIterator[str]:
    for start in range(0, len(text), size):
        yield text[start : start + size]
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
