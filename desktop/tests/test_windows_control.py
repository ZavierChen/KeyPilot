import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from keypilot.assistant_router import SkillCall
from keypilot.windows_control import (
    DIRECT_MATCH_THRESHOLD,
    WindowsController,
    candidate_name_score,
)


class WindowsControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = WindowsController()
        self.controller.volume = MagicMock()

    def test_set_volume_uses_safe_com_wrapper(self) -> None:
        self.controller.volume.set_percent.return_value = 35
        result = self.controller.control_volume({"operation": "set", "percent": 35})
        self.assertTrue(result.ok)
        self.controller.volume.set_percent.assert_called_once_with(35)

    @patch("keypilot.windows_control.subprocess.Popen")
    def test_known_app_uses_allowlist(self, popen) -> None:
        result = self.controller.open_app("计算器")
        self.assertTrue(result.ok)
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["calc.exe"])

    @patch("keypilot.windows_control.copy_text_to_clipboard")
    @patch("keypilot.windows_control.subprocess.Popen")
    def test_marvis_handoff_uses_dedicated_bridge(self, popen, copy_text) -> None:
        self.controller.marvis_handoff = MagicMock()
        self.controller.marvis_handoff.enqueue.return_value = {"id": "request-1"}
        result = self.controller.send_to_marvis("帮我总结今天的新闻")
        self.assertTrue(result.ok)
        copy_text.assert_called_once_with("帮我总结今天的新闻")
        self.controller.marvis_handoff.enqueue.assert_called_once_with(
            "帮我总结今天的新闻", False
        )
        self.assertIn("keypilot.marvis_bridge", popen.call_args.args[0])

    @patch("keypilot.windows_control.subprocess.Popen")
    def test_weixin_is_found_outside_start_menu(self, popen) -> None:
        with patch.object(
            self.controller,
            "_find_discovered_executable",
            return_value=Path(r"D:\Weixin\Weixin.exe"),
        ):
            result = self.controller.open_app("微信")
        self.assertTrue(result.ok)
        self.assertEqual(popen.call_args.args[0], [r"D:\Weixin\Weixin.exe"])

    def test_desktop_shortcut_is_included_and_opened(self) -> None:
        candidate = {
            "name": "Visual Studio Code",
            "path": r"C:\Users\Test\Desktop\Visual Studio Code.lnk",
            "kind": "desktop",
        }
        with (
            patch.object(self.controller, "_load_desktop_catalog", return_value=[candidate]),
            patch.object(self.controller, "_load_app_catalog", return_value=[]),
            patch.object(self.controller, "_launch_desktop_item") as launch,
        ):
            result = self.controller.open_app("visual studio code")
        self.assertTrue(result.ok)
        self.assertEqual(result.details["source"], "桌面")
        launch.assert_called_once_with(candidate["path"])

    def test_custom_path_keyword_opens_file(self) -> None:
        target = r"C:\Users\Test\Desktop\毕业论文.pdf"
        with (
            patch("keypilot.windows_control.load_path_shortcuts", return_value={"毕业论文": target}),
            patch("keypilot.windows_control.Path.exists", return_value=True),
            patch.object(self.controller, "_launch_desktop_item") as launch,
        ):
            result = self.controller.open_app("毕业论文")
        self.assertTrue(result.ok)
        self.assertEqual(result.details["source"], "自定义路径")
        launch.assert_called_once_with(target)

    def test_character_vector_tolerates_one_wrong_character(self) -> None:
        self.assertGreater(candidate_name_score("威信", "微信"), 0.34)

    def test_direct_match_threshold_allows_only_small_variance(self) -> None:
        self.assertGreater(
            candidate_name_score("Dead by Dayligh", "Dead by Daylight"),
            DIRECT_MATCH_THRESHOLD,
        )
        self.assertLess(
            candidate_name_score("黎明杀机", "Dead by Daylight"),
            DIRECT_MATCH_THRESHOLD,
        )

    def test_desktop_catalog_scans_organized_subfolders(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            desktop = Path(folder)
            game_folder = desktop / "04 游戏"
            game_folder.mkdir()
            shortcut = game_folder / "Dead by Daylight.lnk"
            shortcut.write_bytes(b"shortcut")
            with patch.object(self.controller, "_desktop_directories", return_value=[desktop]):
                catalog = self.controller._load_desktop_catalog()
        self.assertTrue(
            any(item["name"] == "Dead by Daylight" and item["path"] == str(shortcut) for item in catalog)
        )

    def test_cs2_alias_uses_steam_uri(self) -> None:
        with patch.object(self.controller, "_launch_web_url") as launch:
            result = self.controller.open_app("CS2")
        self.assertTrue(result.ok)
        launch.assert_called_once_with("steam://rungameid/730")

    def test_youtube_uses_default_browser(self) -> None:
        with patch.object(self.controller, "_launch_web_url") as launch:
            result = self.controller.open_website("youtube", "site")
        self.assertTrue(result.ok)
        launch.assert_called_once_with("https://www.youtube.com/")

    def test_web_search_encodes_query(self) -> None:
        with patch.object(
            self.controller, "_launch_private_web_url", return_value="msedge"
        ) as launch:
            result = self.controller.open_website("微信 下载", "search")
        self.assertTrue(result.ok)
        self.assertIn("q=%E5%BE%AE%E4%BF%A1+%E4%B8%8B%E8%BD%BD", launch.call_args.args[0])
        self.assertIn("udm=50", launch.call_args.args[0])
        self.assertTrue(result.details["private"])

    def test_url_skill_rejects_non_http_protocols(self) -> None:
        with patch.object(self.controller, "_launch_web_url") as launch:
            result = self.controller.open_website("javascript:alert(1)", "url")
        self.assertFalse(result.ok)
        launch.assert_not_called()

    def test_missing_local_app_offers_web_search(self) -> None:
        with patch.object(self.controller, "_load_app_catalog", return_value=[]):
            result = self.controller.open_app("某个不存在的工具")
        self.assertFalse(result.ok)
        self.assertEqual(result.details["offer_web_search"], "某个不存在的工具")

    def test_timer_is_saved_to_persistent_store(self) -> None:
        self.controller.time_tasks = MagicMock()
        self.controller.time_tasks.add.return_value = {"id": "timer-1"}
        result = self.controller.execute(
            SkillCall("set_timer", {"seconds": 120, "label": "泡茶"}, "")
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.details["task_id"], "timer-1")
        self.controller.time_tasks.add.assert_called_once()

    @patch("keypilot.windows_control.subprocess.Popen")
    def test_known_settings_uses_uri(self, popen) -> None:
        result = self.controller.open_settings("bluetooth", "蓝牙")
        self.assertTrue(result.ok)
        self.assertIn("ms-settings:bluetooth", popen.call_args.args[0])

    def test_unknown_setting_waits_for_and_fills_search_box(self) -> None:
        with (
            patch.object(self.controller, "_launch_uri") as launch,
            patch.object(self.controller, "_fill_settings_search", return_value=True) as fill,
        ):
            result = self.controller.open_settings("search", "鼠标指针大小")
        self.assertTrue(result.ok)
        launch.assert_called_once_with("ms-settings:")
        fill.assert_called_once_with("鼠标指针大小")
        self.assertIn("鼠标指针大小", result.message)

    def test_settings_search_accepts_application_frame_host_window(self) -> None:
        self.assertTrue(
            self.controller._is_settings_frame_window(
                "ApplicationFrameWindow", "设置"
            )
        )
        self.assertFalse(
            self.controller._is_settings_frame_window("Chrome_WidgetWin_1", "设置")
        )

    def test_execute_rejects_unknown_skill(self) -> None:
        result = self.controller.execute(SkillCall("dangerous_shell", {}, ""))
        self.assertFalse(result.ok)

    @patch("keypilot.windows_control.subprocess.run", side_effect=FileNotFoundError(2, "missing"))
    def test_missing_app_catalog_shell_returns_empty_catalog(self, _run) -> None:
        self.assertEqual(self.controller._load_app_catalog(), [])

    @patch("keypilot.windows_control.subprocess.run")
    def test_app_catalog_uses_windows_bundled_powershell(self, run) -> None:
        run.return_value = MagicMock(stdout="[]")
        self.controller._load_app_catalog()
        executable = str(run.call_args.args[0][0]).lower().replace("/", "\\")
        self.assertTrue(executable.endswith("windows\\system32\\windowspowershell\\v1.0\\powershell.exe"))

    @patch("keypilot.windows_control.urllib.request.urlopen")
    def test_weather_uses_live_keyless_provider(self, urlopen) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            {
                "nearest_area": [{"areaName": [{"value": "Chicago"}]}],
                "current_condition": [
                    {
                        "weatherCode": "116",
                        "weatherDesc": [{"value": "Partly cloudy"}],
                        "temp_C": "22",
                        "FeelsLikeC": "21",
                        "humidity": "55",
                    }
                ],
                "weather": [{"mintempC": "16", "maxtempC": "24"}],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        urlopen.return_value = response
        result = self.controller.get_weather("", "today")
        self.assertTrue(result.ok)
        self.assertIn("Chicago", result.message)
        self.assertIn("根据网络位置", result.message)

    @patch("keypilot.windows_control.subprocess.Popen")
    @patch("keypilot.windows_control.copy_text_to_clipboard")
    def test_chat_handoff_copies_and_reuses_daily_chat(self, copy_text, popen) -> None:
        self.controller.handoff_state = MagicMock()
        self.controller.chat_handoff = MagicMock()
        self.controller.handoff_state.claim_chatgpt_day.return_value = False
        self.controller.chat_handoff.enqueue.return_value = {"id": "request-1"}
        result = self.controller.send_to_chat("解释一下这个错误")
        self.assertTrue(result.ok)
        self.assertFalse(result.details["new_daily_chat"])
        self.assertEqual(result.details["bridge_request_id"], "request-1")
        copy_text.assert_called_once_with("解释一下这个错误")
        self.controller.chat_handoff.enqueue.assert_called_once_with("解释一下这个错误", False)
        popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
