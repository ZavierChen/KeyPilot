from __future__ import annotations

import asyncio
import base64
import os
import queue
import subprocess
import sys
import tempfile
import threading
import winreg
from pathlib import Path
from typing import Callable


VOICE_PROFILES = {
    "晓晓（自然女声·联网）": ("edge", "zh-CN-XiaoxiaoNeural"),
    "晓伊（活泼女声·联网）": ("edge", "zh-CN-XiaoyiNeural"),
    "云希（自然男声·联网）": ("edge", "zh-CN-YunxiNeural"),
    "云健（沉稳男声·联网）": ("edge", "zh-CN-YunjianNeural"),
    "慧慧（离线女声）": ("onecore", "Huihui"),
    "瑶瑶（离线女声）": ("onecore", "Yaoyao"),
    "康康（离线男声）": ("onecore", "Kangkang"),
}
DEFAULT_VOICE = "晓晓（自然女声·联网）"


def available_voice_profiles() -> dict[str, tuple[str, str]]:
    """Return neural voices plus OneCore voices actually installed on this PC."""
    installed_tokens: list[str] = []
    registry_path = r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path) as key:
            index = 0
            while True:
                try:
                    installed_tokens.append(winreg.EnumKey(key, index).lower())
                    index += 1
                except OSError:
                    break
    except OSError:
        pass
    return {
        label: profile
        for label, profile in VOICE_PROFILES.items()
        if profile[0] == "edge" or any(profile[1].lower() in token for token in installed_tokens)
    }


class SpeechEngine:
    """Queued neural or offline speech with automatic SAPI fallback."""

    def __init__(
        self,
        project_dir: Path,
        *,
        enabled: bool = True,
        voice_name: str = DEFAULT_VOICE,
    ) -> None:
        self.project_dir = project_dir
        self.enabled = enabled
        self.voice_name = voice_name if voice_name in VOICE_PROFILES else DEFAULT_VOICE
        self._process: subprocess.Popen[str] | None = None
        self._sapi_voice: str | None = None
        self._lock = threading.RLock()
        self._generation = 0
        self._active_process: subprocess.Popen[bytes] | None = None
        self._queue: queue.Queue[
            tuple[str, str, int, Callable[[], None] | None] | None
        ] = queue.Queue()
        self._worker: threading.Thread | None = None
        if enabled:
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()

    def set_voice(self, voice_name: str) -> None:
        if voice_name in VOICE_PROFILES:
            self.voice_name = voice_name

    def _ensure_process(self, sapi_voice: str) -> subprocess.Popen[str] | None:
        if not self.enabled:
            return None
        if self._process and self._process.poll() is None and self._sapi_voice == sapi_voice:
            return self._process
        self._close_sapi()
        script = self.project_dir / "scripts" / "tts-host.ps1"
        self._process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-VoiceName",
                sapi_voice,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="ascii",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._sapi_voice = sapi_voice
        return self._process

    def speak(self, text: str, on_complete: Callable[[], None] | None = None) -> None:
        if not self.enabled or not text.strip():
            return
        # A new answer supersedes anything still speaking or waiting to speak.
        self.stop()
        with self._lock:
            generation = self._generation
        self._queue.put((text.strip(), self.voice_name, generation, on_complete))

    def _is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            text, voice_name, generation, on_complete = item
            if not self._is_current(generation):
                continue
            try:
                provider, voice_id = VOICE_PROFILES.get(
                    voice_name, VOICE_PROFILES[DEFAULT_VOICE]
                )
                if provider == "edge":
                    try:
                        self._speak_edge(text, voice_id, generation)
                    except Exception:
                        if self._is_current(generation):
                            self._speak_offline(text, "Huihui", generation)
                else:
                    self._speak_offline(text, voice_id, generation)
            except Exception:
                pass
            finally:
                if on_complete and self._is_current(generation):
                    try:
                        on_complete()
                    except Exception:
                        pass

    def _speak_offline(self, text: str, voice_id: str, generation: int) -> None:
        if not self._is_current(generation):
            return
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        script = self.project_dir / "scripts" / "onecore-tts.ps1"
        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-VoiceName",
                voice_id,
                "-TextBase64",
                payload,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with self._lock:
            self._active_process = process
            cancelled = generation != self._generation
        if cancelled:
            process.terminate()
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        finally:
            with self._lock:
                if self._active_process is process:
                    self._active_process = None

    def _speak_edge(self, text: str, voice_id: str, generation: int) -> None:
        vendor_dir = self.project_dir / "vendor"
        vendor_path = str(vendor_dir)
        if vendor_path not in sys.path:
            sys.path.insert(0, vendor_path)
        import edge_tts

        file_handle, audio_path = tempfile.mkstemp(prefix="keypilot-tts-", suffix=".mp3")
        os.close(file_handle)
        try:
            asyncio.run(edge_tts.Communicate(text, voice_id).save(audio_path))
            if self._is_current(generation):
                self._play_mp3(Path(audio_path), generation)
        finally:
            try:
                os.unlink(audio_path)
            except OSError:
                pass

    def _play_mp3(self, path: Path, generation: int) -> None:
        if not self._is_current(generation):
            return
        script = self.project_dir / "scripts" / "play-audio.ps1"
        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Path",
                str(path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with self._lock:
            self._active_process = process
            cancelled = generation != self._generation
        if cancelled:
            process.terminate()
        try:
            process.wait(timeout=90)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        finally:
            with self._lock:
                if self._active_process is process:
                    self._active_process = None

    def stop(self) -> None:
        """Immediately stop current speech and discard speech waiting in the queue."""
        with self._lock:
            self._generation += 1
            process = self._active_process

        while True:
            try:
                queued = self._queue.get_nowait()
            except queue.Empty:
                break
            if queued is None:
                self._queue.put(None)
                break

        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        with self._lock:
            self._close_sapi()

    def _close_sapi(self) -> None:
        if not self._process:
            return
        try:
            if self._process.stdin:
                self._process.stdin.write("__EXIT__\n")
                self._process.stdin.flush()
        except (OSError, BrokenPipeError):
            pass
        self._process = None
        self._sapi_voice = None

    def close(self) -> None:
        self.stop()
        if self._worker:
            self._queue.put(None)


__all__ = ["DEFAULT_VOICE", "SpeechEngine", "VOICE_PROFILES", "available_voice_profiles"]
