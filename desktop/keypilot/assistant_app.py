from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from keypilot.actions import execute_action, send_hotkey
    from keypilot.assistant_router import (
        LocalCommandRouter,
        SkillRegistry,
        classify_fallback_intent,
        normalize_text,
    )
    from keypilot.codex_bridge import CodexBridge
    from keypilot.cloud_bridge import CloudModelBridge, CloudModelError
    from keypilot.browser_reader import BrowserReader, extract_google_ai_answer, google_page_question
    from keypilot.conversation_memory import ConversationMemory
    from keypilot.ollama_bridge import OllamaAnswer
    from keypilot.local_model import LocalModelBridge, LocalModelConfig, LocalModelError
    from keypilot.data_paths import user_data_dir
    from keypilot.secure_store import delete_secret, load_secret, save_secret
    from keypilot.speech import DEFAULT_VOICE, SpeechEngine, available_voice_profiles
    from keypilot.custom_voice import available_voice_packs
    from keypilot.voice_preferences import (
        ZIPVOICE_QUALITY_OPTIONS,
        restore_voice_selection,
        selected_voice_path,
        set_zipvoice_quality,
        voice_selection_values,
        zipvoice_quality_label,
        zipvoice_quality_options,
    )
    from keypilot.user_settings import assistant_settings_path, save_settings
    from keypilot.reply_length import REPLY_LIMITS, limit_reply
    from keypilot.speech_rate import MIN_RATE, MAX_RATE, clamp_rate
    from keypilot.time_ui import TimeAssistantWindow
    from keypilot.website_shortcuts import load_website_shortcuts, set_website_shortcut
    from keypilot.path_shortcuts import load_path_shortcuts, set_path_shortcut
    from keypilot.windows_control import ActionResult, WindowsController
else:
    from .actions import execute_action, send_hotkey
    from .assistant_router import LocalCommandRouter, SkillRegistry, classify_fallback_intent, normalize_text
    from .codex_bridge import CodexBridge
    from .cloud_bridge import CloudModelBridge, CloudModelError
    from .browser_reader import BrowserReader, extract_google_ai_answer, google_page_question
    from .conversation_memory import ConversationMemory
    from .ollama_bridge import OllamaAnswer
    from .local_model import LocalModelBridge, LocalModelConfig, LocalModelError
    from .data_paths import user_data_dir
    from .secure_store import delete_secret, load_secret, save_secret
    from .speech import DEFAULT_VOICE, SpeechEngine, available_voice_profiles
    from .custom_voice import available_voice_packs
    from .voice_preferences import (
        ZIPVOICE_QUALITY_OPTIONS,
        restore_voice_selection,
        selected_voice_path,
        set_zipvoice_quality,
        voice_selection_values,
        zipvoice_quality_label,
        zipvoice_quality_options,
    )
    from .user_settings import assistant_settings_path, save_settings
    from .reply_length import REPLY_LIMITS, limit_reply
    from .speech_rate import MIN_RATE, MAX_RATE, clamp_rate
    from .time_ui import TimeAssistantWindow
    from .website_shortcuts import load_website_shortcuts, set_website_shortcut
    from .path_shortcuts import load_path_shortcuts, set_path_shortcut
    from .windows_control import ActionResult, WindowsController

try:
    if __package__ in (None, ""):
        from keypilot.edition import (
            DICTATION_NAME as EDITION_DICTATION_NAME,
            INSTANCE_NAME as EDITION_INSTANCE_NAME,
            WINDOW_TITLE as EDITION_WINDOW_TITLE,
            identify_taskbar,
        )
    else:
        from .edition import (
            DICTATION_NAME as EDITION_DICTATION_NAME,
            INSTANCE_NAME as EDITION_INSTANCE_NAME,
            WINDOW_TITLE as EDITION_WINDOW_TITLE,
            identify_taskbar,
        )
except (ImportError, FileNotFoundError, ValueError):
    EDITION_WINDOW_TITLE = "KeyPilot 本地助手"
    EDITION_INSTANCE_NAME = r"Local\KeyPilot.LocalAssistant"
    EDITION_DICTATION_NAME = r"Local\KeyPilot.ToggleDictation"

    def identify_taskbar() -> None:
        pass


BG = "#10131a"
PANEL = "#191e28"
PANEL_2 = "#222936"
TEXT = "#f2f5f9"
MUTED = "#9ca8b8"
ACCENT = "#57b8ff"
SUCCESS = "#55d187"
ERROR = "#ff6b6b"
WINDOW_TITLE = EDITION_WINDOW_TITLE
DICTATION_EVENT_NAME = EDITION_DICTATION_NAME
WAIT_OBJECT_0 = 0
ERROR_ALREADY_EXISTS = 183
CLOUD_MODEL_PRESETS = (
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-v4-flash-vision-exp",
)
COMPLEX_AGENT_CHOICES = ("Codex", "Marvis", "关闭")


def acquire_assistant_instance() -> int | None:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    handle = kernel32.CreateMutexW(None, False, EDITION_INSTANCE_NAME)
    if not handle:
        raise ctypes.WinError()
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return int(handle)


