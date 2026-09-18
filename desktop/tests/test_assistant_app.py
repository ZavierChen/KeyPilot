import unittest
from unittest.mock import Mock

from keypilot.assistant_app import (
    AssistantApp,
    CLOUD_MODEL_PRESETS,
    COMPLEX_AGENT_CHOICES,
)
from keypilot.browser_reader import BrowserCapture
from keypilot.cloud_bridge import CloudAnswer
from keypilot.ollama_bridge import OllamaAnswer


class AssistantAppDecisionTests(unittest.TestCase):
    def test_level_two_read_page_never_uses_qwen(self):
        app = AssistantApp.__new__(AssistantApp)
        app.router = Mock()
        app.router.route.return_value.skill_id = "read_browser_page"
        app.browser_reader = Mock()
        intro = "天空之所以是蓝色的，是因为空气分子对蓝光的散射比红光更强。"
        app.browser_reader.capture_rendered_page.return_value = BrowserCapture(
            "AI 模式\n天空为什么是蓝色的\n" + intro, "天空为什么是蓝色的 - Google 搜索", True)
        app.window_handle = 1
        app.ollama = Mock()
        app._finish = Mock()
        app.root = Mock()
        app.root.after.side_effect = lambda _delay, callback: callback()
        app._process("读取Google", False, 2, False, "", "", "")
        app.ollama.answer_with_context.assert_not_called()
        app.ollama.answer.assert_not_called()
        self.assertEqual(app._finish.call_args.args[1].message, intro)
        self.assertEqual(app._finish.call_args.args[2], "Google AI 页面原文")
    def test_cloud_model_submenu_has_deepseek_presets(self) -> None:
        self.assertIn("deepseek-v4-flash", CLOUD_MODEL_PRESETS)
        self.assertIn("deepseek-v4-pro", CLOUD_MODEL_PRESETS)

    def test_complex_agent_menu_offers_codex_and_marvis(self) -> None:
        self.assertIn("Codex", COMPLEX_AGENT_CHOICES)
        self.assertIn("Marvis", COMPLEX_AGENT_CHOICES)

    def test_web_mode_migrates_to_ai_first_and_preserves_disabled(self) -> None:
        self.assertEqual(AssistantApp._web_mode_from_settings({"web_answer": True}), 2)
        self.assertEqual(AssistantApp._web_mode_from_settings({"web_answer": False}), 0)
        self.assertEqual(AssistantApp._web_mode_from_settings({"web_mode": 1}), 1)
        self.assertEqual(AssistantApp._web_mode_from_settings({"web_mode": 3}), 3)
        self.assertEqual(AssistantApp._web_mode_from_settings({"web_mode": 4}), 4)
        self.assertEqual(AssistantApp._web_mode_from_settings({"web_mode": 99}), 4)

    def test_accepts_natural_cloud_permission_answers(self) -> None:
        self.assertTrue(AssistantApp._permission_decision("要，用 GPT"))
        self.assertTrue(AssistantApp._permission_decision("可以"))
        self.assertTrue(AssistantApp._permission_decision("需要 GPT"))
        self.assertFalse(AssistantApp._permission_decision("不要，千问回答"))
        self.assertFalse(AssistantApp._permission_decision("不用了"))

    def test_unrelated_reply_keeps_waiting(self) -> None:
        self.assertIsNone(AssistantApp._permission_decision("我再想想"))

    def test_search_result_directly_selects_longest_installed_title(self) -> None:
        selected = AssistantApp._candidate_mentioned_in_search(
            "《黎明杀机》的英文名称为 Dead by Daylight，可通过 Steam 游玩。",
            ["Steam", "Dead by Daylight", "Daylight"],
        )
        self.assertEqual(selected, "Dead by Daylight")

    def test_app_identity_search_closes_temporary_browser_tab(self) -> None:
        app = AssistantApp.__new__(AssistantApp)
        app.window_handle = 123
        app.controller = Mock()
        app.browser_reader = Mock()
        app.browser_reader.online_available.return_value = True
        app.browser_reader.capture_rendered_page.return_value = BrowserCapture(
            "search text " * 20, "Google", False
        )
        text, _source = app._search_app_identity("黎明杀机")
        self.assertTrue(text)
        app.browser_reader.capture_rendered_page.assert_called_once_with(
            settle_seconds=4.0,
            restore_hwnd=123,
            close_after_capture=True,
            expected_title="黎明杀机",
        )

    def test_forced_ai_search_accepts_bare_knowledge_topic(self) -> None:
        app = AssistantApp.__new__(AssistantApp)
        app.window_handle = 123
        app.controller = Mock()
        app.memory = Mock()
        app.memory.context.return_value = ""
        app.root = Mock()
        app.ollama = Mock()
        app.browser_reader = Mock()
        app.browser_reader.should_search.return_value = False
        app.browser_reader.online_available.return_value = True
        app.browser_reader.wait_for_google_ai.return_value = BrowserCapture(
            "AI 模式\n东北鱼姐\n这是 Google AI 返回的联网资料答案。\nAI 可能会出错",
            "Google",
            True,
        )
        answer, source = app._search_and_answer(
            "东北鱼姐", force=True, direct_ai_text=True
        )
        self.assertEqual(answer.text, "这是 Google AI 返回的联网资料答案。")
        self.assertIn("Google", source)
        app.ollama.answer_with_context.assert_not_called()
        app.controller.open_website.assert_called_once_with("东北鱼姐", "search")

    def test_level_two_voice_uses_qwen_only_for_routing(self) -> None:
        app = AssistantApp.__new__(AssistantApp)
        app.ollama = Mock()
        app.root = Mock()
        app.root.after.side_effect = lambda _delay, callback: callback()
        app._finish_ollama_dictation_route = Mock()

        app._route_dictation_with_ollama("特朗普是谁", 2)

        app.ollama.route.assert_called_once_with("特朗普是谁")
        app.ollama.answer.assert_not_called()
        app._finish_ollama_dictation_route.assert_called_once_with(
            "特朗普是谁", app.ollama.route.return_value, None, 2
        )

    def test_level_three_knowledge_question_hands_off_to_marvis(self) -> None:
        app = AssistantApp.__new__(AssistantApp)
        app.router = Mock()
        app.router.route.return_value = None
        app.controller = Mock()
        app.controller.send_to_marvis.return_value.ok = True
        app.controller.send_to_marvis.return_value.message = "已交给 Marvis。"
        app.controller.send_to_marvis.return_value.details = {}
        app.root = Mock()
        app.root.after.side_effect = lambda _delay, callback: callback()
        app._finish = Mock()

        app._process(
            "特朗普是谁",
            True,
            3,
            True,
            "https://api.example.com/v1",
            "example-model",
            "secret",
        )

        app.controller.send_to_marvis.assert_called_once_with("特朗普是谁")
        result = app._finish.call_args.args[1]
        source = app._finish.call_args.args[2]
        self.assertTrue(result.ok)
        self.assertEqual(source, "Marvis 转接器")

    def test_level_four_knowledge_question_uses_cloud_api(self) -> None:
        app = AssistantApp.__new__(AssistantApp)
        app.router = Mock()
        app.router.route.return_value = None
        app.cloud = Mock()
        app.cloud.answer.return_value = CloudAnswer("这是云端回答。")
        app.memory = Mock()
        app.memory.context.return_value = ""
        app.root = Mock()
        app.root.after.side_effect = lambda _delay, callback: callback()
        app._finish = Mock()

        app._process(
            "特朗普是谁",
            True,
            4,
            True,
            "https://api.example.com/v1",
            "example-model",
            "secret",
        )

        app.cloud.answer.assert_called_once()
        result = app._finish.call_args.args[1]
        source = app._finish.call_args.args[2]
        self.assertTrue(result.ok)
        self.assertEqual(result.message, "这是云端回答。")
        self.assertEqual(source, "云端 API · example-model")

    def test_complex_operation_uses_selected_marvis_agent(self) -> None:
        app = AssistantApp.__new__(AssistantApp)
        app.router = Mock()
        app.router.route.return_value = None
        app.controller = Mock()
        app.controller.send_to_marvis.return_value.ok = True
        app.controller.send_to_marvis.return_value.message = "已交给 Marvis。"
        app.controller.send_to_marvis.return_value.details = {}
        app.root = Mock()
        app.root.after.side_effect = lambda _delay, callback: callback()
        app._finish = Mock()

        app._process(
            "帮我写一个整理照片的脚本",
            False,
            2,
            True,
            "",
            "",
            "",
            complex_agent="Marvis",
        )

        app.controller.send_to_marvis.assert_called_once_with(
            "帮我写一个整理照片的脚本"
        )
        self.assertEqual(app._finish.call_args.args[2], "Marvis 复杂操作代理")


if __name__ == "__main__":
    unittest.main()
