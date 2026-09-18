from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


def _bucket(value: float, low: float, high: float, labels: tuple[str, str, str]) -> str:
    return labels[0] if value < low else labels[2] if value > high else labels[1]


def doubao_mapping(metrics: dict, transcript: str = "") -> dict:
    pitch_hz = float(metrics.get("pitch_median_hz") or 0)
    pitch = _bucket(pitch_hz, 165, 225, ("偏低", "中等", "偏高")) if pitch_hz else "未测得"
    pause_ratio = float(metrics.get("pause_ratio") or 0)
    pause = _bucket(pause_ratio, 0.12, 0.28, ("停顿较少", "停顿自然", "停顿较多"))
    centroid = float(metrics.get("spectral_centroid_hz") or 0)
    color = _bucket(centroid, 1700, 2600, ("偏温暖厚实", "自然均衡", "偏明亮清晰"))
    cjk = len(re.findall(r"[\u3400-\u9fff]", transcript))
    active = max(float(metrics.get("active_duration_seconds") or 0), 0.001)
    chars_per_second = cjk / active if cjk else None
    if chars_per_second:
        pace = _bucket(chars_per_second, 3.2, 5.2, ("舒缓", "自然", "稍快"))
        speed_ratio = round(max(0.7, min(1.3, chars_per_second / 4.2)), 1)
    else:
        pace, speed_ratio = "自然", 1.0
    instruction = (
        f"保持自然、清晰、亲切的口语表达；音高{pitch}，语速{pace}，{pause}；"
        f"音色{color}，咬字完整，不要播音腔，不要夸张情绪。"
    )
    return {
        "doubao_big_model_api": {
            "speed_ratio": speed_ratio,
            "loudness_ratio": 1.0,
            "emotion": "neutral",
            "emotion_scale": 2.0,
            "pitch_ratio": None,
        },
        "manual_voice_instruction": instruction,
        "observed_style": {"pitch": pitch, "pace": pace, "pausing": pause, "timbre": color},
        "notes": [
            "大模型声音复刻接口目前不支持 pitch_ratio；音高只能写进语音指令，或改用支持音高的接口。",
            "录音音量受麦克风增益影响，因此 loudness_ratio 默认保留 1.0。",
            "没有逐字稿时无法可靠估计说话速度，speed_ratio 会回退到 1.0。",
        ],
    }


def analyze(path: Path, transcript: str = "") -> dict:
    try:
        import librosa
        import numpy as np
        import parselmouth
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("缺少分析依赖；请安装项目的 analysis 可选依赖。") from exc
    audio, sample_rate = sf.read(path, always_2d=False)
    if getattr(audio, "ndim", 1) > 1:
        audio = np.mean(audio, axis=1)
    audio = np.asarray(audio, dtype=np.float64)
    if not len(audio):
        raise ValueError("音频为空。")
    peak = float(np.max(np.abs(audio)))
    duration = len(audio) / sample_rate
    intervals = librosa.effects.split(audio.astype(np.float32), top_db=32)
    active_samples = int(sum(end - start for start, end in intervals))
    active_duration = active_samples / sample_rate
    rms = float(np.sqrt(np.mean(np.square(audio))))
    rms_dbfs = 20 * math.log10(max(rms, 1e-12))
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=audio.astype(np.float32), sr=sample_rate)))

    sound = parselmouth.Sound(audio, sampling_frequency=sample_rate)
    pitch = sound.to_pitch(time_step=0.01, pitch_floor=60, pitch_ceiling=500)
    voiced = pitch.selected_array["frequency"]
    voiced = voiced[voiced > 0]
    pitch_stats = {
        "pitch_median_hz": round(float(np.median(voiced)), 2) if len(voiced) else None,
        "pitch_p10_hz": round(float(np.percentile(voiced, 10)), 2) if len(voiced) else None,
        "pitch_p90_hz": round(float(np.percentile(voiced, 90)), 2) if len(voiced) else None,
    }
    try:
        harmonicity = sound.to_harmonicity_cc(time_step=0.01, minimum_pitch=60)
        values = harmonicity.values[0]
        hnr = float(np.mean(values[np.isfinite(values)]))
    except Exception:
        hnr = float("nan")
    metrics = {
        "file": str(path.resolve()), "sample_rate": int(sample_rate),
        "duration_seconds": round(duration, 3),
        "active_duration_seconds": round(active_duration, 3),
        "pause_ratio": round(max(0.0, 1 - active_duration / duration), 3),
        "peak_dbfs": round(20 * math.log10(max(peak, 1e-12)), 2),
        "rms_dbfs": round(rms_dbfs, 2),
        "spectral_centroid_hz": round(centroid, 2),
        # Praat can return its unvoiced-frame floor for short/noisy clips; that
        # is not a meaningful clip-level HNR, so omit implausible aggregates.
        "hnr_db": round(hnr, 2) if math.isfinite(hnr) and -20 <= hnr <= 60 else None,
        **pitch_stats,
    }
    return {"metrics": metrics, "recommended_parameters": doubao_mapping(metrics, transcript)}


def main() -> None:
    parser = argparse.ArgumentParser(description="从参考声音提取可填入豆包的语速、情绪和语音指令建议")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--transcript", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = analyze(args.audio, args.transcript)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(args.output)
    else:
        print(rendered)


if __name__ == "__main__":
    main()
