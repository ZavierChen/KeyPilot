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
from .chat_handoff import ChatHandoffStore, default_marvis_handoff_path
from .handoff import copy_text_to_clipboard, read_text_from_clipboard


BG = "#10131a"
PANEL = "#191e28"
TEXT = "#f2f5f9"
MUTED = "#9ca8b8"
ACCENT = "#57b8ff"


def _marvis_candidates() -> list[Path]:
    candidates: list[Path] = []
    roots = [
        Path(r"D:\Program Files\Tencent\Marvis\Application"),
        Path(r"C:\Program Files\Tencent\Marvis\Application"),
        Path(r"C:\Program Files (x86)\Tencent\Marvis\Application"),
    ]
    for root in roots:
        if root.exists():
            versioned = sorted(
                (item / "Marvis.exe" for item in root.iterdir() if item.is_dir()),
                key=lambda item: item.parent.name,
                reverse=True,
            )
            candidates.extend(item for item in versioned if item.exists())
        direct = root / "MarvisLauncher.exe"
        if direct.exists():
            candidates.append(direct)
    return candidates


def find_marvis_executable() -> Path | None:
    candidates = _marvis_candidates()
    return candidates[0] if candidates else None


def _open_marvis() -> bool:
    executable = find_marvis_executable()
    if not executable:
        return False
    subprocess.Popen(
        [str(executable)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True


def _wait_for_marvis_window(timeout: float = 18.0) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        windows = _top_level_windows(_process_ids("Marvis.exe"))
        if windows:
            return max(windows, key=_window_area)
        time.sleep(0.25)
    return None


def _window_rect(hwnd: int) -> wintypes.RECT:
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError()
    return rect


def _window_area(hwnd: int) -> int:
    try:
        rect = _window_rect(hwnd)
        return max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
    except OSError:
        return 0


def _click_point(hwnd: int, x_ratio: float, y_ratio: float) -> None:
    rect = _window_rect(hwnd)
    x = int(rect.left + (rect.right - rect.left) * x_ratio)
    y = int(rect.top + (rect.bottom - rect.top) * y_ratio)
    user32 = ctypes.windll.user32
    user32.SetCursorPos(x, y)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def deliver_to_marvis(text: str) -> tuple[bool, str]:
    copy_text_to_clipboard(text)
    if not _process_ids("Marvis.exe") and not _open_marvis():
        return False, "没有找到 Marvis，请确认它仍安装在 Tencent\\Marvis\\Application。"
    hwnd = _wait_for_marvis_window()
    if not hwnd:
        return False, "没有等到 Marvis 窗口。问题仍保留在剪贴板中。"

    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(1.0)
    send_hotkey(["escape"])

    # Marvis has used both a compact launcher and a full conversation window.
    # Try the input positions used by both layouts and verify the paste before
    # pressing Enter, so a UI update cannot send text to the wrong control.
    for x_ratio, y_ratio in (
        (0.50, 0.54),
        (0.50, 0.90),
        (0.55, 0.84),
        (0.62, 0.76),
    ):
        user32.SetForegroundWindow(hwnd)
        _click_point(hwnd, x_ratio, y_ratio)
        time.sleep(0.22)
        copy_text_to_clipboard(text)
        send_hotkey(["ctrl", "a"])
        send_hotkey(["ctrl", "v"])
        time.sleep(0.4)
        send_hotkey(["ctrl", "a"])
        send_hotkey(["ctrl", "c"])
        time.sleep(0.22)
        copied = (read_text_from_clipboard() or "").strip()
        if copied == text.strip():
            copy_text_to_clipboard(text)
            send_hotkey(["right"])
            send_hotkey(["enter"])
            return True, "问题已自动粘贴并发送到 Marvis。"

    copy_text_to_clipboard(text)
    return False, "没有定位到 Marvis 输入框。请点击输入框后选择“重新发送”。"


class MarvisBridgeApp:
    def __init__(self, root: tk.Tk, request_id: str | None) -> None:
        self.root = root
        self.store = ChatHandoffStore(default_marvis_handoff_path())
        self.item = self.store.get(request_id)
        self.busy = False
        self.status_var = tk.StringVar(value="准备发送")
        self.root.title("KeyPilot · Marvis 转接器")
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
            self.root.after(600, self.retry)

    def _build(self) -> None:
        outer = tk.Frame(self.root, bg=BG, padx=24, pady=22)
        outer.pack(fill="both", expand=True)
        tk.Label(outer, text="Marvis 转接器", bg=BG, fg=TEXT, font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
        tk.Label(outer, textvariable=self.status_var, bg=BG, fg=ACCENT, font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(5, 12))
        self.question = tk.Text(outer, height=7, bg=PANEL, fg=TEXT, relief="flat", wrap="word", font=("Microsoft YaHei UI", 11), padx=12, pady=10)
        self.question.pack(fill="both", expand=True)
        self.question.insert("1.0", str(self.item.get("text", "")) if self.item else "目前没有等待发送的问题。")
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
        self.status_var.set("正在等待 Marvis 输入框……")

        def work() -> None:
            ok, message = deliver_to_marvis(str(self.item.get("text", "")))
            self.store.update_status(str(self.item.get("id")), "sent" if ok else "failed", "" if ok else message)
            self.root.after(0, lambda: self._finish(ok, message))

        threading.Thread(target=work, daemon=True).start()

    def _finish(self, ok: bool, message: str) -> None:
        self.busy = False
        self.status_var.set(message)
        self.retry_button.configure(state="normal")
        if ok:
            self.root.after(1200, self.root.destroy)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-id")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    root = tk.Tk()
    MarvisBridgeApp(root, args.request_id)
    if args.smoke_test:
        root.update_idletasks()
        root.destroy()
        return 0
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
