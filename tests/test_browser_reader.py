import unittest

from keypilot.browser_reader import BrowserReader, _clean_page_text, extract_google_ai_answer


class BrowserReaderTests(unittest.TestCase):
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
            "唐纳德·特朗普是美国政治人物，现任美国总统。\n这里是第二段资料。",
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
