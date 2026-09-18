"""Fast source TTS plus local trained timbre conversion, in an isolated worker.

No reference audio upload, capture, virtual audio driver, or ChatGPT modification.
Heavy dependencies are imported only when this backend is selected.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import tempfile


def conversion_options(config: dict) -> tuple[float, float, float]:
    import math
    values = tuple(float(config.get(key, default)) for key, default in
                   (("index_rate", .25), ("protect", .10), ("rms_mix_rate", .5)))
    for value, upper in zip(values, (1, .5, 1)):
        if not math.isfinite(value) or not 0 <= value <= upper:
            raise ValueError("RVC 音色参数无效")
    return values


def conversion_device(config: dict) -> str:
    """Return the requested RVC inference device without importing PyTorch."""
    device = str(config.get("device", "cuda")).strip().lower()
    if device not in {"cpu", "cuda"}:
        raise ValueError("RVC 运行设备必须是 cpu 或 cuda")
    return device


class RvcVoiceRenderer:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.options = conversion_options(config)
        root = Path(config["rvc_root"]).resolve(strict=True)
        model = Path(config["model"]).resolve(strict=True)
        self.index = Path(config["index"]).resolve(strict=True)
        os.chdir(root)
        sys.path.insert(0, str(root))
        os.environ.update(weight_root=str(model.parent), rmvpe_root=str(root / "assets/rmvpe"),
                          index_root=str(root / "logs"), outside_index_root=str(root / "assets/indices"),
                          # Variable-length sentences cause expensive new graph
                          # captures. Eager mode avoids that latency and cache RAM.
                          RVC_CUDA_GRAPH="0")
        import torch
        from infer.cli import create_config
        from infer.vc.modules import VC
        device = conversion_device(config)
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("该 RVC 音色需要可用的 NVIDIA 显卡；已切回普通声音。")
        if device == "cpu" and torch.cuda.is_available():
            raise RuntimeError("CPU 音色进程未正确隔离显卡，已停止生成。")
        self.vc = VC(create_config())
        self.vc.get_vc(model.name)

    async def _source(self, text: str, destination: Path) -> None:
        import edge_tts
        # Only the reply text goes to the same Edge TTS service used by the
        # built-in online voice. The trained speaker data always stays local.
        await asyncio.wait_for(edge_tts.Communicate(
            text, self.config.get("source_voice", "zh-CN-XiaoxiaoNeural"),
            connect_timeout=5, receive_timeout=10,
        ).save(str(destination)), timeout=20)

    def render(self, text: str, destination: Path) -> None:
        import numpy as np
        import soundfile as sf
        import torch
        with tempfile.TemporaryDirectory(prefix="rvc-source-", dir=destination.parent) as folder:
            source = Path(folder) / "source.mp3"
            try:
                asyncio.run(self._source(text, source))
            except Exception as exc:
                raise RuntimeError("该 RVC 音色的联网朗读不可用，已切回普通声音。") from exc
            torch.manual_seed(1234)
            index_rate, protect, rms = self.options
            status, result = self.vc.vc_single(
                0, str(source), 0, "rmvpe", str(self.index), index_rate, 0, rms, protect)
            if not result or result[0] is None:
                raise RuntimeError(f"本地音色转换失败：{status}")
            sr, audio = result
            if not np.isfinite(audio).all() or not np.any(audio):
                raise RuntimeError("本地音色转换生成了无效音频")
            sf.write(str(destination), audio, sr)
