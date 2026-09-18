from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path


def default_memory_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "KeyPilot" / "conversation-memory.json"


class ConversationMemory:
    """Small daily rolling context for follow-up questions, with strict size limits."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        max_turns: int = 4,
        max_chars: int = 2400,
        max_chars_per_message: int = 600,
    ) -> None:
        self.path = path or default_memory_path()
        self.max_turns = max_turns
        self.max_chars = max_chars
        self.max_chars_per_message = max_chars_per_message

    def _read(self) -> list[dict[str, object]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, dict) or payload.get("date") != date.today().isoformat():
            return []
        turns = payload.get("turns", [])
        return turns if isinstance(turns, list) else []

    def _write(self, turns: list[dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"date": date.today().isoformat(), "turns": turns[-self.max_turns :]},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def add(self, user: str, assistant: str) -> None:
        turn = {
            "user": user.strip()[: self.max_chars_per_message],
            "assistant": assistant.strip()[: self.max_chars_per_message],
            "created_at": time.time(),
        }
        turns = self._read()
        turns.append(turn)
        self._write(turns)

    def context(self) -> str:
        lines: list[str] = []
        for turn in self._read()[-self.max_turns :]:
            user = str(turn.get("user", ""))[: self.max_chars_per_message]
            assistant = str(turn.get("assistant", ""))[: self.max_chars_per_message]
            if user and assistant:
                lines.extend((f"用户：{user}", f"助手：{assistant}"))
        text = "\n".join(lines)
        return text[-self.max_chars :]

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


__all__ = ["ConversationMemory", "default_memory_path"]
