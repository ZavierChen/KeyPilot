"""Example: replace fake_llm() with your existing LLM token stream."""

import asyncio

from voice_assistant.audio.playback import PCM16Playback
from voice_assistant.config import Settings
from voice_assistant.pipeline import speak_stream
from voice_assistant.providers.volcengine import VolcengineStreamingTTS
from voice_assistant.voice_profiles import VoiceProfileStore


async def fake_llm():
    for chunk in ["你好，", "这段文字来自", "模拟的 LLM 流式输出。"]:
        yield chunk
        await asyncio.sleep(0.08)


async def main():
    settings = Settings.from_env()
    profile = VoiceProfileStore(settings.profile_dir).load("my_voice")
    tts = VolcengineStreamingTTS(settings)
    await speak_stream(
        tts,
        fake_llm(),
        profile.speaker_id,
        sink=PCM16Playback(settings.sample_rate),
    )


if __name__ == "__main__":
    asyncio.run(main())
