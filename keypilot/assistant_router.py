from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .website_shortcuts import load_website_shortcuts


COMMON_WEBSITES = {
    "youtube": "https://www.youtube.com/",
    "google": "https://www.google.com/",
    "bilibili": "https://www.bilibili.com/",
    "github": "https://github.com/",
    "gmail": "https://mail.google.com/",
    "outlook": "https://outlook.live.com/mail/",
    "baidu": "https://www.baidu.com/",
    "zhihu": "https://www.zhihu.com/",
    "weibo": "https://weibo.com/",
    "xiaohongshu": "https://www.xiaohongshu.com/",
    "taobao": "https://www.taobao.com/",
    "jd": "https://www.jd.com/",
    "netflix": "https://www.netflix.com/",
    "spotify": "https://open.spotify.com/",
}

WEBSITE_ALIASES = {
    "youtube": "youtube",
    "油管": "youtube",
    "谷歌": "google",
    "google": "google",
    "b站": "bilibili",
    "哔哩哔哩": "bilibili",
    "bilibili": "bilibili",
    "github": "github",
    "git hub": "github",
    "gmail": "gmail",
    "谷歌邮箱": "gmail",
    "outlook": "outlook",
    "百度": "baidu",
    "知乎": "zhihu",
    "微博": "weibo",
    "小红书": "xiaohongshu",
    "淘宝": "taobao",
    "京东": "jd",
    "netflix": "netflix",
    "奈飞": "netflix",
    "spotify": "spotify",
}


