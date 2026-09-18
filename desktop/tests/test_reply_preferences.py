"""In-process Tk integration test; never controls the user's running assistant."""
import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from keypilot.assistant_app import AssistantApp


class PreferencesTests(unittest.TestCase):
    def test_length_choices_save_and_layout_fits(self):
        root = tk.Tk()
        root.withdraw()
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(AssistantApp, "_create_dictation_event"), \
             patch.object(AssistantApp, "_load_settings", return_value={}):
            app = AssistantApp(root, Path(__file__).resolve().parent.parent, smoke_test=True)
            app.settings_path = Path(temp) / "settings.json"
            try:
                app.open_preferences()
                window = app.preferences_window
                window.withdraw()
                root.update_idletasks()
                for level in ("低", "中", "高"):
                    app.reply_length_var.set(level)
                    app._on_reply_length_selected()
                    self.assertEqual(json.loads(app.settings_path.read_text(encoding="utf-8"))["reply_length"], level)
                    self.assertEqual(app.cloud.reply_length, level)
                    self.assertEqual(app.ollama.reply_length, level)
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                choices = [w for w in descendants(window) if w.winfo_class() == "TCombobox"
                           and tuple(w.cget("values")) == ("低", "中", "高")]
                self.assertEqual(len(choices), 1)
                app.speech_rate_var.set(.94)
                app._on_speech_rate_changed()
                self.assertEqual(app.speech.rate, .94)
                self.assertEqual(json.loads(app.settings_path.read_text(encoding="utf-8"))["speech_rate"], .94)
                app._reset_speech_rate()
                self.assertEqual(app.speech.rate, 1.0)
                scales = [w for w in descendants(window) if w.winfo_class() == "Scale"
                          and float(w.cget("from")) == .9]
                self.assertEqual(len(scales), 1)
                self.assertEqual(float(scales[0].cget("to")), 1.1)
                for widget in descendants(window):
                    if widget.winfo_class() in ("Button", "Scale", "TCombobox"):
                        bottom = widget.winfo_rooty() - window.winfo_rooty() + widget.winfo_height()
                        self.assertLessEqual(bottom, 800)
                bottom = choices[0].winfo_rooty() - window.winfo_rooty() + choices[0].winfo_reqheight()
                self.assertLess(bottom, 750)
            finally:
                app.close()
