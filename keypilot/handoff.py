from __future__ import annotations

import ctypes
import json
import os
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def copy_text_to_clipboard(text: str) -> None:
    """Put Unicode text on the Windows clipboard without shell quoting."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p

    opened = False
    for _attempt in range(12):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.04)
    if not opened:
        raise OSError("无法打开 Windows 剪贴板")

    handle = None
    try:
        if not user32.EmptyClipboard():
            raise ctypes.WinError()
        encoded = (text + "\0").encode("utf-16-le")
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
        if not handle:
            raise ctypes.WinError()
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            raise ctypes.WinError()
        try:
            ctypes.memmove(pointer, encoded, len(encoded))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise ctypes.WinError()
        handle = None  # Clipboard now owns the allocation.
    finally:
        if handle:
            kernel32.GlobalFree(handle)
        user32.CloseClipboard()


def read_text_from_clipboard() -> str | None:
    """Read Unicode text from the Windows clipboard without changing it."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    opened = False
    for _attempt in range(12):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.04)
    if not opened:
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        handle_pointer = ctypes.c_void_p(handle)
        pointer = kernel32.GlobalLock(handle_pointer)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle_pointer)
    finally:
        user32.CloseClipboard()


class DailyHandoffState:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "KeyPilot"
            path = base / "handoff-state.json"
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def claim_chatgpt_day(self, today: str | None = None) -> bool:
        current_day = today or date.today().isoformat()
        with self._lock:
            payload = self._read()
            chat = payload.get("chatgpt", {})
            first_today = not isinstance(chat, dict) or chat.get("date") != current_day
            if first_today:
                payload["chatgpt"] = {"date": current_day}
                self._write(payload)
            return first_today

    def codex_thread(self, today: str | None = None) -> str | None:
        current_day = today or date.today().isoformat()
        with self._lock:
            codex = self._read().get("codex", {})
            if not isinstance(codex, dict) or codex.get("date") != current_day:
                return None
            thread_id = codex.get("thread_id")
            return thread_id if isinstance(thread_id, str) and thread_id else None

    def save_codex_thread(self, thread_id: str, today: str | None = None) -> None:
        current_day = today or date.today().isoformat()
        with self._lock:
            payload = self._read()
            payload["codex"] = {"date": current_day, "thread_id": thread_id}
            self._write(payload)


__all__ = ["DailyHandoffState", "copy_text_to_clipboard", "read_text_from_clipboard"]
