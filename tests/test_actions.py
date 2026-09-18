import unittest
from pathlib import Path
from unittest.mock import patch

from keypilot import actions


class AppHotkeyTests(unittest.TestCase):
    def test_running_app_sends_hotkey_immediately(self) -> None:
        with (
            patch.object(actions, "_process_ids", return_value={123}),
            patch.object(actions, "send_hotkey") as send_hotkey,
            patch.object(actions, "_open_packaged_app") as open_app,
        ):
            actions._ensure_app_then_hotkey(
                "ChatGPT.exe",
                "example!App",
                ["ctrl", "f12"],
                12,
                3,
                False,
            )
        open_app.assert_not_called()
        send_hotkey.assert_called_once_with(["ctrl", "f12"])

    def test_cold_start_waits_for_window_then_settles(self) -> None:
        with (
            patch.object(actions, "_process_ids", side_effect=[set(), {123}]),
            patch.object(actions, "_top_level_windows", return_value=[456]),
            patch.object(actions, "_open_packaged_app") as open_app,
            patch.object(actions.time, "sleep") as sleep,
            patch.object(actions, "send_hotkey") as send_hotkey,
        ):
            actions._ensure_app_then_hotkey(
                "ChatGPT.exe",
                "example!App",
                ["ctrl", "f12"],
                12,
                3,
                False,
            )
        open_app.assert_called_once_with("example!App")
        sleep.assert_called_once_with(3)
        send_hotkey.assert_called_once_with(["ctrl", "f12"])

    def test_duplicate_launch_is_ignored(self) -> None:
        actions._app_hotkey_lock.acquire()
        try:
            with patch.object(actions, "send_hotkey") as send_hotkey:
                actions._ensure_app_then_hotkey(
                    "ChatGPT.exe",
                    "example!App",
                    ["ctrl", "f12"],
                    12,
                    3,
                    False,
                )
            send_hotkey.assert_not_called()
        finally:
            actions._app_hotkey_lock.release()

    def test_local_app_is_launched_when_window_is_missing(self) -> None:
        with (
            patch.object(actions, "_windows_by_title_prefix", return_value=[]),
            patch.object(actions.subprocess, "Popen") as popen,
        ):
            result = actions.show_local_app(
                "KeyPilot 本地助手",
                "pythonw.exe",
                ["-m", "keypilot.assistant_app"],
                ".",
            )
        self.assertEqual(result, "launched")
        popen.assert_called_once()

    def test_portal_default_is_local_assistant(self) -> None:
        project_dir = Path(__file__).resolve().parent.parent
        action = actions.load_portal_default(project_dir / "portal.json")
        self.assertEqual(action["type"], "show_local_app")
        self.assertIn("keypilot.assistant_app", action["args"])

    def test_running_dictation_app_receives_toggle_signal(self) -> None:
        with (
            patch.object(actions, "_windows_by_title_prefix", return_value=[456]),
            patch.object(actions, "signal_named_event", return_value=True) as signal,
            patch.object(actions.subprocess, "Popen") as popen,
            patch.object(actions.ctypes.windll.user32, "ShowWindow"),
            patch.object(actions.ctypes.windll.user32, "SetForegroundWindow"),
        ):
            result = actions.toggle_dictation_app(
                "KeyPilot 本地助手",
                "Local\\KeyPilot.ToggleDictation",
                "pythonw.exe",
                ["-m", "keypilot.assistant_app", "--dictation"],
                ".",
            )
        self.assertEqual(result, "signaled")
        signal.assert_called_once()
        popen.assert_not_called()

    def test_starting_dictation_app_is_not_launched_twice(self) -> None:
        with (
            patch.object(actions, "_windows_by_title_prefix", return_value=[456]),
            patch.object(actions, "signal_named_event", return_value=False) as signal,
            patch.object(actions.subprocess, "Popen") as popen,
            patch.object(actions.time, "sleep"),
            patch.object(actions.ctypes.windll.user32, "ShowWindow"),
            patch.object(actions.ctypes.windll.user32, "SetForegroundWindow"),
        ):
            result = actions.toggle_dictation_app(
                "KeyPilot 本地助手",
                "Local\\KeyPilot.ToggleDictation",
                "pythonw.exe",
                ["-m", "keypilot.assistant_app", "--dictation"],
                ".",
            )
        self.assertEqual(result, "shown")
        self.assertEqual(signal.call_count, 5)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
