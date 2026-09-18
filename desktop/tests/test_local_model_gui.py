"""Exercise the actual portal widgets without a model or desktop actions."""
import json
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from keypilot.assistant_app import AssistantApp
from keypilot.assistant_router import SkillCall
from keypilot.browser_reader import BrowserCapture
from keypilot.ollama_bridge import OllamaAnswer


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class LocalModelPortalGuiTests(unittest.TestCase):
    def test_portal_saves_arbitrary_model_and_previews_contract(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.dict(os.environ, {"KEYPILOT_DATA_DIR": temp}), \
             patch.object(AssistantApp, "_create_dictation_event"):
            root = tk.Tk()
            root.withdraw()
            app = AssistantApp(root, Path(__file__).resolve().parent.parent, smoke_test=True)
            try:
                app.open_local_model_portal()
                window = app.local_model_window
                window.withdraw()
                widgets = list(descendants(window))
                combos = [widget for widget in widgets if widget.winfo_class() == "TCombobox"]
                combos[0].set("openai-compatible")
                combos[1].set("professor-custom-model")
                combos[2].set("prompt")
                entries = [widget for widget in widgets if widget.winfo_class() == "TEntry"]
                entries[0].delete(0, "end")
                entries[0].insert(0, "http://127.0.0.1:1234/v1")
                buttons = {widget.cget("text"): widget for widget in widgets if widget.winfo_class() == "TButton"}
                buttons["保存并启用"].invoke()
                stored = json.loads(app.settings_path.read_text(encoding="utf-8"))
                self.assertEqual(stored["local_model"]["model"], "professor-custom-model")
                self.assertEqual(stored["local_model"]["protocol"], "openai-compatible")
                self.assertEqual(app.ollama.config.json_mode, "prompt")
                buttons["预览契约"].invoke()
                text_widget = next(widget for widget in widgets if widget.winfo_class() == "Text")
                contract = json.loads(text_widget.get("1.0", "end"))
                self.assertIn("set_volume", {item["id"] for item in contract["skills"]})
                self.assertNotIn("codex_fallback", {item["id"] for item in contract["skills"]})
            finally:
                app.close()

    def test_model_routed_browser_skill_reaches_app_reader(self):
        app = AssistantApp.__new__(AssistantApp)
        app.router = Mock()
        app.router.route.return_value = None
        app.ollama = Mock()
        app.ollama.route.return_value = SkillCall("read_browser_page", {"question": "主要内容"}, "")
        app.ollama.answer_with_context.return_value = OllamaAnswer("页面摘要")
        app.browser_reader = Mock()
        app.browser_reader.capture_rendered_page.return_value = BrowserCapture("页面内容", "测试页面", False)
        app.controller = Mock()
        app.window_handle = 1
        app.memory = Mock()
        app.memory.context.return_value = ""
        app._finish = Mock()
        app.root = Mock()
        app.root.after.side_effect = lambda _delay, callback: callback()
        with patch("keypilot.assistant_app.classify_fallback_intent", return_value="action"):
            app._process("读一下正在看的网页", True, 0, False, "", "", "")
        app.ollama.route.assert_called_once()
        app.ollama.answer_with_context.assert_called_once()
        app.controller.execute.assert_not_called()
        self.assertEqual(app._finish.call_args.args[1].message, "页面摘要")


if __name__ == "__main__":
    unittest.main()
