from __future__ import annotations

import base64
import ctypes
import json
import os
import subprocess
import threading
import time
import uuid
import winsound
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


TIME_ZONES = {
    "本地": None,
    "北京": "Asia/Shanghai",
    "上海": "Asia/Shanghai",
    "中国": "Asia/Shanghai",
    "香港": "Asia/Hong_Kong",
    "台北": "Asia/Taipei",
    "东京": "Asia/Tokyo",
    "日本": "Asia/Tokyo",
    "首尔": "Asia/Seoul",
    "新加坡": "Asia/Singapore",
    "迪拜": "Asia/Dubai",
    "伦敦": "Europe/London",
    "巴黎": "Europe/Paris",
    "柏林": "Europe/Berlin",
    "纽约": "America/New_York",
    "芝加哥": "America/Chicago",
    "洛杉矶": "America/Los_Angeles",
    "旧金山": "America/Los_Angeles",
    "温哥华": "America/Vancouver",
    "多伦多": "America/Toronto",
    "悉尼": "Australia/Sydney",
    "墨尔本": "Australia/Melbourne",
    "utc": "UTC",
}
WEEKDAYS = "一二三四五六日"
ALARM_PATTERNS = {
    "morning": ((659, 180), (784, 180), (988, 220), (784, 160), (988, 320)),
    "digital": ((1046, 130), (1046, 130), (1318, 180), (1046, 130), (1568, 260)),
    "gentle": ((523, 260), (659, 260), (784, 360), (659, 240)),
}


def default_task_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "KeyPilot" / "time-tasks.json"


@contextmanager
def _task_lock() -> Iterator[None]:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, r"Local\KeyPilot.TimeTasks")
    if not handle:
        raise ctypes.WinError()
    try:
        if kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0xFFFFFFFF) != 0:
            raise ctypes.WinError()
        yield
    finally:
        kernel32.ReleaseMutex(ctypes.c_void_p(handle))
        kernel32.CloseHandle(ctypes.c_void_p(handle))


class TimeTaskStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_task_path()

    def _read(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    def _write(self, tasks: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def add(
        self,
        kind: str,
        due: datetime,
        label: str,
        sound: str = "morning",
    ) -> dict[str, Any]:
        task = {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "due_at": due.timestamp(),
            "label": label.strip() or "时间到了",
            "created_at": time.time(),
            "fired": False,
            "sound": sound if sound in ALARM_PATTERNS else "morning",
        }
        with _task_lock():
            tasks = self._read()
            tasks.append(task)
            self._write(tasks)
        return task

    def list_active(self) -> list[dict[str, Any]]:
        with _task_lock():
            tasks = [
                task
                for task in self._read()
                if isinstance(task, dict) and not task.get("fired")
            ]
        return sorted(tasks, key=lambda task: float(task.get("due_at", 0)))

    def cancel(self, task_id: str) -> bool:
        with _task_lock():
            tasks = self._read()
            kept = [task for task in tasks if str(task.get("id", "")) != task_id]
            if len(kept) == len(tasks):
                return False
            self._write(kept)
        return True

    def claim_due(self, now: float | None = None) -> list[dict[str, Any]]:
        current = time.time() if now is None else now
        with _task_lock():
            tasks = self._read()
            due: list[dict[str, Any]] = []
            kept: list[dict[str, Any]] = []
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                due_at = float(task.get("due_at", 0))
                if not task.get("fired") and due_at <= current:
                    task["fired"] = True
                    due.append(task)
                if not task.get("fired") or due_at >= current - 7 * 86400:
                    kept.append(task)
            if due or len(kept) != len(tasks):
                self._write(kept)
            return due


def resolve_clock_due(
    hour: int,
    minute: int,
    day_offset: int,
    now: datetime | None = None,
) -> datetime:
    current = now or datetime.now().astimezone()
    due = current.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=day_offset)
    if day_offset == 0 and due <= current:
        due += timedelta(days=1)
    return due


def format_due(due: datetime, now: datetime | None = None) -> str:
    current = now or datetime.now().astimezone()
    day = "今天" if due.date() == current.date() else due.strftime("%m月%d日")
    return f"{day}{due.hour:02d}:{due.minute:02d}"


def world_time(location: str, now: datetime | None = None) -> str | None:
    requested = location.strip().lower() or "本地"
    display = location.strip() or "本地"
    found = False
    zone_name: str | None = None
    for alias, candidate in TIME_ZONES.items():
        if alias in requested or requested in alias:
            display = alias.upper() if alias == "utc" else alias
            zone_name = candidate
            found = True
            break
    if not found:
        return None
    try:
        current = now or (datetime.now().astimezone() if zone_name is None else datetime.now(ZoneInfo(zone_name)))
        if now is not None and zone_name is not None:
            current = now.astimezone(ZoneInfo(zone_name))
    except ZoneInfoNotFoundError:
        return None
    return (
        f"{display}现在是{current.month}月{current.day}日星期{WEEKDAYS[current.weekday()]}，"
        f"{current.hour:02d}:{current.minute:02d}。"
    )


def create_calendar_draft(due: datetime, label: str) -> Path:
    folder = default_task_path().parent / "CalendarDrafts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"KeyPilot-{uuid.uuid4().hex[:10]}.ics"
    end = due + timedelta(minutes=30)
    escaped = label.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//KeyPilot//Time Assistant//ZH-CN",
        "BEGIN:VEVENT",
        f"UID:{uuid.uuid4().hex}@keypilot.local",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{due.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
        f"SUMMARY:{escaped}",
        "BEGIN:VALARM",
        "TRIGGER:-PT5M",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{escaped}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
    path.write_text("\r\n".join(lines), encoding="utf-8")
    os.startfile(path)
    return path


def _speak(message: str) -> None:
    executable = (
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not executable.exists():
        return
    safe = message.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.Speak('{safe}')"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    subprocess.Popen(
        [str(executable), "-NoProfile", "-EncodedCommand", encoded],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _alarm_sound_loop(stop_event: threading.Event, sound: str) -> None:
    pattern = ALARM_PATTERNS.get(sound, ALARM_PATTERNS["morning"])
    while not stop_event.is_set():
        for frequency, duration in pattern:
            if stop_event.is_set():
                return
            try:
                winsound.Beep(frequency, duration)
            except RuntimeError:
                winsound.MessageBeep()
            if stop_event.wait(0.07):
                return
        if stop_event.wait(0.65):
            return


def notify_task(task: dict[str, Any]) -> None:
    kind = str(task.get("kind", "reminder"))
    label = str(task.get("label", "时间到了"))
    title = "KeyPilot 倒计时" if kind == "timer" else "KeyPilot 闹钟" if kind == "alarm" else "KeyPilot 提醒"
    stop_event = threading.Event()
    sound_thread = threading.Thread(
        target=_alarm_sound_loop,
        args=(stop_event, str(task.get("sound", "morning"))),
        daemon=True,
    )
    sound_thread.start()
    _speak(label)
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            f"{label}\n\n点击“确定”停止响铃。",
            title,
            0x00010040,
        )
    finally:
        stop_event.set()
        sound_thread.join(timeout=1.0)


class TimeTaskScheduler:
    def __init__(self, store: TimeTaskStore | None = None) -> None:
        self.store = store or TimeTaskStore()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._poll_count = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="KeyPilotTimeScheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def poll(self) -> None:
        self._poll_count += 1
        try:
            due = self.store.claim_due()
            if self._poll_count == 1 or self._poll_count % 60 == 0:
                self._write_status("")
        except Exception as exc:
            self._write_status(f"{type(exc).__name__}: {exc}")
            return
        for task in due:
            threading.Thread(target=notify_task, args=(task,), daemon=True).start()

    def _write_status(self, error: str) -> None:
        try:
            path = default_task_path().parent / "scheduler-status.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "last_poll": time.time(),
                        "poll_count": self._poll_count,
                        "task_path": str(self.store.path),
                        "error": error,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    def _run(self) -> None:
        while not self._stop.wait(1.0):
            self.poll()


__all__ = [
    "create_calendar_draft",
    "format_due",
    "ALARM_PATTERNS",
    "resolve_clock_due",
    "TimeTaskScheduler",
    "TimeTaskStore",
    "world_time",
]
