import tempfile
import unittest
from pathlib import Path

from keypilot.chat_handoff import ChatHandoffStore


class ChatHandoffStoreTests(unittest.TestCase):
    def test_request_can_be_retried_and_marked_sent(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = ChatHandoffStore(Path(folder) / "handoff.json")
            item = store.enqueue("测试问题", True)
            self.assertEqual(store.get(item["id"])["status"], "pending")
            store.update_status(item["id"], "sent")
            self.assertEqual(store.get(item["id"])["status"], "sent")


if __name__ == "__main__":
    unittest.main()
