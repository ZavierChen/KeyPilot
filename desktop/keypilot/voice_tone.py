"""Optional fast, formant-preserving pitch adjustment for private voice packs."""
from __future__ import annotations

import math
import subprocess
import sys
import wave
from array import array
from pathlib import Path


def normalize_voice_loudness(audio: Path, config: dict) -> None:
    """Normalize reply loudness with true-peak limiting, never system volume."""
    if config.get("loudness_lufs") is None:
        return
    target = float(config["loudness_lufs"])
    if not math.isfinite(target) or not -24 <= target <= -14:
        raise ValueError("语音响度目标必须在 -24 到 -14 LUFS 之间")
    ffmpeg = Path(config.get("ffmpeg", ""))
    if not ffmpeg.is_file():
        raise FileNotFoundError("语音响度工具不存在，请检查 ffmpeg 路径")
    adjusted = audio.with_suffix(".loud.wav")
    try:
        subprocess.run(
            [str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(audio), "-af", f"loudnorm=I={target:g}:TP=-1.5:LRA=11",
             "-ar", "40000", "-c:a", "pcm_s16le", str(adjusted)],
            check=True, capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        adjusted.replace(audio)
    finally:
        adjusted.unlink(missing_ok=True)


def brighten_voice(audio: Path, config: dict) -> None:
    semitones = float(config.get("pitch_semitones", 0))
    rate = float(config.get("speech_rate", 1))
    if not semitones and rate == 1:
        return
    if not math.isfinite(rate) or not 0.7 <= rate <= 1.3:
        raise ValueError("语音包语速必须在 0.7 到 1.3 之间")
    if not math.isfinite(semitones) or not -3 <= semitones <= 3:
        raise ValueError("语音包升降调必须在 -3 到 3 个半音之间")
    ffmpeg = Path(config.get("ffmpeg", ""))
    if not ffmpeg.is_file():
        raise FileNotFoundError("语音包调音工具不存在，请检查 ffmpeg 路径")
    adjusted = audio.with_suffix(".tone.wav")
    try:
        subprocess.run(
            [str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(audio), "-af",
             f"rubberband=tempo={rate:g}:pitch={2 ** (semitones / 12):.9f}:formant=preserved",
             "-c:a", "pcm_s16le", str(adjusted)],
            check=True, capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        adjusted.replace(audio)
    finally:
        adjusted.unlink(missing_ok=True)


def smooth_voice_edges(audio: Path, config: dict) -> None:
    """Give independently generated WAV segments click-free, untruncated edges."""
    fade_ms = float(config.get("edge_fade_ms", 12))
    leading_ms = float(config.get("leading_silence_ms", 12))
    trailing_ms = float(config.get("trailing_silence_ms", 45))
    for value in (fade_ms, leading_ms, trailing_ms):
        if not math.isfinite(value) or not 0 <= value <= 250:
            raise ValueError("语音首尾平滑时长必须在 0 到 250 毫秒之间")
    if fade_ms == leading_ms == trailing_ms == 0:
        return

    adjusted = audio.with_suffix(".edges.wav")
    try:
        with wave.open(str(audio), "rb") as source:
            params = source.getparams()
            frames = source.readframes(params.nframes)
        # Voice-pack output is PCM16. Leave an unusual format untouched so a
        # third-party pack does not become unreadable merely due to smoothing.
        if params.sampwidth != 2 or params.comptype != "NONE":
            return

        samples = array("h")
        samples.frombytes(frames)
        if sys.byteorder != "little":
            samples.byteswap()
        channels = params.nchannels
        frame_count = len(samples) // channels
        fade_frames = min(frame_count // 2, round(params.framerate * fade_ms / 1000))
        for frame in range(fade_frames):
            gain_in = frame / max(1, fade_frames)
            gain_out = (fade_frames - frame - 1) / max(1, fade_frames)
            for channel in range(channels):
                samples[frame * channels + channel] = round(
                    samples[frame * channels + channel] * gain_in
                )
                tail = (frame_count - fade_frames + frame) * channels + channel
                samples[tail] = round(samples[tail] * gain_out)

        leading_frames = round(params.framerate * leading_ms / 1000)
        trailing_frames = round(params.framerate * trailing_ms / 1000)
        silence_before = array("h", [0]) * (leading_frames * channels)
        silence_after = array("h", [0]) * (trailing_frames * channels)
        output = silence_before + samples + silence_after
        if sys.byteorder != "little":
            output.byteswap()
        with wave.open(str(adjusted), "wb") as target:
            target.setparams(params._replace(nframes=0))
            target.writeframes(output.tobytes())
        adjusted.replace(audio)
    finally:
        adjusted.unlink(missing_ok=True)
