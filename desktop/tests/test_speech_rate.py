import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from keypilot.speech_rate import clamp_rate
from keypilot.speech import SpeechEngine


class SpeechRateTests(unittest.TestCase):
    def test_bounds_and_invalid_saved_values(self):
        for value, expected in [(0.2, .9), (5, 1.1), (.957, .96), (None, 1),
                                ("bad", 1), (float("nan"), 1), (float("inf"), 1)]:
            self.assertEqual(clamp_rate(value), expected)

    def test_custom_rate_adjusts_audio_without_changing_clone_request(self):
        with tempfile.TemporaryDirectory() as temp:
            pack = Path(temp) / "voice.json"
            pack.write_text(json.dumps({"ffmpeg": "test-ffmpeg"}), encoding="utf-8")
            audio = Path(temp) / "cached.wav"
            audio.write_bytes(b"test audio")
            engine = SpeechEngine(Path("."), enabled=False)
            engine._local_voice.synthesize = Mock(return_value=audio)
            engine._play_mp3 = Mock()
            with patch("keypilot.speech.brighten_voice") as adjust:
                engine._speak_part("测试", "晓晓（自然女声·联网）", 0, pack, .9)
            self.assertEqual(engine._local_voice.synthesize.call_args.args[:2], ("测试", pack))
            self.assertEqual(adjust.call_args.args[1]["pitch_semitones"], 0)
            self.assertEqual(adjust.call_args.args[1]["speech_rate"], .9)
            engine._play_mp3.assert_called_once()
            self.assertEqual(audio.read_bytes(), b"test audio")
            self.assertFalse(adjust.call_args.args[0].exists())

    def test_default_custom_rate_skips_post_processing(self):
        engine = SpeechEngine(Path("."), enabled=False)
        audio = Path("cached.wav")
        engine._local_voice.synthesize = Mock(return_value=audio)
        engine._play_mp3 = Mock()
        with patch("keypilot.speech.brighten_voice") as adjust:
            engine._speak_part("测试", "晓晓（自然女声·联网）", 0, Path("voice.json"), 1)
        adjust.assert_not_called()
        engine._play_mp3.assert_called_once_with(audio, 0)

    def test_edge_and_offline_receive_limited_rate(self):
        engine = SpeechEngine(Path("."), enabled=False)
        engine._speak_edge = Mock()
        engine._speak_offline = Mock()
        engine._speak_part("测试", "晓晓（自然女声·联网）", 0, None, 4)
        self.assertEqual(engine._speak_edge.call_args.args[-1], 1.1)
        engine._speak_part("测试", "慧慧（离线女声）", 0, None, .1)
        self.assertEqual(engine._speak_offline.call_args.args[-1], .9)
