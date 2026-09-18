from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import queue
import subprocess
import sys
import tempfile
import threading
import winreg
import wave
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable
from .custom_voice import LocalVoiceClient, speech_chunk_limit
from .reply_length import speech_chunks, progressive_mixed_speech_chunks, progressive_speech_chunks
from .speech_rate import clamp_rate
from .voice_tone import brighten_voice
from .volcengine_voice import VolcengineVoiceRenderer, WaveOutPCMPlayer


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
        self.rate = 1.0
        self.custom_voice_pack: Path | None = None
        self.voice_mode = "performance"
        self.preload_enabled = True
        self.on_voice_error: Callable[[str], None] | None = None
        self._local_voice = LocalVoiceClient(project_dir)
        self._active_process: subprocess.Popen[bytes] | None = None
        self._active_wave_player: WaveOutPCMPlayer | None = None
        self._cloud_voice: VolcengineVoiceRenderer | None = None
        self._queue: queue.Queue[
            tuple[str, str, int, Callable[[], None] | None, Path | None] | None
        ] = queue.Queue()
        self._worker: threading.Thread | None = None
        if enabled:
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()

    def set_voice(self, voice_name: str) -> None:
        if voice_name in VOICE_PROFILES:
            self.voice_name = voice_name

    def set_rate(self, rate: float) -> None:
        self.rate = clamp_rate(rate)

    def set_custom_voice(self, path: Path | None) -> None:
        if path != self.custom_voice_pack:
            self.stop()
            if self._cloud_voice:
                self._cloud_voice.close()
                self._cloud_voice = None
            self._local_voice.close()
        self.custom_voice_pack = path
        self._prewarm()

    def reload_custom_voice(self) -> None:
        """Apply an edited voice-pack configuration on the next utterance."""
        if self.custom_voice_pack is None:
            return
        self.stop()
        if self._cloud_voice:
            self._cloud_voice.close()
            self._cloud_voice = None
        self._local_voice.close()
        self._prewarm()

    def set_schedule_mode(self, mode: str) -> None:
        if mode not in ("performance", "quality"):
            raise ValueError("未知语音调度模式")
        if mode != self.voice_mode:
            self.stop()
        self._local_voice.set_mode(mode)
        self.voice_mode = mode
        self._prewarm()

    def set_preload_enabled(self, enabled: bool) -> None:
        self.preload_enabled = bool(enabled)
        if not enabled:
            self.stop()
            self._local_voice.close()
        else:
            self._prewarm()

    def _prewarm(self) -> None:
        if (self.enabled and self.preload_enabled and self.custom_voice_pack
                and self._pack_engine(self.custom_voice_pack) == "volcengine"):
            self._cloud_renderer(self.custom_voice_pack).prewarm()
            return
        if (self.enabled and self.preload_enabled and self.voice_mode == "quality"
                and self.custom_voice_pack and self._pack_engine(self.custom_voice_pack) != "volcengine"):
            self._local_voice.prewarm(self.custom_voice_pack)

    def prepare_for_dictation(self) -> None:
        """Hide on-demand voice loading behind the time the user is speaking."""
        if (self.enabled and self.preload_enabled and self.custom_voice_pack
                and self._pack_engine(self.custom_voice_pack) == "volcengine"):
            self._cloud_renderer(self.custom_voice_pack).prewarm()
            return
        if (self.enabled and self.preload_enabled and self.custom_voice_pack
                and self._pack_engine(self.custom_voice_pack) != "volcengine"):
            self._local_voice.prewarm(self.custom_voice_pack, transient=True)

    @property
    def voice_status(self) -> str:
        if not self.preload_enabled:
            return "语音回复已关闭 · 不预热"
        if self.custom_voice_pack is None:
            return "选择自定义语音包后生效"
        if self._pack_engine(self.custom_voice_pack) == "volcengine":
            return "联网音色就绪 · 按需流式合成"
        return self._local_voice.status

    @staticmethod
    def _pack_engine(pack: Path) -> str:
        try:
            return str(json.loads(pack.read_text(encoding="utf-8-sig")).get("engine", ""))
        except (OSError, ValueError):
            return ""

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

    def speak(self, text: str, on_complete: Callable[[], None] | None = None,
              *, use_custom: bool = True) -> None:
        if not self.enabled or not text.strip():
            return
        # A new answer supersedes anything still speaking or waiting to speak.
        self.stop()
        self._prewarm()
        with self._lock:
            generation = self._generation
        self._queue.put((text.strip(), self.voice_name, generation, on_complete,
                         self.custom_voice_pack if use_custom else None))

    def _is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            text, voice_name, generation, on_complete, custom_pack = item
            rate = self.rate
            if not self._is_current(generation):
                continue
            try:
                if custom_pack:
                    if self._pack_engine(custom_pack) == "volcengine":
                        self._speak_volcengine(
                            progressive_speech_chunks(text, first_limit=40, limit=180),
                            generation, custom_pack, rate
                        )
                        continue
                    # Both modes pipeline active speech. Only quality keeps a
                    # prewarmed model resident when there is nothing to say.
                    parts = progressive_mixed_speech_chunks(text)
                    self._speak_prefetched(parts, voice_name, generation, custom_pack, rate)
                else:
                    parts = speech_chunks(text, limit=speech_chunk_limit(None, self.voice_mode))
                    for part in parts:
                        if not self._is_current(generation):
                            break
                        self._speak_part(part, voice_name, generation, custom_pack, rate)
            except Exception:
                pass
            finally:
                if on_complete and self._is_current(generation):
                    try:
                        on_complete()
                    except Exception:
                        pass

    def _speak_volcengine(self, parts: list[str], generation: int,
                          pack: Path, rate: float) -> None:
        try:
            renderer = self._cloud_renderer(pack)
            renderer.speak(parts, rate, lambda: self._is_current(generation))
        except Exception as exc:
            try:
                (pack.parent / "last-error.log").write_text(str(exc), encoding="utf-8")
            except OSError:
                pass
            if self._is_current(generation):
                if self.on_voice_error:
                    self.on_voice_error(str(exc))
                self._speak_offline("".join(parts), "Huihui", generation, rate)

    def _cloud_renderer(self, pack: Path) -> VolcengineVoiceRenderer:
        with self._lock:
            if self._cloud_voice is None:
                self._cloud_voice = VolcengineVoiceRenderer(self.project_dir, pack)
            return self._cloud_voice

    def _speak_prefetched(self, parts: list[str], voice_name: str, generation: int,
                         pack: Path, rate: float) -> None:
        """Generate at most one segment ahead while the previous one plays."""
        if not parts or not self._is_current(generation):
            return
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-next")
        queued_player: list[WaveOutPCMPlayer | None] = [None]

        def submit(text):
            return executor.submit(self._local_voice.synthesize, text, pack,
                                   lambda: self._is_current(generation))

        future = submit(parts[0])
        try:
            for index, part in enumerate(parts):
                if not self._is_current(generation):
                    break
                next_ready = []

                def prepare_next():
                    if index + 1 < len(parts) and self._is_current(generation):
                        next_ready.append(submit(parts[index + 1]))

                self._speak_part(part, voice_name, generation, pack, rate,
                                 prepared=future, on_ready=prepare_next,
                                 queued_player=queued_player)
                if index + 1 < len(parts) and self._is_current(generation):
                    future = next_ready[0] if next_ready else submit(parts[index + 1])
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
            player = queued_player[0]
            if player:
                with self._lock:
                    if self._active_wave_player is player:
                        self._active_wave_player = None
                player.close(wait=self._is_current(generation))

    def _speak_part(self, text: str, voice_name: str, generation: int,
                    custom_pack: Path | None, rate: float = 1.0, *,
                    prepared: Future | None = None, on_ready: Callable | None = None,
                    queued_player: list[WaveOutPCMPlayer | None] | None = None) -> None:
        rate = clamp_rate(rate)
        if custom_pack:
            try:
                path = (prepared.result() if prepared is not None else
                        self._local_voice.synthesize(text, custom_pack,
                                                     lambda: self._is_current(generation)))
                if path and self._is_current(generation):
                    if on_ready:
                        on_ready()
                    if rate == 1.0:
                        if queued_player is None:
                            self._play_mp3(path, generation)
                        else:
                            self._queue_wav(path, generation, queued_player)
                    else:
                        # Adjust cached audio, not the cloning request. Moving
                        # the speed slider must never force model regeneration.
                        config = json.loads(custom_pack.read_text(encoding="utf-8"))
                        with tempfile.TemporaryDirectory(prefix="keypilot-rate-") as folder:
                            adjusted = Path(folder) / "speech.wav"
                            shutil.copyfile(path, adjusted)
                            brighten_voice(adjusted, {"ffmpeg": config.get("ffmpeg", ""),
                                                     "speech_rate": rate, "pitch_semitones": 0})
                            if self._is_current(generation):
                                if queued_player is None:
                                    self._play_mp3(adjusted, generation)
                                else:
                                    self._queue_wav(adjusted, generation, queued_player)
                return
            except Exception as exc:
                try:
                    (custom_pack.parent / "last-error.log").write_text(str(exc), encoding="utf-8")
                except OSError:
                    pass
                if not self._is_current(generation):
                    return
                if self.on_voice_error:
                    self.on_voice_error(str(exc))
                try:
                    fast_pack = json.loads(custom_pack.read_text(encoding="utf-8")).get("engine") == "edge-rvc"
                except (OSError, ValueError):
                    fast_pack = False
                if fast_pack:
                    # Do not retry the same online TTS service after a failed
                    # network request. Speak promptly with an offline voice.
                    self._speak_offline(text, "Huihui", generation, rate)
                    return
        provider, voice_id = VOICE_PROFILES.get(voice_name, VOICE_PROFILES[DEFAULT_VOICE])
        if provider == "edge":
            try:
                self._speak_edge(text, voice_id, generation, rate)
            except Exception:
                if self._is_current(generation):
                    self._speak_offline(text, "Huihui", generation, rate)
        else:
            self._speak_offline(text, voice_id, generation, rate)

    def _speak_offline(self, text: str, voice_id: str, generation: int, rate: float = 1.0) -> None:
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
                "-SpeakingRate",
                str(clamp_rate(rate)),
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

    def _speak_edge(self, text: str, voice_id: str, generation: int, rate: float = 1.0) -> None:
        vendor_dir = self.project_dir / "vendor"
        vendor_path = str(vendor_dir)
        if vendor_path not in sys.path:
            sys.path.insert(0, vendor_path)
        import edge_tts

        file_handle, audio_path = tempfile.mkstemp(prefix="keypilot-tts-", suffix=".mp3")
        os.close(file_handle)
        try:
            percentage = round((clamp_rate(rate) - 1) * 100)
            asyncio.run(edge_tts.Communicate(text, voice_id, rate=f"{percentage:+d}%").save(audio_path))
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

    def _queue_wav(self, path: Path, generation: int,
                   holder: list[WaveOutPCMPlayer | None]) -> None:
        """Queue PCM in one persistent device so adjacent local segments touch cleanly."""
        if not self._is_current(generation):
            return
        with wave.open(str(path), "rb") as source:
            if (source.getnchannels(), source.getsampwidth(), source.getcomptype()) != (1, 2, "NONE"):
                raise ValueError("本地语音片段必须是单声道 PCM16 WAV")
            sample_rate = source.getframerate()
            pcm = source.readframes(source.getnframes())
        player = holder[0]
        if player is None:
            player = holder[0] = WaveOutPCMPlayer(sample_rate)
            with self._lock:
                self._active_wave_player = player
                cancelled = generation != self._generation
            if cancelled:
                player.cancel()
                return
        elif player.sample_rate != sample_rate:
            raise ValueError("相邻语音片段的采样率不一致")
        player.write(pcm)

    def stop(self) -> None:
        """Immediately stop current speech and discard speech waiting in the queue."""
        with self._lock:
            self._generation += 1
            process = self._active_process
            wave_player = self._active_wave_player
            cloud_voice = self._cloud_voice
        self._local_voice.cancel()
        if cloud_voice:
            cloud_voice.cancel()
        if wave_player:
            wave_player.cancel()

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
        self.enabled = False
        self.stop()
        if self._cloud_voice:
            self._cloud_voice.close()
            self._cloud_voice = None
        self._local_voice.close()
        if self._worker:
            self._queue.put(None)


__all__ = ["DEFAULT_VOICE", "SpeechEngine", "VOICE_PROFILES", "available_voice_profiles"]
