from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from .handoff import DailyHandoffState, copy_text_to_clipboard


@dataclass(frozen=True)
class CodexResult:
    action: str
    response: str
    query: str = ""


class CodexBridge:
    def __init__(
        self,
        project_dir: Path,
        *,
        timeout_seconds: int = 90,
        state: DailyHandoffState | None = None,
    ) -> None:
        self.project_dir = project_dir
        self.timeout_seconds = timeout_seconds
        self.state = state or DailyHandoffState()
        self._lock = threading.Lock()

    @staticmethod
    def _parse_events(stdout: str) -> tuple[str | None, dict[str, object]]:
        thread_id: str | None = None
        final_text: str | None = None
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
                thread_id = event["thread_id"]
            item = event.get("item")
            if (
                event.get("type") == "item.completed"
                and isinstance(item, dict)
                and item.get("type") == "agent_message"
                and isinstance(item.get("text"), str)
            ):
                final_text = item["text"]
        if final_text is None:
            raise RuntimeError("Codex 没有返回最终结果")
        try:
            payload = json.loads(final_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Codex 没有返回有效的结构化结果") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Codex 返回结果格式错误")
        return thread_id, payload

    def ask(self, utterance: str) -> CodexResult:
        copy_text_to_clipboard(utterance)
        schema = self.project_dir / "codex-action-schema.json"
        prompt = (
            "你是 KeyPilot Windows 本地助手的兜底理解器。用户的话没有被本地 Skill 识别。"
            "不要执行命令、不要修改文件，只返回符合给定 JSON Schema 的结果。"
            "若用户是在寻找某项 Windows 设置，action=settings_search，并提取简短中文 query。"
            "若属于可以直接回答的普通问题，action=speak，给出不超过80个汉字的中文回答。"
            "其他情况 action=unsupported，简短说明暂不支持。用户原话："
            + utterance
        )
        with self._lock:
            existing_thread = self.state.codex_thread()
            if existing_thread:
                command = [
                    "codex",
                    "exec",
                    "resume",
                    existing_thread,
                    "--json",
                    "--skip-git-repo-check",
                    "--output-schema",
                    str(schema),
                    prompt,
                ]
            else:
                command = [
                    "codex",
                    "exec",
                    "--json",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "--output-schema",
                    str(schema),
                    prompt,
                ]
            result = subprocess.run(
                command,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()
            message = detail[-1] if detail else "Codex 调用失败"
            raise RuntimeError(message)
        thread_id, payload = self._parse_events(result.stdout)
        if not existing_thread:
            if not thread_id:
                raise RuntimeError("Codex 没有返回每日会话 ID")
            self.state.save_codex_thread(thread_id)
        return CodexResult(
            action=str(payload.get("action", "unsupported")),
            response=str(payload.get("response", "暂时无法处理这个请求。")),
            query=str(payload.get("query", "")),
        )


__all__ = ["CodexBridge", "CodexResult"]
