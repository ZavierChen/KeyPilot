import unittest
from unittest.mock import Mock, patch

from keypilot.browser_reader import BrowserCapture, BrowserReader, _clean_page_text, extract_google_ai_answer


class BrowserReaderTests(unittest.TestCase):
    def test_accessibility_object_markers_are_not_spoken(self):
        page = "天空\n\ufffc\n天空之所以是蓝色的，是因为空气分子对蓝光的散射比红光更强。"
        self.assertNotIn("\ufffc", extract_google_ai_answer(page, "天空"))

    def test_document_read_ignores_focused_followup_box_and_clipboard(self):
        reader = BrowserReader()
        intro = "天空之所以是蓝色的，是因为太阳光穿过地球大气层时，波长较短的蓝光被空气中的气体分子向四面八方大量散射（称为瑞利散射）。"
        page = f"AI 模式\nAI 模式对话：为什么天空是蓝色的\n为什么天空是蓝色的\n{intro}\n中国科学院\n+1\n阳光的组成\nAI 可能会出错，请注意核查 AI 回答"
        with patch.object(reader, "_browser_window", return_value=123), \
             patch.object(reader, "_read_document", return_value=page), \
             patch.object(reader, "_window_title", return_value="为什么天空是蓝色的 - Google 搜索"), \
             patch("keypilot.browser_reader._read_clipboard_text") as clipboard:
            capture = reader.capture_rendered_page(expected_title="为什么天空是蓝色的？")
        clipboard.assert_not_called()
        self.assertEqual(extract_google_ai_answer(capture.text, "为什么天空是蓝色的？"), intro)

    def test_question_punctuation_is_optional(self):
        page = "AI 模式\n为什么天空是蓝色的\n天空之所以是蓝色的，是因为空气分子对蓝光的散射比红光更强。\nAI 可能会出错"
        self.assertIn("散射", extract_google_ai_answer(page, "为什么天空是蓝色的？"))

    def test_overview_does_not_require_query_in_body(self):
        page = "Google\n全部\nAI Overview\n天空之所以是蓝色的，是因为空气分子对蓝光的散射比红光更强。\nAI responses may include mistakes"
        self.assertIn("散射", extract_google_ai_answer(page, "为什么天空是蓝色的"))

    def test_repeated_query_below_answer_does_not_hide_answer(self):
        page = "AI 模式\n天空\n天空之所以是蓝色的，是因为空气分子对蓝光的散射比红光更强。\nAI 可能会出错\n天空"
        self.assertIn("散射", extract_google_ai_answer(page, "天空"))

    def test_loading_page_is_not_an_answer(self):
        self.assertIsNone(extract_google_ai_answer("AI 模式\n天空\n正在思考\n新话题", "天空"))

    def test_short_complete_intro_does_not_wait_for_long_sections(self):
        intro = "这是一个简短但完整的简介。"
        self.assertEqual(extract_google_ai_answer("测试\n" + intro + "\n详细信息\n还在生成", "测试"), intro)

    def test_paragraph_split_across_many_accessibility_nodes(self):
        page = "测试\n这是\n一个\n完整的\n回答，它被浏览器分成了多个文本节点。\n更多资料"
        answer = extract_google_ai_answer(page, "测试")
        self.assertTrue(answer.endswith("。"))
        self.assertIn("多个文本节点", answer)

    def test_wait_retries_until_generated_answer(self):
        reader = BrowserReader()
        loading = BrowserCapture("AI 模式\n天空\n正在思考", "天空 - Google 搜索", False)
        ready = BrowserCapture("AI 模式\n天空\n天空之所以是蓝色的，是因为空气分子对蓝光的散射比红光更强。", "天空 - Google 搜索", True)
        reader.capture_rendered_page = Mock(side_effect=[loading, ready])
        with patch("keypilot.browser_reader.time.sleep"):
            self.assertIs(reader.wait_for_google_ai("天空"), ready)
        self.assertEqual(reader.capture_rendered_page.call_count, 2)

    def test_wait_reports_challenge_without_attempting_bypass(self):
        reader = BrowserReader()
        reader.capture_rendered_page = Mock(return_value=BrowserCapture("Google unusual traffic", "Google", False))
        self.assertIsNone(reader.wait_for_google_ai("天空"))
        self.assertIn("验证", reader.last_error)

    def test_extracts_ai_mode_answer_without_local_rewrite(self) -> None:
        page = """AI 模式
全部
特朗普是谁
唐纳德·特朗普是美国政治人物，现任美国总统。
这里是第二段资料。
AI 可能会出错，请注意核查 AI 回答
尽情提问"""
        self.assertEqual(
            extract_google_ai_answer(page, "特朗普是谁"),
            "唐纳德·特朗普是美国政治人物，现任美国总统。",
        )

    def test_ai_mode_answer_stops_before_numbered_long_form(self) -> None:
        intro = "这是一段足够完整的简介。" * 15
        page = f"AI 模式\n测试人物是谁\n{intro}\n1. 详细生平\n很长的正文\nAI 可能会出错"
        answer = extract_google_ai_answer(page, "测试人物是谁")
        self.assertLessEqual(len(answer), 450)
        self.assertNotIn("详细生平", answer)
    def test_extracts_ai_overview_region(self) -> None:
        padding = "导航\n" * 500
        text, has_ai = _clean_page_text(padding + "AI 概览\n这是 Gemini 生成的总结\n结论")
        self.assertTrue(has_ai)
        self.assertIn("Gemini 生成的总结", text)

    def test_online_search_skips_sensitive_questions(self) -> None:
        self.assertTrue(BrowserReader.should_search("为什么天空是蓝色的？"))
        self.assertFalse(BrowserReader.should_search("我的银行卡密码是什么？"))


if __name__ == "__main__":
    unittest.main()
