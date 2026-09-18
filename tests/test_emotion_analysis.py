from voice_assistant.emotion_analysis import parse_sensevoice_output


def test_parse_sensevoice_output_preserves_emotion_and_events() -> None:
    result = parse_sensevoice_output(
        "<|zh|><|Speech|><|Laughter|>今天真是个好消息<|HAPPY|><|woitn|>"
    )
    assert result["emotion"] == "happy"
    assert result["events"] == ["Laughter"]
    assert result["transcript"] == "今天真是个好消息"


def test_parse_sensevoice_output_defaults_unknown_emotion() -> None:
    result = parse_sensevoice_output("<|zh|><|Speech|>普通文本<|woitn|>")
    assert result["emotion"] == "emo_unknown"
    assert result["events"] == []
