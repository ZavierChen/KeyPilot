"""Shared limits for answer extraction and speech, independent of providers."""
import re

REPLY_LIMITS = {"低": 120, "中": 600, "高": 6000}


def reply_instruction(level: str) -> str:
    return {"低": "回复长度为低档：优先简短结论。",
            "中": "回复长度为中档：适度详细，短诗或明确要求的完整内容不要只给第一句。",
            "高": "回复长度为高档：尽量完整回答，不要仅给简介；背诗或朗读请求应提供完整作品，不要只给开头。"}.get(level, "")


def limit_reply(text: str, level: str) -> str:
    limit = REPLY_LIMITS.get(level, 600)
    if len(text) <= limit:
        return text
    prefix = text[:limit]
    ends = list(re.finditer(r"[。！？.!?\n]", prefix))
    if ends and ends[-1].end() >= limit // 2:
        prefix = prefix[:ends[-1].end()]
    return prefix.rstrip() + "……"


def speech_chunks(text: str, limit: int = 180) -> list[str]:
    """Preserve all characters and prefer nearby natural speech boundaries."""
    if limit < 1:
        raise ValueError("Speech chunk limit must be positive")
    chunks = []
    while len(text) > limit:
        strong = list(re.finditer(r"[。！？.!?；;\n]\s*", text[:limit]))
        soft = list(re.finditer(r"[，,：:]\s*", text[:limit]))
        if strong and strong[-1].end() >= max(8, limit // 3):
            end = strong[-1].end()
        elif soft and soft[-1].end() >= max(8, limit // 2):
            end = soft[-1].end()
        else:
            # A boundary just beyond the nominal limit is much less audible
            # than cutting a word or clause at exactly the character limit.
            nearby = re.search(r"[。！？.!?；;，,：:\n]\s*", text[limit:limit + 25])
            if nearby:
                end = limit + nearby.end()
            else:
                spaces = list(re.finditer(r"\s+", text[:limit + 1]))
                end = spaces[-1].end() if spaces and spaces[-1].end() >= limit // 2 else limit
        chunks.append(text[:end])
        text = text[end:]
    if text:
        chunks.append(text)
    return chunks


def progressive_speech_chunks(text: str, first_limit: int = 24, limit: int = 60) -> list[str]:
    """A short natural opening, then bounded chunks; never drop any text."""
    if first_limit < 1 or limit < 1:
        raise ValueError("Speech chunk limits must be positive")
    if len(text) <= first_limit:
        return [text] if text else []
    prefix = text[:first_limit]
    # Prefer the first complete sentence, but avoid tiny fragments like “好。”
    sentences = [m.end() for m in re.finditer(r"[。！？!?；;\n]\s*", prefix) if m.end() >= 8]
    clauses = [m.end() for m in re.finditer(r"[，,：:]\s*", prefix) if m.end() >= 8]
    if sentences:
        end = sentences[0]
    elif clauses:
        end = clauses[-1]
    else:
        # Do not hard-cut at 24 characters when a real pause is only a few
        # characters away. This was especially noticeable in cloned voices.
        nearby = re.search(r"[。！？!?；;，,：:\n]\s*", text[first_limit:first_limit + 25])
        if nearby:
            end = first_limit + nearby.end()
        else:
            spaces = list(re.finditer(r"\s+", prefix))
            end = spaces[-1].end() if spaces and spaces[-1].end() >= 8 else first_limit
    return [text[:end], *speech_chunks(text[end:], limit=limit)]


def split_mixed_language_chunks(parts: list[str]) -> list[str]:
    """Split Chinese/English switches only at punctuation, preserving every character."""
    result: list[str] = []
    for part in parts:
        has_chinese = bool(re.search(r"[\u3400-\u9fff]", part))
        has_english = bool(re.search(r"[A-Za-z]", part))
        if not (has_chinese and has_english):
            result.append(part)
            continue
        units = [match.group() for match in re.finditer(
            r".+?(?:[。！？.!?；;：:\n]+\s*|$)", part, flags=re.S
        ) if match.group()]
        if not units or "".join(units) != part:
            result.append(part)
            continue
        buffered = ""
        buffered_language = None
        for unit in units:
            language = "chinese" if re.search(r"[\u3400-\u9fff]", unit) else "english"
            if buffered and language != buffered_language:
                result.append(buffered)
                buffered = ""
            buffered += unit
            buffered_language = language
        if buffered:
            result.append(buffered)
    return result


def progressive_mixed_speech_chunks(
    text: str, first_limit: int = 24, limit: int = 60
) -> list[str]:
    """Keep language switches and length boundaries on complete spoken phrases."""
    runs = split_mixed_language_chunks([text])
    result: list[str] = []
    for index, run in enumerate(runs):
        if index == 0:
            result.extend(progressive_speech_chunks(run, first_limit=first_limit, limit=limit))
        else:
            result.extend(speech_chunks(run, limit=limit))
    return result
