"""Run using the voice pack's isolated Python, never KeyPilot's Python runtime."""
from __future__ import annotations

import contextlib
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

if __package__:
    from .voice_cache import audio_cache_path
    from .speech_text import normalize_chinese_numbers
    from .voice_tone import brighten_voice, normalize_voice_loudness, smooth_voice_edges
else:
    from voice_cache import audio_cache_path
    from speech_text import normalize_chinese_numbers
    from voice_tone import brighten_voice, normalize_voice_loudness, smooth_voice_edges


class VoiceCancelled(Exception):
    """Unwind generation before decoding/saving an interrupted reply."""


def zipvoice_language_key(text: str) -> str:
    """Choose a stable route for Chinese, English, and mixed assistant replies."""
    han = sum("\u3400" <= char <= "\u9fff" for char in text)
    latin = sum(char.isascii() and char.isalpha() for char in text)
    if han:
        return "chinese"
    if latin:
        return "english"
    return "default"


def zipvoice_model_directory(config: dict, text: str = "") -> Path:
    routes = config.get("language_models")
    if isinstance(routes, dict):
        selected = routes.get(zipvoice_language_key(text))
        if isinstance(selected, str) and selected.strip():
            return Path(selected)
    return Path(config["model"])


def zipvoice_reference(config: dict, text: str = "") -> tuple[Path, str]:
    routes = config.get("language_references")
    if isinstance(routes, dict):
        selected = routes.get(zipvoice_language_key(text))
        if isinstance(selected, dict) and str(selected.get("audio", "")).strip():
            return Path(selected["audio"]), str(selected.get("text", ""))
    return Path(config["reference_audio"]), str(config.get("reference_text", ""))


class RequestInbox:
    """Cancellation reaches active/queued requests without waiting on generation."""

    def __init__(self) -> None:
        self.queue = queue.Queue()
        self.events = {}
        self.lock = threading.Lock()

    def put(self, request: dict) -> None:
        with self.lock:
            key = request.get("id")
            if request.get("op") == "cancel":
                event = self.events.get(key)
                if event:
                    event.set()
                return
            event = threading.Event()
            self.events[key] = event
            self.queue.put((request, event))

    def finish(self, key) -> None:
        with self.lock:
            self.events.pop(key, None)

    def close(self) -> None:
        with self.lock:
            for event in self.events.values():
                event.set()
            self.queue.put(None)


