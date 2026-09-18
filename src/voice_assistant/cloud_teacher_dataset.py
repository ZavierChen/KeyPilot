from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import time
import uuid
import wave
from ctypes import wintypes
from pathlib import Path

import websockets

from voice_assistant.providers.volcengine_protocol import Event, Message, MsgType, event_message


CORPUS = [
    "你好，我是本地助手，很高兴继续陪你测试语音功能。",
    "今天阳光很好，窗边的绿叶被照得格外清楚。",
    "如果你有点累，就先喝口水，慢慢来，不用着急。",
    "请帮我打开音乐，把音量调到百分之三十五。",
    "明天早上七点半提醒我起床，别忘了带上雨伞。",
    "现在是下午三点零五分，距离会议开始还有二十五分钟。",
    "你想先听故事，还是先整理今天的任务清单？",
    "好的，我已经记下来了，稍后会按时提醒你。",
    "这件事情并不复杂，我们一步一步处理就可以了。",
    "厨房里有苹果、牛奶、鸡蛋，还有一小盒草莓。",
    "请确认文件名、保存位置和最后修改时间都没有问题。",
    "网络连接已经恢复，刚才没有发送成功的内容正在重试。",
    "从北京到上海大约一千二百公里，乘高铁会更方便。",
    "编号是二零二六九零八，请你再核对一遍。",
    "温度二十三摄氏度，湿度百分之六十八，体感比较舒适。",
    "我没有听清最后几个字，可以麻烦你再说一遍吗？",
    "没关系，这次结果不理想，我们换一种方法再试试。",
    "太好了，所有检查都已经通过，现在可以正常使用了。",
    "等等，这个选项会覆盖原来的设置，你确定要继续吗？",
    "别担心，原始录音和当前语音包都已经安全保留。",
    "春风吹过安静的街道，远处传来清脆的自行车铃声。",
    "清晨的湖面很平静，偶尔有几只小鸟从水面掠过。",
    "红橙黄绿青蓝紫，每一种颜色都有不同的感觉。",
    "玻璃杯里放着冰块，轻轻一碰就发出清亮的声音。",
    "这段话包含声母和韵母，用来检查发音是否清楚自然。",
    "知春路、石景山、长江桥，这几个词要读得完整一些。",
    "七只气球轻轻飘起，青青的草地就在桥的那一边。",
    "人们仍然认真讨论人工智能如何改善日常生活。",
    "零点零五、百分之九十九和三分之二都需要准确朗读。",
    "网址、验证码和英文字母出现时，请保持稳定的节奏。",
    "KeyPilot 已经准备好了，你现在可以直接开始说话。",
    "CPU 模型会在本地运行，断开网络后也能继续合成语音。",
    "请播放下一首歌，然后把屏幕亮度稍微调低一点。",
    "收到，我会把重要信息放在最前面，回答尽量简洁。",
    "你刚才说的是周五下午，对吗？我再确认一下日期。",
    "有些决定可以晚一点做，先把最关键的问题解决掉。",
    "雨停以后，空气里有泥土和树叶混合起来的清新味道。",
    "她轻轻笑了一下，说今天确实是个值得纪念的日子。",
    "欢迎回来，设备状态正常，我们可以接着上次的进度。",
    "训练结束后要先试听对比，确认更自然再替换正式版本。",
]


def corpus_from_srt(paths: list[Path]) -> list[str]:
    """Read reviewed SRT blocks as natural, already-approved speaking material."""
    results: list[str] = []
    seen: set[str] = set()
    for path in paths:
        raw = path.read_text(encoding="utf-8-sig")
        for block in raw.replace("\r\n", "\n").split("\n\n"):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if len(lines) < 3 or "-->" not in lines[1]:
                continue
            text = "".join(lines[2:]).replace(",", "，").strip()
            text = " ".join(text.split())
            if 8 <= len(text) <= 70 and text not in seen:
                seen.add(text)
                results.append(text)
    return results


