"""Small, deterministic text normalization for Chinese local speech models."""
from __future__ import annotations

import re


_DIGITS = "零一二三四五六七八九"
_UNITS = ("", "十", "百", "千")
_GROUP_UNITS = ("", "万", "亿", "兆")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _digits(value: str) -> str:
    return "".join(_DIGITS[int(char)] for char in value)


def _four_digits(value: int) -> str:
    if value == 0:
        return ""
    result = []
    pending_zero = False
    for position in range(3, -1, -1):
        divisor = 10 ** position
        digit = value // divisor % 10
        if digit:
            if pending_zero and result:
                result.append("零")
            result.append(_DIGITS[digit] + _UNITS[position])
            pending_zero = False
        elif result and value % divisor:
            pending_zero = True
    text = "".join(result)
    return text[1:] if text.startswith("一十") else text


def chinese_integer(value: str) -> str:
    number = int(value)
    if number == 0:
        return "零"
    if number >= 10 ** 16:
        return _digits(value)
    groups = []
    while number:
        groups.append(number % 10000)
        number //= 10000
    result = []
    zero_between = False
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if not group:
            if result:
                zero_between = True
            continue
        if result and (zero_between or group < 1000):
            result.append("零")
        result.append(_four_digits(group) + _GROUP_UNITS[index])
        zero_between = False
    return "".join(result)


def _is_english_number(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 10):start]
    after = text[end:min(len(text), end + 10)]
    immediate_before = text[start - 1] if start else ""
    immediate_after = text[end] if end < len(text) else ""
    if _LATIN_RE.match(immediate_before) or _LATIN_RE.match(immediate_after):
        return True
    if immediate_before in "-_" and before[:-1] and _LATIN_RE.search(before[:-1]):
        return True
    if immediate_after in "-_" and _LATIN_RE.search(after[1:]):
        return True
    if _CJK_RE.match(immediate_before) or _CJK_RE.match(immediate_after):
        return False
    window = before + after
    return len(_LATIN_RE.findall(window)) > len(_CJK_RE.findall(window))


def normalize_chinese_numbers(text: str) -> str:
    """Read Arabic numbers in Chinese context while preserving English/model tokens."""
    if not re.search(r"\d", text):
        return text

    protected: dict[str, str] = {}

    def protect_english(match: re.Match[str]) -> str:
        if not _is_english_number(text, match.start(), match.end()):
            return match.group(0)
        marker = "\ue000" + chr(0xE100 + len(protected)) + "\ue001"
        protected[marker] = match.group(0)
        return marker

    value = re.sub(r"\d+(?:\.\d+)?", protect_english, text)

    def date(match: re.Match[str]) -> str:
        return (
            _digits(match.group(1)) + "年" + chinese_integer(match.group(2))
            + "月" + chinese_integer(match.group(3)) + "日"
        )

    value = re.sub(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", date, value)
    value = re.sub(
        r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?",
        lambda m: chinese_integer(m.group(1)) + "点" + _digits(m.group(2))
        + ("分" + _digits(m.group(3)) + "秒" if m.group(3) else "分"),
        value,
    )
    value = re.sub(
        r"(-?\d+(?:\.\d+)?)\s*[%％]",
        lambda m: "百分之" + _number_value(m.group(1)), value,
    )
    value = re.sub(r"(?<!\d)(\d{4})(?=年)", lambda m: _digits(m.group(1)), value)
    value = re.sub(r"-?\d+(?:\.\d+)?", lambda m: _number_value(m.group(0)), value)
    for marker, original in protected.items():
        value = value.replace(marker, original)
    return value


def _number_value(value: str) -> str:
    sign = "负" if value.startswith("-") else ""
    value = value.removeprefix("-")
    if "." in value:
        whole, fraction = value.split(".", 1)
        return sign + chinese_integer(whole) + "点" + _digits(fraction)
    return sign + chinese_integer(value)


__all__ = ["chinese_integer", "normalize_chinese_numbers"]
