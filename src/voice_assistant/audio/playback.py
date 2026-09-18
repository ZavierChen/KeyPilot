from __future__ import annotations

from typing import Protocol


class AudioSink(Protocol):
    def start(self) -> None: ...
    def write(self, chunk: bytes) -> None: ...
    def close(self) -> None: ...


class NullAudioSink:
    def start(self) -> None:
        pass

    def write(self, chunk: bytes) -> None:
        pass

    def close(self) -> None:
        pass


class PCM16Playback:
    """Blocking low-latency playback for mono signed 16-bit PCM chunks."""

    def __init__(self, sample_rate: int = 24000, blocksize: int = 0):
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self._stream = None

    def start(self) -> None:
        import sounddevice as sd

        self._stream = sd.RawOutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.blocksize,
            latency="low",
        )
        self._stream.start()

    def write(self, chunk: bytes) -> None:
        if self._stream is None:
            raise RuntimeError("播放器尚未启动。")
        self._stream.write(chunk)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
