import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from keypilot.time_service import (
    TimeTaskStore,
    TimeTaskScheduler,
    create_calendar_draft,
    resolve_clock_due,
    world_time,
)


class TimeServiceTests(unittest.TestCase):
    def test_persistent_task_is_claimed_once(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = TimeTaskStore(Path(folder) / "tasks.json")
            due = datetime.now().astimezone() - timedelta(seconds=1)
            task = store.add("timer", due, "测试倒计时")
            claimed = store.claim_due()
            self.assertEqual(claimed[0]["id"], task["id"])
            self.assertEqual(store.claim_due(), [])

    def test_active_tasks_can_be_listed_and_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = TimeTaskStore(Path(folder) / "tasks.json")
            due = datetime.now().astimezone() + timedelta(minutes=5)
            task = store.add("alarm", due, "起床", "digital")
            self.assertEqual(store.list_active()[0]["sound"], "digital")
            self.assertTrue(store.cancel(task["id"]))
            self.assertEqual(store.list_active(), [])

    def test_past_clock_time_rolls_to_next_day(self) -> None:
        now = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)
        due = resolve_clock_due(7, 30, 0, now)
        self.assertEqual(due.day, 4)
        self.assertEqual((due.hour, due.minute), (7, 30))

    def test_world_time_converts_timezone_offline(self) -> None:
        now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
        message = world_time("东京", now)
        self.assertIn("21:00", message)

    def test_calendar_draft_contains_alarm(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            fake_task_path = Path(folder) / "tasks.json"
            with (
                patch("keypilot.time_service.default_task_path", return_value=fake_task_path),
                patch("keypilot.time_service.os.startfile") as startfile,
            ):
                path = create_calendar_draft(
                    datetime(2026, 9, 4, 15, 0),
                    "开会",
                )
            text = path.read_text(encoding="utf-8")
            self.assertIn("SUMMARY:开会", text)
            self.assertIn("BEGIN:VALARM", text)
            startfile.assert_called_once_with(path)

    def test_scheduler_poll_dispatches_claimed_task(self) -> None:
        store = unittest.mock.MagicMock()
        store.claim_due.return_value = [{"kind": "timer", "label": "完成"}]
        scheduler = TimeTaskScheduler(store)
        with patch("keypilot.time_service.threading.Thread") as thread:
            scheduler.poll()
        thread.assert_called_once()
        thread.return_value.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
