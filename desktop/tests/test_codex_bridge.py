import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keypilot.codex_bridge import CodexBridge
from keypilot.handoff import DailyHandoffState


def event_output(payload: dict, *, thread_id: str | None = None) -> str:
    events = []
    if thread_id:
        events.append({"type": "thread.started", "thread_id": thread_id})
    events.append(
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": json.dumps(payload, ensure_ascii=False),
            },
        }
    )
    return "\n".join(json.dumps(event, ensure_ascii=False) for event in events)


class CodexBridgeTests(unittest.TestCase):
    @patch("keypilot.codex_bridge.copy_text_to_clipboard")
    @patch("keypilot.codex_bridge.subprocess.run")
    def test_creates_one_read_only_daily_session_then_resumes(self, run, copy_text) -> None:
        payload = {"action": "settings_search", "response": "打开相关设置", "query": "鼠标指针大小"}
        run.return_value.returncode = 0
        run.return_value.stdout = event_output(
            payload,
            thread_id="01a06602-8577-7e50-b2b0-d45c85ec5489",
        )
        run.return_value.stderr = ""
        with tempfile.TemporaryDirectory() as directory:
            state = DailyHandoffState(Path(directory) / "state.json")
            bridge = CodexBridge(Path("."), state=state)
            result = bridge.ask("把鼠标指针调大")
            self.assertEqual(result.query, "鼠标指针大小")
            first_command = run.call_args.args[0]
            self.assertIn("read-only", first_command)
            self.assertNotIn("--ephemeral", first_command)
            copy_text.assert_called_with("把鼠标指针调大")

            run.return_value.stdout = event_output(payload)
            bridge.ask("还是再大一点")
            second_command = run.call_args.args[0]
            self.assertIn("resume", second_command)
            self.assertIn("01a06602-8577-7e50-b2b0-d45c85ec5489", second_command)


if __name__ == "__main__":
    unittest.main()
