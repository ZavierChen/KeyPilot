"""Low-latency Volcengine cloned-voice synthesis and Windows PCM playback."""
from __future__ import annotations

from .data_paths import user_data_dir

import asyncio
import ctypes
import json
import os
import sys
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Callable

from .secure_store import load_secret
from .volcengine_protocol import Event, Message, MsgType, event_message


class VolcengineVoiceError(RuntimeError):
    pass


class _WaveFormat(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class _WaveHeader(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", wintypes.DWORD),
        ("dwBytesRecorded", wintypes.DWORD),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", wintypes.DWORD),
        ("dwLoops", wintypes.DWORD),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
    ]


class WaveOutPCMPlayer:
    """Small waveOut queue that starts playback as soon as the first PCM block arrives."""

    _WAVE_MAPPER = 0xFFFFFFFF
    _WHDR_DONE = 0x00000001

    def __init__(self, sample_rate: int) -> None:
        if os.name != "nt":
            raise VolcengineVoiceError("联网音色实时播放目前只支持 Windows。")
        self._winmm = ctypes.WinDLL("winmm")
        self._handle = ctypes.c_void_p()
        self._pending: list[tuple[ctypes.Array, _WaveHeader]] = []
        self._closed = False
        self.sample_rate = sample_rate
        audio_format = _WaveFormat(
            1, 1, sample_rate, sample_rate * 2, 2, 16, 0
        )
        result = self._winmm.waveOutOpen(
            ctypes.byref(self._handle),
            self._WAVE_MAPPER,
            ctypes.byref(audio_format),
            0,
            0,
            0,
        )
        if result:
            raise VolcengineVoiceError(f"无法打开 Windows 音频设备：{result}")

    def write(self, pcm: bytes) -> None:
        if self._closed or not pcm:
            return
        self._collect_finished()
        while len(self._pending) >= 12:
            self._wait_for_one()
        data = ctypes.create_string_buffer(pcm)
        header = _WaveHeader(ctypes.addressof(data), len(pcm), 0, 0, 0, 0, None, 0)
        size = ctypes.sizeof(header)
        result = self._winmm.waveOutPrepareHeader(self._handle, ctypes.byref(header), size)
        if result:
            raise VolcengineVoiceError(f"准备音频块失败：{result}")
        result = self._winmm.waveOutWrite(self._handle, ctypes.byref(header), size)
        if result:
            self._winmm.waveOutUnprepareHeader(self._handle, ctypes.byref(header), size)
            raise VolcengineVoiceError(f"播放音频块失败：{result}")
        self._pending.append((data, header))

    def _collect_finished(self) -> None:
        size = ctypes.sizeof(_WaveHeader)
        while self._pending and self._pending[0][1].dwFlags & self._WHDR_DONE:
            _, header = self._pending.pop(0)
            self._winmm.waveOutUnprepareHeader(self._handle, ctypes.byref(header), size)

    def _wait_for_one(self) -> None:
        while self._pending and not (self._pending[0][1].dwFlags & self._WHDR_DONE):
            time.sleep(0.005)
        self._collect_finished()

    def cancel(self) -> None:
        if not self._closed:
            self._winmm.waveOutReset(self._handle)

    def close(self, *, wait: bool = True) -> None:
        if self._closed:
            return
        if wait:
            while self._pending:
                self._wait_for_one()
        else:
            self.cancel()
        self._collect_finished()
        size = ctypes.sizeof(_WaveHeader)
        for _, header in self._pending:
            self._winmm.waveOutUnprepareHeader(self._handle, ctypes.byref(header), size)
        self._pending.clear()
        self._winmm.waveOutClose(self._handle)
        self._closed = True


class VolcengineVoiceRenderer:
    def __init__(self, project_dir: Path, pack: Path) -> None:
        config = json.loads(pack.read_text(encoding="utf-8-sig"))
        self.speaker_id = str(config.get("speaker_id", "")).strip()
        self.resource_id = str(config.get("resource_id", "seed-icl-2.0")).strip()
        self.ws_url = str(
            config.get("ws_url", "wss://openspeech.bytedance.com/api/v3/tts/bidirection")
        ).strip()
        self.model = str(config.get("model", "seed-tts-2.0-standard")).strip()
        self.sample_rate = int(config.get("sample_rate", 24000))
        key_path = Path(
            config.get(
                "api_key_path",
                user_data_dir()
                / "volcengine-speech-api-key.dat",
            )
        )
        self.api_key = load_secret(key_path)
        if not self.speaker_id:
            raise VolcengineVoiceError("联网音色缺少 speaker_id。")
        if not self.api_key:
            raise VolcengineVoiceError("尚未保存火山引擎 API Key。")
        vendor = str(project_dir / "vendor")
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        self.metrics_path = user_data_dir() / "voice-latency.jsonl"
        self._cancelled = threading.Event()
        self._player_lock = threading.Lock()
        self._player: WaveOutPCMPlayer | None = None
        self._loop_lock = threading.Lock()
        self._loop_ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._websocket = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if self._loop and self._loop.is_running():
                return self._loop
            self._loop_ready.clear()

            def run() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                self._loop_ready.set()
                loop.run_forever()
                loop.close()

            self._loop_thread = threading.Thread(
                target=run, daemon=True, name="volcengine-voice-connection"
            )
            self._loop_thread.start()
        if not self._loop_ready.wait(timeout=3) or not self._loop:
            raise VolcengineVoiceError("无法启动火山引擎语音连接。")
        return self._loop

    def prewarm(self) -> None:
        """Open the authenticated connection without sending billable text."""
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(self._ensure_connection(), loop)

        def consume_error(done) -> None:
            try:
                done.result()
            except Exception:
                pass  # A real synthesis retries and reports the useful error.

        future.add_done_callback(consume_error)

    def cancel(self) -> None:
        self._cancelled.set()
        with self._player_lock:
            if self._player:
                self._player.cancel()

    def speak(self, parts: list[str], rate: float, is_current: Callable[[], bool]) -> None:
        self._cancelled.clear()
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._stream(parts, rate, is_current), loop
        )
        future.result(timeout=180)

    def close(self) -> None:
        self.cancel()
        loop = self._loop
        if not loop or not loop.is_running():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._close_connection(), loop).result(timeout=3)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        if self._loop_thread and self._loop_thread is not threading.current_thread():
            self._loop_thread.join(timeout=3)
        self._loop = None
        self._loop_thread = None

    async def _ensure_connection(self):
        if self._websocket is not None and self._websocket.close_code is None:
            return self._websocket, 0.0, True
        import websockets

        connect_started = time.perf_counter()
        connect_id = str(uuid.uuid4())
        headers = {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": connect_id,
            "X-Control-Require-Usage-Tokens-Return": "*",
        }
        websocket = await websockets.connect(
            self.ws_url,
            additional_headers=headers,
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=15,
        )
        try:
            await websocket.send(event_message(Event.START_CONNECTION))
            await self._expect(websocket, Event.CONNECTION_STARTED)
        except Exception:
            await websocket.close()
            raise
        self._websocket = websocket
        return websocket, (time.perf_counter() - connect_started) * 1000, False

    async def _close_connection(self) -> None:
        websocket, self._websocket = self._websocket, None
        if websocket is None:
            return
        try:
            await websocket.send(event_message(Event.FINISH_CONNECTION))
            await asyncio.wait_for(
                self._expect(websocket, Event.CONNECTION_FINISHED), timeout=1
            )
        except Exception:
            pass
        await websocket.close()

    async def _stream(self, parts: list[str], rate: float, is_current: Callable[[], bool]) -> None:
        request_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        started = time.perf_counter()
        first_audio_ms = None
        audio_bytes = 0
        synthesis_ms = None
        player = WaveOutPCMPlayer(self.sample_rate)
        with self._player_lock:
            self._player = player
        cancelled = False
        try:
            websocket, connect_ms, connection_reused = await self._ensure_connection()
            try:
                request_base = {
                    "req_params": {
                        "model": self.model,
                        "speaker": self.speaker_id,
                        "audio_params": {
                            "format": "pcm",
                            "sample_rate": self.sample_rate,
                            "speech_rate": round((max(0.5, min(2.0, rate)) - 1.0) * 100),
                            "loudness_rate": 0,
                        },
                        "additions": json.dumps(
                            {"disable_markdown_filter": True, "disable_emoji_filter": True}
                        ),
                    }
                }
                payload = {**request_base, "event": int(Event.START_SESSION)}
                await websocket.send(
                    event_message(
                        Event.START_SESSION,
                        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                        session_id,
                    )
                )
                await self._expect(websocket, Event.SESSION_STARTED)
                session_start_ms = (time.perf_counter() - started) * 1000
                sender = asyncio.create_task(
                    self._send_text(websocket, parts, request_base, session_id, is_current)
                )
                try:
                    while True:
                        if self._cancelled.is_set() or not is_current():
                            cancelled = True
                            break
                        try:
                            raw = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                        except asyncio.TimeoutError:
                            continue
                        message = Message.decode(raw)
                        self._raise_if_error(message)
                        if message.msg_type == MsgType.AUDIO_ONLY_SERVER:
                            if first_audio_ms is None:
                                first_audio_ms = (time.perf_counter() - started) * 1000
                            audio_bytes += len(message.payload)
                            player.write(message.payload)
                        elif message.event == Event.SESSION_FINISHED:
                            break
                    if cancelled:
                        try:
                            await websocket.send(event_message(Event.CANCEL_SESSION, session_id=session_id))
                        except Exception:
                            pass
                    await sender
                finally:
                    if not sender.done():
                        sender.cancel()
                synthesis_ms = (time.perf_counter() - started) * 1000
            except Exception:
                await self._close_connection()
                raise
        finally:
            with self._player_lock:
                self._player = None
            player.close(wait=not cancelled)

        playback_complete_ms = (time.perf_counter() - started) * 1000
        total_ms = synthesis_ms or playback_complete_ms
        audio_seconds = audio_bytes / (self.sample_rate * 2)
        record = {
            "timestamp": time.time(),
            "request_id": request_id,
            "speaker_id": self.speaker_id,
            "text_chars": sum(len(part) for part in parts),
            "connect_ms": connect_ms,
            "connection_reused": connection_reused,
            "session_start_ms": session_start_ms,
            "first_audio_ms": first_audio_ms,
            "total_ms": total_ms,
            "playback_complete_ms": playback_complete_ms,
            "audio_seconds": audio_seconds,
            "realtime_factor": (total_ms / 1000 / audio_seconds) if audio_seconds else None,
            "cancelled": cancelled,
        }
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with self.metrics_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def _send_text(self, websocket, parts, request_base, session_id, is_current) -> None:
        for text in parts:
            if self._cancelled.is_set() or not is_current():
                return
            if not text:
                continue
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

    async def _expect(self, websocket, expected: Event) -> Message:
        message = Message.decode(await websocket.recv())
        self._raise_if_error(message)
        if message.event != expected:
            raise VolcengineVoiceError(
                f"火山引擎协议事件异常：需要 {expected.name}，收到 {message.event}"
            )
        return message

    @staticmethod
    def _raise_if_error(message: Message) -> None:
        if message.msg_type == MsgType.ERROR or message.event in {
            Event.CONNECTION_FAILED,
            Event.SESSION_FAILED,
        }:
            detail = message.payload.decode("utf-8", errors="replace")
            raise VolcengineVoiceError(
                f"火山引擎流式合成失败：code={message.error_code}, detail={detail}"
            )


__all__ = ["VolcengineVoiceError", "VolcengineVoiceRenderer", "WaveOutPCMPlayer"]
