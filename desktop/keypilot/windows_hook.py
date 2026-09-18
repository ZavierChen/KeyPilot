from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Callable

from .config import TriggerConfig
from .gestures import GestureRecognizer


WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_TIMER = 0x0113
WM_QUIT = 0x0012

VK_SHIFT = 0x10
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LWIN = 0x5B
VK_RWIN = 0x5C


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


def virtual_key_code(name: str) -> int:
    upper = name.upper()
    if upper.startswith("F") and upper[1:].isdigit():
        number = int(upper[1:])
        if 1 <= number <= 24:
            return 0x6F + number
    if len(upper) == 1 and upper.isalnum():
        return ord(upper)
    raise ValueError(f"unsupported trigger virtual key: {name}")


class WindowsKeyboardHook:
    def __init__(
        self,
        trigger: TriggerConfig,
        recognizer: GestureRecognizer,
        on_gesture: Callable[[str], None],
        *,
        debug: bool = False,
    ) -> None:
        self.trigger = trigger
        self.recognizer = recognizer
        self.on_gesture = on_gesture
        self.debug = debug
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.user32.SetWindowsHookExW.restype = wintypes.HANDLE
        self.user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            LowLevelKeyboardProc,
            wintypes.HMODULE,
            wintypes.DWORD,
        ]
        self.user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self.user32.CallNextHookEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.SetTimer.restype = ctypes.c_size_t
        self.trigger_vk = virtual_key_code(trigger.virtual_key)
        self._hook = None
        self._trigger_active = False
        self._win_keys_down: set[int] = set()
        self._shift_keys_down: set[int] = set()
        self._callback = LowLevelKeyboardProc(self._hook_proc)

    def _key_is_down(self, vk_code: int) -> bool:
        return bool(self.user32.GetAsyncKeyState(vk_code) & 0x8000)

    def _modifiers_match(self) -> bool:
        win_down = bool(self._win_keys_down) or self._key_is_down(VK_LWIN) or self._key_is_down(VK_RWIN)
        shift_down = bool(self._shift_keys_down) or self._key_is_down(VK_SHIFT)
        if self.trigger.require_windows and not win_down:
            return False
        if self.trigger.require_shift and not shift_down:
            return False
        return True

    def _hook_proc(self, code: int, wparam: int, lparam: int) -> int:
        if code != HC_ACTION:
            return self.user32.CallNextHookEx(self._hook, code, wparam, lparam)

        event = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        is_down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_up = wparam in (WM_KEYUP, WM_SYSKEYUP)

        if event.vkCode in (VK_LWIN, VK_RWIN):
            if is_down:
                self._win_keys_down.add(event.vkCode)
            elif is_up:
                self._win_keys_down.discard(event.vkCode)
        if event.vkCode in (VK_SHIFT, VK_LSHIFT, VK_RSHIFT):
            if is_down:
                self._shift_keys_down.add(event.vkCode)
            elif is_up:
                self._shift_keys_down.discard(event.vkCode)

        if event.vkCode == self.trigger_vk:
            if is_down and (self._trigger_active or self._modifiers_match()):
                self._trigger_active = True
                self.recognizer.key_down(time.monotonic())
                if self.debug:
                    print("[KeyPilot] trigger down", flush=True)
                return 1
            if is_up and self._trigger_active:
                self._trigger_active = False
                gesture = self.recognizer.key_up(time.monotonic())
                if self.debug:
                    print(f"[KeyPilot] trigger up -> {gesture or 'pending tap'}", flush=True)
                if gesture:
                    self.on_gesture(gesture)
                return 1

        return self.user32.CallNextHookEx(self._hook, code, wparam, lparam)

    def run(self) -> None:
        module = self.kernel32.GetModuleHandleW(None)
        self._hook = self.user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._callback, module, 0
        )
        if not self._hook:
            raise ctypes.WinError()

        timer_id = self.user32.SetTimer(None, 0, 25, None)
        if not timer_id:
            self.user32.UnhookWindowsHookEx(self._hook)
            raise ctypes.WinError()

        if self.debug:
            print(
                f"[KeyPilot] hook installed for {self.trigger.virtual_key}; "
                "press Ctrl+C to stop",
                flush=True,
            )

        message = wintypes.MSG()
        try:
            while True:
                result = self.user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == 0 or result == -1:
                    break
                if message.message == WM_TIMER:
                    gesture = self.recognizer.poll(time.monotonic())
                    if gesture:
                        self.on_gesture(gesture)
                self.user32.TranslateMessage(ctypes.byref(message))
                self.user32.DispatchMessageW(ctypes.byref(message))
        finally:
            self.user32.KillTimer(None, timer_id)
            self.user32.UnhookWindowsHookEx(self._hook)
