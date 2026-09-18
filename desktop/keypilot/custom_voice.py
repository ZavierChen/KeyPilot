"""Optional local voice packs; isolated from built-in voice providers."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from .voice_cache import audio_cache_path
from .install_layout import voice_directory
from .voice_catalog import scan_voice_packs


def voice_pack_directory() -> Path:
    return voice_directory()


VOICE_SCHEDULE_MODES = {"performance": "性能", "quality": "质量"}


def speech_chunk_limit(pack: Path | None, mode: str = "performance") -> int:
    if pack:
        if mode == "quality":
            return 60
        try:
            if json.loads(pack.read_text(encoding="utf-8")).get("engine") == "edge-rvc":
                return 60
        except (OSError, ValueError):
            pass
    return 180


def available_voice_packs() -> dict[str, Path]:
    return scan_voice_packs(voice_pack_directory())


class LocalVoiceClient:
    """Serialized worker requests; optional silent preload and persistent residency."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir
        self._lock = threading.RLock()
        self._process = None
        self._pack = None
        self._responses = queue.Queue()
        self._pending = False
        self._rpc_lock = threading.Lock()
        self._request_id = None
        self._operation = None
        self._engine = None
        self._revision = 0
        self._warming = None
        self._ready = False
        self.mode = "performance"
        self._state = "性能模式 · 按需加载，空闲 60 秒释放"

    @property
    def status(self) -> str:
        with self._lock:
            if self._process and self._process.poll() is not None:
                self._ready = False
                return "模型已释放" if self.mode == "performance" else "模型已退出，可切换模式重新预热"
            return self._state

    @property
    def ready(self) -> bool:
        with self._lock:
            return bool(self._ready and self._process and self._process.poll() is None)

    def set_mode(self, mode: str) -> None:
        if mode not in VOICE_SCHEDULE_MODES:
            raise ValueError("未知语音调度模式")
        with self._lock:
            if self.mode == mode:
                return
            self.close()
            self.mode = mode
            self._state = ("质量模式 · 等待预热" if mode == "quality" else
                           "性能模式 · 按需加载，空闲 60 秒释放")

    def prewarm(self, pack: Path, *, transient: bool = False) -> None:
        """Warm asynchronously; transient warming is used while dictation is open."""
        with self._lock:
            if self.mode != "quality" and not transient:
                return
            key = (pack, self._revision)
            if self._warming == key or (self._pack == pack and self.ready):
                return
            self._warming = key
            self._state = "正在预热音色…首次需要数秒"

        def current() -> bool:
            return self._revision == key[1] and self._warming == key

        def warm() -> None:
            try:
                with self._rpc_lock:
                    if current():
                        self._request(pack, {"op": "warmup"}, current)
            except Exception as exc:
                with self._lock:
                    if current():
                        self._state = "预热失败：" + str(exc)[:90]
            finally:
                with self._lock:
                    if self._warming == key:
                        self._warming = None

        threading.Thread(target=warm, daemon=True, name="voice-prewarm").start()

    def _start(self, pack: Path) -> None:
        if self._process and self._process.poll() is None and self._pack == pack:
            return
        self._close_process()
        config = json.loads(pack.read_text(encoding="utf-8"))
        log_dir = pack.parent
        with (log_dir / "worker.log").open("a", encoding="utf-8") as log:
            env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONUTF8="1")
            env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="4")
            env["KEYPILOT_VOICE_MODE"] = self.mode
            # Use the real CPython executable with isolated packages. Windows
            # venv launchers spawn another process, which survives terminate().
            if config.get("site_packages"):
                env["PYTHONPATH"] = config["site_packages"]
                env["PYTHONNOUSERSITE"] = "1"
            process = subprocess.Popen(
                [config["python"], "-u", str(self.project_dir / "keypilot" / "voice_worker.py"), str(pack)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                text=True, encoding="utf-8", env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        self._process, self._pack = process, pack
        self._engine = config.get("engine", "qwen3-tts-zero-shot")
        self._ready = False
        responses = self._responses = queue.Queue()

        def read() -> None:
            try:
                for line in process.stdout:
                    try:
                        responses.put(json.loads(line))
                    except ValueError:
                        continue
            finally:
                responses.put({"error": "本地语音进程已经退出，请查看语音包中的 worker.log。"})

        threading.Thread(target=read, daemon=True).start()

    def _request(self, pack: Path, payload: dict, is_current: Callable[[], bool]) -> dict | None:
        with self._lock:
            if not is_current():
                return None
            self._start(pack)
            request_id = uuid.uuid4().hex
            process, responses = self._process, self._responses
            self._pending = True
            self._request_id = request_id
            self._operation = payload.get("op", "synthesize")
            self._state = "正在预热音色…" if self._operation == "warmup" else "正在生成语音…"
            try:
                process.stdin.write(json.dumps({"id": request_id, **payload}, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except (OSError, ValueError):
                self._pending = False
                self.close()
                raise
        deadline = time.monotonic() + 180
        try:
            while time.monotonic() < deadline:
                if not is_current():
                    self.cancel()
                    return None
                if self._process is not process:
                    return None
                try:
                    result = responses.get(timeout=0.1)
                except queue.Empty:
                    continue
                if not is_current():
                    return None
                if result.get("error"):
                    if result.get("id") not in (None, request_id):
                        continue
                    raise RuntimeError(str(result["error"]))
                if result.get("id") == request_id:
                    if result.get("cancelled"):
                        return None
                    self._ready = True
                    return result
            self.close()
            raise TimeoutError("本地语音生成超时。")
        finally:
            with self._lock:
                if self._request_id == request_id:
                    self._pending = False
                    self._request_id = self._operation = None
                    if self._ready and self._process is process:
                        self._state = ("质量模式 · 音色已就绪，模型保持驻留" if self.mode == "quality"
                                       else "音色已就绪 · 空闲 60 秒后释放")

    def synthesize(self, text: str, pack: Path, is_current: Callable[[], bool]) -> Path | None:
        # A stale queued reply must not start a model after microphone activation.
        while not self._rpc_lock.acquire(timeout=.05):
            if not is_current():
                return None
        try:
            if not is_current():
                return None
            config = json.loads(pack.read_text(encoding="utf-8"))
            cached = audio_cache_path(pack, config, text)
            if cached.is_file():
                return cached
            result = self._request(pack, {"op": "synthesize", "text": text}, is_current)
            if result is None or not is_current():
                return None
            path = Path(result["audio"])
            if not path.is_file():
                raise RuntimeError("本地语音没有生成音频。")
            return path
        finally:
            self._rpc_lock.release()

    def cancel(self) -> None:
        with self._lock:
            if self._pending:
                if self._operation == "warmup":
                    return  # Silent preload must not be killed by speak()'s stop().
                if self.mode == "quality" and self._engine == "qwen3-tts-zero-shot":
                    try:
                        self._process.stdin.write(json.dumps({"op": "cancel", "id": self._request_id}) + "\n")
                        self._process.stdin.flush()
                        return
                    except (OSError, ValueError, AttributeError):
                        pass
                self.close()

    def close(self) -> None:
        with self._lock:
            self._revision += 1
            self._warming = None
            self._state = "模型已释放"
            self._close_process()

    def _close_process(self) -> None:
        with self._lock:
            process, self._process = self._process, None
            self._ready = False
            self._pending = False
            self._request_id = self._operation = None
            if process:
                if process.poll() is None:
                    try:
                        process.terminate()
                    except OSError:
                        pass
                    # Reap asynchronously so microphone activation never waits.
                    threading.Thread(target=process.wait, daemon=True).start()
                if process.stdin:
                    try:
                        process.stdin.close()
                    except (OSError, ValueError):
                        pass
