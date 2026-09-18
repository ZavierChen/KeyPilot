import unittest
from pathlib import Path
from unittest.mock import patch

from keypilot.assistant_router import (
    LocalCommandRouter,
    SkillRegistry,
    classify_fallback_intent,
    normalize_text,
)


PROJECT_DIR = Path(__file__).resolve().parent.parent


class AssistantRouterTests(unittest.TestCase):
    def test_read_google_is_page_read_not_new_search(self):
        router = LocalCommandRouter(SkillRegistry(PROJECT_DIR / "skills"))
        for text in ("读取Google", "读一下谷歌的回答", "朗读Google AI内容"):
            self.assertEqual(router.route(text).skill_id, "read_browser_page")

    def setUp(self) -> None:
        self.registry = SkillRegistry(PROJECT_DIR / "skills")
        self.router = LocalCommandRouter(self.registry)

    def test_loads_expected_skills(self) -> None:
        self.assertTrue({"open_app", "set_volume", "set_brightness", "open_settings"} <= set(self.registry.skills))

    def test_normalizes_polite_chinese(self) -> None:
        self.assertEqual(normalize_text("请帮我打开一下计算器。"), "打开计算器")

    def test_routes_open_app(self) -> None:
        call = self.router.route("帮我打开 GPT")
        self.assertIsNotNone(call)
        self.assertEqual(call.skill_id, "open_app")
        self.assertEqual(call.arguments["app"], "gpt")

    def test_routes_desktop_file_without_location_filler(self) -> None:
        call = self.router.route("打开桌面上的毕业论文")
        self.assertEqual(call.skill_id, "open_app")
        self.assertEqual(call.arguments["app"], "毕业论文")

    def test_app_suffix_does_not_open_windows_app_settings(self) -> None:
        call = self.router.route("打开微信应用")
        self.assertEqual(call.skill_id, "open_app")
        self.assertEqual(call.arguments["app"], "微信")

    def test_routes_youtube_to_browser_instead_of_local_app(self) -> None:
        call = self.router.route("打开 YouTube")
        self.assertEqual(call.skill_id, "open_website")
        self.assertEqual(call.arguments, {"mode": "site", "target": "youtube"})

    def test_routes_explicit_url_safely(self) -> None:
        call = self.router.route("打开 docs.python.org/3/")
        self.assertEqual(call.skill_id, "open_website")
        self.assertEqual(call.arguments["mode"], "url")
        self.assertEqual(call.arguments["target"], "docs.python.org/3/")

    def test_routes_explicit_browser_search(self) -> None:
        call = self.router.route("在浏览器中搜索 Windows 快捷键")
        self.assertEqual(call.skill_id, "open_website")
        self.assertEqual(call.arguments, {"mode": "search", "target": "windows 快捷键"})

    def test_routes_current_browser_page_to_reader(self) -> None:
        call = self.router.route("总结当前网页")
        self.assertEqual(call.skill_id, "read_browser_page")
        self.assertEqual(call.arguments["question"], "总结当前网页")

    def test_unknown_explicit_web_destination_uses_search(self) -> None:
        call = self.router.route("访问 Stack Overflow")
        self.assertEqual(call.skill_id, "open_website")
        self.assertEqual(call.arguments, {"mode": "search", "target": "stack overflow"})

    def test_routes_custom_website_keyword(self) -> None:
        with patch(
            "keypilot.assistant_router.load_website_shortcuts",
            return_value={"学校网站": "https://school.example.edu/"},
        ):
            call = self.router.route("打开学校网站")
        self.assertEqual(call.skill_id, "open_website")
        self.assertEqual(
            call.arguments,
            {"mode": "url", "target": "https://school.example.edu/"},
        )

    def test_unknown_website_never_falls_through_to_local_app(self) -> None:
        call = self.router.route("打开陌生学校官网")
        self.assertEqual(call.skill_id, "open_website")
        self.assertEqual(call.arguments, {"mode": "search", "target": "陌生学校官网"})

    def test_routes_exact_volume_with_chinese_number(self) -> None:
        call = self.router.route("把音量调到百分之三十五")
        self.assertEqual(call.skill_id, "set_volume")
        self.assertEqual(call.arguments, {"operation": "set", "percent": 35})

    def test_routes_volume_step_and_mute(self) -> None:
        self.assertEqual(self.router.route("声音大一点").arguments["operation"], "up")
        self.assertEqual(self.router.route("静音").arguments["operation"], "mute")

    def test_routes_brightness(self) -> None:
        call = self.router.route("屏幕亮度调到 60%")
        self.assertEqual(call.skill_id, "set_brightness")
        self.assertEqual(call.arguments["percent"], 60)

    def test_routes_known_settings_directly(self) -> None:
        call = self.router.route("打开蓝牙设置")
        self.assertEqual(call.skill_id, "open_settings")
        self.assertEqual(call.arguments["topic"], "bluetooth")

    def test_routes_unknown_settings_to_search(self) -> None:
        call = self.router.route("在设置里找颜色管理")
        self.assertEqual(call.skill_id, "open_settings")
        self.assertEqual(call.arguments["topic"], "search")
        self.assertEqual(call.arguments["query"], "颜色管理")

    def test_unknown_request_returns_none(self) -> None:
        self.assertIsNone(self.router.route("解释一下量子纠缠"))

    def test_only_low_risk_no_confirmation_skill_auto_executes(self) -> None:
        self.assertTrue(self.registry.can_execute_without_confirmation(self.router.route("打开计算器")))
        self.assertFalse(self.registry.can_execute_without_confirmation(None))

    def test_routes_questions_to_chat_and_complex_actions_to_codex(self) -> None:
        self.assertEqual(classify_fallback_intent("为什么天空是蓝色的"), "chat")
        self.assertEqual(classify_fallback_intent("讲个笑话"), "chat")
        self.assertEqual(classify_fallback_intent("帮我写一个整理照片的脚本"), "codex")

    def test_routes_weather_without_city_to_network_location(self) -> None:
        call = self.router.route("电脑今天天气怎么样")
        self.assertEqual(call.skill_id, "get_weather")
        self.assertEqual(call.arguments, {"location": "", "day": "today"})

    def test_routes_city_weather_for_tomorrow(self) -> None:
        call = self.router.route("上海明天天气预报")
        self.assertEqual(call.skill_id, "get_weather")
        self.assertEqual(call.arguments, {"location": "上海", "day": "tomorrow"})

    def test_routes_world_time_offline(self) -> None:
        call = self.router.route("东京现在几点")
        self.assertEqual(call.skill_id, "get_world_time")
        self.assertEqual(call.arguments["location"], "东京")

    def test_routes_countdown_duration(self) -> None:
        call = self.router.route("倒计时二十分钟")
        self.assertEqual(call.skill_id, "set_timer")
        self.assertEqual(call.arguments["seconds"], 1200)

    def test_routes_alarm_and_reminder(self) -> None:
        alarm = self.router.route("明早七点叫我起床")
        self.assertEqual(alarm.skill_id, "set_alarm")
        self.assertEqual(alarm.arguments["hour"], 7)
        self.assertEqual(alarm.arguments["day_offset"], 1)
        reminder = self.router.route("周五下午三点提醒我交作业")
        self.assertEqual(reminder.skill_id, "set_reminder")
        self.assertEqual(reminder.arguments["hour"], 15)
        self.assertEqual(reminder.arguments["label"], "交作业")
        self.assertFalse(reminder.arguments["calendar"])

    def test_routes_calendar_draft(self) -> None:
        call = self.router.route("在日历添加明天下午三点开会")
        self.assertEqual(call.skill_id, "set_reminder")
        self.assertTrue(call.arguments["calendar"])
        self.assertEqual(call.arguments["label"], "开会")


if __name__ == "__main__":
    unittest.main()