def main() -> None:
    if os.environ.get("KEYPILOT_VOICE_DIAGNOSTICS"):
        import faulthandler
        faulthandler.dump_traceback_later(30, repeat=True)
    pack_path = Path(sys.argv[1])
    config = json.loads(pack_path.read_text(encoding="utf-8"))
    engine = config.get("engine", "qwen3-tts-zero-shot")
    if engine not in {"qwen3-tts-zero-shot", "edge-rvc", "zipvoice"}:
        raise ValueError(f"不支持的语音引擎：{engine}")
    if engine == "edge-rvc":
        rvc_device = str(config.get("device", "cuda")).strip().lower()
        if rvc_device not in {"cpu", "cuda"}:
            raise ValueError("RVC 运行设备必须是 cpu 或 cuda")
        if rvc_device == "cpu":
            # The worker is one process per voice pack. Hide CUDA before
            # importing torch so RVC selects its supported float32 CPU path.
            os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    persistent = os.environ.get("KEYPILOT_VOICE_MODE") == "quality"
    idle_seconds = max(15, min(600, int(config.get("idle_seconds", 60))))
    # Initialize native numerical libraries before a thread blocks in stdin.
    # Some Windows CRT/OpenBLAS builds otherwise deadlock during DLL loading.
    model = prompt = None
    zipvoice_models = {}
    zipvoice_references = {}
    torch = None
    warmed = False
    current_event = threading.Event()
    with contextlib.redirect_stdout(sys.stderr):
        import numpy
        import soundfile as sf
        if engine == "qwen3-tts-zero-shot":
            import torch
            from qwen_tts import Qwen3TTSModel
            torch.set_num_threads(4)
        elif engine == "edge-rvc":
            import torch
            if __package__:
                from .rvc_voice import RvcVoiceRenderer
            else:
                from rvc_voice import RvcVoiceRenderer
            # Importing the wrapper alone does not load FAISS/OpenMP. Its
            # constructor imports those native libraries lazily. On Windows
            # that can hang if the stdin reader has already entered the CRT.
            # A worker is only spawned when a model is needed (or prewarmed).
            model = RvcVoiceRenderer(config)
            torch.set_num_threads(4)
        else:
            import sherpa_onnx
    inbox = RequestInbox()

    def read() -> None:
        try:
            for line in sys.stdin:
                try:
                    inbox.put(json.loads(line))
                except (ValueError, TypeError, AttributeError):
                    continue
        finally:
            inbox.close()

    threading.Thread(target=read, daemon=True).start()
    cache = pack_path.parent / "cache"
    cache.mkdir(exist_ok=True)

    def check_cancelled(*_args):
        if current_event.is_set():
            raise VoiceCancelled()

    def ensure_model(text: str = ""):
        nonlocal model, prompt
        check_cancelled()
        if model is None:
            if engine == "edge-rvc":
                model = RvcVoiceRenderer(config)
            elif engine == "qwen3-tts-zero-shot":
                print("Loading local speech model", file=sys.stderr, flush=True)
                model = Qwen3TTSModel.from_pretrained(
                    config["model"], device_map="cuda:0", dtype=torch.bfloat16,
                    attn_implementation="sdpa",
                )
                # The installed Qwen wrapper discards stopping_criteria kwargs.
                # A per-forward hook cancels at the next talker step instead,
                # without modifying vendor code or throwing away the model.
                model.model.talker.register_forward_pre_hook(check_cancelled)
            else:
                model_dir = zipvoice_model_directory(config, text)
                model_key = str(model_dir.resolve())
                print(f"Loading ZipVoice CPU model: {model_dir.name}", file=sys.stderr, flush=True)
                zipvoice = sherpa_onnx.OfflineTtsZipvoiceModelConfig(
                    tokens=str(model_dir / "tokens.txt"),
                    encoder=str(model_dir / "encoder.int8.onnx"),
                    decoder=str(model_dir / "decoder.int8.onnx"),
                    data_dir=str(config.get("data_dir", model_dir / "espeak-ng-data")),
                    lexicon=str(config.get("lexicon", model_dir / "lexicon.txt")),
                    vocoder=str(config["vocoder"]),
                )
                tts_config = sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        zipvoice=zipvoice,
                        debug=bool(config.get("debug", False)),
                        num_threads=max(1, min(8, int(config.get("num_threads", 2)))),
                        provider="cpu",
                    )
                )
                if not tts_config.validate():
                    raise ValueError("ZipVoice 配置无效，请检查模型路径")
                zipvoice_models[model_key] = sherpa_onnx.OfflineTts(tts_config)
                model = zipvoice_models[model_key]
        elif engine == "zipvoice":
            model_dir = zipvoice_model_directory(config, text)
            model_key = str(model_dir.resolve())
            if model_key not in zipvoice_models:
                print(f"Loading ZipVoice CPU model: {model_dir.name}", file=sys.stderr, flush=True)
                zipvoice = sherpa_onnx.OfflineTtsZipvoiceModelConfig(
                    tokens=str(model_dir / "tokens.txt"),
                    encoder=str(model_dir / "encoder.int8.onnx"),
                    decoder=str(model_dir / "decoder.int8.onnx"),
                    data_dir=str(config.get("data_dir", model_dir / "espeak-ng-data")),
                    lexicon=str(config.get("lexicon", model_dir / "lexicon.txt")),
                    vocoder=str(config["vocoder"]),
                )
                tts_config = sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        zipvoice=zipvoice,
                        debug=bool(config.get("debug", False)),
                        num_threads=max(1, min(8, int(config.get("num_threads", 2)))),
                        provider="cpu",
                    )
                )
                if not tts_config.validate():
                    raise ValueError("ZipVoice 配置无效，请检查模型路径")
                zipvoice_models[model_key] = sherpa_onnx.OfflineTts(tts_config)
            model = zipvoice_models[model_key]
        check_cancelled()
        if engine == "qwen3-tts-zero-shot" and prompt is None:
            prompt = model.create_voice_clone_prompt(
                ref_audio=config["reference_audio"],
                ref_text=config.get("reference_text", ""),
                x_vector_only_mode=not bool(config.get("reference_text")),
            )
        check_cancelled()
        return model

    def generate_zipvoice(text: str):
        selected_model = ensure_model(text)
        reference_path, reference_text = zipvoice_reference(config, text)
        reference_key = str(reference_path.resolve())
        if reference_key not in zipvoice_references:
            samples, sample_rate = sf.read(reference_path, dtype="float32")
            if samples.ndim > 1:
                samples = samples[:, 0]
            zipvoice_references[reference_key] = (samples, sample_rate)
        reference_samples, reference_sample_rate = zipvoice_references[reference_key]
        generation = sherpa_onnx.GenerationConfig()
        generation.reference_audio = reference_samples
        generation.reference_sample_rate = reference_sample_rate
        generation.reference_text = reference_text
        generation.num_steps = max(1, min(16, int(config.get("num_steps", 4))))
        generation.extra["min_char_in_sentence"] = str(
            max(1, min(120, int(config.get("min_char_in_sentence", 5))))
        )

        def callback(_samples, _progress):
            return 1 if current_event.is_set() else 0

        audio = selected_model.generate(normalize_chinese_numbers(text), generation, callback)
        check_cancelled()
        if len(audio.samples) == 0:
            raise RuntimeError("ZipVoice 没有生成音频")
        return audio

    while True:
        try:
            item = inbox.queue.get(timeout=None if persistent else idle_seconds)
        except queue.Empty:
            return
        if item is None:
            return
        request, current_event = item
        temporary = None
        started = time.perf_counter()
        try:
            check_cancelled()
            if request.get("op") == "warmup":
                with contextlib.redirect_stdout(sys.stderr):
                    ensure_model()
                    if not warmed and engine == "qwen3-tts-zero-shot":
                        # Warm actual inference/tokenizer kernels, never play or cache it.
                        model.generate_voice_clone(
                            text="你好。", language="Chinese", voice_clone_prompt=prompt,
                            max_new_tokens=64, do_sample=False,
                        )
                        torch.cuda.synchronize()
                    elif not warmed and engine == "zipvoice":
                        generate_zipvoice("你好。")
                    check_cancelled()
                    warmed = True
                print(json.dumps({"id": request["id"], "ready": True, "pid": os.getpid(),
                                  "warmup_seconds": time.perf_counter() - started}), flush=True)
                continue
            text = str(request["text"]).strip()[:500]
            if not text:
                raise ValueError("没有要朗读的文字")
            output = audio_cache_path(pack_path, config, text)
            if not output.exists():
                with contextlib.redirect_stdout(sys.stderr):
                    temporary = output.with_suffix(".tmp.wav")
                    ensure_model(text if engine == "zipvoice" else "")
                    if engine == "edge-rvc":
                        model.render(text, temporary)
                    elif engine == "zipvoice":
                        audio = generate_zipvoice(text)
                        sf.write(str(temporary), audio.samples, audio.sample_rate)
                    else:
                        print("Synthesizing", file=sys.stderr, flush=True)
                        wavs, sr = model.generate_voice_clone(
                            text=text, language="Chinese", voice_clone_prompt=prompt,
                            max_new_tokens=1536, do_sample=False,
                        )
                        check_cancelled()
                        sf.write(str(temporary), wavs[0], sr)
                    check_cancelled()
                    brighten_voice(temporary, config)
                    check_cancelled()
                    normalize_voice_loudness(temporary, config)
                    check_cancelled()
                    smooth_voice_edges(temporary, config)
                    check_cancelled()
                    temporary.replace(output)
                    warmed = True
                for stale in sorted(cache.glob("*.wav"), key=lambda p: p.stat().st_mtime)[:-40]:
                    if stale != output:
                        stale.unlink(missing_ok=True)
            print(json.dumps({"id": request["id"], "audio": str(output), "pid": os.getpid(),
                              "generation_seconds": time.perf_counter() - started}), flush=True)
        except VoiceCancelled:
            print(json.dumps({"id": request.get("id"), "cancelled": True,
                              "pid": os.getpid()}), flush=True)
        except Exception as exc:
            import traceback
            traceback.print_exc(file=sys.stderr)
            print(json.dumps({"id": request.get("id"), "error": str(exc)}), flush=True)
        finally:
            inbox.finish(request.get("id"))
            if temporary:
                temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
