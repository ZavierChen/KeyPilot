import tempfile
import unittest
from pathlib import Path

from keypilot.website_shortcuts import (
    load_website_shortcuts,
    normalize_safe_url,
    set_website_shortcut,
)


class WebsiteShortcutTests(unittest.TestCase):
    def test_add_update_and_delete_persistent_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shortcuts.json"
            self.assertTrue(set_website_shortcut("学校网站", "school.example.edu", path))
            self.assertEqual(
                load_website_shortcuts(path)["学校网站"],
                "https://school.example.edu",
            )
            self.assertTrue(set_website_shortcut("学校网站", "", path))
            self.assertEqual(load_website_shortcuts(path), {})

    def test_only_http_and_https_are_allowed(self) -> None:
        self.assertEqual(normalize_safe_url("example.com"), "https://example.com")
        self.assertIsNone(normalize_safe_url("javascript:alert(1)"))
        self.assertIsNone(normalize_safe_url("file:///C:/secret.txt"))


if __name__ == "__main__":
    unittest.main()
