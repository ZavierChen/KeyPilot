from __future__ import annotations

from collections.abc import AsyncIterable
from pathlib import Path

from voice_assistant.audio.playback import AudioSink, NullAudioSink
from voice_assistant.providers.base import StreamingTTS


async def speak_stream(
    tts: StreamingTTS,
    text_chunks: AsyncIterable[str],
    speaker_id: str,
    *,
    sink: AudioSink | None = None,
    output_path: Path | None = None,
) -> int:
    """Bridge LLM text chunks to TTS audio chunks and an optional live player."""
    sink = sink or NullAudioSink()
    output = None
    total = 0
    try:
        sink.start()
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output = output_path.open("wb")
        async for audio in tts.synthesize(text_chunks, speaker_id):
            total += len(audio)
            if output:
                output.write(audio)
            sink.write(audio)
    finally:
        if output:
            output.close()
        sink.close()
    return total