class AssistantApp:
    def __init__(self, root: tk.Tk, project_dir: Path, *, smoke_test: bool = False) -> None:
        self.root = root
        self.project_dir = project_dir
        self.registry = SkillRegistry(project_dir / "skills")
        self.router = LocalCommandRouter(self.registry)
        self.controller = WindowsController()
        self.codex = CodexBridge(project_dir)
        self.cloud = CloudModelBridge()
        self.browser_reader = BrowserReader()
        self.memory = ConversationMemory()
        self.settings_path = assistant_settings_path(project_dir)
        self.settings = self._load_settings()
        try:
            self.local_model_config = LocalModelConfig.from_settings(self.settings)
        except (ValueError, TypeError):
            self.local_model_config = LocalModelConfig()
        self.ollama = LocalModelBridge(self.registry, self.local_model_config)
        self.local_model_window: tk.Toplevel | None = None
        local_data = user_data_dir()
        self.cloud_secret_path = local_data / "cloud-api-key.dat"
        self.cloud_api_key = load_secret(self.cloud_secret_path)
        self.portal_path = local_data / "portal.json"
        self.portal = self._load_portal()
        self.portal_children = self.portal.get("children", {})
        self.voice_profiles = available_voice_profiles()
        self.busy = False
        self.voice_armed = False
        self.voice_timer: str | None = None
        self.voice_last_value = ""
        self.voice_last_change = 0.0
        self.dictation_started_at = 0.0
        self.ollama_voice_pending = False
        self.ollama_voice_value = ""
        self._programmatic_input = False
        self.pending_cloud_question: str | None = None
        self.pending_local_answer = ""
        self.pending_web_search: str | None = None
        self.dictation_event_handle: int | None = None
        self.dictation_event_timer: str | None = None
        self.time_window: TimeAssistantWindow | None = None
        self.preferences_window: tk.Toplevel | None = None

        self.command_var = tk.StringVar()
        self.speak_var = tk.BooleanVar(value=bool(self.settings.get("speak", True)))
        self.reply_length = str(self.settings.get("reply_length", "中"))
        if self.reply_length not in REPLY_LIMITS:
            self.reply_length = "中"
        self.reply_length_var = tk.StringVar(value=self.reply_length)
        self.speech_rate_var = tk.DoubleVar(value=clamp_rate(self.settings.get("speech_rate", 1.0)))
        self.speech_rate_label_var = tk.StringVar(value=f"{self.speech_rate_var.get():.2f}×")
        self.ollama.reply_length = self.cloud.reply_length = self.reply_length
        self.codex_var = tk.BooleanVar(value=bool(self.settings.get("codex", True)))
        saved_agent = str(
            self.settings.get(
                "complex_agent",
                "Codex" if self.codex_var.get() else "关闭",
            )
        )
        if saved_agent not in COMPLEX_AGENT_CHOICES:
            saved_agent = "Codex"
        self.complex_agent_var = tk.StringVar(value=saved_agent)
        self.ollama_var = tk.BooleanVar(value=bool(self.settings.get("ollama", True)))
        self.web_mode_var = tk.IntVar(value=self._web_mode_from_settings(self.settings))
        self.web_mode_label_var = tk.StringVar()
        self.cloud_base_url_var = tk.StringVar(
            value=str(self.settings.get("cloud_base_url", "https://api.openai.com/v1"))
        )
        self.cloud_model_var = tk.StringVar(value=str(self.settings.get("cloud_model", "")))
        self.auto_voice_var = tk.BooleanVar(value=bool(self.settings.get("auto_low_risk", True)))
        saved_voice = str(self.settings.get("voice", DEFAULT_VOICE))
        if saved_voice not in self.voice_profiles:
            saved_voice = DEFAULT_VOICE
        self.voice_choice_var = tk.StringVar(value=saved_voice)
        self.voice_packs = available_voice_packs()
        saved_pack, self.custom_voice_id = restore_voice_selection(self.settings, self.voice_packs)
        self.custom_voice_var = tk.StringVar(value=saved_pack)
        self.voice_quality_var = tk.StringVar(value="不适用")
        self.voice_quality_help_var = tk.StringVar()
        saved_mode = self.settings.get("voice_mode", "performance")
        self.voice_mode_var = tk.StringVar(value=saved_mode if saved_mode in ("performance", "quality") else "performance")
        self.voice_status_var = tk.StringVar()
        self.voice_status_timer = None
        self.portal_default_var = tk.StringVar(value=self._portal_default_name())
        self.speech = SpeechEngine(project_dir, enabled=not smoke_test, voice_name=saved_voice)
        self.speech.set_rate(self.speech_rate_var.get())
        self.speech.on_voice_error = lambda message: self.root.after(
            0, lambda: self._set_status("自定义声音暂不可用", "临时使用普通声音：" + message[:160], ERROR)
        )
        self.speech.set_custom_voice(selected_voice_path(saved_pack, self.custom_voice_id, self.voice_packs))
        self.speech.set_preload_enabled(self.speak_var.get())
        self.speech.set_schedule_mode(self.voice_mode_var.get())
        self.status_var = tk.StringVar(value="就绪")
        self.status_detail_var = tk.StringVar(value="输入一句命令，或使用 Windows 中文听写。")
        self._update_web_mode_label()

        self._configure_window()
        self._build_ui()
        self.window_handle = int(self.root.winfo_id())
        self.command_var.trace_add("write", self._on_command_changed)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._create_dictation_event()
        self._refresh_voice_status()
        if not smoke_test and self.custom_voice_id and (
            self.settings.get("custom_voice_pack_id") != self.custom_voice_id
            or self.settings.get("custom_voice_pack") != saved_pack
        ):
            self._save_settings()  # Persist a legacy selection's ID before the next update.

    def _refresh_voice_status(self) -> None:
        self.voice_status_var.set(self.speech.voice_status)
        self.voice_status_timer = self.root.after(500, self._refresh_voice_status)

    def _on_voice_mode_selected(self) -> None:
        self.speech.set_schedule_mode(self.voice_mode_var.get())
        self.voice_status_var.set(self.speech.voice_status)
        self._save_settings()

    def _on_speak_toggled(self) -> None:
        self.speech.set_preload_enabled(self.speak_var.get())
        self.voice_status_var.set(self.speech.voice_status)
        self._save_settings()

    def _load_settings(self) -> dict[str, object]:
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            try:
                payload = json.loads((self.project_dir / "assistant-settings.example.json").read_text(encoding="utf-8-sig"))
                return payload if isinstance(payload, dict) else {}
            except (OSError, json.JSONDecodeError):
                return {}

    def _load_portal(self) -> dict[str, object]:
        try:
            path = self.portal_path if self.portal_path.exists() else self.project_dir / "portal.example.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                children = payload.get("children", {})
                for child in children.values() if isinstance(children, dict) else ():
                    action = child.get("action") if isinstance(child, dict) else None
                    if isinstance(action, dict) and isinstance(action.get("working_directory"), str):
                        working = Path(action["working_directory"])
                        if not working.is_absolute():
                            action["working_directory"] = str((self.project_dir / working).resolve())
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _web_mode_from_settings(settings: dict[str, object]) -> int:
        value = settings.get("web_mode")
        if isinstance(value, int) and not isinstance(value, bool):
            return max(0, min(4, value))
        # Existing users with web search enabled migrate to the new AI-first
        # default; an explicitly disabled legacy setting remains disabled.
        return 2 if bool(settings.get("web_answer", True)) else 0

    def _update_web_mode_label(self, _value=None) -> None:
        labels = {
            0: "关闭",
            1: "需要时",
            2: "Google AI 优先",
            3: "Marvis",
            4: "云端 API",
        }
        mode = max(0, min(4, int(self.web_mode_var.get())))
        self.web_mode_label_var.set(labels[mode])

    def _portal_default_name(self) -> str:
        default_id = str(self.portal.get("default", "local_assistant"))
        child = self.portal_children.get(default_id, {})
        return str(child.get("name", "本地助手")) if isinstance(child, dict) else "本地助手"

    def _save_settings(self) -> None:
        payload = {
            **self.settings,
            "voice": self.voice_choice_var.get(),
            "custom_voice_pack": self.custom_voice_var.get(),
            "custom_voice_pack_id": self.custom_voice_id,
            "voice_mode": self.voice_mode_var.get(),
            "speak": self.speak_var.get(),
            "reply_length": self.reply_length,
            "speech_rate": clamp_rate(self.speech_rate_var.get()),
            "codex": self.complex_agent_var.get() != "关闭",
            "complex_agent": self.complex_agent_var.get(),
            "ollama": self.ollama_var.get(),
            "local_model": self.local_model_config.to_dict(),
            "web_mode": self.web_mode_var.get(),
            "web_answer": self.web_mode_var.get() > 0,
            "cloud_base_url": self.cloud_base_url_var.get().strip(),
            "cloud_model": self.cloud_model_var.get().strip(),
            "auto_low_risk": self.auto_voice_var.get(),
        }
        try:
            save_settings(self.settings_path, payload)
            self.settings = payload
        except OSError:
            pass

    def _configure_window(self) -> None:
        self.root.title(WINDOW_TITLE)
        self.root.geometry("780x720")
        self.root.minsize(680, 600)
        self.root.configure(bg=BG)
        icon_path = self.project_dir / "assets" / "keypilot.ico"
        if icon_path.exists():
            try:
                self.root.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCheckbutton", background=PANEL, foreground=MUTED, font=("Microsoft YaHei UI", 10))
        style.map("TCheckbutton", background=[("active", PANEL)], foreground=[("active", TEXT)])

    def _build_ui(self) -> None:
        outer = tk.Frame(self.root, bg=BG, padx=28, pady=24)
        outer.pack(fill="both", expand=True)

        top = tk.Frame(outer, bg=BG)
        top.pack(fill="x")
        tk.Label(
            top,
            text="KeyPilot",
            bg=BG,
            fg=TEXT,
            font=("Microsoft YaHei UI", 24, "bold"),
        ).pack(side="left")
        tk.Label(
            top,
            text="本地助手",
            bg=ACCENT,
            fg="#07131d",
            padx=10,
            pady=4,
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="left", padx=(12, 0), pady=(5, 0))
        tk.Button(
            top,
            text="⚙ 设置",
            command=self.open_preferences,
            bg=PANEL_2,
            fg=TEXT,
            activebackground="#303a4a",
            activeforeground=TEXT,
            relief="flat",
            padx=12,
            pady=6,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right", pady=(3, 0))
        tk.Button(top, text="本地模型门户", command=self.open_local_model_portal,
                  bg=PANEL_2, fg=TEXT, relief="flat", padx=10, pady=6,
                  font=("Microsoft YaHei UI", 9)).pack(side="right", padx=6, pady=(3, 0))
        tk.Button(top, text="项目与接入", command=lambda: self._open_project_doc("START_HERE.md"),
                  bg=PANEL_2, fg=TEXT, relief="flat", padx=10, pady=6,
                  font=("Microsoft YaHei UI", 9)).pack(side="right", pady=(3, 0))

        portal = tk.Frame(outer, bg=PANEL_2, padx=16, pady=11)
        portal.pack(fill="x", pady=(18, 0))
        tk.Label(
            portal,
            text="Copilot 门户",
            bg=PANEL_2,
            fg=TEXT,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")
        tk.Label(
            portal,
            text="快捷入口",
            bg=PANEL_2,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(20, 7))
        portal_names = [
            str(child.get("name", child_id))
            for child_id, child in self.portal_children.items()
            if isinstance(child, dict)
        ]
        self.portal_combo = ttk.Combobox(
            portal,
            textvariable=self.portal_default_var,
            values=portal_names,
            state="readonly",
            width=18,
        )
        self.portal_combo.pack(side="left")
        self.portal_combo.bind("<<ComboboxSelected>>", self._on_portal_default_selected)
        tk.Button(
            portal,
            text="打开入口",
            command=self._open_selected_portal_child,
            bg=ACCENT,
            fg="#07131d",
            activebackground="#80caff",
            relief="flat",
            padx=12,
            pady=4,
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="right")

        status = tk.Frame(outer, bg=PANEL, padx=18, pady=14)
        status.pack(fill="x", pady=(14, 14))
        self.status_label = tk.Label(
            status,
            textvariable=self.status_var,
            bg=PANEL,
            fg=SUCCESS,
            font=("Microsoft YaHei UI", 12, "bold"),
        )
        self.status_label.pack(anchor="w")
        tk.Label(
            status,
            textvariable=self.status_detail_var,
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        command_panel = tk.Frame(outer, bg=PANEL, padx=18, pady=18)
        command_panel.pack(fill="x")
        tk.Label(
            command_panel,
            text="你想让电脑做什么？",
            bg=PANEL,
            fg=TEXT,
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w")

        entry_row = tk.Frame(command_panel, bg=PANEL)
        entry_row.pack(fill="x", pady=(12, 0))
        self.entry = tk.Entry(
            entry_row,
            textvariable=self.command_var,
            bg="#0e1117",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#354052",
            highlightcolor=ACCENT,
            font=("Microsoft YaHei UI", 13),
        )
        self.entry.pack(side="left", fill="x", expand=True, ipady=10)
        self.entry.bind("<Return>", lambda _event: self.submit())

        self.voice_button = tk.Button(
            entry_row,
            text="🎙 听写",
            command=self.start_dictation,
            bg=PANEL_2,
            fg=TEXT,
            activebackground="#303a4a",
            activeforeground=TEXT,
            relief="flat",
            padx=16,
            pady=10,
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.voice_button.pack(side="left", padx=(10, 0))

        self.run_button = tk.Button(
            entry_row,
            text="执行",
            command=self.submit,
            bg=ACCENT,
            fg="#07131d",
            activebackground="#80caff",
            activeforeground="#07131d",
            relief="flat",
            padx=20,
            pady=10,
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.run_button.pack(side="left", padx=(10, 0))

        clock_card = tk.Frame(outer, bg=PANEL_2, padx=16, pady=12)
        clock_card.pack(fill="x", pady=(14, 0))
        clock_text = tk.Frame(clock_card, bg=PANEL_2)
        clock_text.pack(side="left")
        tk.Label(
            clock_text,
            text="时钟助手",
            bg=PANEL_2,
            fg=TEXT,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w")
        tk.Label(
            clock_text,
            text="倒计时 · 闹钟 · 提醒 · 世界时间",
            bg=PANEL_2,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(3, 0))
        self.main_clock_var = tk.StringVar()
        tk.Label(
            clock_card,
            textvariable=self.main_clock_var,
            bg=PANEL_2,
            fg=ACCENT,
            font=("Consolas", 18, "bold"),
        ).pack(side="left", padx=(28, 0))
        tk.Button(
            clock_card,
            text="打开时钟助手",
            command=self.open_time_assistant,
            bg=ACCENT,
            fg="#07131d",
            activebackground="#80caff",
            relief="flat",
            padx=15,
            pady=7,
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="right")

        answer_panel = tk.Frame(outer, bg=PANEL, padx=18, pady=14)
        answer_panel.pack(fill="x", pady=(14, 0))
        answer_header = tk.Frame(answer_panel, bg=PANEL)
        answer_header.pack(fill="x")
        tk.Label(
            answer_header,
            text="最后结果",
            bg=PANEL,
            fg=TEXT,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(side="left")
        tk.Button(
            answer_header,
            text="复制",
            command=self.copy_answer,
            bg=PANEL_2,
            fg=MUTED,
            activebackground="#303a4a",
            activeforeground=TEXT,
            relief="flat",
            padx=10,
            pady=2,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right")
        tk.Button(
            answer_header,
            text="朗读",
            command=self.read_answer_aloud,
            bg=PANEL_2,
            fg=MUTED,
            activebackground="#303a4a",
            activeforeground=TEXT,
            relief="flat",
            padx=10,
            pady=2,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right", padx=(0, 8))
        tk.Button(
            answer_header,
            text="清除上下文",
            command=self.clear_context,
            bg=PANEL_2,
            fg=MUTED,
            activebackground="#303a4a",
            activeforeground=TEXT,
            relief="flat",
            padx=10,
            pady=2,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right", padx=(0, 8))
        self.answer = tk.Text(
            answer_panel,
            height=7,
            bg="#0e1117",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            wrap="word",
            undo=True,
            font=("Microsoft YaHei UI", 12),
            padx=12,
            pady=10,
        )
        self.answer.pack(fill="x", pady=(9, 0))
        self._set_answer("结果会显示在这里。")

        history_panel = tk.Frame(outer, bg=PANEL, padx=18, pady=16)
        history_panel.pack(fill="both", expand=True, pady=(14, 0))
        tk.Label(
            history_panel,
            text="运行记录",
            bg=PANEL,
            fg=TEXT,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w")
        self.history = tk.Text(
            history_panel,
            bg=PANEL,
            fg=MUTED,
            relief="flat",
            wrap="word",
            state="disabled",
            font=("Microsoft YaHei UI", 10),
            padx=0,
            pady=8,
        )
        self.history.pack(fill="both", expand=True)
        self.history.tag_configure("user", foreground=TEXT)
        self.history.tag_configure("success", foreground=SUCCESS)
        self.history.tag_configure("error", foreground=ERROR)
        self.history.tag_configure("meta", foreground="#6f7c8e")

        footer = tk.Frame(outer, bg=BG)
        footer.pack(fill="x", pady=(12, 0))
        tk.Label(
            footer,
            text=f"{len(self.registry.skills)} 个 Skill · 单击：打开/最小化 · 双击：听写",
            bg=BG,
            fg="#6f7c8e",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        tk.Label(
            footer,
            text="语音输入暂用 Windows 听写（Win+H）",
            bg=BG,
            fg="#6f7c8e",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right")

        self.entry.focus_set()
        self._update_main_clock()

    def _set_status(self, title: str, detail: str, color: str = SUCCESS) -> None:
        self.status_var.set(title)
        self.status_detail_var.set(detail)
        self.status_label.configure(fg=color)

    def _set_answer(self, text: str) -> None:
        self.answer.configure(state="normal")
        self.answer.delete("1.0", "end")
        self.answer.insert("1.0", text)

    def read_answer_aloud(self) -> None:
        text = self.answer.get("1.0", "end-1c").strip()
        if not text or text == "结果会显示在这里。":
            self._set_status("没有可朗读的结果", "请先获得回答或在结果框中输入文字。", ERROR)
            return
        level = getattr(self, "reply_length", "中")
        self.speech.speak(limit_reply(text, level))
        self._set_status("正在重新朗读", "使用当前声音和语速；再次听写会立即停止朗读。", ACCENT)

    def copy_answer(self) -> None:
        text = self.answer.get("1.0", "end-1c").strip()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._set_status("已复制", "最后结果已复制到剪贴板。", SUCCESS)

    def clear_context(self) -> None:
        self.memory.clear()
        self._set_status("上下文已清除", "后续回答将从新的对话开始。", SUCCESS)

    def _append_history(self, utterance: str, response: str, *, ok: bool, source: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.history.configure(state="normal")
        self.history.insert("end", f"{stamp}  你：{utterance}\n", "user")
        self.history.insert("end", f"          助手：{response}\n", "success" if ok else "error")
        self.history.insert("end", f"          来源：{source}\n\n", "meta")
        self.history.see("end")
        self.history.configure(state="disabled")

    def _set_command(self, value: str) -> None:
        self._programmatic_input = True
        self.command_var.set(value)
        self._programmatic_input = False

    def run_example(self, command: str) -> None:
        self._set_command(command)
        self.submit()

    def _update_main_clock(self) -> None:
        self.main_clock_var.set(datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._update_main_clock)

    def open_time_assistant(self) -> None:
        if self.time_window and self.time_window.is_open():
            self.time_window.show()
            return
        self.time_window = TimeAssistantWindow(
            self.root,
            self.controller.time_tasks,
            self._on_time_assistant_result,
        )

    def _on_time_assistant_result(self, message: str, ok: bool) -> None:
        self._set_status("时钟助手" if ok else "设置失败", message, SUCCESS if ok else ERROR)
        self._set_answer(message)
        self._append_history("时钟助手", message, ok=ok, source="可视化时钟助手")

    def _portal_child_id_by_name(self, name: str) -> str | None:
        for child_id, child in self.portal_children.items():
            if isinstance(child, dict) and str(child.get("name", child_id)) == name:
                return str(child_id)
        return None

    def _on_portal_default_selected(self, _event=None) -> None:
        child_id = self._portal_child_id_by_name(self.portal_default_var.get())
        if not child_id:
            return
        self.portal["default"] = child_id
        try:
            self.portal_path.parent.mkdir(parents=True, exist_ok=True)
            self.portal_path.write_text(
                json.dumps(self.portal, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self._set_status("快捷入口已更新", self.portal_default_var.get(), SUCCESS)
        except OSError as exc:
            self._set_status("保存失败", str(exc), ERROR)

    def _open_selected_portal_child(self) -> None:
        child_id = self._portal_child_id_by_name(self.portal_default_var.get())
        child = self.portal_children.get(child_id or "", {})
        action = child.get("action") if isinstance(child, dict) else None
        if not isinstance(action, dict):
            self._set_status("入口无效", "请检查 portal.json。", ERROR)
            return
        try:
            execute_action(action)
            self._set_status("已打开入口", self.portal_default_var.get(), SUCCESS)
        except Exception as exc:
            self._set_status("打开失败", str(exc), ERROR)

    def open_preferences(self) -> None:
        if self.preferences_window and self.preferences_window.winfo_exists():
            self.preferences_window.deiconify()
            self.preferences_window.lift()
            self.preferences_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        self.preferences_window = window
        window.title("KeyPilot 设置")
        window.geometry("710x780")
        window.minsize(650, 540)
        window.resizable(True, True)
        window.configure(bg=BG)
        window.transient(self.root)

        outer = tk.Frame(window, bg=BG, padx=22, pady=14)
        outer.pack(fill="both", expand=True)
        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        tk.Label(
            header,
            text="设置",
            bg=BG,
            fg=TEXT,
            font=("Microsoft YaHei UI", 20, "bold"),
        ).pack(side="left")
        tk.Label(
            header,
            text="关闭窗口时自动保存",
            bg=BG,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right", pady=(8, 0))

        scroll_area = tk.Frame(outer, bg=PANEL)
        scroll_area.pack(fill="both", expand=True, pady=(14, 0))
        canvas = tk.Canvas(scroll_area, bg=PANEL, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_area, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        panel = tk.Frame(canvas, bg=PANEL, padx=18, pady=16)
        panel_id = canvas.create_window((0, 0), window=panel, anchor="nw")
        panel.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(panel_id, width=event.width))
        window.bind("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"))

        toggles = tk.Frame(panel, bg=PANEL)
        toggles.pack(fill="x")
        ttk.Checkbutton(toggles, text="语音回复", variable=self.speak_var,
                        command=self._on_speak_toggled).pack(side="left")
        ttk.Checkbutton(
            toggles,
            text="本地模型理解",
            variable=self.ollama_var,
        ).pack(side="left", padx=(20, 0))

        model_portal_row = tk.Frame(panel, bg=PANEL)
        model_portal_row.pack(fill="x", pady=(12, 0))
        tk.Button(model_portal_row, text="本地模型门户 / 连接与测试", command=self.open_local_model_portal,
                  bg=PANEL_2, fg=TEXT, relief="flat", padx=12, pady=5).pack(side="left")
        tk.Button(model_portal_row, text="项目与接入", command=lambda: self._open_project_doc("START_HERE.md"),
                  bg=PANEL_2, fg=TEXT, relief="flat", padx=12, pady=5).pack(side="left", padx=8)
        ttk.Checkbutton(
            toggles,
            text="低风险 Skill 直接执行",
            variable=self.auto_voice_var,
        ).pack(side="left", padx=(20, 0))

        intelligence = tk.Frame(panel, bg=PANEL)
        intelligence.pack(fill="x", pady=(12, 0))
        tk.Label(
            intelligence,
            text="知识问答",
            bg=PANEL,
            fg=TEXT,
            width=11,
            anchor="w",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")
        tk.Scale(
            intelligence,
            from_=0,
            to=4,
            resolution=1,
            orient="horizontal",
            showvalue=False,
            length=250,
            variable=self.web_mode_var,
            command=self._update_web_mode_label,
            bg=PANEL,
            fg=TEXT,
            troughcolor="#354052",
            activebackground=ACCENT,
            highlightthickness=0,
            bd=0,
        ).pack(side="left", padx=(8, 12))
        tk.Label(
            intelligence,
            textvariable=self.web_mode_label_var,
            width=16,
            anchor="w",
            bg=PANEL,
            fg=ACCENT,
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="left")
        tk.Label(
            panel,
            text="0 关闭　1 需要时　2 Google AI　3 Marvis　4 云端 API",
            bg=PANEL,
            fg="#6f7c8e",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=(102, 0))

        agent_row = tk.Frame(panel, bg=PANEL)
        agent_row.pack(fill="x", pady=(12, 0))
        tk.Label(
            agent_row,
            text="复杂操作代理",
            bg=PANEL,
            fg=TEXT,
            width=11,
            anchor="w",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")
        self.complex_agent_combo = ttk.Combobox(
            agent_row,
            textvariable=self.complex_agent_var,
            values=COMPLEX_AGENT_CHOICES,
            state="readonly",
            width=18,
        )
        self.complex_agent_combo.pack(side="left", padx=(8, 12))
        self.complex_agent_combo.bind(
            "<<ComboboxSelected>>", self._on_complex_agent_selected
        )
        tk.Label(
            agent_row,
            text="本地 Skill 无法完成时使用",
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")

        cloud_row = tk.Frame(panel, bg=PANEL)
        cloud_row.pack(fill="x", pady=(12, 0))
        tk.Label(
            cloud_row,
            text="云端模型",
            bg=PANEL,
            fg=TEXT,
            width=11,
            anchor="w",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")
        model_values = list(CLOUD_MODEL_PRESETS)
        if self.cloud_model_var.get().strip() and self.cloud_model_var.get() not in model_values:
            model_values.insert(0, self.cloud_model_var.get().strip())
        self.cloud_model_combo = ttk.Combobox(
            cloud_row,
            textvariable=self.cloud_model_var,
            values=model_values,
            state="normal",
            width=28,
        )
        self.cloud_model_combo.pack(side="left", padx=(8, 10))
        self.cloud_model_combo.bind("<<ComboboxSelected>>", self._on_cloud_model_selected)
        self.cloud_model_combo.bind("<Return>", self._on_cloud_model_selected)
        self.cloud_model_combo.bind("<FocusOut>", self._on_cloud_model_selected)
        tk.Button(
            cloud_row,
            text="API 连接设置",
            command=self.open_cloud_api_settings,
            bg=PANEL_2,
            fg=TEXT,
            activebackground="#303a4a",
            activeforeground=TEXT,
            relief="flat",
            padx=10,
            pady=5,
        ).pack(side="left")

        voice_row = tk.Frame(panel, bg=PANEL)
        voice_row.pack(fill="x", pady=(12, 0))
        tk.Label(
            voice_row,
            text="回复声音",
            bg=PANEL,
            fg=TEXT,
            width=11,
            anchor="w",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")
        self.voice_combo = ttk.Combobox(
            voice_row,
            textvariable=self.voice_choice_var,
            values=list(self.voice_profiles),
            state="readonly",
            width=28,
        )
        self.voice_combo.pack(side="left", padx=(8, 10))
        self.voice_combo.bind("<<ComboboxSelected>>", self._on_voice_selected)
        tk.Button(
            voice_row,
            text="试听",
            command=lambda: self.preview_voice(builtin=True),
            bg=PANEL_2,
            fg=TEXT,
            activebackground="#303a4a",
            activeforeground=TEXT,
            relief="flat",
            padx=14,
            pady=5,
        ).pack(side="left")

        custom_row = tk.Frame(panel, bg=PANEL)
        custom_row.pack(fill="x", pady=(12, 0))
        tk.Label(custom_row, text="自定义语音包", bg=PANEL, fg=TEXT,
                 width=11, anchor="w", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        self.voice_packs = available_voice_packs()
        selected_label, self.custom_voice_id = restore_voice_selection(
            {"custom_voice_pack": self.custom_voice_var.get(), "custom_voice_pack_id": self.custom_voice_id},
            self.voice_packs,
        )
        self.custom_voice_var.set(selected_label)
        self.speech.set_custom_voice(selected_voice_path(selected_label, self.custom_voice_id, self.voice_packs))
        self.custom_voice_combo = ttk.Combobox(
            custom_row,
            textvariable=self.custom_voice_var,
            values=voice_selection_values(selected_label, self.voice_packs),
            state="readonly",
            width=28,
        )
        self.custom_voice_combo.pack(side="left", padx=(8, 10))
        self.custom_voice_combo.bind("<<ComboboxSelected>>", self._on_custom_voice_selected)
        tk.Button(custom_row, text="试听", command=self.preview_voice, bg=PANEL_2,
                  fg=TEXT, relief="flat", padx=14, pady=5).pack(side="left")
        tk.Button(custom_row, text="刷新", command=self._refresh_voice_packs, bg=PANEL_2,
                  fg=TEXT, relief="flat", padx=10, pady=5).pack(side="left", padx=(6, 0))
        voice_import_row = tk.Frame(panel, bg=PANEL)
        voice_import_row.pack(fill="x", pady=(8, 0))
        tk.Button(voice_import_row, text="导入语音包", command=self._import_voice_pack,
                  bg=PANEL_2, fg=TEXT, relief="flat", padx=12, pady=5).pack(side="left")
        tk.Button(voice_import_row, text="语音包实现与导入规范", command=lambda: self._open_project_doc("VOICE_PACKS.md"),
                  bg=PANEL_2, fg=TEXT, relief="flat", padx=12, pady=5).pack(side="left", padx=8)
        quality_row = tk.Frame(panel, bg=PANEL)
        quality_row.pack(fill="x", pady=(8, 0))
        tk.Label(quality_row, text="CPU 生成精度", bg=PANEL, fg=TEXT, width=11,
                 anchor="w", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        self.voice_quality_combo = ttk.Combobox(
            quality_row,
            textvariable=self.voice_quality_var,
            values=ZIPVOICE_QUALITY_OPTIONS,
            state="disabled",
            width=21,
        )
        self.voice_quality_combo.pack(side="left", padx=(8, 10))
        self.voice_quality_combo.bind("<<ComboboxSelected>>", self._on_voice_quality_selected)
        tk.Label(quality_row, textvariable=self.voice_quality_help_var, bg=PANEL,
                 fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self._refresh_voice_quality_control()
        tk.Label(panel, text="云端声音联网合成；CPU / GPU / 变声包按各自方式运行。",
                 bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(5, 0))
        schedule_row = tk.Frame(panel, bg=PANEL)
        schedule_row.pack(fill="x", pady=(10, 0))
        tk.Label(schedule_row, text="语音调度", bg=PANEL, fg=TEXT, width=11,
                 anchor="w", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        for mode, label in (("performance", "性能 · 按需加载"), ("quality", "质量 · 预热常驻")):
            tk.Radiobutton(schedule_row, text=label, value=mode, variable=self.voice_mode_var,
                           command=self._on_voice_mode_selected, indicatoron=False,
                           bg=PANEL_2, fg=TEXT, selectcolor="#24506b", activebackground="#303a4a",
                           activeforeground=TEXT, relief="flat", padx=12, pady=5).pack(side="left", padx=(8, 0))
        tk.Label(panel, textvariable=self.voice_status_var, bg=PANEL, fg=ACCENT,
                 anchor="w", wraplength=550, font=("Microsoft YaHei UI", 9)).pack(fill="x", pady=(4, 0))
        tk.Label(panel, text="质量模式持续占用内存 / 显存；性能模式空闲 45 秒释放。音色参数不变。",
                 bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 8)).pack(anchor="w")
        reading_row = tk.Frame(panel, bg=PANEL)
        length_row = tk.Frame(panel, bg=PANEL)
        length_row.pack(fill="x", pady=(12, 0))
        tk.Label(length_row, text="语音回复长度", bg=PANEL, fg=TEXT, width=11,
                 anchor="w", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        length_combo = ttk.Combobox(length_row, textvariable=self.reply_length_var,
                                   values=list(REPLY_LIMITS), state="readonly", width=6)
        length_combo.pack(side="left", padx=(8, 10))
        length_combo.bind("<<ComboboxSelected>>", self._on_reply_length_selected)
        tk.Label(length_row, text="低：简短　中：适中　高：尽量全文", bg=PANEL,
                 fg=MUTED).pack(side="left")
        rate_row = tk.Frame(panel, bg=PANEL)
        rate_row.pack(fill="x", pady=(8, 0))
        tk.Label(rate_row, text="语速微调", bg=PANEL, fg=TEXT, width=11,
                 anchor="w", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        tk.Scale(rate_row, from_=MIN_RATE, to=MAX_RATE, resolution=0.01, length=150,
                 variable=self.speech_rate_var, orient="horizontal", showvalue=False,
                 command=self._on_speech_rate_changed, bg=PANEL, fg=TEXT,
                 highlightthickness=0, troughcolor=PANEL_2).pack(side="left", padx=8)
        tk.Label(rate_row, textvariable=self.speech_rate_label_var, bg=PANEL, fg=ACCENT,
                 width=6).pack(side="left")
        tk.Button(rate_row, text="恢复默认", command=self._reset_speech_rate,
                  bg=PANEL_2, fg=TEXT, relief="flat", padx=8).pack(side="left", padx=6)
        tk.Label(panel, text="0.90× 稍慢 — 1.00× 当前音色默认 — 1.10× 稍快；下次朗读生效。",
                 bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(4, 0))
        reading_row.pack(fill="x", pady=(10, 0))
        tk.Button(reading_row, text="朗读剪贴板", command=self.read_clipboard_aloud,
                  bg=PANEL_2, fg=TEXT, relief="flat", padx=14, pady=5).pack(side="left")
        tk.Button(reading_row, text="停止朗读", command=self.speech.stop,
                  bg=PANEL_2, fg=TEXT, relief="flat", padx=14, pady=5).pack(side="left", padx=8)
        tk.Label(reading_row, text="可复制 ChatGPT 的回复后朗读", bg=PANEL, fg=MUTED).pack(side="left")

        tools = tk.Frame(panel, bg=PANEL)
        tools.pack(fill="x", pady=(22, 0))
        tk.Button(
            tools,
            text="关键词与路径管理",
            command=self.open_keyword_manager,
            bg=PANEL_2,
            fg=TEXT,
            activebackground="#303a4a",
            activeforeground=TEXT,
            relief="flat",
            padx=14,
            pady=7,
        ).pack(side="left")
        tk.Label(
            tools,
            text="网站、应用和桌面文件别名",
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(12, 0))

        def close_preferences() -> None:
            self._save_settings()
            self.preferences_window = None
            window.destroy()

        tk.Button(
            outer,
            text="完成",
            command=close_preferences,
            bg=ACCENT,
            fg="#07131d",
            activebackground="#80caff",
            relief="flat",
            padx=22,
            pady=7,
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(anchor="e", pady=(12, 0))
        window.protocol("WM_DELETE_WINDOW", close_preferences)
        window.update_idletasks()
        popup_width = window.winfo_width()
        popup_height = window.winfo_height()
        x = self.root.winfo_rootx() + self.root.winfo_width() - popup_width - 18
        y = self.root.winfo_rooty() + 54
        x = max(0, min(x, window.winfo_screenwidth() - popup_width))
        y = max(0, min(y, window.winfo_screenheight() - popup_height))
        window.geometry(f"+{x}+{y}")

    def _open_project_doc(self, filename: str) -> None:
        path = self.project_dir.parent / "docs" / filename
        try:
            content = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            self._set_status("文档暂不可用", str(exc), ERROR)
            return
        window = tk.Toplevel(self.root)
        window.title("项目与接入 · " + path.name)
        window.geometry("860x640")
        controls = ttk.Frame(window, padding=10)
        controls.pack(fill="x")
        for label, name in (("项目入口", "START_HERE.md"), ("本地模型", "LOCAL_MODELS.md"),
                            ("模型接入 Skill", "../skills/keypilot-model-adapter/SKILL.md"),
                            ("语音规范", "VOICE_PACKS.md"), ("版本迭代", "VERSION_HISTORY.md")):
            ttk.Button(controls, text=label, command=lambda name=name: self._open_project_doc(name)).pack(side="left", padx=3)
        ttk.Button(controls, text="打开文档文件", command=lambda: os.startfile(str(path))).pack(side="right")
        area = tk.Frame(window)
        area.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        scroll = ttk.Scrollbar(area)
        scroll.pack(side="right", fill="y")
        text = tk.Text(area, wrap="word", font=("Microsoft YaHei UI", 10), padx=16, pady=14,
                       yscrollcommand=scroll.set)
        text.pack(fill="both", expand=True)
        scroll.configure(command=text.yview)
        text.insert("1.0", content)
        text.configure(state="disabled")

    def open_local_model_portal(self) -> None:
        if self.local_model_window and self.local_model_window.winfo_exists():
            self.local_model_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.local_model_window = window
        window.title("本地模型门户 · 连接 / 发现 / 操作契约")
        window.geometry("780x690")
        window.minsize(680, 600)
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="连接任意兼容模型服务", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="填写服务地址和真实模型 ID；测试只显示 Skill 候选，不操作电脑。", wraplength=690).pack(anchor="w", pady=(5, 12))
        protocol = tk.StringVar(value=self.local_model_config.protocol)
        endpoint = tk.StringVar(value=self.local_model_config.endpoint)
        model = tk.StringVar(value=self.local_model_config.model)
        mode = tk.StringVar(value=self.local_model_config.json_mode)
        timeout = tk.StringVar(value=str(self.local_model_config.timeout_seconds))
        key_env = tk.StringVar(value=self.local_model_config.api_key_env)
        status = tk.StringVar(value="Ollama 常用端口 11434；兼容服务请填写其实际地址（可含 /v1）。")
        fields = ttk.Frame(frame)
        fields.pack(fill="x")
        fields.columnconfigure(1, weight=1)
        for index, (label, variable) in enumerate((("协议", protocol), ("服务地址", endpoint), ("模型 ID", model),
                                                  ("JSON 模式", mode), ("超时（秒）", timeout), ("API Key 环境变量名", key_env))):
            ttk.Label(fields, text=label).grid(row=index, column=0, sticky="w", pady=4, padx=(0, 14))
            if index == 0:
                widget = ttk.Combobox(fields, textvariable=variable, values=("ollama", "openai-compatible"), state="readonly")
            elif index == 2:
                widget = ttk.Combobox(fields, textvariable=variable)
                model_combo = widget
            elif index == 3:
                widget = ttk.Combobox(fields, textvariable=variable, values=("schema", "json", "prompt"), state="readonly")
            else:
                widget = ttk.Entry(fields, textvariable=variable)
            widget.grid(row=index, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text="schema：结构化输出；json：JSON 对象；prompt：纯提示词兼容。认证无需时留空环境变量名。",
                  wraplength=710).pack(anchor="w", pady=(6, 8))

        def config() -> LocalModelConfig:
            return LocalModelConfig(protocol.get(), endpoint.get(), model.get(), mode.get(), timeout.get(), key_env.get()).validated()

        def display(value: object) -> None:
            result_text.configure(state="normal")
            result_text.delete("1.0", "end")
            result_text.insert("1.0", json.dumps(value, ensure_ascii=False, indent=2) if not isinstance(value, str) else value)
            result_text.configure(state="disabled")

        def background(operation: str) -> None:
            try:
                bridge = LocalModelBridge(self.registry, config())
                text = test_text.get().strip()
                if operation == "probe" and not text:
                    raise LocalModelError("请输入测试命令。")
            except (ValueError, TypeError) as exc:
                status.set(str(exc))
                return
            for button in network_buttons:
                button.configure(state="disabled")
            status.set("正在连接服务……" if operation == "models" else "正在测试路由（不会执行操作）……")

            def done(value: object, error: str = "") -> None:
                if not window.winfo_exists():
                    return
                for button in network_buttons:
                    button.configure(state="normal")
                if error:
                    status.set(error)
                    return
                if operation == "models":
                    model_combo.configure(values=value)
                    if value and not model.get().strip():
                        model.set(value[0])
                    status.set(f"连接成功，发现 {len(value)} 个模型；请选择后保存。")
                else:
                    status.set("测试完成；结果仅供预览，未执行任何操作。")
                display(value)

            def work() -> None:
                try:
                    value = bridge.list_models() if operation == "models" else bridge.probe(text)
                    self.root.after(0, lambda: done(value))
                except Exception as exc:
                    error = str(exc)
                    self.root.after(0, lambda: done(None, error))
            threading.Thread(target=work, daemon=True).start()

        def save() -> None:
            try:
                chosen = config()
                if not chosen.model:
                    raise LocalModelError("请选择或填写模型 ID 后保存。")
                payload = {**self.settings, "local_model": chosen.to_dict(), "ollama": True}
                save_settings(self.settings_path, payload)
                self.settings = payload
                self.local_model_config = chosen
                self.ollama = LocalModelBridge(self.registry, chosen)
                self.ollama.reply_length = self.reply_length
                self.ollama_var.set(True)
            except (ValueError, TypeError, OSError) as exc:
                status.set("保存失败：" + str(exc))
                return
            status.set(f"已保存并启用：{chosen.model}（{chosen.protocol}）。")
            self._set_status("本地模型配置已更新", chosen.model, SUCCESS)

        def contract(export: bool = False) -> None:
            value = self.ollama.contract()
            display(value)
            if export:
                path = filedialog.asksaveasfilename(parent=window, title="导出模型操作契约", initialfile="keypilot-model-contract.json",
                                                  defaultextension=".json", filetypes=[("JSON", "*.json")])
                if path:
                    try:
                        Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                        status.set("已导出契约：" + path)
                    except OSError as exc:
                        status.set("导出失败：" + str(exc))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(0, 10))
        discover = ttk.Button(buttons, text="连接并发现模型", command=lambda: background("models"))
        discover.pack(side="left")
        ttk.Button(buttons, text="保存并启用", command=save).pack(side="left", padx=6)
        ttk.Button(buttons, text="预览契约", command=contract).pack(side="left", padx=3)
        ttk.Button(buttons, text="导出契约", command=lambda: contract(True)).pack(side="left", padx=3)
        ttk.Button(buttons, text="接入说明", command=lambda: self._open_project_doc("LOCAL_MODELS.md")).pack(side="right")
        test_row = ttk.Frame(frame)
        test_row.pack(fill="x", pady=(0, 8))
        test_text = tk.StringVar(value="把音量设置为 50%")
        ttk.Entry(test_row, textvariable=test_text).pack(side="left", fill="x", expand=True, padx=(0, 8))
        probe_button = ttk.Button(test_row, text="只读路由测试", command=lambda: background("probe"))
        probe_button.pack(side="right")
        network_buttons = [discover, probe_button]
        ttk.Label(frame, textvariable=status, wraplength=710).pack(fill="x", pady=(0, 8))
        result_text = tk.Text(frame, wrap="word", height=12, font=("Consolas", 10))
        result_text.pack(fill="both", expand=True)
        display("首次接入：启动服务 → 发现模型 → 只读测试 → 保存并启用。\n新模型应先读取操作契约与 repository 中的接入 Skill。")

    def _import_voice_pack(self) -> None:
        source = filedialog.askdirectory(parent=self.preferences_window, title="选择包含 voice.json 的可移植语音包文件夹")
        if not source:
            return
        runtime = filedialog.askopenfilename(parent=self.preferences_window, title="选择可信的本机语音运行时 python.exe（不是包内程序）",
                                            filetypes=[("Python", "python.exe"), ("Executable", "*.exe")])
        if not runtime:
            return
        self._set_status("正在校验并导入语音包", "正在检查所选 Python 运行时、模型与音频。", ACCENT)

        def complete(path: Path | None, error: str = "") -> None:
            if error:
                self._set_status("语音包导入失败", error, ERROR)
                return
            self.voice_packs = available_voice_packs()
            for label, candidate in self.voice_packs.items():
                if candidate.resolve() == path.resolve():
                    self.custom_voice_var.set(label)
                    self.custom_voice_id = path.parent.name
                    break
            if self.preferences_window and self.preferences_window.winfo_exists():
                self._refresh_voice_packs()
            else:
                self.speech.set_custom_voice(path)
                self._save_settings()
            self._set_status("语音包已导入", self.custom_voice_var.get(), SUCCESS)

        def work() -> None:
            try:
                if __package__ in (None, ""):
                    from keypilot.voice_pack_manager import import_voice_pack
                else:
                    from .voice_pack_manager import import_voice_pack
                imported = import_voice_pack(Path(source), python=Path(runtime))
                self.root.after(0, lambda: complete(imported))
            except Exception as exc:
                error = str(exc)
                self.root.after(0, lambda: complete(None, error))
        threading.Thread(target=work, daemon=True).start()

    def open_cloud_api_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("云端大模型 API 设置")
        window.geometry("650x500")
        window.resizable(False, False)
        window.configure(bg=BG)
        window.transient(self.root)

        panel = tk.Frame(window, bg=PANEL, padx=22, pady=20)
        panel.pack(fill="both", expand=True, padx=18, pady=18)
        tk.Label(
            panel,
            text="OpenAI 兼容 API",
            bg=PANEL,
            fg=TEXT,
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(anchor="w")
        tk.Label(
            panel,
            text="支持 OpenAI、DeepSeek、通义及其他提供 /v1/chat/completions 的服务。",
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(5, 14))

        base_var = tk.StringVar(value=self.cloud_base_url_var.get())
        model_var = tk.StringVar(value=self.cloud_model_var.get())
        key_var = tk.StringVar()
        status_var = tk.StringVar(
            value="API Key 已加密保存。" if self.cloud_api_key else "尚未保存 API Key。"
        )

        def field(label: str, variable: tk.StringVar, *, secret: bool = False) -> None:
            tk.Label(panel, text=label, bg=PANEL, fg=TEXT).pack(anchor="w")
            entry = tk.Entry(
                panel,
                textvariable=variable,
                show="•" if secret else "",
                bg="#0e1117",
                fg=TEXT,
                insertbackground=TEXT,
                relief="flat",
                font=("Microsoft YaHei UI", 10),
            )
            entry.pack(fill="x", ipady=8, pady=(4, 10))

        field("API 基础地址", base_var)
        tk.Label(panel, text="模型名称", bg=PANEL, fg=TEXT).pack(anchor="w")
        dialog_model_values = list(CLOUD_MODEL_PRESETS)
        if model_var.get().strip() and model_var.get().strip() not in dialog_model_values:
            dialog_model_values.insert(0, model_var.get().strip())
        ttk.Combobox(
            panel,
            textvariable=model_var,
            values=dialog_model_values,
            state="normal",
        ).pack(fill="x", ipady=5, pady=(4, 10))
        field("API Key（留空表示继续使用已经保存的密钥）", key_var, secret=True)
        tk.Label(
            panel,
            textvariable=status_var,
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w")

        buttons = tk.Frame(panel, bg=PANEL)
        buttons.pack(fill="x", pady=(15, 0))

        def save() -> bool:
            base = base_var.get().strip()
            model = model_var.get().strip()
            new_key = key_var.get().strip()
            if not base or not model:
                status_var.set("请填写 API 地址和模型名称。")
                return False
            if not (new_key or self.cloud_api_key):
                status_var.set("请填写 API Key。")
                return False
            try:
                if new_key:
                    save_secret(self.cloud_secret_path, new_key)
                    self.cloud_api_key = new_key
                    key_var.set("")
            except OSError as exc:
                status_var.set(f"API Key 加密保存失败：{exc}")
                return False
            self.cloud_base_url_var.set(base)
            self.cloud_model_var.set(model)
            values = list(CLOUD_MODEL_PRESETS)
            if model not in values:
                values.insert(0, model)
            combo = getattr(self, "cloud_model_combo", None)
            if combo is not None and combo.winfo_exists():
                combo.configure(values=values)
            self.web_mode_var.set(4)
            self._update_web_mode_label()
            self._save_settings()
            status_var.set("已保存并切换到第 4 级云端 API。")
            self._set_status("云端 API 已启用", model, SUCCESS)
            return True

        def test_connection() -> None:
            if not save():
                return
            base_url = self.cloud_base_url_var.get()
            model_name = self.cloud_model_var.get()
            api_key = self.cloud_api_key
            test_button.configure(state="disabled", text="测试中…")
            status_var.set("正在连接云端模型……")

            def run() -> None:
                try:
                    answer = self.cloud.answer(
                        "请只回复：连接成功",
                        "",
                        base_url=base_url,
                        model=model_name,
                        api_key=api_key,
                    )
                    message = f"连接成功：{answer.text[:80]}"
                    ok = True
                except CloudModelError as exc:
                    message = str(exc)
                    ok = False

                def done() -> None:
                    test_button.configure(state="normal", text="测试连接")
                    status_var.set(message)
                    self._set_status(
                        "API 测试成功" if ok else "API 测试失败",
                        message,
                        SUCCESS if ok else ERROR,
                    )

                self.root.after(0, done)

            threading.Thread(target=run, daemon=True).start()

        def clear_key() -> None:
            try:
                delete_secret(self.cloud_secret_path)
            except OSError as exc:
                status_var.set(f"清除失败：{exc}")
                return
            self.cloud_api_key = ""
            key_var.set("")
            status_var.set("已清除保存的 API Key。")

        tk.Button(
            buttons,
            text="保存并启用",
            command=save,
            bg=ACCENT,
            fg="#07131d",
            activebackground="#80caff",
            relief="flat",
            padx=14,
            pady=7,
        ).pack(side="left")
        test_button = tk.Button(
            buttons,
            text="测试连接",
            command=test_connection,
            bg=PANEL_2,
            fg=TEXT,
            activebackground="#303a4a",
            activeforeground=TEXT,
            relief="flat",
            padx=14,
            pady=7,
        )
        test_button.pack(side="left", padx=(9, 0))
        tk.Button(
            buttons,
            text="清除密钥",
            command=clear_key,
            bg="#49252a",
            fg="#ffb4b4",
            activebackground="#673239",
            relief="flat",
            padx=14,
            pady=7,
        ).pack(side="right")

    def open_keyword_manager(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("关键词管理")
        window.geometry("800x500")
        window.minsize(680, 380)
        window.configure(bg=BG)
        window.transient(self.root)
        notebook = ttk.Notebook(window)
        notebook.pack(fill="both", expand=True, padx=18, pady=18)
        website_tab = tk.Frame(notebook, bg=PANEL, padx=14, pady=14)
        path_tab = tk.Frame(notebook, bg=PANEL, padx=14, pady=14)
        notebook.add(website_tab, text="网站关键词")
        notebook.add(path_tab, text="应用 / 文件关键词")
        self._build_keyword_tab(
            website_tab,
            load_website_shortcuts,
            set_website_shortcut,
            "网址（https://…）",
            allow_browse=False,
        )
        self._build_keyword_tab(
            path_tab,
            load_path_shortcuts,
            set_path_shortcut,
            r"完整系统路径（例如 C:\Users\…\文件.pdf）",
            allow_browse=True,
        )

    def edit_website_shortcut(self) -> None:
        """Keep the old entry point working while using the new inline editor."""
        self.open_keyword_manager()

    def _build_keyword_tab(
        self,
        parent: tk.Frame,
        loader,
        setter,
        target_hint: str,
        *,
        allow_browse: bool,
    ) -> None:
        tk.Label(
            parent,
            text="直接修改后点保存；点 × 可立即删除。",
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(0, 10))
        rows = tk.Frame(parent, bg=PANEL)
        rows.pack(fill="both", expand=True)
        header = tk.Frame(rows, bg=PANEL)
        header.pack(fill="x", pady=(0, 3))
        tk.Label(header, text="关键词", width=18, anchor="w", bg=PANEL, fg=TEXT).pack(side="left")
        tk.Label(header, text=target_hint, anchor="w", bg=PANEL, fg=TEXT).pack(
            side="left", fill="x", expand=True, padx=(8, 0)
        )

        def refresh() -> None:
            for child in rows.winfo_children()[1:]:
                child.destroy()
            mappings = loader()
            for old_keyword, target in mappings.items():
                add_row(old_keyword, target, old_keyword)
            add_row("", "", None)

        def add_row(keyword: str, target: str, original: str | None) -> None:
            row = tk.Frame(rows, bg=PANEL)
            row.pack(fill="x", pady=4)
            keyword_var = tk.StringVar(value=keyword)
            target_var = tk.StringVar(value=target)
            keyword_entry = tk.Entry(
                row, textvariable=keyword_var, width=18, bg="#0e1117", fg=TEXT,
                insertbackground=TEXT, relief="flat", font=("Microsoft YaHei UI", 10),
            )
            keyword_entry.pack(side="left", fill="x", ipady=7)
            target_entry = tk.Entry(
                row, textvariable=target_var, bg="#0e1117", fg=TEXT,
                insertbackground=TEXT, relief="flat", font=("Microsoft YaHei UI", 10),
            )
            target_entry.pack(side="left", fill="x", expand=True, padx=(8, 0), ipady=7)

            if allow_browse:
                def browse() -> None:
                    selected = filedialog.askopenfilename(parent=parent, title="选择应用或文件")
                    if not selected:
                        selected = filedialog.askdirectory(parent=parent, title="选择文件夹")
                    if selected:
                        target_var.set(selected)

                tk.Button(
                    row, text="浏览", command=browse, bg=PANEL_2, fg=TEXT,
                    activebackground="#303a4a", activeforeground=TEXT,
                    relief="flat", padx=9, pady=5,
                ).pack(side="left", padx=(8, 0))

            def save() -> None:
                new_keyword = keyword_var.get().strip()
                new_target = target_var.get().strip()
                try:
                    setter(new_keyword, new_target)
                    if original and original != new_keyword:
                        setter(original, "")
                except ValueError as exc:
                    self._set_status("关键词保存失败", str(exc), ERROR)
                    return
                self._set_status("关键词已保存", f'现在可以说“打开{new_keyword}”。', SUCCESS)
                refresh()

            tk.Button(
                row, text="保存", command=save, bg=ACCENT, fg="#07131d",
                activebackground="#80caff", relief="flat", padx=9, pady=5,
            ).pack(side="left", padx=(8, 0))

            def remove() -> None:
                key = original or keyword_var.get().strip()
                if not key:
                    return
                setter(key, "")
                self._set_status("关键词已删除", key, SUCCESS)
                refresh()

            tk.Button(
                row, text="×", command=remove, bg="#49252a", fg="#ffb4b4",
                activebackground="#673239", activeforeground=TEXT,
                relief="flat", padx=10, pady=5,
            ).pack(side="left", padx=(8, 0))
            if original is None:
                keyword_entry.configure(highlightthickness=1, highlightbackground="#354052")
                target_entry.configure(highlightthickness=1, highlightbackground="#354052")

        refresh()

    def _on_voice_selected(self, _event=None) -> None:
        self.speech.set_voice(self.voice_choice_var.get())
        self._save_settings()
        self._set_status("声音已切换", self.voice_choice_var.get(), SUCCESS)

    def _on_cloud_model_selected(self, _event=None) -> None:
        model = self.cloud_model_var.get().strip()
        if not model:
            return
        self.cloud_model_var.set(model)
        values = list(CLOUD_MODEL_PRESETS)
        if model not in values:
            values.insert(0, model)
        combo = getattr(self, "cloud_model_combo", None)
        if combo is not None and combo.winfo_exists():
            combo.configure(values=values)
        self._save_settings()
        self._set_status("云端模型已切换", model, SUCCESS)

    def _on_complex_agent_selected(self, _event=None) -> None:
        agent = self.complex_agent_var.get()
        self.codex_var.set(agent != "关闭")
        self._save_settings()
        detail = "复杂操作不会再转交代理。" if agent == "关闭" else f"复杂操作将转交 {agent}。"
        self._set_status("复杂操作代理已切换", detail, SUCCESS)

    def preview_voice(self, *, builtin: bool = False) -> None:
        self.speech.set_voice(self.voice_choice_var.get())
        self._save_settings()
        self.speech.speak("你好，我是你的语音助手。有什么需要我帮忙的吗？", use_custom=not builtin)
        label = "关闭" if builtin else self.custom_voice_var.get()
        self._set_status("正在生成试听", label if label != "关闭" else self.voice_choice_var.get(), ACCENT)

    def _on_reply_length_selected(self, _event=None) -> None:
        self.reply_length = self.reply_length_var.get()
        self.ollama.reply_length = self.cloud.reply_length = self.reply_length
        self._save_settings()

    def _on_speech_rate_changed(self, _value=None) -> None:
        rate = clamp_rate(self.speech_rate_var.get())
        self.speech_rate_var.set(rate)
        self.speech_rate_label_var.set(f"{rate:.2f}×")
        self.speech.set_rate(rate)
        self._save_settings()

    def _reset_speech_rate(self) -> None:
        self.speech_rate_var.set(1.0)
        self._on_speech_rate_changed()

    def _on_custom_voice_selected(self, _event=None) -> None:
        label = self.custom_voice_var.get()
        path = self.voice_packs.get(label)
        if label == "关闭":
            self.custom_voice_id = ""
        elif path:
            self.custom_voice_id = path.parent.name
        self.speech.set_custom_voice(selected_voice_path(label, self.custom_voice_id, self.voice_packs))
        self._refresh_voice_quality_control()
        self._save_settings()
        if label != "关闭" and not path:
            self._set_status("已保留自定义声音选择", "语音包暂不可用，恢复后重新打开设置即可；未清除你的选择。", ERROR)
        else:
            self._set_status("自定义语音包已切换", label, SUCCESS)

    def _refresh_voice_packs(self) -> None:
        self.voice_packs = available_voice_packs()
        selected_label, self.custom_voice_id = restore_voice_selection(
            {
                "custom_voice_pack": self.custom_voice_var.get(),
                "custom_voice_pack_id": self.custom_voice_id,
            },
            self.voice_packs,
        )
        self.custom_voice_var.set(selected_label)
        self.custom_voice_combo.configure(
            values=voice_selection_values(selected_label, self.voice_packs)
        )
        self.speech.set_custom_voice(
            selected_voice_path(selected_label, self.custom_voice_id, self.voice_packs)
        )
        self._refresh_voice_quality_control()
        self._save_settings()
        self._set_status("语音包列表已刷新", f"找到 {len(self.voice_packs)} 个可用语音包。", SUCCESS)

    def _refresh_voice_quality_control(self) -> None:
        path = selected_voice_path(
            self.custom_voice_var.get(), self.custom_voice_id, self.voice_packs
        )
        label = zipvoice_quality_label(path)
        if label:
            options = zipvoice_quality_options(path)
            self.voice_quality_var.set(label)
            self.voice_quality_combo.configure(values=options, state="readonly")
            if any("自动" in option for option in options):
                self.voice_quality_help_var.set("v4 快速 · v5 英文 · v6 中文")
            elif any("v5" in option.lower() for option in options):
                self.voice_quality_help_var.set("v4 快速 · v5 更自然")
            else:
                self.voice_quality_help_var.set("4 最快 · 8 均衡 · 16 最慢")
        else:
            self.voice_quality_var.set("不适用")
            self.voice_quality_combo.configure(values=ZIPVOICE_QUALITY_OPTIONS, state="disabled")
            self.voice_quality_help_var.set("仅 CPU 本地训练声音可调")

    def _on_voice_quality_selected(self, _event=None) -> None:
        path = selected_voice_path(
            self.custom_voice_var.get(), self.custom_voice_id, self.voice_packs
        )
        if path is None:
            self._refresh_voice_quality_control()
            return
        try:
            steps = set_zipvoice_quality(path, self.voice_quality_var.get())
        except (OSError, ValueError) as exc:
            self._refresh_voice_quality_control()
            self._set_status("生成精度未更改", str(exc), ERROR)
            return
        self.speech.reload_custom_voice()
        self.voice_status_var.set(self.speech.voice_status)
        self._set_status(
            "CPU 声音模式已切换",
            f"{steps} 步；下次朗读生效。步数越高通常更细致，但不保证每句话都更好。",
            SUCCESS,
        )

    def read_clipboard_aloud(self) -> None:
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            text = ""
        if not text:
            self._set_status("没有可朗读的文字", "请先复制一段文字。", ERROR)
            return
        level = getattr(self, "reply_length", "中")
        self.speech.speak(limit_reply(text, level))
        self._set_status("正在朗读剪贴板", f"{level}档，最多约 {REPLY_LIMITS[level]} 字，可随时停止。", ACCENT)

    def start_dictation(self) -> None:
        if self.busy:
            return
        self.speech.stop()
        send_hotkey(["escape"])
        self.voice_armed = True
        self.dictation_started_at = time.monotonic()
        self.root.title(f"{WINDOW_TITLE} · 听写中")
        self.voice_last_value = ""
        self.voice_last_change = time.monotonic()
        self.ollama_voice_pending = False
        self.ollama_voice_value = ""
        self._set_command("")
        self.entry.focus_force()
        self._set_status("正在听写", "低风险命令会在停顿后直接执行；其他请求等待确认。", ACCENT)
        self.root.after(320, self._open_dictation_microphone)
        self.root.after(12000, self._dictation_timeout)
        self._poll_dictation()

    def cancel_dictation(self) -> None:
        self.voice_armed = False
        self.root.title(WINDOW_TITLE)
        self.ollama_voice_pending = False
        if self.voice_timer:
            try:
                self.root.after_cancel(self.voice_timer)
            except tk.TclError:
                pass
            self.voice_timer = None
        send_hotkey(["escape"])
        self._set_command("")
        self._set_status("听写已取消", "再次双击 Copilot 键即可重新开始。", MUTED)
        self.entry.focus_set()

    def toggle_dictation(self) -> None:
        if self.voice_armed:
            if time.monotonic() - self.dictation_started_at < 1.2:
                return
            self.cancel_dictation()
        else:
            self.start_dictation()

    def _open_dictation_microphone(self) -> None:
        if not self.voice_armed:
            return
        self.speech.stop()
        self.speech.prepare_for_dictation()
        send_hotkey(["win", "h"])

    def _create_dictation_event(self) -> None:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateEventW.restype = ctypes.c_void_p
        handle = kernel32.CreateEventW(None, False, False, DICTATION_EVENT_NAME)
        if handle:
            self.dictation_event_handle = int(handle)
            self.dictation_event_timer = self.root.after(80, self._poll_dictation_event)

    def _poll_dictation_event(self) -> None:
        if not self.dictation_event_handle:
            return
        kernel32 = ctypes.windll.kernel32
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint
        result = kernel32.WaitForSingleObject(ctypes.c_void_p(self.dictation_event_handle), 0)
        if result == WAIT_OBJECT_0:
            self.toggle_dictation()
        self.dictation_event_timer = self.root.after(80, self._poll_dictation_event)

    def _dictation_timeout(self) -> None:
        if not self.voice_armed:
            return
        self.voice_armed = False
        self.root.title(WINDOW_TITLE)
        send_hotkey(["escape"])
        if not self.command_var.get().strip():
            self._set_status("未听到内容", "可以再次点击听写，或直接输入文字。", ERROR)
        else:
            self._set_status("等待确认", "这不是已知低风险 Skill；点击执行后会按类型分流。", ACCENT)

    def _on_command_changed(self, *_args) -> None:
        if self._programmatic_input or not self.voice_armed:
            return
        value = self.command_var.get().strip()
        if value != self.voice_last_value:
            if value:
                self.speech.stop()
            self.voice_last_value = value
            self.voice_last_change = time.monotonic()

    def _poll_dictation(self) -> None:
        if not self.voice_armed:
            return
        value = self.command_var.get().strip()
        if value != self.voice_last_value:
            self.voice_last_value = value
            self.voice_last_change = time.monotonic()
        stable_for = time.monotonic() - self.voice_last_change
        if value and stable_for >= 0.9:
            if self.pending_cloud_question or self.pending_web_search:
                self.voice_armed = False
                self.root.title(WINDOW_TITLE)
                send_hotkey(["escape"])
                self.submit()
                return
            call = self.router.route(value)
            if self.auto_voice_var.get() and self.registry.can_execute_without_confirmation(call):
                self.voice_armed = False
                self.root.title(WINDOW_TITLE)
                send_hotkey(["escape"])
                self.submit()
                return
            if (
                call is None
                and self.auto_voice_var.get()
                and self.web_mode_var.get() >= 2
                and classify_fallback_intent(value) == "chat"
            ):
                # Obvious knowledge questions already have a deterministic
                # destination in level 2. Avoid loading a multi-GB model merely
                # to return matched=false before the Google AI search.
                self.voice_armed = False
                self.root.title(WINDOW_TITLE)
                send_hotkey(["escape"])
                self.submit()
                return
            if (
                call is None
                and self.auto_voice_var.get()
                and self.ollama_var.get()
                and not self.ollama_voice_pending
                and value != self.ollama_voice_value
            ):
                self.ollama_voice_pending = True
                self._set_status("本地模型 正在理解", value, ACCENT)
                threading.Thread(
                    target=self._route_dictation_with_ollama,
                    args=(value, self.web_mode_var.get()),
                    daemon=True,
                ).start()
            if stable_for >= 1.4:
                if not self.ollama_voice_pending:
                    destination = (
                        "知识问答服务"
                        if classify_fallback_intent(value) == "chat"
                        else self.complex_agent_var.get()
                    )
                    self._set_status(
                        "等待确认",
                        f"未匹配低风险 Skill；点击执行后转交 {destination}。",
                        ACCENT,
                    )
        self.voice_timer = self.root.after(120, self._poll_dictation)

    def _route_dictation_with_ollama(self, utterance: str, web_mode: int) -> None:
        call = None
        answer = None
        try:
            if classify_fallback_intent(utterance) == "chat" and web_mode < 2:
                answer = self.ollama.answer(utterance)
            else:
                call = self.ollama.route(utterance)
        except Exception:
            pass
        self.root.after(
            0,
            lambda: self._finish_ollama_dictation_route(
                utterance, call, answer, web_mode
            ),
        )

    def _finish_ollama_dictation_route(
        self, utterance: str, call, answer, web_mode: int
    ) -> None:
        self.ollama_voice_pending = False
        self.ollama_voice_value = utterance
        if not self.voice_armed or self.command_var.get().strip() != utterance:
            return
        if self.registry.can_execute_without_confirmation(call):
            self.voice_armed = False
            self.root.title(WINDOW_TITLE)
            send_hotkey(["escape"])
            self.submit(resolved_call=call, resolved_source="本地模型 → 本地 Skill")
            return
        self.voice_armed = False
        self.root.title(WINDOW_TITLE)
        send_hotkey(["escape"])
        if classify_fallback_intent(utterance) == "chat" and web_mode >= 2:
            # Level 2 uses 本地模型 only as the intent/Skill router. Continue
            # through the normal path so voice questions use Google AI too.
            self.submit()
            return
        if answer is not None:
            if answer.recommend_cloud:
                result = self._cloud_permission_result(utterance, answer.text)
                self._finish(utterance, result, "本地模型 本地评估")
            else:
                self._finish(utterance, ActionResult(True, answer.text), "本地模型 本地回答")
            return
        if classify_fallback_intent(utterance) == "chat":
            self._finish(
                utterance,
                self._cloud_permission_result(utterance, ""),
                "本地模型 本地评估",
            )
            return
        agent = self.complex_agent_var.get()
        detail = (
            "本地模型 未匹配低风险 Skill；复杂操作代理当前已关闭。"
            if agent == "关闭"
            else f"本地模型 未匹配低风险 Skill；点击执行后可转交 {agent}。"
        )
        self._set_status("等待确认", detail, ACCENT)

    @staticmethod
    def _permission_decision(text: str) -> bool | None:
        normalized = normalize_text(text).replace(" ", "")
        no_phrases = ("不要", "不用", "不需要", "不可以", "不是", "不", "本地回答", "千问回答", "否")
        yes_phrases = ("需要", "要", "可以", "同意", "用gpt", "使用gpt", "交给gpt", "好的", "是")
        if normalized in no_phrases or any(phrase in normalized for phrase in no_phrases):
            return False
        if normalized in yes_phrases or any(phrase in normalized for phrase in yes_phrases):
            return True
        return None

    @staticmethod
    def _cloud_permission_result(utterance: str, local_answer: str) -> ActionResult:
        return ActionResult(
            True,
            "请问需要用 GPT 回答吗？",
            {
                "ask_cloud": True,
                "original_question": utterance,
                "local_answer": local_answer,
            },
        )

    def _handle_cloud_permission(self, utterance: str) -> bool:
        if not self.pending_cloud_question:
            return False
        decision = self._permission_decision(utterance)
        if decision is None:
            message = "请直接回答需要或不需要使用 GPT。"
            self._set_status("等待选择", message, ACCENT)
            self._set_answer(message)
            self._set_command("")
            self._speak_and_listen_for_confirmation(message)
            return True
        original = self.pending_cloud_question
        local_answer = self.pending_local_answer
        self.pending_cloud_question = None
        self.pending_local_answer = ""
        if not decision:
            message = local_answer or "好的，不使用 GPT。这个问题超出了当前本地模型的可靠能力。"
            self._finish(utterance, ActionResult(bool(local_answer), message), "本地模型 本地回答")
            return True
        self.busy = True
        self.run_button.configure(state="disabled", text="处理中…")
        self._set_status("正在转交 GPT", original, ACCENT)

        def handoff() -> None:
            try:
                result = self.controller.send_to_chat(original)
            except Exception as exc:
                result = ActionResult(False, f"转交失败：{exc}")
            self.root.after(0, lambda: self._finish(utterance, result, "ChatGPT 今日聊天"))

        threading.Thread(target=handoff, daemon=True).start()
        return True

    def _handle_web_search_permission(self, utterance: str) -> bool:
        if not self.pending_web_search:
            return False
        decision = self._permission_decision(utterance)
        if decision is None:
            message = "请直接回答需要或不需要在浏览器中搜索。"
            self._set_status("等待选择", message, ACCENT)
            self._set_answer(message)
            self._set_command("")
            self._speak_and_listen_for_confirmation(message)
            return True
        query = self.pending_web_search
        self.pending_web_search = None
        if not decision:
            self._finish(utterance, ActionResult(True, "好的，已取消浏览器搜索。"), "本地 Skill")
            return True
        self.busy = True
        self.run_button.configure(state="disabled", text="处理中…")
        self._set_status("正在打开浏览器", query, ACCENT)

        def search() -> None:
            try:
                result = self.controller.open_website(query, "search")
            except Exception as exc:
                result = ActionResult(False, f"浏览器搜索失败：{exc}")
            self.root.after(0, lambda: self._finish(utterance, result, "浏览器搜索"))

        threading.Thread(target=search, daemon=True).start()
        return True

    def submit(self, *, resolved_call=None, resolved_source: str | None = None) -> None:
        utterance = self.command_var.get().strip()
        if not utterance or self.busy:
            return
        # Cancel old synthesis/playback before starting a new request, not only
        # when the next answer is ready. This also frees a busy voice GPU worker.
        self.speech.stop()
        self.voice_armed = False
        self.root.title(WINDOW_TITLE)
        if self.voice_timer:
            try:
                self.root.after_cancel(self.voice_timer)
            except tk.TclError:
                pass
            self.voice_timer = None
        if resolved_call is None:
            if self._handle_web_search_permission(utterance):
                return
            if self._handle_cloud_permission(utterance):
                return
        self.busy = True
        self.run_button.configure(state="disabled", text="处理中…")
        self._set_status("正在处理", utterance, ACCENT)
        self._set_answer("正在处理，请稍候……")
        threading.Thread(
            target=self._process,
            args=(
                utterance,
                self.ollama_var.get(),
                self.web_mode_var.get(),
                self.codex_var.get(),
                self.cloud_base_url_var.get(),
                self.cloud_model_var.get(),
                self.cloud_api_key,
                resolved_call,
                resolved_source,
                self.complex_agent_var.get(),
            ),
            daemon=True,
        ).start()

    def _search_and_answer(
        self,
        utterance: str,
        *,
        force: bool = False,
        direct_ai_text: bool = False,
    ):
        """Use free rendered Google results only after the local model declines."""
        if not force and not self.browser_reader.should_search(utterance):
            return None, None
        if not force and not self.browser_reader.online_available():
            return None, None
        opened = self.controller.open_website(utterance, "search")
        if opened.ok is False:
            self.browser_reader.last_error = opened.message
            return None, None
        if direct_ai_text:
            detail = getattr(self, "reply_length", "低")
            wait_seconds = 60 if detail == "高" else 30
            self.root.after(0, lambda: self._set_status("正在读取 Google AI", f"{detail}档：等待页面生成回答，最长约 {wait_seconds} 秒。", ACCENT))
            capture = self.browser_reader.wait_for_google_ai(utterance, restore_hwnd=self.window_handle,
                                                             detail=detail, timeout=wait_seconds)
        else:
            capture = self.browser_reader.capture_rendered_page(
                settle_seconds=4.0,
                restore_hwnd=self.window_handle,
                expected_title=utterance,
            )
        if not capture:
            return None, None
        if direct_ai_text:
            answer_text = extract_google_ai_answer(capture.text, utterance, detail=detail)
            if not answer_text:
                return None, None
            return OllamaAnswer(answer_text), "Google AI 页面原文"
        answer = self.ollama.answer_with_context(
            utterance,
            capture.text,
            self.memory.context(),
        )
        if not answer:
            return None, None
        source = (
            "Google Gemini AI 概览 → 本地模型"
            if capture.has_ai_overview
            else "Google 页面 → 本地模型"
        )
        return answer, source

    def _search_app_identity(self, requested: str) -> tuple[str, str | None]:
        """Read free search results that can map a nickname to an installed title."""
        if not self.browser_reader.online_available():
            return "", None
        query = f"{requested} 是什么应用或游戏 英文名"
        self.controller.open_website(query, "search")
        capture = self.browser_reader.capture_rendered_page(
            settle_seconds=4.0,
            restore_hwnd=self.window_handle,
            close_after_capture=True,
            expected_title=requested,
        )
        if not capture:
            return "", None
        source = (
            "Google Gemini AI 概览 → 本地模型 → 本机名单"
            if capture.has_ai_overview
            else "Google 页面 → 本地模型 → 本机名单"
        )
        return capture.text, source

    @staticmethod
    def _candidate_mentioned_in_search(
        search_text: str, candidates: list[str]
    ) -> str | None:
        """Prefer a title literally present in search results over model inference."""
        compact_context = re.sub(
            r"[^0-9a-z\u4e00-\u9fff]+", "", search_text.casefold()
        )
        mentioned: list[tuple[int, str]] = []
        for candidate in dict.fromkeys(candidates):
            compact_name = re.sub(
                r"[^0-9a-z\u4e00-\u9fff]+", "", candidate.casefold()
            )
            if len(compact_name) >= 3 and compact_name in compact_context:
                mentioned.append((len(compact_name), candidate))
        return max(mentioned, default=(0, ""))[1] or None

    def _process(
        self,
        utterance: str,
        ollama_enabled: bool,
        web_mode: int,
        codex_enabled: bool,
        cloud_base_url: str,
        cloud_model: str,
        cloud_api_key: str,
        resolved_call=None,
        resolved_source: str | None = None,
        complex_agent: str | None = None,
    ) -> None:
        source = resolved_source or "本地 Skill"
        try:
            call = resolved_call or self.router.route(utterance)
            intent = classify_fallback_intent(utterance)
            local_answer = None
            ai_first_failed = False
            cloud_failure: str | None = None
            capture = None
            if call and call.skill_id == "read_browser_page":
                if web_mode == 2:
                    capture = self.browser_reader.capture_rendered_page(restore_hwnd=self.window_handle)
                    answer_text = None
                    if capture:
                        query = google_page_question(capture.text, capture.title)
                        answer_text = extract_google_ai_answer(capture.text, query, detail=getattr(self, "reply_length", "低"))
                    if answer_text:
                        source = "Google AI 页面原文"
                        result = ActionResult(True, answer_text)
                    else:
                        result = ActionResult(False, "已尝试读取当前页面，但没有识别出 Google AI 简介；二级模式不会调用本地模型改写或补答。")
                elif not ollama_enabled:
                    result = ActionResult(False, "请先启用 本地模型，才能整理网页内容。")
                else:
                    capture = self.browser_reader.capture_rendered_page(
                        restore_hwnd=self.window_handle
                    )
                    if capture:
                        local_answer = self.ollama.answer_with_context(
                            str(call.arguments.get("question", utterance)),
                            capture.text,
                            self.memory.context(),
                        )
                    if local_answer:
                        source = "浏览器页面 → 本地模型"
                        if capture and capture.has_ai_overview:
                            source = "Google Gemini AI 概览 → 本地模型"
                        result = ActionResult(True, local_answer.text)
                    else:
                        result = ActionResult(
                            False,
                            "没有从当前浏览器页面读取到足够内容，请确认页面已经加载完成。",
                        )
                call = None
                intent = "browser_read_complete"
            if call is None and intent != "browser_read_complete":
                try:
                    if intent == "chat":
                        if web_mode >= 4:
                            try:
                                local_answer = self.cloud.answer(
                                    utterance,
                                    self.memory.context(),
                                    base_url=cloud_base_url,
                                    model=cloud_model,
                                    api_key=cloud_api_key,
                                )
                                source = f"云端 API · {cloud_model.strip()}"
                            except CloudModelError as exc:
                                cloud_failure = str(exc)
                        elif web_mode == 3:
                            result = self.controller.send_to_marvis(utterance)
                            source = "Marvis 转接器"
                            intent = "marvis_handoff_complete"
                        elif web_mode >= 2:
                            local_answer, online_source = self._search_and_answer(
                                utterance,
                                force=True,
                                direct_ai_text=True,
                            )
                            if local_answer and online_source:
                                source = online_source
                            else:
                                ai_first_failed = True
                        elif ollama_enabled:
                            local_answer = self.ollama.answer(
                                utterance, self.memory.context()
                            )
                            if local_answer is None and web_mode >= 1:
                                local_answer, online_source = self._search_and_answer(
                                    utterance
                                )
                                if local_answer and online_source:
                                    source = online_source
                        elif web_mode >= 1:
                            local_answer, online_source = self._search_and_answer(
                                utterance,
                                force=True,
                                direct_ai_text=True,
                            )
                            if local_answer and online_source:
                                source = online_source
                    elif ollama_enabled:
                        call = self.ollama.route(utterance)
                        if call is not None:
                            source = "本地模型 → 本地 Skill"
                except Exception:
                    call = None
                    if intent == "chat" and web_mode >= 4:
                        cloud_failure = "云端 API 请求失败，请检查配置和网络。"
                    elif intent == "chat" and web_mode >= 2:
                        ai_first_failed = True
            # Browser-reading is handled by the app (not WindowsController),
            # including when a model supplied the validated Skill proposal.
            if call and call.skill_id == "read_browser_page":
                self._process(utterance, ollama_enabled, web_mode, codex_enabled,
                              cloud_base_url, cloud_model, cloud_api_key,
                              resolved_call=call, resolved_source=source, complex_agent=complex_agent)
                return
            if intent in {"browser_read_complete", "marvis_handoff_complete"}:
                pass
            elif call:
                result = self.controller.execute(call)
                if (
                    call.skill_id == "open_app"
                    and not result.ok
                    and ollama_enabled
                    and result.details
                    and result.details.get("candidate_names")
                ):
                    candidate_names = list(result.details["candidate_names"])
                    app_lookup_source = None
                    web_context = ""
                    try:
                        if web_mode >= 1:
                            web_context, app_lookup_source = self._search_app_identity(
                                str(call.arguments.get("app", utterance))
                            )
                    except Exception:
                        web_context = ""
                        app_lookup_source = None

                    direct_candidate = self._candidate_mentioned_in_search(
                        web_context, candidate_names
                    )
                    if direct_candidate:
                        retried = self.controller.open_app(direct_candidate)
                        if retried.ok:
                            source = app_lookup_source or "联网名称 → 桌面直接匹配"
                            details = dict(retried.details or {})
                            details["interpreted_from"] = str(
                                call.arguments.get("app", utterance)
                            )
                            result = ActionResult(
                                True,
                                f"联网结果直接命中“{direct_candidate}”，已打开。",
                                details,
                            )

                    canonical_name = str(call.arguments.get("app", utterance))
                    model_error = None
                    if not result.ok:
                        try:
                            canonical_name, selected = self.ollama.resolve_app_identity(
                                str(call.arguments.get("app", utterance)),
                                candidate_names,
                                web_context,
                            )
                        except Exception as exc:
                            selected = None
                            model_error = exc
                        retry_name = selected or canonical_name
                        if retry_name and normalize_text(retry_name) != normalize_text(
                            str(call.arguments.get("app", utterance))
                        ):
                            retried = self.controller.open_app(retry_name)
                            if retried.ok:
                                source = app_lookup_source or "本地模型 → 桌面/应用名称匹配"
                                details = dict(retried.details or {})
                                details["interpreted_from"] = str(
                                    call.arguments.get("app", utterance)
                                )
                                result = ActionResult(
                                    True,
                                    f"已判断你说的是“{retry_name}”，并成功打开。",
                                    details,
                                )
                            elif canonical_name != str(call.arguments.get("app", utterance)):
                                result = ActionResult(
                                    False,
                                    f"本地模型判断它可能是“{canonical_name}”，但本机候选中仍没有找到。",
                                    retried.details,
                                )

                    if web_context and not result.ok:
                        details = dict(result.details or {})
                        details.pop("offer_web_search", None)
                        if model_error:
                            message = (
                                f"已联网查找，但页面中没有直接命中本机文件；"
                                f"本地模型 {self.ollama.model} 当前未安装或不可用。"
                            )
                        else:
                            message = (
                                f"联网查找后，它可能是“{canonical_name}”，"
                                "但桌面、关键词和本机应用名单中都没有高置信度匹配项。"
                            )
                        result = ActionResult(
                            False,
                            message,
                            details,
                        )
                if (
                    call.skill_id == "get_weather"
                    and not result.ok
                    and ollama_enabled
                ):
                    # The dedicated weather service may occasionally be unavailable.
                    # Let 本地模型 assess the question, then use rendered search results
                    # for the live facts it correctly refuses to invent.
                    try:
                        weather_answer = self.ollama.answer(
                            utterance, self.memory.context()
                        )
                        online_source = None
                        if weather_answer is None and web_mode >= 1:
                            weather_answer, online_source = self._search_and_answer(
                                utterance
                            )
                        if weather_answer:
                            source = online_source or "本地模型 本地回答"
                            result = ActionResult(True, weather_answer.text)
                    except Exception:
                        pass
                if not result.ok and result.details and result.details.get("fallback") == "display_settings":
                    self.controller.open_settings("display", "显示")
                    result = ActionResult(True, result.message, result.details)
            elif intent == "chat" and local_answer is not None:
                if local_answer.recommend_cloud:
                    source = "本地模型 本地评估"
                    result = self._cloud_permission_result(utterance, local_answer.text)
                else:
                    if source == "本地 Skill":
                        source = "本地模型 本地回答"
                    result = ActionResult(True, local_answer.text)
            elif intent == "chat" and web_mode >= 4 and cloud_failure:
                source = "云端 API"
                result = ActionResult(False, cloud_failure)
            elif intent == "chat" and web_mode >= 2 and ai_first_failed:
                source = "Google AI 页面"
                result = ActionResult(
                    False,
                    (self.browser_reader.last_error or "暂时没有读取到可用的 Google AI 回答。")
                    + " 二级模式不会改用 本地模型 自己作答。",
                )
            elif intent == "chat":
                source = "本地模型 本地评估"
                result = self._cloud_permission_result(utterance, "")
            elif (complex_agent or "Codex") == "Marvis" and codex_enabled:
                source = "Marvis 复杂操作代理"
                result = self.controller.send_to_marvis(utterance)
            elif codex_enabled and (complex_agent or "Codex") != "关闭":
                source = "Codex 每日会话"
                codex_result = self.codex.ask(utterance)
                if codex_result.action == "settings_search" and codex_result.query:
                    result = self.controller.open_settings("search", codex_result.query)
                    if codex_result.response:
                        result = ActionResult(result.ok, codex_result.response, result.details)
                else:
                    result = ActionResult(codex_result.action != "unsupported", codex_result.response)
            else:
                result = ActionResult(False, "本地 Skill 暂时无法理解这个请求。")
        except Exception as exc:
            result = ActionResult(False, f"处理失败：{exc}")
        self.root.after(0, lambda: self._finish(utterance, result, source))

    def _finish(self, utterance: str, result: ActionResult, source: str) -> None:
        self.busy = False
        self.run_button.configure(state="normal", text="执行")
        if result.details and result.details.get("offer_web_search"):
            self.pending_web_search = str(result.details["offer_web_search"])
            message = (
                f"没有找到本地应用“{self.pending_web_search}”。"
                "请问需要在浏览器中搜索吗？"
            )
            self._append_history(utterance, message, ok=True, source=source)
            self._set_status("等待选择", "正在等待语音回答。", ACCENT)
            self._set_answer(message)
            self._set_command("")
            self.entry.focus_set()
            self._speak_and_listen_for_confirmation(message)
            return
        if result.details and result.details.get("ask_cloud"):
            self.pending_cloud_question = str(result.details.get("original_question", utterance))
            self.pending_local_answer = str(result.details.get("local_answer", ""))
            self._append_history(utterance, result.message, ok=True, source=source)
            self._set_status("等待选择", "正在等待语音回答。", ACCENT)
            self._set_answer(result.message)
            self._set_command("")
            self.entry.focus_set()
            self._speak_and_listen_for_confirmation(result.message)
            return
        self._append_history(utterance, result.message, ok=result.ok, source=source)
        if result.ok and any(
            marker in source
            for marker in (
                "本地模型",
                "Google 页面",
                "Google AI",
                "Google Gemini",
                "浏览器页面",
                "云端 API",
            )
        ):
            self.memory.add(utterance, result.message)
        self._set_status(
            "完成" if result.ok else "未完成",
            f"来源：{source}",
            SUCCESS if result.ok else ERROR,
        )
        self._set_answer(result.message)
        if self.speak_var.get():
            self.speech.speak(limit_reply(result.message, getattr(self, "reply_length", "中")))
        self._set_command("")
        self.entry.focus_set()

    def _speak_and_listen_for_confirmation(self, prompt: str) -> None:
        if self.speak_var.get():
            self.speech.speak(
                prompt,
                on_complete=lambda: self.root.after(
                    0, self._start_pending_confirmation_dictation
                ),
            )
        else:
            self.root.after(250, self._start_pending_confirmation_dictation)

    def _start_pending_confirmation_dictation(self) -> None:
        if self.busy or self.voice_armed:
            return
        if not (self.pending_cloud_question or self.pending_web_search):
            return
        self.start_dictation()

    def close(self) -> None:
        self._save_settings()
        if self.voice_status_timer:
            self.root.after_cancel(self.voice_status_timer)
            self.voice_status_timer = None
        if self.dictation_event_timer:
            try:
                self.root.after_cancel(self.dictation_event_timer)
            except tk.TclError:
                pass
            self.dictation_event_timer = None
        if self.dictation_event_handle:
            kernel32 = ctypes.windll.kernel32
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle(ctypes.c_void_p(self.dictation_event_handle))
            self.dictation_event_handle = None
        self.speech.close()
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KeyPilot local Windows assistant test app")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--dictation", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_dir = Path(__file__).resolve().parent.parent
    identify_taskbar()
    mutex = acquire_assistant_instance()
    if mutex is None:
        return 0
    try:
        from keypilot.startup_check import check_startup
        startup = check_startup(project_dir)
        root = tk.Tk()
        app = AssistantApp(root, project_dir, smoke_test=args.smoke_test)
        if not startup['ok']:
            app._set_status('语音加载检查未通过', '；'.join(startup['errors'])[:300], ERROR)
        if args.smoke_test:
            root.update_idletasks()
            app.close()
            return 0 if startup['ok'] else 2
        if args.dictation:
            root.after(200, app.start_dictation)
        root.mainloop()
        return 0
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle(ctypes.c_void_p(mutex))


if __name__ == "__main__":
    raise SystemExit(main())
