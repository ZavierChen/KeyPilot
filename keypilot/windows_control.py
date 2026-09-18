from __future__ import annotations

import ctypes
import math
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import winreg
from ctypes import wintypes
from dataclasses import dataclass
from collections import Counter
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .actions import _process_ids, _top_level_windows, send_hotkey
from .assistant_router import COMMON_WEBSITES, SkillCall, normalize_text
from .handoff import DailyHandoffState, copy_text_to_clipboard, read_text_from_clipboard
from .chat_handoff import ChatHandoffStore, default_marvis_handoff_path
from .time_service import (
    TimeTaskStore,
    create_calendar_draft,
    format_due,
    resolve_clock_due,
    world_time,
)
from .website_shortcuts import normalize_safe_url
from .path_shortcuts import load_path_shortcuts


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str
    details: dict[str, Any] | None = None


SETTINGS_URIS = {
    "root": "ms-settings:",
    "bluetooth": "ms-settings:bluetooth",
    "wifi": "ms-settings:network-wifi",
    "network": "ms-settings:network",
    "sound": "ms-settings:sound",
    "display": "ms-settings:display",
    "apps": "ms-settings:appsfeatures",
    "storage": "ms-settings:storagesense",
    "windows_update": "ms-settings:windowsupdate",
    "notifications": "ms-settings:notifications",
    "privacy": "ms-settings:privacy",
    "power": "ms-settings:powersleep",
    "date_time": "ms-settings:dateandtime",
    "language": "ms-settings:regionlanguage",
    "mouse": "ms-settings:mousetouchpad",
    "personalization": "ms-settings:personalization",
    "background": "ms-settings:personalization-background",
    "themes": "ms-settings:themes",
}


KNOWN_APPS = {
    "chatgpt": ("packaged", "OpenAI.Codex_2p2nqsd0c76g0!App"),
    "gpt": ("packaged", "OpenAI.Codex_2p2nqsd0c76g0!App"),
    "计算器": ("command", "calc.exe"),
    "calculator": ("command", "calc.exe"),
    "记事本": ("command", "notepad.exe"),
    "notepad": ("command", "notepad.exe"),
    "文件资源管理器": ("command", "explorer.exe"),
    "资源管理器": ("command", "explorer.exe"),
    "文件管理器": ("command", "explorer.exe"),
    "设置": ("settings", "root"),
    "浏览器": ("uri", "https://www.google.com"),
    "edge": ("command", "msedge.exe"),
    "微信": ("discover", "weixin"),
    "wechat": ("discover", "weixin"),
    "weixin": ("discover", "weixin"),
    "cs2": ("uri", "steam://rungameid/730"),
    "counter-strike2": ("uri", "steam://rungameid/730"),
    "counter-strike 2": ("uri", "steam://rungameid/730"),
    "counter strike 2": ("uri", "steam://rungameid/730"),
}


DISCOVERED_EXECUTABLES = {
    "weixin": (
        r"Weixin\Weixin.exe",
        r"WeChat\WeChat.exe",
        r"Program Files\Tencent\Weixin\Weixin.exe",
        r"Program Files\Tencent\WeChat\WeChat.exe",
        r"Program Files (x86)\Tencent\Weixin\Weixin.exe",
        r"Program Files (x86)\Tencent\WeChat\WeChat.exe",
    )
}

SAFE_DESKTOP_EXTENSIONS = {
    ".lnk", ".url", ".exe", ".appref-ms",
    ".pdf", ".txt", ".md", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
    ".mp3", ".wav", ".m4a", ".mp4", ".mov", ".mkv",
    ".zip", ".7z", ".rar",
    ".csv", ".json", ".xml", ".html", ".htm", ".svg", ".epub",
    ".psd", ".ai", ".heic", ".flac", ".avi", ".wmv", ".webm",
}

# Automatic launches require a strong name match. Exact equality is deliberately
# not required so a missing letter or a small dictation error can still succeed.
DIRECT_MATCH_THRESHOLD = 0.82
DESKTOP_SCAN_MAX_DEPTH = 3
DESKTOP_SCAN_MAX_ITEMS = 1200


def _match_text(value: str) -> str:
    normalized = normalize_text(value).lower()
    normalized = re.sub(r"^\d{1,2}[\s._-]+", "", normalized)
    normalized = normalized.replace("快捷方式", "")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalized)


