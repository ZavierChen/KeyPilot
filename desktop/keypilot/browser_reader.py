from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from .actions import _process_ids, _top_level_windows, send_hotkey
from .handoff import copy_text_to_clipboard
from .reply_length import REPLY_LIMITS
from .data_paths import user_data_dir


CF_UNICODETEXT = 13
BROWSER_PROCESSES = ("msedge.exe", "chrome.exe", "firefox.exe")


@dataclass(frozen=True)
class BrowserCapture:
    text: str
    title: str
    has_ai_overview: bool


def _read_clipboard_text() -> str | None:
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


def _clean_page_text(text: str, limit: int = 24000) -> tuple[str, bool]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    compact = "\n".join(lines)
    markers = (
        "AI Overview",
        "AI 概览",
        "AI 摘要",
        "Gemini",
        "AI 模式回答已准备就绪",
        "AI 可能会出错",
        "AI Mode",
        "AI 模式对话",
        "AI responses may include mistakes",
    )
    positions = [compact.lower().find(marker.lower()) for marker in markers]
    positions = [position for position in positions if position >= 0]
    has_ai = bool(positions)
    # Keep the beginning of the copied page.  Google AI Mode places the query
    # before the generated answer, while its most reliable AI marker is often
    # in the footer.  Cropping backwards from that footer can discard both the
    # query and the introductory paragraph that we need to read aloud.
    compact = compact[:limit]
    return compact, has_ai


def _query_key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold())


def google_page_question(text: str, title: str = "") -> str:
    for line in text.splitlines():
        match = re.match(r"(?:AI 模式对话|AI Mode conversation)\s*[:：]\s*(.+)", line.strip(), re.I)
        if match:
            return match.group(1).strip()
    return re.split(r"\s[-–—]\sGoogle(?:\s|$)", title, maxsplit=1)[0].strip()


