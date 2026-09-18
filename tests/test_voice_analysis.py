from voice_assistant.voice_analysis import doubao_mapping


def test_doubao_mapping_with_transcript() -> None:
    result = doubao_mapping(
        {
            "pitch_median_hz": 238,
            "pause_ratio": 0.2,
            "spectral_centroid_hz": 2800,
            "active_duration_seconds": 2.0,
        },
        "这是十二个汉字左右的测试文本",
    )
    assert result["doubao_big_model_api"]["speed_ratio"] >= 1.0
    assert result["doubao_big_model_api"]["pitch_ratio"] is None
    assert "偏高" in result["manual_voice_instruction"]


def test_doubao_mapping_without_transcript_uses_safe_defaults() -> None:
    result = doubao_mapping({"pitch_median_hz": 180, "pause_ratio": 0.1, "spectral_centroid_hz": 2000})
    assert result["doubao_big_model_api"]["speed_ratio"] == 1.0
    assert result["doubao_big_model_api"]["loudness_ratio"] == 1.0
