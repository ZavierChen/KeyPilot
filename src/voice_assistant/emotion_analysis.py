from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable


EMOTION_TAGS = (
    "HAPPY",
    "SAD",
    "ANGRY",
    "NEUTRAL",
    "FEARFUL",
    "DISGUSTED",
    "SURPRISED",
    "EMO_UNKNOWN",
)
EVENT_TAGS = (
    "BGM",
    "Speech",
    "Applause",
    "Laughter",
    "Cry",
    "Sneeze",
    "Breath",
    "Cough",
    "Sing",
    "Speech_Noise",
    "Event_UNK",
)
_TAG_RE = re.compile(r"<\|([^|>]+)\|>")


def parse_sensevoice_output(raw_text: str) -> dict[str, Any]:
    """Keep SenseVoice's raw tags while exposing stable fields for reports."""
    tags = _TAG_RE.findall(raw_text or "")
    emotion = next((tag for tag in reversed(tags) if tag in EMOTION_TAGS), "EMO_UNKNOWN")
    events = [tag for tag in tags if tag in EVENT_TAGS and tag != "Speech"]
    transcript = _TAG_RE.sub("", raw_text or "").strip()
    return {
        "emotion": emotion.lower(),
        "events": events,
        "transcript": transcript,
        "raw": raw_text,
    }


def extract_opensmile_features(audio_path: Path) -> dict[str, Any]:
    """Extract the 88-dimensional eGeMAPSv02 utterance descriptor."""
    try:
        import opensmile
    except ImportError as exc:
        raise RuntimeError(
            "缺少 openSMILE；请使用 work/run-emotion-analysis.ps1 提供的隔离环境。"
        ) from exc

    smile = opensmile.Smile(
        feature_set=opensmile.FeatureSet.eGeMAPSv02,
        feature_level=opensmile.FeatureLevel.Functionals,
    )
    frame = smile.process_file(str(audio_path))
    if frame.empty:
        raise ValueError(f"openSMILE 没有从音频中提取到特征：{audio_path}")
    row = {name: round(float(value), 6) for name, value in frame.iloc[0].items()}
    selected_names = (
        "F0semitoneFrom27.5Hz_sma3nz_amean",
        "F0semitoneFrom27.5Hz_sma3nz_stddevNorm",
        "F0semitoneFrom27.5Hz_sma3nz_pctlrange0-2",
        "loudness_sma3_amean",
        "loudness_sma3_stddevNorm",
        "loudness_sma3_pctlrange0-2",
        "spectralFlux_sma3_amean",
        "HNRdBACF_sma3nz_amean",
        "jitterLocal_sma3nz_amean",
        "shimmerLocaldB_sma3nz_amean",
        "loudnessPeaksPerSec",
        "VoicedSegmentsPerSec",
        "MeanVoicedSegmentLengthSec",
        "MeanUnvoicedSegmentLength",
        "equivalentSoundLevel_dBp",
    )
    return {
        "feature_set": "eGeMAPSv02",
        "feature_level": "Functionals",
        "selected": {name: row[name] for name in selected_names},
        "all": row,
    }


class SenseVoiceAnalyzer:
    """Load SenseVoiceSmall once and reuse it across a dataset."""

    def __init__(self, *, device: str = "cuda:0", model: str = "iic/SenseVoiceSmall") -> None:
        try:
            from funasr import AutoModel
        except ImportError as exc:
            raise RuntimeError(
                "缺少 SenseVoice/FunASR；请使用 work/run-emotion-analysis.ps1 提供的隔离环境。"
            ) from exc
        self._model = AutoModel(
            model=model,
            trust_remote_code=False,
            device=device,
            disable_update=True,
        )

    def analyze(self, audio_path: Path) -> dict[str, Any]:
        result = self._model.generate(
            input=str(audio_path),
            cache={},
            language="zh",
            use_itn=False,
            batch_size=1,
        )
        if not result:
            raise RuntimeError(f"SenseVoice 没有返回结果：{audio_path}")
        return parse_sensevoice_output(str(result[0].get("text", "")))


def _records_from_dataset(dataset_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    summary_path = dataset_dir / "dataset-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    records = []
    for row in summary.get("records", []):
        records.append({
            "id": row["id"],
            "text": row.get("text", ""),
            "wav": row["wav"],
            "expected_style": summary.get("style_label", "neutral"),
        })
    return records, summary


def analyze_records(
    records: Iterable[dict[str, Any]],
    *,
    sensevoice: SenseVoiceAnalyzer | None,
) -> list[dict[str, Any]]:
    analyzed: list[dict[str, Any]] = []
    for index, source in enumerate(records, start=1):
        audio_path = Path(source["wav"])
        item = dict(source)
        item["opensmile"] = extract_opensmile_features(audio_path)
        if sensevoice is not None:
            item["sensevoice"] = sensevoice.analyze(audio_path)
        bad_events = set(item.get("sensevoice", {}).get("events", [])) - {"Breath"}
        item["accepted"] = not bad_events
        item["rejection_reasons"] = [f"检测到非语音事件：{event}" for event in sorted(bad_events)]
        analyzed.append(item)
        print(f"[{index}] {source['id']}: {'通过' if item['accepted'] else '排除'}")
    return analyzed


def _summary(rows: list[dict[str, Any]], source: dict[str, Any]) -> dict[str, Any]:
    emotion_counts: dict[str, int] = {}
    for row in rows:
        emotion = row.get("sensevoice", {}).get("emotion")
        if emotion:
            emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1
    selected_keys = next(
        (list(row["opensmile"]["selected"]) for row in rows if row.get("opensmile")), []
    )
    means = {
        key: round(sum(row["opensmile"]["selected"][key] for row in rows) / len(rows), 6)
        for key in selected_keys
    } if rows else {}
    return {
        "source_style": source.get("style_label", "unknown"),
        "context_texts": source.get("context_texts", []),
        "utterances": len(rows),
        "accepted": sum(bool(row["accepted"]) for row in rows),
        "emotion_counts": emotion_counts,
        "opensmile_selected_means": means,
        "records": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="用 SenseVoice 与 openSMILE 标注和筛选训练语音")
    parser.add_argument("dataset_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--skip-sensevoice", action="store_true")
    args = parser.parse_args()
    records, source = _records_from_dataset(args.dataset_dir)
    analyzer = None if args.skip_sensevoice else SenseVoiceAnalyzer(device=args.device)
    rows = analyze_records(records, sensevoice=analyzer)
    report = _summary(rows, source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
