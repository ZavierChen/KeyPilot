from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from voice_assistant.audio.playback import NullAudioSink, PCM16Playback
from voice_assistant.config import Settings
from voice_assistant.pipeline import speak_stream
from voice_assistant.providers.volcengine import (
    VolcengineStreamingTTS,
    VolcengineVoiceCloneClient,
    chunk_text,
)
from voice_assistant.voice_profiles import VoiceProfile, VoiceProfileStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="火山引擎声音复刻低延迟原型")
    parser.add_argument("--env", default=".env", help="环境变量文件")
    sub = parser.add_subparsers(dest="command", required=True)

    train = sub.add_parser("train", help="上传授权录音并训练音色")
    train.add_argument("--audio", type=Path, required=True)
    train.add_argument("--speaker-id", required=True, help="预付费槽位 ID；后付费传 custom_speaker_id")
    train.add_argument("--custom-speaker-id")
    train.add_argument("--profile", required=True, help="本地音色配置名")
    train.add_argument("--text", help="录音逐字稿，建议提供")
    train.add_argument("--demo-text", help="4~300 字试听文本")
    train.add_argument("--language", type=int, default=0, help="0 中文，1 英文")
    train.add_argument("--denoise", action="store_true")
    train.add_argument("--consent", action="store_true", help="确认已获得声音本人授权")

    status = sub.add_parser("status", help="查询音色训练状态")
    status.add_argument("--speaker-id", required=True)
    status.add_argument("--custom-speaker-id")

    tts = sub.add_parser("tts", help="在线流式合成并播放或保存 PCM")
    tts.add_argument("--text", required=True)
    choice = tts.add_mutually_exclusive_group(required=True)
    choice.add_argument("--profile")
    choice.add_argument("--speaker-id")
    tts.add_argument("--play", action="store_true")
    tts.add_argument("--output", type=Path)
    tts.add_argument("--chunk-size", type=int, default=12)
    tts.add_argument("--chunk-delay-ms", type=int, default=0)

    remove = sub.add_parser("delete-profile", help="删除本地音色配置（不删除云端音色）")
    remove.add_argument("--profile", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env(args.env)
    profiles = VoiceProfileStore(settings.profile_dir)

    if args.command == "train":
        if not args.consent:
            raise SystemExit("拒绝上传：请仅在获得声音本人授权后添加 --consent。")
        client = VolcengineVoiceCloneClient(settings)
        result = client.train(
            args.audio,
            speaker_id=args.speaker_id,
            custom_speaker_id=args.custom_speaker_id,
            text=args.text,
            demo_text=args.demo_text,
            language=args.language,
            denoise=args.denoise,
        )
        effective_id = args.custom_speaker_id or result.get("speaker_id") or args.speaker_id
        path = profiles.save(
            VoiceProfile(
                name=args.profile,
                speaker_id=effective_id,
                resource_id="seed-icl-2.0",
                consent_confirmed=True,
            )
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"已保存本地音色配置：{path}")
        return

    if args.command == "status":
        result = VolcengineVoiceCloneClient(settings).status(
            speaker_id=args.speaker_id, custom_speaker_id=args.custom_speaker_id
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "delete-profile":
        profiles.delete(args.profile)
        print(f"已删除本地音色配置：{args.profile}（云端音色未更改）")
        return

    if args.command == "tts":
        speaker_id = args.speaker_id
        if args.profile:
            profile = profiles.load(args.profile)
            if not profile.consent_confirmed:
                raise SystemExit("该音色配置没有授权确认标记，拒绝调用。")
            speaker_id = profile.speaker_id
        sink = PCM16Playback(settings.sample_rate) if args.play else NullAudioSink()
        tts = VolcengineStreamingTTS(settings)
        asyncio.run(
            speak_stream(
                tts,
                chunk_text(args.text, args.chunk_size, args.chunk_delay_ms),
                speaker_id,
                sink=sink,
                output_path=args.output,
            )
        )
        if tts.last_metrics:
            print(json.dumps(tts.last_metrics.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
