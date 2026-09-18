import io
import json
import threading
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from keypilot.custom_voice import LocalVoiceClient, speech_chunk_limit
from keypilot.speech import SpeechEngine, DEFAULT_VOICE
from keypilot.voice_worker import RequestInbox
from keypilot import voice_worker


class VoiceScheduleTests(unittest.TestCase):
    def test_both_modes_pipeline_a_short_first_chunk_and_complete_once(self):
        text = "先把最重要的结论告诉你。" + "后续内容会在播放期间继续生成。" * 20
        for mode in ("performance", "quality"):
            with self.subTest(mode=mode):
                engine = SpeechEngine(Path("."), enabled=False)
                engine.voice_mode = mode
                callback = Mock()
                engine._speak_prefetched = Mock()
                engine._queue.put((text, DEFAULT_VOICE, 0, callback, Path("pack")))
                engine._queue.put(None)
                engine._worker_loop()
                parts = engine._speak_prefetched.call_args.args[0]
                self.assertLessEqual(len(parts[0]), 24)
                self.assertEqual("".join(parts), text)
                self.assertTrue(all(len(part) <= 60 for part in parts))
                engine._speak_prefetched.assert_called_once()
                callback.assert_called_once_with()
                engine.close()

    def test_rvc_native_initialization_precedes_blocking_input_thread(self):
        events = []
        class ImmediateReader:
            def __init__(self, target, **kwargs):
                self.target = target
            def start(self):
                events.append("stdin-reader")
                self.target()
        with tempfile.TemporaryDirectory() as folder:
            pack = Path(folder) / "voice.json"
            pack.write_text(json.dumps({"engine": "edge-rvc"}), encoding="utf-8")
            with (
                patch.dict(sys.modules, {"numpy": Mock(), "torch": Mock(), "soundfile": Mock()}),
                patch("keypilot.rvc_voice.RvcVoiceRenderer", side_effect=lambda config: events.append("rvc-native-load") or Mock()),
                patch.object(sys, "argv", ["voice_worker.py", str(pack)]),
                patch.object(sys, "stdin", io.StringIO("")),
                patch.object(voice_worker.threading, "Thread", ImmediateReader),
            ):
                voice_worker.main()
        self.assertEqual(events, ["rvc-native-load", "stdin-reader"])

    def test_chunks_preserve_performance_default(self):
        self.assertEqual(speech_chunk_limit(Path("missing")), 180)
        self.assertEqual(speech_chunk_limit(Path("missing"), "quality"), 60)
        self.assertEqual(speech_chunk_limit(None, "quality"), 180)

    def test_cancel_targets_only_matching_request(self):
        inbox = RequestInbox()
        inbox.put({"id": "old", "text": "one"})
        inbox.put({"id": "new", "text": "two"})
        inbox.put({"id": "old", "op": "cancel"})
        self.assertTrue(inbox.queue.get_nowait()[1].is_set())
        self.assertFalse(inbox.queue.get_nowait()[1].is_set())
        inbox.finish("old")
        self.assertNotIn("old", inbox.events)
        inbox.close()
        self.assertTrue(inbox.events["new"].is_set())

    def test_quality_cancellation_keeps_model(self):
        client = LocalVoiceClient(Path("."))
        client.set_mode("quality")
        client._process = Mock(stdin=io.StringIO())
        client._pending = True
        client._engine = "qwen3-tts-zero-shot"
        client._request_id = "current"
        client.cancel()
        self.assertEqual(json.loads(client._process.stdin.getvalue()), {"op": "cancel", "id": "current"})
        client._process.terminate.assert_not_called()

    def test_speak_does_not_cancel_silent_warmup(self):
        for mode in ("performance", "quality"):
            with self.subTest(mode=mode):
                client = LocalVoiceClient(Path("."))
                client.set_mode(mode)
                client._process = Mock()
                client._pending = True
                client._operation = "warmup"
                client.cancel()
                client._process.terminate.assert_not_called()
                client._process.stdin.write.assert_not_called()

    def test_mode_change_releases_resident_model(self):
        client = LocalVoiceClient(Path("."))
        client.set_mode("quality")
        process = client._process = Mock()
        process.poll.return_value = None
        client.set_mode("performance")
        process.terminate.assert_called_once()
        self.assertIsNone(client._process)

    def test_prewarm_async_and_deduplicated(self):
        client = LocalVoiceClient(Path("."))
        client.set_mode("quality")
        entered, release = threading.Event(), threading.Event()
        def warm(*args):
            entered.set()
            release.wait(3)
        with patch.object(client, "_request", side_effect=warm) as request:
            try:
                client.prewarm(Path("pack"))
                self.assertTrue(entered.wait(1))
                client.prewarm(Path("pack"))
                request.assert_called_once()
            finally:
                release.set()
                client.close()

    def test_transient_dictation_prewarm_works_in_performance_mode(self):
        client = LocalVoiceClient(Path("."))
        entered, release = threading.Event(), threading.Event()
        def warm(*args):
            entered.set()
            release.wait(3)
        with patch.object(client, "_request", side_effect=warm) as request:
            try:
                client.prewarm(Path("pack"), transient=True)
                self.assertTrue(entered.wait(1))
                request.assert_called_once()
            finally:
                release.set()
                client.close()

    def test_quality_preload_obeys_speech_toggle(self):
        engine = SpeechEngine(Path("."), enabled=False)
        engine._local_voice = Mock()
        engine.enabled = True
        engine.set_custom_voice(Path("pack"))
        engine._local_voice.prewarm.assert_not_called()
        engine.set_schedule_mode("quality")
        engine._local_voice.prewarm.assert_called_once_with(Path("pack"))
        engine._local_voice.reset_mock()
        engine.set_preload_enabled(False)
        engine._local_voice.close.assert_called_once()
        engine.set_schedule_mode("quality")
        engine._local_voice.prewarm.assert_not_called()
        engine.close()

    def test_dictation_prewarm_uses_selected_pack_without_changing_mode(self):
        engine = SpeechEngine(Path("."), enabled=False)
        engine._local_voice = Mock()
        engine.enabled = True
        engine.custom_voice_pack = Path("pack")
        engine.prepare_for_dictation()
        engine._local_voice.prewarm.assert_called_once_with(Path("pack"), transient=True)
        engine.close()

    def test_prefetch_overlaps_playback_without_reordering(self):
        engine = SpeechEngine(Path("."), enabled=False)
        second_started = threading.Event()
        played = []
        def synth(text, pack, current):
            if text == "two":
                second_started.set()
            return Path(text + ".wav") if current() else None
        def play(path, generation, _holder):
            played.append(path.name)
            if len(played) == 1:
                self.assertTrue(second_started.wait(2), "next segment must generate during playback")
        engine._local_voice.synthesize = synth
        engine._queue_wav = play
        engine._speak_prefetched(["one", "two", "three"], DEFAULT_VOICE, 0, Path("pack"), 1.0)
        self.assertEqual(played, ["one.wav", "two.wav", "three.wav"])
        engine.close()

    def test_stop_prevents_prefetched_playback(self):
        engine = SpeechEngine(Path("."), enabled=False)
        engine._local_voice.synthesize = lambda text, pack, current: Path(text) if current() else None
        engine._queue_wav = Mock(side_effect=lambda *args: engine.stop())
        engine._speak_prefetched(["one", "two", "three"], DEFAULT_VOICE, 0, Path("pack"), 1.0)
        engine._queue_wav.assert_called_once()
        engine.close()
