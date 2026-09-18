import tempfile
import unittest
from pathlib import Path

from keypilot.conversation_memory import ConversationMemory


class ConversationMemoryTests(unittest.TestCase):
    def test_memory_is_bounded_and_can_be_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            memory = ConversationMemory(
                Path(folder) / "memory.json",
                max_turns=2,
                max_chars=120,
                max_chars_per_message=30,
            )
            memory.add("第一问" * 20, "第一答" * 20)
            memory.add("第二问", "第二答")
            memory.add("第三问", "第三答")
            context = memory.context()
            self.assertNotIn("第一问", context)
            self.assertIn("第三问", context)
            self.assertLessEqual(len(context), 120)
            memory.clear()
            self.assertEqual(memory.context(), "")


if __name__ == "__main__":
    unittest.main()
