import tempfile
import unittest
from pathlib import Path

from keypilot.handoff import DailyHandoffState


class DailyHandoffStateTests(unittest.TestCase):
    def test_chatgpt_only_claims_one_new_chat_per_day(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = DailyHandoffState(Path(directory) / "state.json")
            self.assertTrue(state.claim_chatgpt_day("2026-09-03"))
            self.assertFalse(state.claim_chatgpt_day("2026-09-03"))
            self.assertTrue(state.claim_chatgpt_day("2026-09-04"))

    def test_codex_thread_is_scoped_to_day(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = DailyHandoffState(Path(directory) / "state.json")
            state.save_codex_thread("thread-one", "2026-09-03")
            self.assertEqual(state.codex_thread("2026-09-03"), "thread-one")
            self.assertIsNone(state.codex_thread("2026-09-04"))


if __name__ == "__main__":
    unittest.main()
