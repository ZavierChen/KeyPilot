import tempfile
import unittest
from pathlib import Path

from keypilot.path_shortcuts import load_path_shortcuts, set_path_shortcut


class PathShortcutTests(unittest.TestCase):
    def test_add_update_and_delete_path_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = root / "shortcuts.json"
            target = root / "report.pdf"
            target.write_text("test", encoding="utf-8")
            self.assertTrue(set_path_shortcut("学校文件", str(target), store))
            self.assertEqual(load_path_shortcuts(store)["学校文件"], str(target))
            self.assertTrue(set_path_shortcut("学校文件", "", store))
            self.assertEqual(load_path_shortcuts(store), {})

    def test_rejects_relative_or_missing_path(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "shortcuts.json"
            with self.assertRaises(ValueError):
                set_path_shortcut("测试", "relative.txt", store)


if __name__ == "__main__":
    unittest.main()