def corpus_from_text_files(paths: list[Path]) -> list[str]:
    """Read one approved training sentence per line from UTF-8 text files."""
    results: list[str] = []
    seen: set[str] = set()
    for path in paths:
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            text = " ".join(raw_line.strip().split())
            # Preserve English punctuation.  Replacing every ASCII comma with
            # a Chinese comma subtly changes multilingual teacher prosody.
            if any("\u4e00" <= character <= "\u9fff" for character in text):
                text = text.replace(",", "，")
            if not text or text.startswith("#"):
                continue
            if not 8 <= len(text) <= 70:
                raise ValueError(f"训练句长度必须为 8 到 70 字：{path}: {text}")
            if text not in seen:
                seen.add(text)
                results.append(text)
    return results


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def load_dpapi_secret(path: Path) -> str:
    if os.name != "nt":
        raise RuntimeError("DPAPI 密钥文件只能由创建它的 Windows 用户读取。")
    encrypted = path.read_bytes()
    source_buffer = ctypes.create_string_buffer(encrypted)
    source = _DataBlob(len(encrypted), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    plain = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(plain)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(plain.pbData, plain.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(plain.pbData)


def build_req_params(
    *,
    speaker_id: str,
    model: str,
    sample_rate: int,
    context_texts: list[str] | None = None,
) -> dict:
    """Build one Volcengine TTS 2.0 request without leaking credentials.

    ``context_texts`` is intentionally a top-level ``req_params`` field.  It is
    the documented TTS 2.0 mechanism for supplying conversational or style
    context and is different from the JSON-encoded compatibility additions.
    """
    params = {
        "model": model,
        "speaker": speaker_id,
        "audio_params": {
            "format": "pcm",
            "sample_rate": sample_rate,
            "speech_rate": 0,
            "loudness_rate": 0,
        },
        "additions": json.dumps(
            {"disable_markdown_filter": True, "disable_emoji_filter": True}
        ),
    }
    if context_texts:
        params["context_texts"] = list(context_texts)
    return params


class TeacherSynthesizer:
    def __init__(
        self,
        api_key: str,
        speaker_id: str,
        resource_id: str,
        model: str,
        sample_rate: int,
        context_texts: list[str] | None = None,
    ):
        self.api_key = api_key
        self.speaker_id = speaker_id
        self.resource_id = resource_id
        self.model = model
        self.sample_rate = sample_rate
        self.context_texts = list(context_texts or [])
        self.url = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"

    @staticmethod
    def _raise_if_error(message: Message) -> None:
        if message.msg_type == MsgType.ERROR or message.event in {Event.CONNECTION_FAILED, Event.SESSION_FAILED}:
            detail = message.payload.decode("utf-8", errors="replace")
            raise RuntimeError(f"火山引擎合成失败：code={message.error_code}, detail={detail}")

    async def _expect(self, websocket, event: Event) -> Message:
        message = Message.decode(await websocket.recv())
        self._raise_if_error(message)
        if message.event != event:
            raise RuntimeError(f"协议事件异常：需要 {event.name}，收到 {message.event}")
        return message

    async def synthesize_many(self, items: list[tuple[str, str]], output_dir: Path) -> list[dict]:
        headers = {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
            "X-Control-Require-Usage-Tokens-Return": "*",
        }
        records: list[dict] = []
        async with websockets.connect(
            self.url, additional_headers=headers, max_size=10 * 1024 * 1024,
            ping_interval=20, ping_timeout=20, open_timeout=15,
        ) as websocket:
            await websocket.send(event_message(Event.START_CONNECTION))
            await self._expect(websocket, Event.CONNECTION_STARTED)
            for item_id, text in items:
                wav_path = output_dir / "audio" / f"{item_id}.wav"
                if wav_path.is_file() and wav_path.stat().st_size > 44:
                    records.append(_wav_record(item_id, text, wav_path, self.sample_rate, reused=True))
                    continue
                session_id = str(uuid.uuid4())
                request_base = {"req_params": build_req_params(
                    speaker_id=self.speaker_id,
                    model=self.model,
                    sample_rate=self.sample_rate,
                    context_texts=self.context_texts,
                )}
                started = time.perf_counter()
                payload = {**request_base, "event": int(Event.START_SESSION)}
                await websocket.send(event_message(
                    Event.START_SESSION,
                    json.dumps(payload, ensure_ascii=False).encode("utf-8"), session_id,
                ))
                await self._expect(websocket, Event.SESSION_STARTED)
                task_payload = json.loads(json.dumps(request_base))
                task_payload["event"] = int(Event.TASK_REQUEST)
                task_payload["req_params"]["text"] = text
                await websocket.send(event_message(
                    Event.TASK_REQUEST,
                    json.dumps(task_payload, ensure_ascii=False).encode("utf-8"), session_id,
                ))
                await websocket.send(event_message(Event.FINISH_SESSION, session_id=session_id))
                chunks: list[bytes] = []
                first_audio_ms = None
                while True:
                    message = Message.decode(await websocket.recv())
                    self._raise_if_error(message)
                    if message.msg_type == MsgType.AUDIO_ONLY_SERVER:
                        if first_audio_ms is None:
                            first_audio_ms = round((time.perf_counter() - started) * 1000, 1)
                        chunks.append(message.payload)
                    elif message.event == Event.SESSION_FINISHED:
                        break
                pcm = b"".join(chunks)
                wav_path.parent.mkdir(parents=True, exist_ok=True)
                with wave.open(str(wav_path), "wb") as out:
                    out.setnchannels(1)
                    out.setsampwidth(2)
                    out.setframerate(self.sample_rate)
                    out.writeframes(pcm)
                record = _wav_record(item_id, text, wav_path, self.sample_rate, reused=False)
                record["first_audio_ms"] = first_audio_ms
                record["synthesis_ms"] = round((time.perf_counter() - started) * 1000, 1)
                records.append(record)
                print(f"[{len(records)}/{len(items)}] {item_id}: {record['duration_seconds']:.2f}s, {len(text)} 字")
            await websocket.send(event_message(Event.FINISH_CONNECTION))
            try:
                await asyncio.wait_for(self._expect(websocket, Event.CONNECTION_FINISHED), timeout=2)
            except Exception:
                pass
        return records


def _wav_record(item_id: str, text: str, path: Path, sample_rate: int, reused: bool) -> dict:
    data = path.read_bytes()
    with wave.open(str(path), "rb") as stream:
        duration = stream.getnframes() / stream.getframerate()
    return {
        "id": item_id, "text": text, "wav": str(path.resolve()),
        "duration_seconds": round(duration, 3), "sample_rate": sample_rate,
        "sha256": hashlib.sha256(data).hexdigest(), "resumed_existing": reused,
    }


def write_manifests(
    output_dir: Path,
    records: list[dict],
    speaker_id: str,
    model: str,
    context_texts: list[str] | None = None,
    style_label: str = "neutral",
) -> None:
    ordered = sorted(records, key=lambda row: row["id"])
    # ZipVoice/Lhotse's validation loader creates ten duration buckets, so the
    # pilot must keep at least ten validation cuts.  A 3:1 split provides that
    # minimum for the built-in 40-utterance corpus.
    dev_ids = {row["id"] for index, row in enumerate(ordered) if index % 4 == 3}
    for split in ("train", "dev"):
        rows = [row for row in ordered if (row["id"] in dev_ids) == (split == "dev")]
        path = output_dir / f"custom_{split}.tsv"
        path.write_text("".join(f"{row['id']}\t{row['text']}\t{row['wav']}\n" for row in rows), encoding="utf-8")
    summary = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "speaker_id": speaker_id, "teacher_model": model,
        "context_texts": list(context_texts or []),
        "style_label": style_label,
        "utterances": len(ordered),
        "text_characters": sum(len(row["text"]) for row in ordered),
        "audio_minutes": round(sum(row["duration_seconds"] for row in ordered) / 60, 2),
        "train_utterances": sum(row["id"] not in dev_ids for row in ordered),
        "dev_utterances": sum(row["id"] in dev_ids for row in ordered),
        "records": ordered,
    }
    (output_dir / "dataset-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="用已授权的火山复刻音色生成 ZipVoice 微调语料")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--speaker-id", required=True, help="Your own authorized speaker ID")
    parser.add_argument("--resource-id", default="seed-icl-2.0")
    parser.add_argument("--model", default="seed-tts-2.0-standard")
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--key-file", type=Path, help="Optional DPAPI key file; otherwise use VOLCENGINE_SPEECH_API_KEY")
    parser.add_argument("--limit", type=int, default=40, help="首轮最多合成多少条；可重复运行续传")
    parser.add_argument("--srt", type=Path, action="append", default=[], help="从已校对 SRT 提取自然口语；可重复指定")
    parser.add_argument("--text-file", type=Path, action="append", default=[], help="UTF-8 纯文本，每行一条已审核训练句；可重复指定")
    parser.add_argument("--prefix", default="cloud", help="文件 ID 前缀，用于分开不同批次")
    parser.add_argument(
        "--context-text",
        action="append",
        default=[],
        help="声音复刻 2.0 的语境/语气提示；可重复指定并写入 context_texts",
    )
    parser.add_argument("--style-label", default="neutral", help="记录到数据集摘要中的预期语气标签")
    parser.add_argument("--consent", action="store_true", help="确认声音本人已授权本次本地模型训练")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.consent:
        raise SystemExit("拒绝生成：只有确认声音本人已授权后才能添加 --consent。")
    corpus: list[str] = []
    if args.srt:
        corpus.extend(corpus_from_srt(args.srt))
    if args.text_file:
        existing = set(corpus)
        corpus.extend(text for text in corpus_from_text_files(args.text_file) if text not in existing)
    if not corpus:
        corpus = CORPUS
    if not 1 <= args.limit <= len(corpus):
        raise SystemExit(f"--limit 必须在 1 到 {len(corpus)} 之间。")
    if args.key_file:
        api_key = load_dpapi_secret(args.key_file)
    else:
        from voice_assistant.config import Settings
        settings = Settings.from_env()
        settings.require_api_key()
        api_key = settings.api_key
    items = [(f"{args.prefix}_{index:04d}", text) for index, text in enumerate(corpus[: args.limit], start=1)]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    synth = TeacherSynthesizer(
        api_key,
        args.speaker_id,
        args.resource_id,
        args.model,
        args.sample_rate,
        context_texts=args.context_text,
    )
    records = asyncio.run(synth.synthesize_many(items, args.output_dir))
    write_manifests(
        args.output_dir,
        records,
        args.speaker_id,
        args.model,
        context_texts=args.context_text,
        style_label=args.style_label,
    )
    print(f"完成：{args.output_dir / 'dataset-summary.json'}")


if __name__ == "__main__":
    main()