def _character_vector(value: str) -> Counter[str]:
    compact = _match_text(value)
    vector: Counter[str] = Counter()
    for character in compact:
        vector[f"u:{character}"] += 1.0
    for index in range(max(0, len(compact) - 1)):
        vector[f"b:{compact[index:index + 2]}"] += 1.4
    return vector


def _cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0.0) for key, value in left.items())
    left_size = math.sqrt(sum(value * value for value in left.values()))
    right_size = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_size * right_size) if left_size and right_size else 0.0


def candidate_name_score(requested: str, candidate: str) -> float:
    query = _match_text(requested)
    name = _match_text(candidate)
    if not query or not name:
        return 0.0
    if query == name:
        return 1.0
    if query in name or name in query:
        coverage = min(len(query), len(name)) / max(len(query), len(name))
        return 0.86 + 0.12 * coverage
    sequence = SequenceMatcher(None, query, name).ratio()
    vector = _cosine_similarity(_character_vector(query), _character_vector(name))
    prefix = 1.0 if query[0] == name[0] else 0.0
    return min(1.0, sequence * 0.56 + vector * 0.36 + prefix * 0.08)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value: str) -> "GUID":
        raw = uuid.UUID(value).bytes_le
        return cls.from_buffer_copy(raw)


def _com_method(pointer: ctypes.c_void_p, index: int, restype: Any, *argtypes: Any):
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(vtable[index])


class MasterVolume:
    CLSID_MM_DEVICE_ENUMERATOR = GUID.from_string("BCDE0395-E52F-467C-8E3D-C4579291692E")
    IID_MM_DEVICE_ENUMERATOR = GUID.from_string("A95664D2-9614-4F35-A746-DE8DB63617E6")
    IID_AUDIO_ENDPOINT_VOLUME = GUID.from_string("5CDF2C82-841E-4546-9722-0CF74078229A")

    def _with_endpoint(self, callback):
        ole32 = ctypes.windll.ole32
        initialized = ole32.CoInitializeEx(None, 0) >= 0
        enumerator = ctypes.c_void_p()
        device = ctypes.c_void_p()
        endpoint = ctypes.c_void_p()
        try:
            hr = ole32.CoCreateInstance(
                ctypes.byref(self.CLSID_MM_DEVICE_ENUMERATOR),
                None,
                23,
                ctypes.byref(self.IID_MM_DEVICE_ENUMERATOR),
                ctypes.byref(enumerator),
            )
            if hr < 0:
                raise OSError(f"CoCreateInstance failed: 0x{hr & 0xFFFFFFFF:08X}")
            get_default = _com_method(
                enumerator,
                4,
                ctypes.c_long,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_void_p),
            )
            hr = get_default(enumerator, 0, 1, ctypes.byref(device))
            if hr < 0:
                raise OSError(f"GetDefaultAudioEndpoint failed: 0x{hr & 0xFFFFFFFF:08X}")
            activate = _com_method(
                device,
                3,
                ctypes.c_long,
                ctypes.POINTER(GUID),
                wintypes.DWORD,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            )
            hr = activate(
                device,
                ctypes.byref(self.IID_AUDIO_ENDPOINT_VOLUME),
                23,
                None,
                ctypes.byref(endpoint),
            )
            if hr < 0:
                raise OSError(f"Activate IAudioEndpointVolume failed: 0x{hr & 0xFFFFFFFF:08X}")
            return callback(endpoint)
        finally:
            for pointer in (endpoint, device, enumerator):
                if pointer.value:
                    _com_method(pointer, 2, wintypes.ULONG)(pointer)
            if initialized:
                ole32.CoUninitialize()

    def get_percent(self) -> int:
        def read(endpoint: ctypes.c_void_p) -> int:
            value = ctypes.c_float()
            hr = _com_method(endpoint, 9, ctypes.c_long, ctypes.POINTER(ctypes.c_float))(
                endpoint, ctypes.byref(value)
            )
            if hr < 0:
                raise OSError("GetMasterVolumeLevelScalar failed")
            return round(value.value * 100)

        return self._with_endpoint(read)

    def set_percent(self, percent: int) -> int:
        percent = max(0, min(100, int(percent)))

        def write(endpoint: ctypes.c_void_p) -> int:
            hr = _com_method(
                endpoint,
                7,
                ctypes.c_long,
                ctypes.c_float,
                ctypes.c_void_p,
            )(endpoint, ctypes.c_float(percent / 100), None)
            if hr < 0:
                raise OSError("SetMasterVolumeLevelScalar failed")
            return percent

        return self._with_endpoint(write)

    def set_mute(self, muted: bool) -> None:
        def write(endpoint: ctypes.c_void_p) -> None:
            hr = _com_method(
                endpoint,
                14,
                ctypes.c_long,
                wintypes.BOOL,
                ctypes.c_void_p,
            )(endpoint, bool(muted), None)
            if hr < 0:
                raise OSError("SetMute failed")

        self._with_endpoint(write)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", INPUTUNION)]