def _write_diagnostic(name: str, info: dict) -> None:
    directory = user_data_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def extract_google_ai_answer(text: str, question: str, limit: int | None = None, *, detail: str = "低") -> str | None:
    """Extract Google AI Mode's visible answer without asking a model to rewrite it."""
    text = text.replace("\ufffc", "").replace("\ufffd", "")
    if limit is None:
        limit = REPLY_LIMITS.get(detail, 120)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    normalized_question = _query_key(question)
    start = None
    for index, line in enumerate(lines):
        normalized_line = _query_key(line)
        if normalized_question and normalized_line == normalized_question:
            start = index + 1
            break
    if start is None:
        for index, line in enumerate(lines):
            if line.casefold() in {"ai overview", "ai 概览", "ai 摘要", "ai 摘要总览"}:
                start = index + 1
                break
        if start is None:
            return None
    footer_markers = (
        "AI 可能会出错",
        "尽情提问",
        "AI 模式回答已准备就绪",
        "相关链接",
        "AI responses may include mistakes",
        "AI can make mistakes",
        "Ask anything",
        "People also ask",
        "相关搜索",
        "复制文字",
    )
    navigation = {"AI 模式", "全部", "图片", "视频", "新闻", "更多", "登录",
                  "AI Mode", "All", "Images", "Videos", "News", "More", "Sign in",
                  "Show more", "显示更多", "Thinking", "正在思考", "正在搜索", "新话题"}
    answer_lines: list[str] = []
    for line in lines[start:]:
        if any(marker in line for marker in footer_markers):
            break
        if line in navigation:
            continue
        if _query_key(line) == normalized_question or re.fullmatch(r"\+?\d+", line):
            continue
        if line.startswith(("http://", "https://")) or "。相关结果" in line:
            continue
        if detail == "低" and answer_lines and re.match(r"^(?:\d+[.、]|[一二三四五六七八九十]+、)", line):
            break
        answer_lines.append(line)
        current = "\n".join(answer_lines)
        # AI Mode normally puts the concise identity/summary in its first
        # paragraph. Stop there once it is substantial enough for speech.
        minimum = 8 if re.search(r"[\u4e00-\u9fff]", current) else 20
        if detail == "低" and len(current) >= minimum and re.search(r"[。！？.!?][\"”’）)]?$", line):
            break
        # Accessibility text may split one paragraph across many nodes. A
        # three-node limit cut off its sentence before the full stop, causing
        # the polling code to wait until timeout despite a visible answer.
        if len(current) >= limit:
            break
    answer = "\n".join(answer_lines).strip()
    if len(answer) < (8 if re.search(r"[\u4e00-\u9fff]", answer) else 20):
        return None
    if len(answer) > limit:
        shortened = answer[:limit]
        sentence_end = max(
            shortened.rfind("。"),
            shortened.rfind("！"),
            shortened.rfind("？"),
            shortened.rfind("."),
        )
        answer = (
            shortened[: sentence_end + 1]
            if sentence_end >= max(80, limit // 2)
            else shortened.rstrip() + "……"
        )
    return answer


class BrowserReader:
    """Read rendered text only after an explicit KeyPilot question or page request."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.last_error = ""

    def wait_for_google_ai(self, question: str, *, restore_hwnd: int | None = None,
                           timeout: float = 30.0, detail: str = "低") -> BrowserCapture | None:
        """Poll the same query; never substitute another browser or a local answer."""
        self.last_error = ""
        deadline = time.monotonic() + timeout
        attempts = []
        while time.monotonic() < deadline:
            capture = self.capture_rendered_page(restore_hwnd=restore_hwnd, expected_title=question)
            if capture:
                answer = extract_google_ai_answer(capture.text, question, detail=detail)
                attempts.append({"characters": len(capture.text), "ai_marker": capture.has_ai_overview,
                                 "answer_characters": len(answer or ""),
                                 "query_line_found": any(_query_key(line) == _query_key(question)
                                                         for line in capture.text.splitlines())})
                _write_diagnostic("google-ai-diagnostic.json", {"stage": "extracting", "attempts": attempts})
                if os.environ.get("KEYPILOT_BROWSER_DEBUG") == "1":
                    _write_diagnostic("google-ai-debug.json", {"question": question, "text": capture.text})
                complete = any(m in capture.text for m in (
                    "AI 可能会出错", "AI responses may include mistakes", "AI can make mistakes",
                    "AI 模式回答已准备就绪"))
                enough = len(answer or "") >= REPLY_LIMITS.get(detail, 120)
                if answer and (complete or enough or (detail == "低" and
                               re.search(r"[。！？.!?][\"”’）)]?$", answer))):
                    self.last_error = ""
                    _write_diagnostic("google-ai-diagnostic.json", {"stage": "complete", "attempts": attempts})
                    return capture
                lower = capture.text.casefold()
                if any(marker in lower for marker in (
                    "unusual traffic", "异常流量", "不是机器人", "not a robot",
                    "ai mode isn't available", "无法使用 ai 模式", "不支持 ai 模式",
                )):
                    self.last_error = "Google 页面要求验证或暂不提供 AI 模式，请在浏览器中查看。"
                    return None
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        if attempts:
            self.last_error = f"已读取页面（{attempts[-1]['characters']} 字符），但在 {timeout:g} 秒内未识别出完整 AI 简介；这不是语音合成超时。"
        else:
            self.last_error = self.last_error or f"等待 {timeout:g} 秒仍未读取到页面正文；请确认浏览器页面已加载。"
        _write_diagnostic("google-ai-diagnostic.json", {"stage": "failed", "error": self.last_error, "attempts": attempts})
        return None

    @staticmethod
    def _read_document(hwnd: int) -> str:
        """Read browser accessibility document without touching input focus/clipboard."""
        script = Path(__file__).resolve().parent.parent / "scripts" / "read-browser-document.ps1"
        started = time.monotonic()
        info = {"hwnd": hwnd}
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                 str(script), "-WindowHandle", str(hwnd)],
                capture_output=True, text=True, encoding="utf-8-sig", timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            payload = json.loads(result.stdout)
            info.update(returncode=result.returncode, error=payload.get("error", ""),
                        stderr=result.stderr[:500], length=len(payload.get("text", "")))
            return str(payload.get("text", ""))
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            info["error"] = str(exc)
            return ""
        finally:
            info["seconds"] = round(time.monotonic() - started, 2)
            _write_diagnostic("browser-read-diagnostic.json", info)

    @staticmethod
    def online_available(timeout: float = 2.5) -> bool:
        request = urllib.request.Request(
            "https://www.google.com/generate_204",
            headers={"User-Agent": "Mozilla/5.0 KeyPilot/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status in (200, 204)
        except (OSError, TimeoutError, urllib.error.URLError):
            return False

    @staticmethod
    def should_search(question: str) -> bool:
        normalized = question.strip().lower()
        if len(normalized) < 4:
            return False
        private_markers = ("密码", "验证码", "密钥", "api key", "银行卡", "身份证")
        if any(marker in normalized for marker in private_markers):
            return False
        question_markers = (
            "?", "？", "什么", "为什么", "怎么", "如何", "谁", "哪里", "多少",
            "是否", "能不能", "可以吗", "告诉我", "解释", "介绍", "最新", "今天",
        )
        return any(marker in normalized for marker in question_markers)

    @staticmethod
    def _window_title(hwnd: int) -> str:
        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    @classmethod
    def _browser_window(cls, expected_title: str | None = None) -> int | None:
        user32 = ctypes.windll.user32
        foreground = user32.GetForegroundWindow()
        candidates: list[int] = []
        for process_name in BROWSER_PROCESSES:
            candidates.extend(_top_level_windows(_process_ids(process_name)))
        if expected_title:
            expected = _query_key(expected_title)
            for hwnd in candidates:
                title = _query_key(cls._window_title(hwnd))
                if expected and expected in title:
                    return hwnd
            return None
        if foreground in candidates:
            return foreground
        return candidates[0] if candidates else None

    def capture_rendered_page(
        self,
        *,
        settle_seconds: float = 0.0,
        restore_hwnd: int | None = None,
        close_after_capture: bool = False,
        expected_title: str | None = None,
    ) -> BrowserCapture | None:
        with self._lock:
            if settle_seconds:
                time.sleep(settle_seconds)
            hwnd = self._browser_window(expected_title)
            if not hwnd:
                self.last_error = "未找到与这次问题匹配的浏览器窗口。"
                return None
            # Most reads need neither activation nor clipboard access. This is
            # crucial when Google has automatically focused its follow-up box.
            if not close_after_capture:
                document = self._read_document(hwnd)
                if len(document.strip()) >= 80:
                    cleaned, has_ai = _clean_page_text(document)
                    self.last_error = ""
                    return BrowserCapture(cleaned, self._window_title(hwnd), has_ai)
            user32 = ctypes.windll.user32
            previous = user32.GetForegroundWindow()
            original_clipboard = _read_clipboard_text()
            clipboard_marker = f"__KEYPILOT_CAPTURE_{time.time_ns()}__"
            try:
                copy_text_to_clipboard(clipboard_marker)
                clipboard_baseline = clipboard_marker
            except OSError:
                clipboard_baseline = original_clipboard
            title = self._window_title(hwnd)
            try:
                user32.ShowWindow(hwnd, 9)
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.18)
                copied = self._read_document(hwnd) or None
                if user32.GetForegroundWindow() != hwnd:
                    try:
                        user32.SwitchToThisWindow(hwnd, True)
                        time.sleep(0.18)
                    except (AttributeError, OSError):
                        pass
                if not copied and user32.GetForegroundWindow() == hwnd:
                    send_hotkey(["escape"])
                    send_hotkey(["ctrl", "a"])
                    send_hotkey(["ctrl", "c"])
                    deadline = time.monotonic() + 2.2
                    while time.monotonic() < deadline:
                        time.sleep(0.08)
                        candidate = _read_clipboard_text()
                        if candidate and candidate != clipboard_baseline:
                            copied = candidate
                            break
                    send_hotkey(["escape"])
            finally:
                if close_after_capture and user32.GetForegroundWindow() == hwnd and (
                    not expected_title or _query_key(expected_title) in _query_key(self._window_title(hwnd))
                ):
                    # Internal application-name lookups are temporary. Close only
                    # the active result tab; ordinary user searches remain open.
                    try:
                        send_hotkey(["ctrl", "w"])
                        time.sleep(0.12)
                    except OSError:
                        pass
                try:
                    if _read_clipboard_text() in (clipboard_baseline, copied):
                        copy_text_to_clipboard(original_clipboard or "")
                except OSError:
                    pass
                restore = restore_hwnd or previous
                if restore and restore != hwnd:
                    user32.ShowWindow(restore, 9)
                    user32.SetForegroundWindow(restore)
            if not copied:
                return None
            cleaned, has_ai = _clean_page_text(copied)
            if len(cleaned) < 80:
                return None
            return BrowserCapture(cleaned, title, has_ai)


__all__ = [
    "BrowserCapture",
    "BrowserReader",
    "_clean_page_text",
    "extract_google_ai_answer",
]
