from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from typing import Protocol


class StreamingASR(Protocol):
    async def transcribe(self, audio: AsyncIterable[bytes]) -> AsyncIterator[str]: ...


class StreamingLLM(Protocol):
    async def generate(self, prompt: str) -> AsyncIterator[str]: ...


class StreamingTTS(Protocol):
    async def synthesize(
        self, text_chunks: AsyncIterable[str], speaker_id: str
    ) -> AsyncIterator[bytes]: ...
