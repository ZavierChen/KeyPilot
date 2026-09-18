import json
import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from unittest.mock import Mock, patch

from keypilot.custom_voice import LocalVoiceClient, available_voice_packs
from keypilot.speech import DEFAULT_VOICE, SpeechEngine
from keypilot.voice_preferences import (
    set_zipvoice_quality,
    zipvoice_quality_label,
    zipvoice_quality_options,
)
from keypilot.voice_worker import zipvoice_language_key, zipvoice_model_directory, zipvoice_reference


class CustomVoiceTests(unittest.TestCase):
    def test_ready_pack_stays_visible_with_missing_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pack = folder / "sister"
            pack.mkdir()
            (pack / "voice.json").write_text(json.dumps(dict(name="姐姐", ready=True,
                python="missing-python.exe", reference_audio="missing.wav", model="missing-model")), encoding="utf-8")
            with patch("keypilot.custom_voice.voice_pack_directory", return_value=folder):
                self.assertIn("姐姐", available_voice_packs())

    def test_pitch_change_invalidates_audio_cache(self):
        from keypilot.voice_cache import audio_cache_path
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "voice.json"
            reference = Path(tmp) / "ref.wav"
            reference.write_bytes(b"reference")
            config = dict(reference_audio=str(reference))
            before = audio_cache_path(pack, config, "你好")
            config["pitch_semitones"] = 0.8
            self.assertNotEqual(before, audio_cache_path(pack, config, "你好"))

    def test_no_pitch_does_not_launch_ffmpeg(self):
        from keypilot.voice_tone import brighten_voice
        with patch("keypilot.voice_tone.subprocess.run") as run:
            brighten_voice(Path("unused.wav"), {})
        run.assert_not_called()

    def test_rate_change_invalidates_audio_cache(self):
        from keypilot.voice_cache import audio_cache_path
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "voice.json"
            reference = Path(tmp) / "ref.wav"
            reference.write_bytes(b"reference")
            config = dict(reference_audio=str(reference))
            original = audio_cache_path(pack, config, "你好")
            config["speech_rate"] = 0.82
            self.assertNotEqual(original, audio_cache_path(pack, config, "你好"))

    def test_invalid_speech_rate_is_rejected(self):
        from keypilot.voice_tone import brighten_voice
        for value in (0, 2, float("nan")):
            with self.assertRaises(ValueError):
                brighten_voice(Path("unused.wav"), {"speech_rate": value})

    def test_voice_edges_are_faded_and_padded(self):
        from keypilot.voice_tone import smooth_voice_edges
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "segment.wav"
            with wave.open(str(wav), "wb") as target:
                target.setparams((1, 2, 1000, 20, "NONE", "not compressed"))
                target.writeframes(array("h", [10000] * 20).tobytes())
            smooth_voice_edges(wav, {"edge_fade_ms": 5,
                                     "leading_silence_ms": 3,
                                     "trailing_silence_ms": 7})
            with wave.open(str(wav), "rb") as result:
                samples = array("h")
                samples.frombytes(result.readframes(result.getnframes()))
            self.assertEqual(len(samples), 30)
            self.assertEqual(samples[:4], array("h", [0, 0, 0, 0]))
            self.assertEqual(samples[-8:], array("h", [0] * 8))

    def test_prefetched_segments_share_one_pcm_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav = root / "segment.wav"
            with wave.open(str(wav), "wb") as target:
                target.setparams((1, 2, 24000, 4, "NONE", "not compressed"))
                target.writeframes(array("h", [0, 1, 0, -1]).tobytes())
            engine = SpeechEngine(root, enabled=False)
            engine._local_voice = Mock()
            engine._local_voice.synthesize.return_value = wav
            player = Mock(sample_rate=24000)
            with patch("keypilot.speech.WaveOutPCMPlayer", return_value=player) as factory:
                engine._speak_prefetched(["第一段。", "第二段。"], DEFAULT_VOICE, 0,
                                         root / "voice.json", 1.0)
            factory.assert_called_once_with(24000)
            self.assertEqual(player.write.call_count, 2)
            player.close.assert_called_once_with(wait=True)

    def test_qwen_loudness_change_invalidates_quiet_cache(self):
        from keypilot.voice_cache import audio_cache_path
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "voice.json"
            reference = Path(tmp) / "ref.wav"
            reference.write_bytes(b"reference")
            config = dict(engine="qwen3-tts-zero-shot", reference_audio=str(reference))
            quiet = audio_cache_path(pack, config, "你好")
            loud = audio_cache_path(pack, {**config, "loudness_lufs": -14}, "你好")
            self.assertNotEqual(quiet, loud)
            self.assertNotEqual(loud, audio_cache_path(pack, {**config, "loudness_lufs": -16}, "你好"))

    def test_zipvoice_step_change_invalidates_audio_cache(self):
        from keypilot.voice_cache import audio_cache_path
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "voice.json"
            reference = Path(tmp) / "ref.wav"
            reference.write_bytes(b"reference")
            config = dict(engine="zipvoice", model="model", vocoder="vocoder.onnx",
                          reference_audio=str(reference), reference_text="你好", num_steps=4)
            before = audio_cache_path(pack, config, "测试")
            self.assertNotEqual(before, audio_cache_path(pack, {**config, "num_steps": 8}, "测试"))

    def test_zipvoice_quality_preset_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "voice.json"
            pack.write_text(json.dumps({"engine": "zipvoice", "num_steps": 4,
                                        "model": "kept"}), encoding="utf-8")
            self.assertEqual(zipvoice_quality_label(pack), "快速（4步）")
            self.assertEqual(set_zipvoice_quality(pack, "精细（16步）"), 16)
            saved = json.loads(pack.read_text(encoding="utf-8"))
            self.assertEqual(saved["num_steps"], 16)
            self.assertEqual(saved["model"], "kept")
            self.assertEqual(zipvoice_quality_label(pack), "精细（16步）")

    def test_zipvoice_model_aware_quality_preset_switches_model_and_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "voice.json"
            fast = "快速（v4 · 4步）"
            high = "高质量（v5 · 8步）"
            config = {
                "engine": "zipvoice",
                "model": "v4",
                "vocoder": "vocoder.onnx",
                "num_steps": 4,
                "cache_version": 4,
                "quality_preset": fast,
                "quality_presets": {
                    fast: {"model": "v4", "num_steps": 4, "cache_version": 4},
                    high: {"model": "v5", "num_steps": 8, "cache_version": 5},
                },
            }
            pack.write_text(json.dumps(config), encoding="utf-8")
            self.assertEqual(zipvoice_quality_options(pack), (fast, high))
            self.assertEqual(zipvoice_quality_label(pack), fast)
            self.assertEqual(set_zipvoice_quality(pack, high), 8)
            saved = json.loads(pack.read_text(encoding="utf-8"))
            self.assertEqual(saved["model"], "v5")
            self.assertEqual(saved["num_steps"], 8)
            self.assertEqual(saved["cache_version"], 5)
            self.assertEqual(zipvoice_quality_label(pack), high)

    def test_zipvoice_adaptive_preset_routes_english_and_chinese(self):
        config = {
            "engine": "zipvoice",
            "model": "v6",
            "language_models": {"english": "v5", "chinese": "v6"},
        }
        self.assertEqual(zipvoice_language_key("Everything is ready."), "english")
        self.assertEqual(zipvoice_language_key("中英文双语测试。"), "chinese")
        self.assertEqual(zipvoice_language_key("请打开 Spotify。"), "chinese")
        self.assertEqual(zipvoice_model_directory(config, "Hello."), Path("v5"))
        self.assertEqual(zipvoice_model_directory(config, "你好。"), Path("v6"))

    def test_zipvoice_adaptive_preset_routes_language_reference(self):
        config = {
            "reference_audio": "real-chinese.wav",
            "reference_text": "中文参考。",
            "language_references": {
                "english": {"audio": "steady-english.wav", "text": "A steady English reference."}
            },
        }
        self.assertEqual(
            zipvoice_reference(config, "How has your day been?"),
            (Path("steady-english.wav"), "A steady English reference."),
        )
        self.assertEqual(
            zipvoice_reference(config, "今天怎么样？"),
            (Path("real-chinese.wav"), "中文参考。"),
        )

    def test_switching_away_from_adaptive_preset_clears_routing(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "voice.json"
            adaptive = "中英自动"
            fast = "快速"
            pack.write_text(json.dumps({
                "engine": "zipvoice",
                "model": "v6",
                "num_steps": 8,
                "language_models": {"english": "v5", "chinese": "v6"},
                "language_references": {"english": {"audio": "english.wav", "text": "Hello."}},
                "quality_preset": adaptive,
                "quality_presets": {
                    adaptive: {"model": "v6", "num_steps": 8,
                               "language_models": {"english": "v5", "chinese": "v6"}},
                    fast: {"model": "v4", "num_steps": 4},
                },
            }), encoding="utf-8")
            set_zipvoice_quality(pack, fast)
            saved = json.loads(pack.read_text(encoding="utf-8"))
            self.assertNotIn("language_models", saved)
            self.assertNotIn("language_references", saved)

    def test_non_zipvoice_quality_is_not_editable(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "voice.json"
            pack.write_text(json.dumps({"engine": "volcengine"}), encoding="utf-8")
            self.assertIsNone(zipvoice_quality_label(pack))
            with self.assertRaisesRegex(ValueError, "不支持"):
                set_zipvoice_quality(pack, "快速（4步）")

    def test_only_ready_local_packs_are_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pack = folder / "sister"
            pack.mkdir()
            (pack / "python.exe").touch()
            (pack / "reference.wav").touch()
            (pack / "model").mkdir()
            config = dict(name="姐姐", ready=False, python=str(pack / "python.exe"),
                          reference_audio=str(pack / "reference.wav"), model=str(pack / "model"))
            with patch("keypilot.custom_voice.voice_pack_directory", return_value=folder):
                (pack / "voice.json").write_text(json.dumps(config), encoding="utf-8")
                self.assertEqual(available_voice_packs(), {})
                config["ready"] = True
                (pack / "voice.json").write_text(json.dumps(config), encoding="utf-8")
                self.assertEqual(available_voice_packs(), {"姐姐": pack / "voice.json"})

    def test_custom_selection_does_not_replace_builtin_voice(self):
        engine = SpeechEngine(Path("."), enabled=False)
        engine._local_voice = Mock()
        engine.set_custom_voice(Path("sister/voice.json"))
        self.assertEqual(engine.voice_name, DEFAULT_VOICE)
        engine.set_voice("康康（离线男声）")
        self.assertEqual(engine.custom_voice_pack, Path("sister/voice.json"))
        engine.set_custom_voice(None)
        self.assertEqual(engine.voice_name, "康康（离线男声）")

    def test_stop_cancels_local_generation(self):
        engine = SpeechEngine(Path("."), enabled=False)
        engine._local_voice = Mock()
        engine.stop()
        engine._local_voice.cancel.assert_called_once_with()

    def test_reload_custom_voice_restarts_local_worker(self):
        engine = SpeechEngine(Path("."), enabled=False)
        engine._local_voice = Mock()
        engine.custom_voice_pack = Path("sister/voice.json")
        engine.reload_custom_voice()
        engine._local_voice.cancel.assert_called_once_with()
        engine._local_voice.close.assert_called_once_with()

    def test_builtin_preview_does_not_clear_custom_selection(self):
        engine = SpeechEngine(Path("."), enabled=False)
        engine.enabled = True
        pack = Path("sister/voice.json")
        engine.set_custom_voice(pack)
        engine.speak("试听原声音", use_custom=False)
        self.assertIsNone(engine._queue.get_nowait()[4])
        self.assertEqual(engine.custom_voice_pack, pack)
        engine.speak("使用克隆音色")
        self.assertEqual(engine._queue.get_nowait()[4], pack)

    def test_cancel_only_terminates_busy_worker(self):
        client = LocalVoiceClient(Path("."))
        client.close = Mock()
        client.cancel()
        client.close.assert_not_called()
        client._pending = True
        client.cancel()
        client.close.assert_called_once_with()

    def test_stale_request_never_loads_model(self):
        client = LocalVoiceClient(Path("."))
        client._start = Mock()
        self.assertIsNone(client.synthesize("hello", Path("voice.json"), lambda: False))
        client._start.assert_not_called()

    def test_clipboard_reading_is_bounded(self):
        from keypilot.assistant_app import AssistantApp
        app = AssistantApp.__new__(AssistantApp)
        app.root = Mock()
        app.root.clipboard_get.return_value = "字" * 1000
        app.speech = Mock()
        app._set_status = Mock()
        app.read_clipboard_aloud()
        app.speech.speak.assert_called_once_with("字" * 600 + "……")


if __name__ == "__main__":
    unittest.main()