def type_unicode(text: str) -> None:
    units = text.encode("utf-16-le")
    values = [int.from_bytes(units[index : index + 2], "little") for index in range(0, len(units), 2)]
    inputs: list[INPUT] = []
    for unit in values:
        inputs.append(INPUT(type=1, ki=KEYBDINPUT(0, unit, 0x0004, 0, 0)))
        inputs.append(INPUT(type=1, ki=KEYBDINPUT(0, unit, 0x0004 | 0x0002, 0, 0)))
    if inputs:
        array = (INPUT * len(inputs))(*inputs)
        sent = ctypes.windll.user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            raise ctypes.WinError()


class WindowsController:
    def __init__(self) -> None:
        self.volume = MasterVolume()
        self._app_catalog: list[dict[str, str]] | None = None
        self._catalog_lock = threading.Lock()
        self.handoff_state = DailyHandoffState()
        self.chat_handoff = ChatHandoffStore()
        self.marvis_handoff = ChatHandoffStore(default_marvis_handoff_path())
        self.time_tasks = TimeTaskStore()

    def execute(self, call: SkillCall) -> ActionResult:
        if call.skill_id == "open_app":
            return self.open_app(str(call.arguments["app"]))
        if call.skill_id == "set_volume":
            return self.control_volume(call.arguments)
        if call.skill_id == "set_brightness":
            return self.control_brightness(call.arguments)
        if call.skill_id == "open_settings":
            return self.open_settings(
                str(call.arguments.get("topic", "search")),
                str(call.arguments.get("query", "设置")),
            )
        if call.skill_id == "get_weather":
            return self.get_weather(
                str(call.arguments.get("location", "")),
                str(call.arguments.get("day", "today")),
            )
        if call.skill_id == "open_website":
            return self.open_website(
                str(call.arguments.get("target", "")),
                str(call.arguments.get("mode", "site")),
            )
        if call.skill_id == "get_world_time":
            message = world_time(str(call.arguments.get("location", "本地")))
            return (
                ActionResult(True, message)
                if message
                else ActionResult(False, "暂时不认识这个地点的时区，请换一个城市名称。")
            )
        if call.skill_id == "set_timer":
            seconds = int(call.arguments["seconds"])
            label = str(call.arguments.get("label", "倒计时结束"))
            due = datetime.now().astimezone() + timedelta(seconds=seconds)
            task = self.time_tasks.add("timer", due, label)
            minutes, remainder = divmod(seconds, 60)
            duration = f"{minutes}分钟" if remainder == 0 else f"{minutes}分{remainder}秒" if minutes else f"{remainder}秒"
            return ActionResult(True, f"已设置{duration}倒计时：{label}。", {"task_id": task["id"]})
        if call.skill_id in {"set_alarm", "set_reminder"}:
            due = resolve_clock_due(
                int(call.arguments["hour"]),
                int(call.arguments["minute"]),
                int(call.arguments.get("day_offset", 0)),
            )
            label = str(call.arguments.get("label", "提醒事项"))
            if call.skill_id == "set_reminder" and bool(call.arguments.get("calendar")):
                try:
                    path = create_calendar_draft(due, label)
                except OSError as exc:
                    return ActionResult(False, f"无法打开日历事件：{exc}")
                return ActionResult(
                    True,
                    f"已创建{format_due(due)}的日历事件“{label}”，请在日历中确认添加。",
                    {"calendar_draft": str(path)},
                )
            kind = "alarm" if call.skill_id == "set_alarm" else "reminder"
            task = self.time_tasks.add(kind, due, label)
            noun = "闹钟" if kind == "alarm" else "提醒"
            return ActionResult(
                True,
                f"已设置{format_due(due)}的{noun}：{label}。",
                {"task_id": task["id"], "due_at": due.timestamp()},
            )
        return ActionResult(False, f"尚未安装 Skill：{call.skill_id}")

    @staticmethod
    def _weather_description(code: str, fallback: str) -> str:
        if code == "113":
            return "晴"
        if code == "116":
            return "晴间多云"
        if code == "119":
            return "多云"
        if code == "122":
            return "阴"
        numeric = int(code) if code.isdigit() else 0
        if numeric in {143, 248, 260}:
            return "有雾"
        if numeric in {200, 386, 389, 392, 395}:
            return "有雷雨"
        if numeric in {227, 230, 320, 323, 326, 329, 332, 335, 338, 368, 371}:
            return "有雪"
        if numeric in {179, 182, 185, 281, 284, 311, 314, 317, 350, 362, 365, 374, 377}:
            return "有雨夹雪或冻雨"
        if numeric in {176, 263, 266, 293, 296, 299, 302, 305, 308, 353, 356, 359}:
            return "有雨"
        return fallback.strip() or "天气状况未知"

    @staticmethod
    def _weather_value(container: dict[str, Any], key: str, default: str = "") -> str:
        value = container.get(key, default)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return str(value[0].get("value", default))
        return str(value)

    def get_weather(self, location: str = "", day: str = "today") -> ActionResult:
        """Fetch current or next-day weather without an API key."""
        target = urllib.parse.quote(location.strip())
        url = f"https://wttr.in/{target}?format=j1&lang=zh"
        request = urllib.request.Request(url, headers={"User-Agent": "KeyPilot/0.8"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            forecasts = payload.get("weather", [])
            index = 1 if day == "tomorrow" else 0
            if not isinstance(forecasts, list) or len(forecasts) <= index:
                raise ValueError("weather forecast missing")
            forecast = forecasts[index]
            if not isinstance(forecast, dict):
                raise ValueError("invalid weather forecast")
            areas = payload.get("nearest_area", [])
            area = areas[0] if isinstance(areas, list) and areas and isinstance(areas[0], dict) else {}
            resolved = self._weather_value(area, "areaName", location or "当前位置")
            low = self._weather_value(forecast, "mintempC", "?")
            high = self._weather_value(forecast, "maxtempC", "?")
            if day == "tomorrow":
                hourly = forecast.get("hourly", [])
                midday = hourly[len(hourly) // 2] if isinstance(hourly, list) and hourly else {}
                if not isinstance(midday, dict):
                    midday = {}
                fallback = self._weather_value(midday, "weatherDesc")
                description = self._weather_description(
                    self._weather_value(midday, "weatherCode"), fallback
                )
                message = f"{resolved}明天{description}，最低{low}度，最高{high}度。"
            else:
                conditions = payload.get("current_condition", [])
                current = (
                    conditions[0]
                    if isinstance(conditions, list) and conditions and isinstance(conditions[0], dict)
                    else {}
                )
                fallback = self._weather_value(current, "weatherDesc")
                description = self._weather_description(
                    self._weather_value(current, "weatherCode"), fallback
                )
                temp = self._weather_value(current, "temp_C", "?")
                feels = self._weather_value(current, "FeelsLikeC", temp)
                humidity = self._weather_value(current, "humidity", "?")
                prefix = "根据网络位置，" if not location.strip() else ""
                message = (
                    f"{prefix}{resolved}现在{description}，{temp}度，体感{feels}度；"
                    f"今天最低{low}度，最高{high}度，湿度百分之{humidity}。"
                )
            return ActionResult(
                True,
                message,
                {"provider": "wttr.in", "location": resolved, "day": day},
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError, urllib.error.URLError) as exc:
            return ActionResult(
                False,
                "天气服务暂时不可用。你可以稍后再试，或指定城市名称。",
                {"provider": "wttr.in", "error": str(exc)},
            )

    def _launch_uri(self, uri: str) -> None:
        subprocess.Popen(
            ["explorer.exe", uri],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    @staticmethod
    def _launch_web_url(url: str) -> None:
        shell32 = ctypes.windll.shell32
        shell32.ShellExecuteW.argtypes = [
            wintypes.HWND,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.c_int,
        ]
        shell32.ShellExecuteW.restype = ctypes.c_void_p
        result = shell32.ShellExecuteW(None, "open", url, None, None, 1)
        if not result or int(result) <= 32:
            raise OSError(f"ShellExecute failed: {int(result or 0)}")

    @staticmethod
    def _private_browser_candidates() -> list[tuple[str, str]]:
        """Return the default browser first, then private-capable fallbacks."""
        default_id = ""
        try:
            key_path = (
                r"Software\Microsoft\Windows\Shell\Associations"
                r"\UrlAssociations\https\UserChoice"
            )
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                default_id = str(winreg.QueryValueEx(key, "ProgId")[0]).lower()
        except OSError:
            pass

        local = Path(os.environ.get("LOCALAPPDATA", ""))
        program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        browsers = {
            "edge": (
                "--inprivate",
                [
                    program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                    program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                ],
            ),
            "chrome": (
                "--incognito",
                [
                    local / "Google" / "Chrome" / "Application" / "chrome.exe",
                    program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
                    program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
                ],
            ),
            "firefox": (
                "-private-window",
                [
                    program_files / "Mozilla Firefox" / "firefox.exe",
                    program_files_x86 / "Mozilla Firefox" / "firefox.exe",
                ],
            ),
        }
        if "chrome" in default_id:
            order = ("chrome", "edge", "firefox")
        elif "firefox" in default_id:
            order = ("firefox", "edge", "chrome")
        else:
            order = ("edge", "chrome", "firefox")
        candidates: list[tuple[str, str]] = []
        for browser in order:
            flag, paths = browsers[browser]
            for executable in paths:
                if executable.is_file():
                    candidates.append((str(executable), flag))
                    break
        return candidates

    def _launch_private_web_url(self, url: str) -> str:
        candidates = self._private_browser_candidates()
        if not candidates:
            raise OSError("没有找到支持无痕模式的 Edge、Chrome 或 Firefox。")
        executable, flag = candidates[0]
        arguments = [executable, flag]
        if flag in {"--inprivate", "--incognito"}:
            arguments.append("--new-window")
        arguments.append(url)
        subprocess.Popen(
            arguments,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return Path(executable).stem

    def _launch_packaged(self, app_id: str) -> None:
        self._launch_uri(f"shell:AppsFolder\\{app_id}")

    def open_website(self, target: str, mode: str = "site") -> ActionResult:
        target = target.strip()
        if not target:
            return ActionResult(False, "没有提供要打开的网站或搜索内容。")
        if mode == "site":
            url = COMMON_WEBSITES.get(target.lower())
            if not url:
                return ActionResult(False, f"常用网站列表中没有“{target}”。")
            message = f"已用浏览器打开{target}。"
        elif mode == "search":
            url = (
                "https://www.google.com/search?udm=50&hl=zh-CN&q="
                + urllib.parse.quote_plus(target)
            )
            message = f"已在无痕浏览器的 Google AI 模式中搜索“{target}”。"
        elif mode == "url":
            candidate = normalize_safe_url(target)
            if not candidate:
                return ActionResult(False, "网址无效；只允许打开 http 或 https 地址。")
            parsed = urllib.parse.urlsplit(candidate)
            url = candidate
            message = f"已用浏览器打开{parsed.hostname}。"
        else:
            return ActionResult(False, "无法识别网页打开方式。")
        try:
            if mode == "search":
                browser = self._launch_private_web_url(url)
            else:
                browser = "default"
                self._launch_web_url(url)
        except OSError as exc:
            return ActionResult(False, f"浏览器启动失败：{exc}")
        return ActionResult(
            True,
            message,
            {"url": url, "mode": mode, "private": mode == "search", "browser": browser},
        )

    @staticmethod
    def _find_discovered_executable(app_key: str) -> Path | None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        user_candidates: list[Path] = []
        if local_app_data:
            user_candidates.extend(
                [
                    Path(local_app_data) / "Tencent" / "Weixin" / "Weixin.exe",
                    Path(local_app_data) / "Tencent" / "WeChat" / "WeChat.exe",
                ]
            )
        for candidate in user_candidates:
            if candidate.is_file():
                return candidate
        relatives = DISCOVERED_EXECUTABLES.get(app_key, ())
        drives_mask = ctypes.windll.kernel32.GetLogicalDrives()
        for index in range(26):
            if not drives_mask & (1 << index):
                continue
            root = Path(f"{chr(ord('A') + index)}:\\")
            for relative in relatives:
                candidate = root / relative
                if candidate.is_file():
                    return candidate
        return None

    def _load_app_catalog(self) -> list[dict[str, str]]:
        with self._catalog_lock:
            if self._app_catalog is not None:
                return self._app_catalog
            windows_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
            bundled_powershell = (
                windows_dir / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
            )
            powershell = (
                str(bundled_powershell)
                if bundled_powershell.exists()
                else shutil.which("powershell.exe") or shutil.which("pwsh.exe")
            )
            if not powershell:
                self._app_catalog = []
                return self._app_catalog
            command = (
                "$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new();"
                "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
            )
            try:
                result = subprocess.run(
                    [powershell, "-NoProfile", "-Command", command],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=12,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.SubprocessError):
                self._app_catalog = []
                return self._app_catalog
            try:
                payload = json.loads(result.stdout.strip() or "[]")
            except json.JSONDecodeError:
                payload = []
            if isinstance(payload, dict):
                payload = [payload]
            self._app_catalog = [
                {"name": str(item.get("Name", "")), "app_id": str(item.get("AppID", ""))}
                for item in payload
                if isinstance(item, dict) and item.get("Name") and item.get("AppID")
            ]
            return self._app_catalog

    @staticmethod
    def _desktop_directories() -> list[Path]:
        candidates: list[Path] = []
        user_profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
        one_drive = os.environ.get("OneDrive")
        for path in (
            Path(one_drive) / "Desktop" if one_drive else None,
            user_profile / "OneDrive" / "Desktop",
            user_profile / "Desktop",
        ):
            if path and path.is_dir() and path not in candidates:
                candidates.append(path)
        return candidates

    def _load_desktop_catalog(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for desktop in self._desktop_directories():
            pending: list[tuple[Path, int]] = [(desktop, 0)]
            while pending and len(items) < DESKTOP_SCAN_MAX_ITEMS:
                directory, depth = pending.pop(0)
                try:
                    entries = sorted(directory.iterdir(), key=lambda path: path.name.lower())
                except OSError:
                    continue
                for entry in entries:
                    if len(items) >= DESKTOP_SCAN_MAX_ITEMS:
                        break
                    if entry.name.lower() == "desktop.ini" or entry.name.startswith("."):
                        continue
                    try:
                        is_directory = entry.is_dir()
                    except OSError:
                        continue
                    if is_directory:
                        if depth < DESKTOP_SCAN_MAX_DEPTH and not entry.is_symlink():
                            pending.append((entry, depth + 1))
                    elif entry.suffix.lower() not in SAFE_DESKTOP_EXTENSIONS:
                        continue
                    name = entry.name if is_directory else entry.stem
                    key = f"{name.lower()}|{entry}"
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(
                        {
                            "name": name,
                            "path": str(entry),
                            "kind": "folder" if is_directory else "desktop",
                        }
                    )
        return items

    @staticmethod
    def _launch_desktop_item(path: str) -> None:
        shell32 = ctypes.windll.shell32
        shell32.ShellExecuteW.argtypes = [
            wintypes.HWND,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.c_int,
        ]
        shell32.ShellExecuteW.restype = ctypes.c_void_p
        result = shell32.ShellExecuteW(None, "open", path, None, None, 1)
        if not result or int(result) <= 32:
            raise OSError(f"ShellExecute failed: {int(result or 0)}")

    def open_app(self, requested: str) -> ActionResult:
        normalized = normalize_text(requested).replace(" ", "")
        for keyword, path in sorted(
            load_path_shortcuts().items(), key=lambda item: len(item[0]), reverse=True
        ):
            if normalized == normalize_text(keyword).replace(" ", ""):
                if not Path(path).exists():
                    return ActionResult(
                        False,
                        f"关键词“{keyword}”指向的目标已经不存在，请在关键词管理中更新路径。",
                    )
                try:
                    self._launch_desktop_item(path)
                except OSError as exc:
                    return ActionResult(False, f"找到了“{keyword}”，但打开失败：{exc}")
                return ActionResult(
                    True,
                    f"已打开{keyword}。",
                    {"matched_name": keyword, "source": "自定义路径"},
                )
        for alias, (kind, target) in KNOWN_APPS.items():
            if normalized == normalize_text(alias).replace(" ", ""):
                try:
                    if kind == "packaged":
                        self._launch_packaged(target)
                    elif kind == "settings":
                        return self.open_settings(target, requested)
                    elif kind == "uri":
                        self._launch_web_url(target)
                    elif kind == "discover":
                        executable = self._find_discovered_executable(target)
                        if executable is None:
                            return ActionResult(
                                False,
                                f"没有找到“{requested}”的安装文件。请检查安装位置。",
                            )
                        subprocess.Popen(
                            [str(executable)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                    else:
                        subprocess.Popen(
                            [target],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                except OSError as exc:
                    return ActionResult(False, f"找到了“{requested}”，但启动失败：{exc}")
                return ActionResult(True, f"已打开{requested}。")

        best: dict[str, str] | None = None
        best_score = 0.0
        candidates: list[dict[str, str]] = []
        candidates.extend(
            {"name": keyword, "path": path, "kind": "custom"}
            for keyword, path in load_path_shortcuts().items()
        )
        candidates.extend(self._load_desktop_catalog())
        candidates.extend(
            {"name": item["name"], "app_id": item["app_id"], "kind": "start_app"}
            for item in self._load_app_catalog()
        )
        ranked: list[tuple[float, dict[str, str]]] = []
        for item in candidates:
            score = candidate_name_score(requested, item["name"])
            ranked.append((score, item))
            if score > best_score:
                best, best_score = item, score
        if best and best_score >= DIRECT_MATCH_THRESHOLD:
            try:
                if best.get("kind") in {"custom", "desktop", "folder"}:
                    if best.get("kind") == "custom" and not Path(best["path"]).exists():
                        return ActionResult(False, f"“{best['name']}”指向的目标已经不存在。")
                    self._launch_desktop_item(best["path"])
                else:
                    self._launch_packaged(best["app_id"])
            except OSError as exc:
                return ActionResult(False, f"找到了“{best['name']}”，但启动失败：{exc}")
            return ActionResult(
                True,
                f"已打开{best['name']}。",
                {
                    "matched_name": best["name"],
                    "score": round(best_score, 3),
                    "source": (
                        "自定义路径" if best.get("kind") == "custom"
                        else "桌面" if best.get("kind") in {"desktop", "folder"}
                        else "Windows 应用"
                    ),
                },
            )
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        desktop_names = [
            item["name"]
            for item in candidates
            if item.get("kind") in {"custom", "desktop", "folder"}
        ]
        likely_names = desktop_names + [item["name"] for _score, item in ranked[:30]]
        likely_names = list(dict.fromkeys(likely_names))[:140]
        return ActionResult(
            False,
            f"没有找到足够接近的桌面文件或本地应用“{requested}”。",
            {"offer_web_search": requested, "candidate_names": likely_names},
        )

    def send_to_chat(self, utterance: str) -> ActionResult:
        """Queue the request for the dedicated, retryable ChatGPT bridge app."""
        copy_text_to_clipboard(utterance)
        first_today = self.handoff_state.claim_chatgpt_day()
        request = self.chat_handoff.enqueue(utterance, first_today)
        project_dir = Path(__file__).resolve().parent.parent
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "keypilot.chat_bridge",
                "--request-id",
                str(request["id"]),
            ],
            cwd=project_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return ActionResult(
            True,
            "已交给 GPT 转接器；它会等待输入框就绪后粘贴并发送。",
            {
                "clipboard": True,
                "new_daily_chat": first_today,
                "bridge_request_id": request["id"],
            },
        )

    def send_to_marvis(self, utterance: str) -> ActionResult:
        """Queue a question for the installed Marvis desktop client."""
        copy_text_to_clipboard(utterance)
        request = self.marvis_handoff.enqueue(utterance, False)
        project_dir = Path(__file__).resolve().parent.parent
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "keypilot.marvis_bridge",
                "--request-id",
                str(request["id"]),
            ],
            cwd=project_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return ActionResult(
            True,
            "已交给 Marvis 转接器；它会启动 Marvis，并自动粘贴发送。",
            {"clipboard": True, "bridge_request_id": request["id"]},
        )

    def control_volume(self, arguments: dict[str, Any]) -> ActionResult:
        operation = str(arguments.get("operation", "get"))
        if operation == "get":
            percent = self.volume.get_percent()
            return ActionResult(True, f"当前音量是百分之{percent}。", {"percent": percent})
        if operation == "set":
            percent = self.volume.set_percent(int(arguments["percent"]))
            return ActionResult(True, f"音量已调到百分之{percent}。", {"percent": percent})
        if operation == "mute":
            self.volume.set_mute(True)
            return ActionResult(True, "已静音。")
        if operation == "unmute":
            self.volume.set_mute(False)
            return ActionResult(True, "已取消静音。")
        if operation == "up":
            send_hotkey(["volumeup"])
            return ActionResult(True, "已调高音量。")
        if operation == "down":
            send_hotkey(["volumedown"])
            return ActionResult(True, "已调低音量。")
        return ActionResult(False, "无法识别音量操作。")

    def _read_brightness(self) -> int:
        command = (
            "$v=(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness "
            "-ErrorAction Stop | Select-Object -First 1 -ExpandProperty CurrentBrightness);"
            "[Console]::Write($v)"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        match = re.search(r"\d+", result.stdout)
        if result.returncode != 0 or not match:
            raise RuntimeError("无法读取内置屏幕亮度")
        return max(0, min(100, int(match.group())))

    def _write_brightness(self, percent: int) -> int:
        percent = max(0, min(100, int(percent)))
        command = (
            "$m=Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods "
            "-ErrorAction Stop | Select-Object -First 1;"
            f"Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{{Timeout=1;Brightness={percent}}} "
            "-ErrorAction Stop | Out-Null"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise RuntimeError("无法控制此显示器的硬件亮度")
        return percent

    def control_brightness(self, arguments: dict[str, Any]) -> ActionResult:
        operation = str(arguments.get("operation", "get"))
        try:
            current = self._read_brightness()
            if operation == "get":
                return ActionResult(True, f"当前屏幕亮度是百分之{current}。", {"percent": current})
            if operation == "set":
                target = int(arguments["percent"])
            elif operation == "up":
                target = current + int(arguments.get("step", 10))
            elif operation == "down":
                target = current - int(arguments.get("step", 10))
            else:
                return ActionResult(False, "无法识别亮度操作。")
            target = self._write_brightness(target)
            return ActionResult(True, f"屏幕亮度已调到百分之{target}。", {"percent": target})
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
            return ActionResult(
                False,
                "这块显示器不支持 Windows 内置亮度接口，已为你打开显示设置。",
                {"error": str(exc), "fallback": "display_settings"},
            )

    def open_settings(self, topic: str, query: str) -> ActionResult:
        if topic in SETTINGS_URIS and topic != "search":
            self._launch_uri(SETTINGS_URIS[topic])
            return ActionResult(True, f"已打开{query}设置。")
        self._launch_uri(SETTINGS_URIS["root"])
        if self._fill_settings_search(query):
            return ActionResult(True, f"已在设置的查找框中输入“{query}”。")
        copy_text_to_clipboard(query)
        return ActionResult(
            False,
            f"已打开设置，但没有定位到查找框；“{query}”已复制到剪贴板。",
            {"clipboard": True, "query": query},
        )

    @staticmethod
    def _click_settings_search(hwnd: int) -> None:
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError()
        width = max(1, rect.right - rect.left)
        x = rect.left + min(230, max(135, int(width * 0.16)))
        y = rect.top + 72
        user32.SetCursorPos(x, y)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)

    @staticmethod
    def _settings_windows() -> list[int]:
        windows = _top_level_windows(_process_ids("SystemSettings.exe"))
        user32 = ctypes.windll.user32
        enum_proc_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def visit(hwnd: int, _lparam: int) -> bool:
            if hwnd in windows or not (user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd)):
                return True
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name, len(class_name))
            length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, len(title))
            if WindowsController._is_settings_frame_window(
                class_name.value, title.value
            ):
                windows.append(hwnd)
            return True

        callback = enum_proc_type(visit)
        user32.EnumWindows(callback, 0)
        return windows

    @staticmethod
    def _is_settings_frame_window(class_name: str, title: str) -> bool:
        return (
            class_name == "ApplicationFrameWindow"
            and title.strip().lower() in {"设置", "settings"}
        )

    def _fill_settings_search(self, query: str) -> bool:
        deadline = time.monotonic() + 10.0
        windows: list[int] = []
        while time.monotonic() < deadline:
            windows = self._settings_windows()
            if windows:
                break
            time.sleep(0.2)
        if not windows:
            return False

        hwnd = windows[0]
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.45)
        original_clipboard = read_text_from_clipboard()

        for use_mouse in (False, True):
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            if use_mouse:
                try:
                    self._click_settings_search(hwnd)
                except OSError:
                    continue
            else:
                send_hotkey(["ctrl", "f"])
            time.sleep(0.22)
            copy_text_to_clipboard(query)
            send_hotkey(["ctrl", "a"])
            send_hotkey(["ctrl", "v"])
            time.sleep(0.25)
            send_hotkey(["ctrl", "a"])
            send_hotkey(["ctrl", "c"])
            time.sleep(0.18)
            verified = (read_text_from_clipboard() or "").strip() == query.strip()
            send_hotkey(["right"])
            if verified:
                if original_clipboard is not None:
                    copy_text_to_clipboard(original_clipboard)
                return True
        if original_clipboard is not None:
            copy_text_to_clipboard(original_clipboard)
        return False


__all__ = ["ActionResult", "MasterVolume", "WindowsController", "type_unicode"]
