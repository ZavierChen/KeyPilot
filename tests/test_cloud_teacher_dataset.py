import json

from voice_assistant.cloud_teacher_dataset import build_req_params, corpus_from_text_files


def test_context_texts_are_sent_as_tts_2_req_params() -> None:
    params = build_req_params(
        speaker_id="voice-id",
        model="seed-tts-2.0-standard",
        sample_rate=24000,
        context_texts=["用温柔自然的语气说话。"],
    )
    assert params["context_texts"] == ["用温柔自然的语气说话。"]
    assert "context_texts" not in json.loads(params["additions"])


def test_empty_context_is_not_sent() -> None:
    params = build_req_params(
        speaker_id="voice-id",
        model="seed-tts-2.0-standard",
        sample_rate=24000,
    )
    assert "context_texts" not in params


def test_english_commas_are_preserved(tmp_path) -> None:
    corpus = tmp_path / "english.txt"
    corpus.write_text("First, check the microphone, then start recording.\n", encoding="utf-8")
    assert corpus_from_text_files([corpus]) == [
        "First, check the microphone, then start recording."
    ]


def test_chinese_ascii_commas_are_normalized(tmp_path) -> None:
    corpus = tmp_path / "chinese.txt"
    corpus.write_text("首先,检查麦克风,然后开始录音。\n", encoding="utf-8")
    assert corpus_from_text_files([corpus]) == ["首先，检查麦克风，然后开始录音。"]
