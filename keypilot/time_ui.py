from __future__ import annotations

import tkinter as tk
import threading
import winsound
from datetime import datetime, timedelta
from tkinter import ttk
from typing import Callable

from .time_service import ALARM_PATTERNS, TIME_ZONES, TimeTaskStore, format_due, resolve_clock_due, world_time


BG = "#10131a"
PANEL = "#191e28"
PANEL_2 = "#222936"
TEXT = "#f2f5f9"
MUTED = "#9ca8b8"
ACCENT = "#57b8ff"
SUCCESS = "#55d187"
ERROR = "#ff6b6b"
SOUNDS = {"晨光旋律": "morning", "数字闹铃": "digital", "柔和铃声": "gentle"}


class TimeAssistantWindow:
    def __init__(
        self,
        parent: tk.Tk,
        store: TimeTaskStore,
        on_result: Callable[[str, bool], None],
    ) -> None:
        self.parent = parent
        self.store = store
        self.on_result = on_result
        self.window = tk.Toplevel(parent)
        self.window.title("KeyPilot 时钟助手")
        self.window.geometry("720x690")
        self.window.minsize(650, 580)
        self.window.configure(bg=BG)

        self.clock_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.timer_minutes = tk.StringVar(value="10")
        self.timer_label = tk.StringVar(value="倒计时结束")
        upcoming = datetime.now().astimezone() + timedelta(minutes=1)
        self.alarm_hour = tk.StringVar(value=f"{upcoming.hour:02d}")
        self.alarm_minute = tk.StringVar(value=f"{upcoming.minute:02d}")
        self.alarm_day = tk.StringVar(value="今天")
        self.alarm_label = tk.StringVar(value="闹钟")
        self.reminder_hour = tk.StringVar(value=f"{upcoming.hour:02d}")
        self.reminder_minute = tk.StringVar(value=f"{upcoming.minute:02d}")
        self.reminder_day = tk.StringVar(value="今天")
        self.reminder_label = tk.StringVar(value="提醒事项")
        self.sound_name = tk.StringVar(value="晨光旋律")
        self.city = tk.StringVar(value="北京")
        self.world_result = tk.StringVar(value="选择城市后查看当地时间")

        self._build()
        self._tick()
        self.refresh_tasks()

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def is_open(self) -> bool:
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def _build(self) -> None:
        outer = tk.Frame(self.window, bg=BG, padx=24, pady=20)
        outer.pack(fill="both", expand=True)
        top = tk.Frame(outer, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text="时钟助手", bg=BG, fg=TEXT, font=("Microsoft YaHei UI", 21, "bold")).pack(side="left")
        time_box = tk.Frame(top, bg=BG)
        time_box.pack(side="right")
        tk.Label(time_box, textvariable=self.clock_var, bg=BG, fg=ACCENT, font=("Consolas", 26, "bold")).pack(anchor="e")
        tk.Label(time_box, textvariable=self.date_var, bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="e")

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="x", pady=(18, 0))
        notebook.add(self._timer_tab(notebook), text="倒计时")
        notebook.add(self._alarm_tab(notebook), text="闹钟")
        notebook.add(self._reminder_tab(notebook), text="提醒")
        notebook.add(self._world_tab(notebook), text="世界时间")

        tasks = tk.Frame(outer, bg=PANEL, padx=16, pady=14)
        tasks.pack(fill="both", expand=True, pady=(16, 0))
        header = tk.Frame(tasks, bg=PANEL)
        header.pack(fill="x")
        tk.Label(header, text="即将到来", bg=PANEL, fg=TEXT, font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        tk.Button(header, text="刷新", command=self.refresh_tasks, bg=PANEL_2, fg=MUTED, relief="flat", padx=10).pack(side="right")
        self.task_list = tk.Listbox(
            tasks,
            bg="#0e1117",
            fg=TEXT,
            selectbackground="#30465b",
            relief="flat",
            font=("Microsoft YaHei UI", 10),
            height=7,
        )
        self.task_list.pack(fill="both", expand=True, pady=(10, 8))
        tk.Button(
            tasks,
            text="取消选中的项目",
            command=self.cancel_selected,
            bg=PANEL_2,
            fg=TEXT,
            activebackground="#303a4a",
            activeforeground=TEXT,
            relief="flat",
            pady=6,
        ).pack(fill="x")

    def _tab(self, notebook: ttk.Notebook) -> tk.Frame:
        return tk.Frame(notebook, bg=PANEL, padx=18, pady=18)

    def _entry(self, parent: tk.Widget, variable: tk.StringVar, width: int = 16) -> tk.Entry:
        return tk.Entry(parent, textvariable=variable, width=width, bg="#0e1117", fg=TEXT, insertbackground=TEXT, relief="flat", font=("Microsoft YaHei UI", 11))

    def _button(self, parent: tk.Widget, text: str, command) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=ACCENT, fg="#07131d", activebackground="#80caff", relief="flat", padx=16, pady=7, font=("Microsoft YaHei UI", 10, "bold"))

    def _timer_tab(self, notebook: ttk.Notebook) -> tk.Frame:
        tab = self._tab(notebook)
        tk.Label(tab, text="分钟", bg=PANEL, fg=MUTED).grid(row=0, column=0, sticky="w")
        self._entry(tab, self.timer_minutes, 8).grid(row=1, column=0, padx=(0, 12), ipady=7)
        tk.Label(tab, text="名称", bg=PANEL, fg=MUTED).grid(row=0, column=1, sticky="w")
        self._entry(tab, self.timer_label, 26).grid(row=1, column=1, padx=(0, 12), ipady=7)
        self._button(tab, "开始倒计时", self.set_timer).grid(row=1, column=2)
        return tab

    def _clock_fields(self, tab: tk.Frame, hour: tk.StringVar, minute: tk.StringVar, day: tk.StringVar, label: tk.StringVar, command, button_text: str) -> None:
        tk.Label(tab, text="日期", bg=PANEL, fg=MUTED).grid(row=0, column=0, sticky="w")
        ttk.Combobox(tab, textvariable=day, values=("今天", "明天"), state="readonly", width=7).grid(row=1, column=0, padx=(0, 8))
        tk.Label(tab, text="时", bg=PANEL, fg=MUTED).grid(row=0, column=1, sticky="w")
        ttk.Combobox(tab, textvariable=hour, values=[f"{v:02d}" for v in range(24)], state="readonly", width=4).grid(row=1, column=1, padx=(0, 6))
        tk.Label(tab, text="分", bg=PANEL, fg=MUTED).grid(row=0, column=2, sticky="w")
        ttk.Combobox(tab, textvariable=minute, values=[f"{v:02d}" for v in range(60)], state="readonly", width=4).grid(row=1, column=2, padx=(0, 8))
        self._entry(tab, label, 19).grid(row=1, column=3, padx=(0, 10), ipady=7)
        self._button(tab, button_text, command).grid(row=1, column=4)

    def _alarm_tab(self, notebook: ttk.Notebook) -> tk.Frame:
        tab = self._tab(notebook)
        self._clock_fields(tab, self.alarm_hour, self.alarm_minute, self.alarm_day, self.alarm_label, self.set_alarm, "设置闹钟")
        tk.Label(tab, text="铃声", bg=PANEL, fg=MUTED).grid(row=2, column=0, sticky="w", pady=(14, 0))
        ttk.Combobox(tab, textvariable=self.sound_name, values=list(SOUNDS), state="readonly", width=14).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        tk.Button(
            tab,
            text="试听铃声",
            command=self.preview_sound,
            bg=PANEL_2,
            fg=TEXT,
            activebackground="#303a4a",
            activeforeground=TEXT,
            relief="flat",
            padx=12,
            pady=4,
        ).grid(row=3, column=2, columnspan=2, sticky="w", pady=(4, 0))
        return tab

    def _reminder_tab(self, notebook: ttk.Notebook) -> tk.Frame:
        tab = self._tab(notebook)
        self._clock_fields(tab, self.reminder_hour, self.reminder_minute, self.reminder_day, self.reminder_label, self.set_reminder, "设置提醒")
        return tab

    def _world_tab(self, notebook: ttk.Notebook) -> tk.Frame:
        tab = self._tab(notebook)
        ttk.Combobox(tab, textvariable=self.city, values=list(TIME_ZONES), width=18).pack(side="left")
        self._button(tab, "查看时间", self.show_world_time).pack(side="left", padx=(12, 0))
        tk.Label(tab, textvariable=self.world_result, bg=PANEL, fg=SUCCESS, font=("Microsoft YaHei UI", 11)).pack(side="left", padx=(18, 0))
        return tab

    def _tick(self) -> None:
        if not self.is_open():
            return
        now = datetime.now().astimezone()
        self.clock_var.set(now.strftime("%H:%M:%S"))
        self.date_var.set(now.strftime("%Y年%m月%d日  %A"))
        self.window.after(1000, self._tick)

    def _report(self, message: str, ok: bool = True) -> None:
        self.on_result(message, ok)
        self.refresh_tasks()

    def set_timer(self) -> None:
        try:
            minutes = int(self.timer_minutes.get())
            if not 1 <= minutes <= 1440:
                raise ValueError
        except ValueError:
            self._report("倒计时分钟数需要在 1 到 1440 之间。", False)
            return
        due = datetime.now().astimezone() + timedelta(minutes=minutes)
        self.store.add("timer", due, self.timer_label.get(), SOUNDS[self.sound_name.get()])
        self._report(f"已设置 {minutes} 分钟倒计时：{self.timer_label.get()}。")

    def _set_clock_task(self, kind: str, hour: tk.StringVar, minute: tk.StringVar, day: tk.StringVar, label: tk.StringVar) -> None:
        due = resolve_clock_due(int(hour.get()), int(minute.get()), 1 if day.get() == "明天" else 0)
        sound = SOUNDS[self.sound_name.get()] if kind == "alarm" else "gentle"
        self.store.add(kind, due, label.get(), sound)
        noun = "闹钟" if kind == "alarm" else "提醒"
        self._report(f"已设置{format_due(due)}的{noun}：{label.get()}。")

    def set_alarm(self) -> None:
        self._set_clock_task("alarm", self.alarm_hour, self.alarm_minute, self.alarm_day, self.alarm_label)

    def preview_sound(self) -> None:
        sound = SOUNDS[self.sound_name.get()]

        def play() -> None:
            for frequency, duration in ALARM_PATTERNS[sound]:
                try:
                    winsound.Beep(frequency, duration)
                except RuntimeError:
                    winsound.MessageBeep()

        threading.Thread(target=play, daemon=True).start()

    def set_reminder(self) -> None:
        self._set_clock_task("reminder", self.reminder_hour, self.reminder_minute, self.reminder_day, self.reminder_label)

    def show_world_time(self) -> None:
        result = world_time(self.city.get())
        self.world_result.set(result or "暂不认识这个时区")

    def refresh_tasks(self) -> None:
        self.tasks = self.store.list_active()
        self.task_list.delete(0, "end")
        names = {"timer": "倒计时", "alarm": "闹钟", "reminder": "提醒"}
        for task in self.tasks:
            due = datetime.fromtimestamp(float(task.get("due_at", 0))).astimezone()
            self.task_list.insert("end", f"{due:%m-%d %H:%M}  {names.get(str(task.get('kind')), '提醒')}  ·  {task.get('label', '')}")
        if not self.tasks:
            self.task_list.insert("end", "目前没有等待中的计时项目")

    def cancel_selected(self) -> None:
        selection = self.task_list.curselection()
        if not selection or not self.tasks:
            return
        index = selection[0]
        if index >= len(self.tasks):
            return
        if self.store.cancel(str(self.tasks[index].get("id", ""))):
            self._report("已取消选中的计时项目。")


__all__ = ["TimeAssistantWindow"]
