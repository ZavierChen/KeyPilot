from __future__ import annotations

import csv
import ctypes
import json
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any


KEYEVENTF_KEYUP = 0x0002
_last_toggled_window: int | None = None
_app_hotkey_lock = threading.Lock()
EVENT_MODIFY_STATE = 0x0002

VK_CODES = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "delete": 0x2E,
    "win": 0x5B,
    "volumemute": 0xAD,
    "volumedown": 0xAE,
    "volumeup": 0xAF,
}
VK_CODES.update({chr(code).lower(): code for code in range(ord("A"), ord("Z") + 1)})
VK_CODES.update({str(number): ord(str(number)) for number in range(10)})
VK_CODES.update({f"f{number}": 0x6F + number for number in range(1, 25)})


def _vk(name: str) -> int:
    try:
        return VK_CODES[name.lower()]
    except KeyError as exc:
        raise ValueError(f"unsupported hotkey key: {name}") from exc


def send_hotkey(keys: list[str]) -> None:
    if not keys:
        raise ValueError("hotkey requires at least one key")
    codes = [_vk(key) for key in keys]
    user32 = ctypes.windll.user32
    for code in codes:
        user32.keybd_event(code, 0, 0, 0)
    for code in reversed(codes):
        user32.keybd_event(code, 0, KEYEVENTF_KEYUP, 0)


def _open_packaged_app(app_id: str) -> None:
    subprocess.Popen(
        ["explorer.exe", f"shell:AppsFolder\\{app_id}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _process_ids(process_name: str) -> set[int]:
    result = subprocess.run(
        [
            "tasklist.exe",
            "/FI",
            f"IMAGENAME eq {process_name}",
            "/FO",
            "CSV",
            "/NH",
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    process_ids: set[int] = set()
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) < 2 or row[0].lower() != process_name.lower():
            continue
        try:
            process_ids.add(int(row[1]))
        except ValueError:
            continue
    return process_ids


def _top_level_windows(process_ids: set[int]) -> list[int]:
    if not process_ids:
        return []

    user32 = ctypes.windll.user32
    windows: list[int] = []
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _lparam: int) -> bool:
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value not in process_ids:
            return True
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return True
        if user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            windows.append(hwnd)
        return True

    callback = enum_proc_type(visit)
    user32.EnumWindows(callback, 0)
    return windows


def _windows_by_title_prefix(title_prefix: str) -> list[int]:
    user32 = ctypes.windll.user32
    windows: list[int] = []
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _lparam: int) -> bool:
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        if buffer.value.startswith(title_prefix) and (user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd)):
            windows.append(hwnd)
        return True

    callback = enum_proc_type(visit)
    user32.EnumWindows(callback, 0)
    return windows


def show_local_app(
    title_prefix: str,
    program: str,
    args: list[str],
    working_directory: str | None,
    *,
    toggle: bool = False,
) -> str:
    """Show an existing local app window, or launch it when it is not running."""
    user32 = ctypes.windll.user32
    windows = _windows_by_title_prefix(title_prefix)
    foreground = user32.GetForegroundWindow()
    if windows:
        target = foreground if foreground in windows else windows[0]
        if toggle and foreground in windows and not user32.IsIconic(target):
            user32.ShowWindow(target, 6)
            return "minimized"
        user32.ShowWindow(target, 9)
        user32.SetForegroundWindow(target)
        return "shown"
    subprocess.Popen(
        [program, *args],
        cwd=working_directory or None,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return "launched"


def signal_named_event(event_name: str) -> bool:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenEventW.restype = wintypes.HANDLE
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, event_name)
    if not handle:
        return False
    try:
        if not kernel32.SetEvent(handle):
            raise ctypes.WinError()
        return True
    finally:
        kernel32.CloseHandle(handle)


