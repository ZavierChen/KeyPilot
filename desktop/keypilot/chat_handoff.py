from __future__ import annotations

from .data_paths import user_data_dir

import ctypes
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def default_handoff_path() -> Path:
    return user_data_dir() / "chat-handoff.json"


def default_marvis_handoff_path() -> Path:
    return user_data_dir() / "marvis-handoff.json"


@contextmanager
def _handoff_lock() -> Iterator[None]:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, r"Local\KeyPilot.Repro.ChatHandoff")
    if not handle:
        raise ctypes.WinError()
    try:
        kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0xFFFFFFFF)
        yield
    finally:
        kernel32.ReleaseMutex(ctypes.c_void_p(handle))
        kernel32.CloseHandle(ctypes.c_void_p(handle))


class ChatHandoffStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_handoff_path()

    def _read(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _write(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(items[-30:], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def enqueue(self, text: str, first_today: bool) -> dict[str, Any]:
        item = {
            "id": uuid.uuid4().hex,
            "text": text,
            "first_today": first_today,
            "status": "pending",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        with _handoff_lock():
            items = self._read()
            items.append(item)
            self._write(items)
        return item

    def get(self, request_id: str | None = None) -> dict[str, Any] | None:
        with _handoff_lock():
            items = self._read()
        if request_id:
            return next((item for item in items if str(item.get("id")) == request_id), None)
        pending = [item for item in items if item.get("status") != "sent"]
        return (pending or items)[-1] if items else None

    def update_status(self, request_id: str, status: str, error: str = "") -> None:
        with _handoff_lock():
            items = self._read()
            for item in items:
                if str(item.get("id")) == request_id:
                    item["status"] = status
                    item["error"] = error
                    item["updated_at"] = time.time()
                    break
            self._write(items)

    def mark_chat_prepared(self, request_id: str) -> None:
        with _handoff_lock():
            items = self._read()
            for item in items:
                if str(item.get("id")) == request_id:
                    item["first_today"] = False
                    item["updated_at"] = time.time()
                    break
            self._write(items)


__all__ = ["ChatHandoffStore", "default_handoff_path", "default_marvis_handoff_path"]
