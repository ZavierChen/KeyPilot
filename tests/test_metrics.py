import json

from voice_assistant.metrics import LatencyMetrics


def test_metrics_jsonl(tmp_path):
    path = tmp_path / "metrics.jsonl"
    LatencyMetrics(request_id="r1", text_chars=2, first_audio_ms=123.4).write_jsonl(path)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["request_id"] == "r1"
    assert record["first_audio_ms"] == 123.4
