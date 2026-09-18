from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

from .actions import _process_ids, _top_level_windows, send_hotkey
from .chat_handoff import ChatHandoffStore
from .handoff import copy_text_to_clipboard


BG = "#10131a"
PANEL = "#191e28"
TEXT = "#f2f5f9"
MUTED = "#9ca8b8"
ACCENT = "#57b8ff"
SUCCESS = "#55d187"
ERROR = "#ff6b6b"
CHATGPT_APP_ID = "OpenAI.Codex_2p2nqsd0c76g0!App"


def _read_clipboard_text() -> str:
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
        return ""
    try:
        handle = user32.GetClipboardData(13)
        if not handle:
            return ""
        handle_pointer = ctypes.c_void_p(handle)
        pointer = kernel32.GlobalLock(handle_pointer)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle_pointer)
    finally:
        user32.CloseClipboard()


def _open_chatgpt() -> None:
    subprocess.Popen(
        ["explorer.exe", f"shell:AppsFolder\\{CHATGPT_APP_ID}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_chat_window(timeout: float = 15.0) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        windows = _top_level_windows(_process_ids("ChatGPT.exe"))
        if windows:
            return windows[0]
        time.sleep(0.25)
    return None


def _click(hwnd: int, x_ratio: float, bottom_offset: int) -> None:
    rect = wintypes.RECT()
    user32 = ctypes.windll.user32
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError()
    x = int(rect.left + (rect.right - rect.left) * x_ratio)
    y = int(rect.bottom - bottom_offset)
    user32.SetCursorPos(x, y)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def deliver_to_chatgpt(text: str, first_today: bool) -> tuple[bool, str, bool]:
    copy_text_to_clipboard(text)
    _open_chatgpt()
    hwnd = _wait_for_chat_window()
    if not hwnd:
        return False, "没有等到 ChatGPT 窗口。问题仍保留在剪贴板中。", False
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.9)
    if first_today:
        send_hotkey(["ctrl", "shift", "o"])
        time.sleep(1.1)
    prepared_new_chat = first_today
    send_hotkey(["escape"])

    for x_ratio, bottom_offset in ((0.62, 105), (0.60, 145), (0.68, 80)):
        user32.SetForegroundWindow(hwnd)
        _click(hwnd, x_ratio, bottom_offset)
        time.sleep(0.2)
        copy_text_to_clipboard(text)
        send_hotkey(["ctrl", "a"])
        send_hotkey(["ctrl", "v"])
        time.sleep(0.35)
        send_hotkey(["ctrl", "a"])
        send_hotkey(["ctrl", "c"])
        time.sleep(0.25)
        copied = _read_clipboard_text().strip()
        if copied == text.strip():
            copy_text_to_clipboard(text)
            send_hotkey(["right"])
            send_hotkey(["enter"])
            return True, "问题已粘贴并发送到 ChatGPT。", prepared_new_chat

    copy_text_to_clipboard(text)
    return False, "没有定位到 ChatGPT 输入框。请点击输入框后选择“重新发送”。", prepared_new_chat


class ChatBridgeApp:
    def __init__(self, root: tk.Tk, request_id: str | None) -> None:
        self.root = root
        self.store = ChatHandoffStore()
        self.item = self.store.get(request_id)
        self.busy = False
        self.status_var = tk.StringVar(value="准备发送")
        self.root.title("KeyPilot · GPT 转接器")
        self.root.geometry("590x360")
        self.root.minsize(520, 320)
        self.root.configure(bg=BG)
        project_dir = Path(__file__).resolve().parent.parent
        icon = project_dir / "assets" / "keypilot.ico"
        if icon.exists():
            try:
                self.root.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        self._build()
        if self.item:
            self.root.after(700, self.retry)

    def _build(self) -> None:
        outer = tk.Frame(self.root, bg=BG, padx=24, pady=22)
        outer.pack(fill="both", expand=True)
        tk.Label(outer, text="GPT 转接器", bg=BG, fg=TEXT, font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
        tk.Label(outer, textvariable=self.status_var, bg=BG, fg=ACCENT, font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(5, 12))
        self.question = tk.Text(outer, height=7, bg=PANEL, fg=TEXT, relief="flat", wrap="word", font=("Microsoft YaHei UI", 11), padx=12, pady=10)
        self.question.pack(fill="both", expand=True)
        text = str(self.item.get("text", "")) if self.item else "目前没有等待发送的问题。"
        self.question.insert("1.0", text)
        self.question.configure(state="disabled")
        buttons = tk.Frame(outer, bg=BG)
        buttons.pack(fill="x", pady=(14, 0))
        self.retry_button = tk.Button(buttons, text="重新发送", command=self.retry, bg=ACCENT, fg="#07131d", relief="flat", padx=18, pady=7, font=("Microsoft YaHei UI", 10, "bold"))
        self.retry_button.pack(side="left")
        tk.Button(buttons, text="仅复制问题", command=self.copy_only, bg=PANEL, fg=TEXT, relief="flat", padx=16, pady=7).pack(side="left", padx=(10, 0))
        tk.Button(buttons, text="关闭", command=self.root.destroy, bg=PANEL, fg=MUTED, relief="flat", padx=16, pady=7).pack(side="right")

    def copy_only(self) -> None:
        if self.item:
            copy_text_to_clipboard(str(self.item.get("text", "")))
            self.status_var.set("问题已复制到剪贴板。")

    def retry(self) -> None:
        if self.busy or not self.item:
            return
        self.busy = True
        self.retry_button.configure(state="disabled")
        self.status_var.set("正在等待 ChatGPT 输入框……")

        def work() -> None:
            ok, message, prepared_new_chat = deliver_to_chatgpt(
                str(self.item.get("text", "")),
                bool(self.item.get("first_today")),
            )
            if prepared_new_chat:
                self.item["first_today"] = False
                self.store.mark_chat_prepared(str(self.item.get("id")))
            self.store.update_status(str(self.item.get("id")), "sent" if ok else "failed", "" if ok else message)
            self.root.after(0, lambda: self._finish(ok, message))

        threading.Thread(target=work, daemon=True).start()

    def _finish(self, ok: bool, message: str) -> None:
        self.busy = False
        self.status_var.set(message)
        self.retry_button.configure(state="normal")
        if ok:
            self.root.after(1600, self.root.destroy)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-id")
    parser.add_argument("--smoke-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = tk.Tk()
    ChatBridgeApp(root, args.request_id)
    if args.smoke_test:
        root.update_idletasks()
        root.destroy()
        return 0
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
