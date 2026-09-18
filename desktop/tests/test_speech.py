import unittest
from pathlib import Path
from unittest.mock import Mock

from keypilot.speech import DEFAULT_VOICE, VOICE_PROFILES, SpeechEngine, available_voice_profiles


PROJECT_DIR = Path(__file__).resolve().parent.parent


class SpeechEngineTests(unittest.TestCase):
    def test_has_neural_and_offline_chinese_voices(self) -> None:
        providers = {provider for provider, _voice_id in VOICE_PROFILES.values()}
        self.assertEqual(providers, {"edge", "onecore"})

    def test_only_lists_installed_offline_voices(self) -> None:
        profiles = available_voice_profiles()
        self.assertIn(DEFAULT_VOICE, profiles)
        for _label, (provider, voice_id) in profiles.items():
            if provider == "onecore":
                self.assertIn(voice_id, {"Huihui", "Yaoyao", "Kangkang"})

    def test_rejects_unknown_voice_and_accepts_known_voice(self) -> None:
        engine = SpeechEngine(PROJECT_DIR, enabled=False, voice_name="not-a-voice")
        self.assertEqual(engine.voice_name, DEFAULT_VOICE)
        offline_voice = "康康（离线男声）"
        engine.set_voice(offline_voice)
        self.assertEqual(engine.voice_name, offline_voice)

    def test_stop_discards_queued_speech_and_terminates_active_process(self) -> None:
        engine = SpeechEngine(PROJECT_DIR, enabled=False)
        engine._queue.put(("旧回复一", DEFAULT_VOICE, 0, None))
        engine._queue.put(("旧回复二", DEFAULT_VOICE, 0, None))
        process = Mock()
        process.poll.return_value = None
        engine._active_process = process

        engine.stop()

        self.assertTrue(engine._queue.empty())
        self.assertEqual(engine._generation, 1)
        process.terminate.assert_called_once_with()

    def test_new_speech_interrupts_previous_playback(self) -> None:
        engine = SpeechEngine(PROJECT_DIR, enabled=False)
        engine.enabled = True
        process = Mock()
        process.poll.return_value = None
        engine._active_process = process

        engine.speak("新的回答")

        process.terminate.assert_called_once_with()
        queued = engine._queue.get_nowait()
        self.assertEqual(queued[0], "新的回答")


if __name__ == "__main__":
    unittest.main()
