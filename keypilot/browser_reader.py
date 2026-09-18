from __future__ import annotations

import ctypes
import re
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from dataclasses import dataclass

from .actions import _process_ids, _top_level_windows, send_hotkey
from .handoff import copy_text_to_clipboard


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


def _clean_page_text(text: str, limit: int = 7000) -> tuple[str, bool]:
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


def extract_google_ai_answer(text: str, question: str, limit: int = 450) -> str | None:
    """Extract Google AI Mode's visible answer without asking a model to rewrite it."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    normalized_question = re.sub(r"\s+", "", question).casefold()
    start = None
    for index, line in enumerate(lines):
        normalized_line = re.sub(r"\s+", "", line).casefold()
        if normalized_question and normalized_line == normalized_question:
            start = index + 1
    if start is None:
        return None
    footer_markers = (
        "AI 可能会出错",
        "尽情提问",
        "AI 模式回答已准备就绪",
        "相关链接",
    )
    navigation = {"AI 模式", "全部", "图片", "视频", "新闻", "更多", "登录"}
    answer_lines: list[str] = []
    for line in lines[start:]:
        if any(marker in line for marker in footer_markers):
            break
        if line in navigation:
            continue
        if answer_lines and re.match(r"^(?:\d+[.、]|[一二三四五六七八九十]+、)", line):
            break
        answer_lines.append(line)
        current = "\n".join(answer_lines)
        # AI Mode normally puts the concise identity/summary in its first
        # paragraph. Stop there once it is substantial enough for speech.
        if len(current) >= 150 and re.search(r"[。！？.!?]$", line):
            break
        if len(answer_lines) >= 3:
            break
    answer = "\n".join(answer_lines).strip()
    if len(answer) < 20:
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
            expected = re.sub(r"\s+", "", expected_title).casefold()
            for hwnd in candidates:
                title = re.sub(r"\s+", "", cls._window_title(hwnd)).casefold()
                if expected and expected in title:
                    return hwnd
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
                return None
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
                copied = None
                if user32.GetForegroundWindow() != hwnd:
                    try:
                        user32.SwitchToThisWindow(hwnd, True)
                        time.sleep(0.18)
                    except (AttributeError, OSError):
                        pass
                if user32.GetForegroundWindow() == hwnd:
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
                if close_after_capture:
                    # Internal application-name lookups are temporary. Close only
                    # the active result tab; ordinary user searches remain open.
                    try:
                        send_hotkey(["ctrl", "w"])
                        time.sleep(0.12)
                    except OSError:
                        pass
                try:
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