@dataclass(frozen=True)
class SkillCall:
    skill_id: str
    arguments: dict[str, Any]
    spoken_response: str
    confidence: float = 1.0


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _parse_chinese_number(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if value == "百":
        return 100
    if "十" in value:
        left, right = value.split("十", 1)
        tens = _CHINESE_DIGITS.get(left, 1) if left else 1
        ones = _CHINESE_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    if len(value) == 1:
        return _CHINESE_DIGITS.get(value)
    digits = [_CHINESE_DIGITS.get(char) for char in value]
    if all(digit is not None for digit in digits):
        return int("".join(str(digit) for digit in digits))
    return None


def normalize_text(text: str) -> str:
    normalized = text.strip().lower()
    normalized = normalized.replace("％", "%")
    normalized = re.sub(r"[，。！？、,.!?]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    for filler in (
        "请帮我",
        "麻烦帮我",
        "能不能帮我",
        "可以帮我",
        "帮我",
        "请",
        "一下",
        "好吗",
        "谢谢",
    ):
        normalized = normalized.replace(filler, "")
    return re.sub(r"\s+", " ", normalized).strip()


def classify_fallback_intent(text: str) -> str:
    """Route ordinary conversation locally/cloud and explicit work to Codex."""
    normalized = normalize_text(text)
    question_markers = (
        "什么",
        "为什么",
        "怎么",
        "如何",
        "哪里",
        "哪个",
        "谁",
        "多少",
        "是不是",
        "能否",
        "可以吗",
        "告诉我",
        "解释",
        "介绍",
    )
    action_markers = (
        "创建",
        "修改",
        "删除",
        "安装",
        "卸载",
        "下载",
        "整理",
        "生成",
        "写一个",
        "修复",
        "运行",
        "执行",
        "配置",
        "重构",
        "编程",
        "脚本",
    )
    if any(marker in normalized for marker in action_markers):
        return "codex"
    if "?" in text or "？" in text or any(marker in normalized for marker in question_markers):
        return "chat"
    return "chat"


def _extract_percent(text: str) -> int | None:
    match = re.search(r"(?:百分之)?\s*(\d{1,3})\s*%?", text)
    if match:
        return max(0, min(100, int(match.group(1))))
    match = re.search(r"(?:百分之)?([零〇一二两三四五六七八九十百]{1,4})", text)
    if not match:
        return None
    number = _parse_chinese_number(match.group(1))
    return None if number is None else max(0, min(100, number))


def _extract_duration_seconds(text: str) -> int | None:
    total = 0
    if "一个半小时" in text:
        total += 5400
        text = text.replace("一个半小时", "")
    if "半小时" in text:
        total += 1800
        text = text.replace("半小时", "")
    for pattern, multiplier in (
        (r"(\d+|[零〇一二两三四五六七八九十百]+)\s*个?小时", 3600),
        (r"(\d+|[零〇一二两三四五六七八九十百]+)\s*分(?:钟)?", 60),
        (r"(\d+|[零〇一二两三四五六七八九十百]+)\s*秒(?:钟)?", 1),
    ):
        for match in re.finditer(pattern, text):
            number = _parse_chinese_number(match.group(1))
            if number is not None:
                total += number * multiplier
    return total if total > 0 else None


def _extract_clock_time(text: str) -> tuple[int, int] | None:
    match = re.search(r"(\d{1,2}|[零〇一二两三四五六七八九十]{1,3})\s*(?:点|时)", text)
    if not match:
        return None
    hour = _parse_chinese_number(match.group(1))
    if hour is None or hour > 23:
        return None
    suffix = text[match.end() :]
    minute = 30 if suffix.startswith("半") else 0
    minute_match = re.match(r"\s*(\d{1,2}|[零〇一二两三四五六七八九十]{1,3})\s*分?", suffix)
    if minute_match:
        parsed_minute = _parse_chinese_number(minute_match.group(1))
        if parsed_minute is not None:
            minute = parsed_minute
    if minute > 59:
        return None
    if any(marker in text for marker in ("下午", "晚上", "傍晚")) and hour < 12:
        hour += 12
    if "中午" in text and 1 <= hour < 11:
        hour += 12
    if "凌晨" in text and hour == 12:
        hour = 0
    return hour, minute


class SkillRegistry:
    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir
        self.skills = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        loaded: dict[str, dict[str, Any]] = {}
        if not self.skills_dir.exists():
            return loaded
        for path in sorted(self.skills_dir.glob("*/skill.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            skill_id = payload.get("id")
            if isinstance(skill_id, str) and skill_id:
                loaded[skill_id] = payload
        return loaded

    def can_execute_without_confirmation(self, call: SkillCall | None) -> bool:
        """Only explicitly low-risk, no-confirmation skills may run from dictation."""
        if call is None:
            return False
        skill = self.skills.get(call.skill_id, {})
        return skill.get("risk") == "low" and skill.get("confirmation") == "never"


class LocalCommandRouter:
    SETTINGS_TOPICS = {
        "蓝牙": "bluetooth",
        "wifi": "wifi",
        "wi-fi": "wifi",
        "无线网络": "wifi",
        "网络": "network",
        "声音": "sound",
        "音频": "sound",
        "麦克风": "sound",
        "显示": "display",
        "屏幕": "display",
        "亮度": "display",
        "应用": "apps",
        "卸载": "apps",
        "存储": "storage",
        "磁盘空间": "storage",
        "更新": "windows_update",
        "windows更新": "windows_update",
        "通知": "notifications",
        "隐私": "privacy",
        "电源": "power",
        "睡眠": "power",
        "时间": "date_time",
        "日期": "date_time",
        "语言": "language",
        "鼠标": "mouse",
        "触摸板": "mouse",
        "个性化": "personalization",
        "壁纸": "background",
        "主题": "themes",
    }

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def route(self, utterance: str) -> SkillCall | None:
        text = normalize_text(utterance)
        if not text:
            return None

        call = self._route_browser_read(utterance, text)
        if call:
            return call
        call = self._route_website(utterance, text)
        if call:
            return call
        call = self._route_volume(text)
        if call:
            return call
        call = self._route_brightness(text)
        if call:
            return call
        call = self._route_weather(text)
        if call:
            return call
        call = self._route_time(text)
        if call:
            return call
        call = self._route_settings(text)
        if call:
            return call
        call = self._route_app(text)
        if call:
            return call
        return None

    @staticmethod
    def _route_browser_read(utterance: str, text: str) -> SkillCall | None:
        browser_markers = ("当前网页", "这个网页", "浏览器页面", "页面内容", "网页内容")
        read_markers = ("读", "总结", "概括", "讲了什么", "说了什么", "回答")
        if any(marker in text for marker in browser_markers) and any(
            marker in text for marker in read_markers
        ):
            return SkillCall(
                "read_browser_page",
                {"question": utterance.strip()},
                "",
                confidence=0.95,
            )
        return None

    def _route_time(self, text: str) -> SkillCall | None:
        if "倒计时" in text:
            seconds = _extract_duration_seconds(text)
            if seconds is None:
                return None
            label_match = re.search(r"提醒我\s*(.+)$", text)
            label = label_match.group(1).strip() if label_match else "倒计时结束"
            return SkillCall(
                "set_timer",
                {"seconds": seconds, "label": label},
                "",
            )

        is_alarm = "闹钟" in text or "叫我起床" in text
        is_reminder = "提醒我" in text or "日历" in text
        if is_alarm or is_reminder:
            clock = _extract_clock_time(text)
            if clock is None:
                delayed = _extract_duration_seconds(text) if "后" in text else None
                if delayed:
                    label_match = re.search(r"提醒我\s*(.+)$", text)
                    label = label_match.group(1).strip() if label_match else "提醒事项"
                    return SkillCall("set_timer", {"seconds": delayed, "label": label}, "")
                return None
            hour, minute = clock
            now = datetime.now().astimezone()
            if "后天" in text:
                day_offset = 2
            elif "明天" in text or "明早" in text or "明晚" in text:
                day_offset = 1
            else:
                weekday_match = re.search(r"(?:周|星期)([一二三四五六日天])", text)
                if weekday_match:
                    target_weekday = "一二三四五六日".index(
                        "日" if weekday_match.group(1) == "天" else weekday_match.group(1)
                    )
                    day_offset = (target_weekday - now.weekday()) % 7
                    if day_offset == 0 and (hour, minute) <= (now.hour, now.minute):
                        day_offset = 7
                else:
                    day_offset = 0
            label_match = re.search(r"(?:提醒我|叫我)\s*(.+)$", text)
            if label_match:
                label = label_match.group(1).strip()
            elif "日历" in text:
                label = text
                for pattern in (
                    r"(?:在)?日历(?:里|中)?(?:添加|加入|新建)?",
                    r"(?:今天|明天|后天|明早|明晚|周[一二三四五六日天]|星期[一二三四五六日天])",
                    r"(?:上午|下午|晚上|中午|凌晨|傍晚)?(?:\d{1,2}|[零〇一二两三四五六七八九十]{1,3})点(?:半|\d{1,2}分?)?",
                    r"(?:提醒|事件|日程)",
                ):
                    label = re.sub(pattern, "", label)
                label = label.strip() or "日历事件"
            else:
                label = "起床" if "叫我起床" in text else "闹钟" if is_alarm else "提醒事项"
            label = re.sub(r"(?:添加|加入|放到)?日历(?:里|中)?", "", label).strip() or "提醒事项"
            arguments = {
                "hour": hour,
                "minute": minute,
                "day_offset": day_offset,
                "label": label,
            }
            if is_alarm:
                return SkillCall("set_alarm", arguments, "")
            arguments["calendar"] = "日历" in text
            return SkillCall("set_reminder", arguments, "")

        if "设置" not in text and (
            "几点" in text or ("时间" in text and any(marker in text for marker in ("现在", "当前", "当地")))
        ):
            location = text
            for filler in ("现在", "当前", "当地", "的", "是", "几点", "时间", "多少", "请问"):
                location = location.replace(filler, "")
            return SkillCall(
                "get_world_time",
                {"location": location.strip() or "本地"},
                "",
            )
        return None

    def _route_website(self, utterance: str, text: str) -> SkillCall | None:
        raw = utterance.strip()
        url_match = re.search(
            r"(?:https?://|www\.)[^\s，。！？]+|(?<![\w@])(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s，。！？]*)?",
            raw,
            re.IGNORECASE,
        )
        if url_match and any(marker in text for marker in ("打开", "访问", "进入", "浏览")):
            target = url_match.group(0).rstrip(".,")
            return SkillCall(
                "open_website",
                {"mode": "url", "target": target},
                "正在用浏览器打开网址。",
            )

        search_match = re.match(
            r"^(?:在)?(?:浏览器|谷歌|google)?(?:里|中)?(?:搜索|搜一下|查一下|查询)\s*(.+)$",
            text,
        )
        if search_match and search_match.group(1).strip():
            query = search_match.group(1).strip()
            return SkillCall(
                "open_website",
                {"mode": "search", "target": query},
                f"正在浏览器中搜索{query}。",
            )

        if not any(marker in text for marker in ("打开", "访问", "进入", "浏览", "去")):
            return None
        compact = text.replace(" ", "")
        custom_shortcuts = load_website_shortcuts()
        for keyword, url in sorted(custom_shortcuts.items(), key=lambda item: len(item[0]), reverse=True):
            normalized_keyword = normalize_text(keyword).replace(" ", "")
            if normalized_keyword and normalized_keyword in compact:
                return SkillCall(
                    "open_website",
                    {"mode": "url", "target": url},
                    f"正在打开{keyword}。",
                )
        for alias, site_id in sorted(WEBSITE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if alias.replace(" ", "") in compact:
                return SkillCall(
                    "open_website",
                    {"mode": "site", "target": site_id},
                    f"正在打开{alias}。",
                )
        if any(marker in text for marker in ("网站", "网页", "官网")):
            query = re.sub(r"^(?:打开|访问|进入|浏览|去)\s*", "", text).strip()
            return SkillCall(
                "open_website",
                {"mode": "search", "target": query},
                f"正在浏览器中搜索{query}。",
            )
        explicit_web = re.match(r"^(?:访问|浏览|去)\s*(.+)$", text)
        if explicit_web and explicit_web.group(1).strip():
            query = explicit_web.group(1).strip()
            return SkillCall(
                "open_website",
                {"mode": "search", "target": query},
                f"正在浏览器中搜索{query}。",
            )
        return None

    def _route_weather(self, text: str) -> SkillCall | None:
        if "天气" not in text:
            return None
        day = "tomorrow" if "明天" in text else "today"
        location = text
        for filler in (
            "电脑",
            "本地",
            "这里",
            "我这",
            "附近",
            "今天",
            "今日",
            "现在",
            "当前",
            "明天",
            "的天气",
            "天气",
            "预报",
            "怎么样",
            "如何",
            "是什么",
            "查一下",
            "看一下",
            "看看",
        ):
            location = location.replace(filler, "")
        location = location.strip()
        return SkillCall(
            "get_weather",
            {"location": location, "day": day},
            "",
            confidence=0.95,
        )

    def _route_volume(self, text: str) -> SkillCall | None:
        if not any(word in text for word in ("音量", "声音", "静音", "取消静音")):
            return None
        if "取消静音" in text or "恢复声音" in text:
            return SkillCall("set_volume", {"operation": "unmute"}, "已取消静音。")
        if "静音" in text:
            return SkillCall("set_volume", {"operation": "mute"}, "已静音。")
        if any(word in text for word in ("当前", "多少", "几")):
            return SkillCall("set_volume", {"operation": "get"}, "")
        percent = _extract_percent(text)
        if percent is not None and any(word in text for word in ("调到", "设置", "设为", "改成", "%", "百分之")):
            return SkillCall(
                "set_volume",
                {"operation": "set", "percent": percent},
                f"音量已调到百分之{percent}。",
            )
        if any(word in text for word in ("调高", "增大", "大点", "大一点", "提高", "增加")):
            return SkillCall("set_volume", {"operation": "up"}, "已调高音量。")
        if any(word in text for word in ("调低", "减小", "小点", "小一点", "降低", "减少")):
            return SkillCall("set_volume", {"operation": "down"}, "已调低音量。")
        return None

    def _route_brightness(self, text: str) -> SkillCall | None:
        if not any(word in text for word in ("亮度", "屏幕亮", "屏幕暗", "调亮", "调暗")):
            return None
        if any(word in text for word in ("当前", "多少", "几")):
            return SkillCall("set_brightness", {"operation": "get"}, "")
        percent = _extract_percent(text)
        if percent is not None:
            return SkillCall(
                "set_brightness",
                {"operation": "set", "percent": percent},
                f"屏幕亮度已调到百分之{percent}。",
            )
        if any(word in text for word in ("调高", "提高", "调亮", "亮一点", "增加")):
            return SkillCall("set_brightness", {"operation": "up", "step": 10}, "已调高屏幕亮度。")
        if any(word in text for word in ("调低", "降低", "调暗", "暗一点", "减少")):
            return SkillCall("set_brightness", {"operation": "down", "step": 10}, "已调低屏幕亮度。")
        return None

    def _route_settings(self, text: str) -> SkillCall | None:
        if "设置" not in text and re.match(
            r"^(?:打开|启动|运行|开启|唤起|开)\s*.+(?:应用|软件|程序)$",
            text,
        ):
            return None
        if "设置" not in text and not any(topic in text for topic in self.SETTINGS_TOPICS):
            return None
        for phrase, topic in sorted(self.SETTINGS_TOPICS.items(), key=lambda item: len(item[0]), reverse=True):
            if phrase in text:
                return SkillCall(
                    "open_settings",
                    {"topic": topic, "query": phrase},
                    f"已打开{phrase}设置。",
                )
        query = re.sub(r"^(?:在)?设置(?:里|中)?(?:搜索|查找|找)?", "", text)
        query = re.sub(r"^(打开|进入|搜索|查找|找)", "", query)
        query = re.sub(r"设置$", "", query).strip() or "设置"
        return SkillCall(
            "open_settings",
            {"topic": "search", "query": query},
            f"正在设置中搜索{query}。",
            confidence=0.85,
        )

    def _route_app(self, text: str) -> SkillCall | None:
        match = re.match(r"^(?:打开|启动|运行|开启|唤起|开)\s*(.+)$", text)
        if not match:
            return None
        app = match.group(1).strip()
        app = re.sub(
            r"^(?:桌面中的|桌面上的|桌面里的|桌面中|桌面上|桌面里|桌面)(?:的)?",
            "",
            app,
        ).strip()
        app = re.sub(r"(?:应用|软件|程序)$", "", app).strip()
        if not app:
            return None
        return SkillCall("open_app", {"app": app}, f"正在打开{app}。", confidence=0.95)


__all__ = [
    "COMMON_WEBSITES",
    "classify_fallback_intent",
    "LocalCommandRouter",
    "SkillCall",
    "SkillRegistry",
    "normalize_text",
]
