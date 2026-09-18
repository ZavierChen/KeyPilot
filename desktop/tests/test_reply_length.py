import unittest
import re
from pathlib import Path
from unittest.mock import Mock

from keypilot.reply_length import (
    limit_reply,
    progressive_speech_chunks,
    speech_chunks,
    split_mixed_language_chunks,
    progressive_mixed_speech_chunks,
)
from keypilot.browser_reader import BrowserCapture, BrowserReader, extract_google_ai_answer
from keypilot.speech import SpeechEngine, DEFAULT_VOICE


class ReplyLengthTests(unittest.TestCase):
    def test_progressive_opening_uses_first_complete_sentence(self):
        first = "我先把结论告诉你。"
        text = first + "后续解释保持同一个音色，并且一边播放一边准备下一段。" * 10
        parts = progressive_speech_chunks(text)
        self.assertEqual(parts[0], first)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(len(p) <= 60 for p in parts))

    def test_progressive_chunks_bound_opening_without_punctuation(self):
        text = "长" * 603
        parts = progressive_speech_chunks(text)
        self.assertEqual(len(parts[0]), 24)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(0 < len(p) <= 60 for p in parts))

    def test_progressive_opening_extends_to_nearby_pause_instead_of_hard_cut(self):
        text = "这是一个需要完整表达并且不应该从词组中间突然切开的开头，后面才是下一段。"
        parts = progressive_speech_chunks(text)
        self.assertTrue(parts[0].endswith("，"))
        self.assertGreater(len(parts[0]), 24)
        self.assertEqual("".join(parts), text)

    def test_long_english_prefers_word_boundary_when_no_punctuation_is_nearby(self):
        text = "natural speech should never split through the middle of an English word even during streaming"
        parts = progressive_speech_chunks(text)
        self.assertTrue(parts[0].endswith(" "))
        self.assertEqual("".join(parts), text)

    def test_mixed_language_switches_split_at_complete_sentences(self):
        original = "中文先稳定开场。How has your day been? 接着回到中文说明。Is there anything I can help you with?"
        parts = split_mixed_language_chunks([original])
        self.assertEqual("".join(parts), original)
        self.assertEqual(parts, [
            "中文先稳定开场。",
            "How has your day been? ",
            "接着回到中文说明。",
            "Is there anything I can help you with?",
        ])

    def test_progressive_mixed_chunks_never_mix_language_runs(self):
        original = (
            "先用中文完整开场，再说明下面会切换英文。"
            "Hello, I'm Rannie, and this sentence should stay together. How has your day been? "
            "现在切回中文，并且继续保持完整自然的停顿。"
        )
        parts = progressive_mixed_speech_chunks(original, first_limit=32, limit=72)
        self.assertEqual("".join(parts), original)
        self.assertTrue(all(not (
            re.search(r"[\u3400-\u9fff]", part) and re.search(r"[A-Za-z]", part)
        ) for part in parts))
        self.assertIn("How has your day been? ", parts)

    def test_progressive_empty_short_and_whitespace_preserved(self):
        for text in ("", "你好。", "好。接下来给你详细说明。\n\n" * 12, "甲，" + "乙" * 90):
            parts = progressive_speech_chunks(text)
            self.assertEqual("".join(parts), text)
            self.assertTrue(all(parts))
            if parts:
                self.assertLessEqual(len(parts[0]), 24)

    def test_high_preserves_entire_poem(self):
        poem = "床前明月光，疑是地上霜。\n举头望明月，低头思故乡。"
        page = "AI 模式\n背静夜思\n" + poem + "\nAI 可能会出错\n导航"
        self.assertEqual(extract_google_ai_answer(page, "背静夜思", detail="高"), poem)
        self.assertEqual(limit_reply(poem, "高"), poem)
        self.assertNotIn("举头", extract_google_ai_answer(page, "背静夜思", detail="低"))

    def test_high_waits_past_first_sentence(self):
        reader = BrowserReader()
        first = BrowserCapture("诗\n床前明月光，疑是地上霜。", "诗", False)
        full = BrowserCapture(first.text + "\n举头望明月，低头思故乡。\nAI 可能会出错", "诗", True)
        reader.capture_rendered_page = Mock(side_effect=[first, full])
        from unittest.mock import patch
        with patch("keypilot.browser_reader.time.sleep"):
            self.assertIs(reader.wait_for_google_ai("诗", detail="高"), full)

    def test_lengths_are_distinct_and_bounded(self):
        text = "这一句内容完整。" * 1000
        lengths = [len(limit_reply(text, level)) for level in ("低", "中", "高")]
        self.assertLess(lengths[0], lengths[1])
        self.assertLess(lengths[1], lengths[2])
        self.assertLessEqual(lengths[2], 6002)

    def test_chunks_preserve_long_text_and_keep_each_request_small(self):
        text = ("第一句诗。\n第二句诗！" * 100) + "尾声"
        chunks = speech_chunks(text)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(c) <= 180 for c in chunks))
        self.assertEqual("".join(speech_chunks("长" * 1300)), "长" * 1300)

    def test_all_chunks_play_and_callback_only_once(self):
        engine = SpeechEngine(Path("."), enabled=False)
        engine.enabled = True
        callback = Mock()
        engine._speak_part = Mock()
        text = "完整诗句。" * 160
        engine.speak(text, callback)
        engine._queue.put(None)
        engine._worker_loop()
        self.assertEqual("".join(c.args[0] for c in engine._speak_part.call_args_list), text)
        callback.assert_called_once_with()

    def test_cancel_between_chunks_stops_rest_and_callback(self):
        engine = SpeechEngine(Path("."), enabled=False)
        callback = Mock()
        def cancel(*_args):
            engine._generation += 1
        engine._speak_part = Mock(side_effect=cancel)
        engine._queue.put(("长篇内容。" * 100, DEFAULT_VOICE, 0, callback, None))
        engine._queue.put(None)
        engine._worker_loop()
        engine._speak_part.assert_called_once()
        callback.assert_not_called()