def toggle_dictation_app(
    title_prefix: str,
    event_name: str,
    program: str,
    args: list[str],
    working_directory: str | None,
) -> str:
    """Signal a running assistant, or cold-start it directly in dictation mode."""
    windows = _windows_by_title_prefix(title_prefix)
    if windows:
        target = windows[0]
        user32 = ctypes.windll.user32
        user32.ShowWindow(target, 9)
        user32.SetForegroundWindow(target)
        for _attempt in range(5):
            if signal_named_event(event_name):
                return "signaled"
            time.sleep(0.04)
        return "shown"
    subprocess.Popen(
        [program, *args],
        cwd=working_directory or None,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return "launched"


def load_portal_default(portal_path: str | Path) -> dict[str, Any]:
    path = Path(portal_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    payload = json.loads(path.read_text(encoding="utf-8"))
    default_id = payload.get("default")
    children = payload.get("children", {})
    if not isinstance(default_id, str) or not isinstance(children, dict):
        raise ValueError("portal.json requires default and children")
    child = children.get(default_id)
    if not isinstance(child, dict) or not isinstance(child.get("action"), dict):
        raise ValueError(f"portal default child is invalid: {default_id}")
    return child["action"]


def toggle_app_window(process_name: str, app_id: str) -> str:
    """Minimize a foreground app window; otherwise restore/open and foreground it."""
    global _last_toggled_window
    user32 = ctypes.windll.user32
    sw_minimize = 6
    sw_restore = 9
    windows = _top_level_windows(_process_ids(process_name))
    foreground = user32.GetForegroundWindow()

    # Prefer restoring the exact window that KeyPilot most recently minimized.
    # ChatGPT can own multiple top-level windows; without this state, minimizing
    # one may foreground another and the next toggle would minimize that one too.
    if _last_toggled_window in windows and user32.IsIconic(_last_toggled_window):
        user32.ShowWindow(_last_toggled_window, sw_restore)
        user32.SetForegroundWindow(_last_toggled_window)
        return "restored"

    if foreground in windows and user32.IsWindowVisible(foreground) and not user32.IsIconic(foreground):
        user32.ShowWindow(foreground, sw_minimize)
        _last_toggled_window = foreground
        return "minimized"

    if windows:
        target = next((hwnd for hwnd in windows if user32.IsIconic(hwnd)), windows[0])
        user32.ShowWindow(target, sw_restore)
        user32.SetForegroundWindow(target)
        _last_toggled_window = target
        return "restored"

    _last_toggled_window = None
    _open_packaged_app(app_id)
    return "opened"


def _ensure_app_then_hotkey(
    process_name: str,
    app_id: str,
    keys: list[str],
    startup_timeout_seconds: float,
    startup_settle_seconds: float,
    debug: bool,
) -> None:
    if not _app_hotkey_lock.acquire(blocking=False):
        if debug:
            print("[KeyPilot] app launch already in progress; ignoring duplicate", flush=True)
        return
    try:
        already_running = bool(_process_ids(process_name))
        if not already_running:
            if debug:
                print(f"[KeyPilot] starting {process_name}", flush=True)
            _open_packaged_app(app_id)
            deadline = time.monotonic() + startup_timeout_seconds
            while time.monotonic() < deadline:
                process_ids = _process_ids(process_name)
                if process_ids and _top_level_windows(process_ids):
                    # Electron shows its window before all global shortcuts are ready.
                    # Keep a configurable settling period after the first window appears.
                    if debug:
                        print(
                            f"[KeyPilot] window ready; settling {startup_settle_seconds:.1f}s",
                            flush=True,
                        )
                    time.sleep(startup_settle_seconds)
                    break
                time.sleep(0.2)
        send_hotkey(keys)
    finally:
        _app_hotkey_lock.release()


def ensure_app_then_hotkey(
    process_name: str,
    app_id: str,
    keys: list[str],
    startup_timeout_seconds: float,
    startup_settle_seconds: float,
    *,
    debug: bool,
) -> None:
    threading.Thread(
        target=_ensure_app_then_hotkey,
        args=(
            process_name,
            app_id,
            keys,
            startup_timeout_seconds,
            startup_settle_seconds,
            debug,
        ),
        name="KeyPilotAppHotkey",
        daemon=True,
    ).start()


def execute_action(action: dict[str, Any], *, debug: bool = False) -> None:
    action_type = action.get("type")
    if debug:
        print(f"[KeyPilot] action: {action}", flush=True)

    if action_type == "open_packaged_app":
        app_id = action.get("app_id")
        if not isinstance(app_id, str) or not app_id:
            raise ValueError("open_packaged_app requires app_id")
        _open_packaged_app(app_id)
        return

    if action_type == "toggle_packaged_app_window":
        app_id = action.get("app_id")
        process_name = action.get("process_name")
        if not isinstance(app_id, str) or not app_id:
            raise ValueError("toggle_packaged_app_window requires app_id")
        if not isinstance(process_name, str) or not process_name:
            raise ValueError("toggle_packaged_app_window requires process_name")
        outcome = toggle_app_window(process_name, app_id)
        if debug:
            print(f"[KeyPilot] window: {outcome}", flush=True)
        return

    if action_type in ("show_local_app", "toggle_local_app"):
        title_prefix = action.get("title_prefix")
        program = action.get("program")
        args = action.get("args", [])
        working_directory = action.get("working_directory")
        if not isinstance(title_prefix, str) or not title_prefix:
            raise ValueError(f"{action_type} requires title_prefix")
        if not isinstance(program, str) or not program:
            raise ValueError(f"{action_type} requires program")
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError(f"{action_type} args must be a list of strings")
        if working_directory is not None and not isinstance(working_directory, str):
            raise ValueError(f"{action_type} working_directory must be a string")
        outcome = show_local_app(
            title_prefix,
            program,
            args,
            working_directory,
            toggle=action_type == "toggle_local_app",
        )
        if debug:
            print(f"[KeyPilot] local app: {outcome}", flush=True)
        return

    if action_type == "portal_default":
        portal_path = action.get("portal_path", "portal.json")
        if not isinstance(portal_path, str) or not portal_path:
            raise ValueError("portal_default requires portal_path")
        execute_action(load_portal_default(portal_path), debug=debug)
        return

    if action_type == "toggle_dictation_app":
        title_prefix = action.get("title_prefix")
        event_name = action.get("event_name")
        program = action.get("program")
        args = action.get("args", [])
        working_directory = action.get("working_directory")
        if not isinstance(title_prefix, str) or not title_prefix:
            raise ValueError("toggle_dictation_app requires title_prefix")
        if not isinstance(event_name, str) or not event_name:
            raise ValueError("toggle_dictation_app requires event_name")
        if not isinstance(program, str) or not program:
            raise ValueError("toggle_dictation_app requires program")
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError("toggle_dictation_app args must be a list of strings")
        if working_directory is not None and not isinstance(working_directory, str):
            raise ValueError("toggle_dictation_app working_directory must be a string")
        outcome = toggle_dictation_app(
            title_prefix,
            event_name,
            program,
            args,
            working_directory,
        )
        if debug:
            print(f"[KeyPilot] dictation app: {outcome}", flush=True)
        return

    if action_type == "noop":
        return

    if action_type == "command":
        program = action.get("program")
        args = action.get("args", [])
        if not isinstance(program, str) or not program:
            raise ValueError("command requires program")
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError("command args must be a list of strings")
        subprocess.Popen([program, *args])
        return

    if action_type == "hotkey":
        keys = action.get("keys")
        if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
            raise ValueError("hotkey requires a list of key names")
        send_hotkey(keys)
        return

    if action_type == "app_hotkey":
        app_id = action.get("app_id")
        process_name = action.get("process_name")
        keys = action.get("keys")
        timeout = action.get("startup_timeout_seconds", 10)
        settle = action.get("startup_settle_seconds", 3)
        if not isinstance(app_id, str) or not app_id:
            raise ValueError("app_hotkey requires app_id")
        if not isinstance(process_name, str) or not process_name:
            raise ValueError("app_hotkey requires process_name")
        if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
            raise ValueError("app_hotkey requires a list of key names")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("app_hotkey startup_timeout_seconds must be positive")
        if not isinstance(settle, (int, float)) or settle < 0:
            raise ValueError("app_hotkey startup_settle_seconds must be non-negative")
        ensure_app_then_hotkey(
            process_name,
            app_id,
            keys,
            float(timeout),
            float(settle),
            debug=debug,
        )
        return

    if action_type == "wait":
        milliseconds = action.get("milliseconds", 0)
        if not isinstance(milliseconds, int) or milliseconds < 0:
            raise ValueError("wait.milliseconds must be a non-negative integer")
        time.sleep(milliseconds / 1000)
        return

    if action_type == "sequence":
        steps = action.get("steps", [])
        if not isinstance(steps, list):
            raise ValueError("sequence.steps must be a list")
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("each sequence step must be an object")
            execute_action(step, debug=debug)
        return

    raise ValueError(f"unsupported action type: {action_type}")
