"""Import data-only, portable ZipVoice packs into the user's voice directory.

The runtime is always supplied by the local user, never by a downloaded pack.
Import copies only declared audio/model assets, then loads the model before
publishing a ready manifest. No package installers or pack scripts are run.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from .install_layout import voice_directory


class VoicePackError(ValueError):
    """An incomplete, unsupported, or unsafe portable voice pack."""


_FIELDS = {
    "schema_version", "id", "name", "engine", "ready", "model", "vocoder",
    "reference_audio", "reference_text", "num_steps", "num_threads",
    "idle_seconds", "min_char_in_sentence", "synthetic_voice",
}
_MODEL_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt", "lexicon.txt")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}
_CODE_SUFFIXES = {".exe", ".dll", ".com", ".bat", ".cmd", ".ps1", ".sh",
                  ".py", ".pyc", ".pyd", ".pth", ".zip", ".whl", ".so"}


def voice_pack_template(identity: str = "my-voice", name: str = "我的自定义音色") -> dict:
    _check_identity(identity)
    return {
        "schema_version": 1, "id": identity, "name": name,
        "engine": "zipvoice", "ready": False, "synthetic_voice": True,
        "model": "model", "vocoder": "vocos_24khz.onnx",
        "reference_audio": "reference.wav",
        "reference_text": "请替换为参考录音中实际说出的文字。",
        "num_steps": 4, "num_threads": 2,
    }


def _check_identity(identity: object) -> None:
    if (not isinstance(identity, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identity)
            or identity in _RESERVED):
        raise VoicePackError("id 必须为 1–64 个小写字母、数字、连字符或下划线，且不能是 Windows 保留名称")


def _relative(value: object, field: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise VoicePackError(f"{field} 必须使用包内相对路径和 / 分隔符")
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    if (posix.is_absolute() or windows.drive or windows.root
            or any(p in {"", ".", ".."} for p in value.split("/"))
            or any(c in value for c in ':<>"|?*')
            or any(ord(c) < 32 for c in value)
            or any(p.endswith((" ", ".")) or p.split(".")[0].lower() in _RESERVED for p in posix.parts)):
        raise VoicePackError(f"{field} 路径越界或无效：{value}")
    return Path(*posix.parts)


def _inside(root: Path, relative: Path, *, directory: bool = False) -> Path:
    candidate = root / relative
    # Reject junctions/reparse points as well as ordinary symlinks. Check each
    # component before resolving; Path.resolve alone loses this information.
    current = root
    for part in relative.parts:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise VoicePackError(f"缺少语音资源：{relative}") from exc
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise VoicePackError(f"语音资源不能使用符号链接或目录联接：{relative}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise VoicePackError(f"资源路径超出语音包：{relative}")
    if directory:
        if not resolved.is_dir():
            raise VoicePackError(f"需要资源文件夹：{relative}")
    elif not resolved.is_file() or resolved.stat().st_size == 0:
        raise VoicePackError(f"需要非空资源文件：{relative}")
    return resolved


def _read_pack(source: Path) -> tuple[Path, dict, list[Path]]:
    source = Path(source).expanduser()
    manifest = source / "voice.json" if source.is_dir() else source
    if manifest.name != "voice.json":
        raise VoicePackError("请选择语音包文件夹或 voice.json（不接受压缩包）")
    root = manifest.parent.resolve()
    try:
        _inside(root, Path("voice.json"))
        if manifest.stat().st_size > 64 * 1024:
            raise VoicePackError("voice.json 不得超过 64 KiB")
        config = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise VoicePackError(f"无法读取 voice.json：{exc}") from exc
    if not isinstance(config, dict):
        raise VoicePackError("voice.json 必须是 JSON 对象")
    unknown = set(config) - _FIELDS
    if unknown:
        raise VoicePackError("可移植 v1 不接受这些字段（解释器和工具只能由本机提供）：" + ", ".join(sorted(unknown)))
    if type(config.get("schema_version")) is not int or config["schema_version"] != 1:
        raise VoicePackError("需要 schema_version: 1")
    if config.get("engine") != "zipvoice":
        raise VoicePackError("可移植导入目前仅支持 zipvoice；其他引擎参见 docs/VOICE_PACKS.md")
    _check_identity(config.get("id"))
    for field, limit in (("name", 100), ("reference_text", 4000)):
        value = config.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
            raise VoicePackError(f"{field} 必须是非空字符串，最长 {limit} 字符")
    for field in ("ready", "synthetic_voice"):
        if field in config and type(config[field]) is not bool:
            raise VoicePackError(f"{field} 必须是 JSON 布尔值")
    for field, default, low, high in (("num_steps", 4, 1, 16), ("num_threads", 2, 1, 8),
                                    ("idle_seconds", 60, 15, 600), ("min_char_in_sentence", 5, 1, 120)):
        value = config.get(field, default)
        if type(value) is not int or not low <= value <= high:
            raise VoicePackError(f"{field} 必须是 {low}–{high} 的整数")
        config[field] = value
    model = _relative(config.get("model"), "model")
    _inside(root, model, directory=True)
    assets = [model / filename for filename in _MODEL_FILES]
    assets += [_relative(config.get(field), field) for field in ("vocoder", "reference_audio")]
    if assets[-2].suffix.lower() != ".onnx" or assets[-1].suffix.lower() != ".wav":
        raise VoicePackError("vocoder 必须为 .onnx，reference_audio 必须为 .wav")
    data = model / "espeak-ng-data"
    _inside(root, data, directory=True)
    # Follow no links, and copy no unrelated recordings, scripts, caches or logs.
    for folder, directories, filenames in os.walk(root / data, followlinks=False):
        for dirname in directories:
            _inside(root, (Path(folder) / dirname).relative_to(root), directory=True)
        for filename in filenames:
            relative = (Path(folder) / filename).relative_to(root)
            if relative.suffix.lower() in _CODE_SUFFIXES:
                raise VoicePackError(f"espeak-ng-data 中不接受执行文件：{relative}")
            assets.append(relative)
    if len(assets) == len(_MODEL_FILES) + 2:
        raise VoicePackError("espeak-ng-data 文件夹为空")
    for relative in assets:
        _inside(root, relative)
    # A supplied ready flag is never evidence that the model is usable here.
    config["ready"] = False
    return root, config, list(dict.fromkeys(assets))


_PROBE = r'''
import contextlib, json, sys, sysconfig
from pathlib import Path
cfg = json.load(sys.stdin)
with contextlib.redirect_stdout(sys.stderr):
    import numpy as np
    import soundfile as sf
    import sherpa_onnx as sherpa
    if not hasattr(sherpa, "OfflineTtsZipvoiceModelConfig"):
        raise RuntimeError("sherpa-onnx lacks ZipVoice support")
    info = sf.info(cfg["reference_audio"])
    if info.channels != 1 or not 8000 <= info.samplerate <= 48000 or not 1 <= info.duration <= 30:
        raise ValueError("reference.wav must be mono, 8–48 kHz, and 1–30 seconds")
    audio, _ = sf.read(cfg["reference_audio"], dtype="float32")
    if not np.isfinite(audio).all() or np.max(np.abs(audio)) < 0.0001:
        raise ValueError("reference.wav contains silence or non-finite samples")
    model = Path(cfg["model"])
    settings = sherpa.OfflineTtsConfig(model=sherpa.OfflineTtsModelConfig(
        zipvoice=sherpa.OfflineTtsZipvoiceModelConfig(
            tokens=str(model / "tokens.txt"), encoder=str(model / "encoder.int8.onnx"),
            decoder=str(model / "decoder.int8.onnx"), lexicon=str(model / "lexicon.txt"),
            data_dir=str(model / "espeak-ng-data"), vocoder=cfg["vocoder"]),
        num_threads=cfg["num_threads"], provider="cpu"))
    if not settings.validate():
        raise ValueError("ZipVoice model configuration validation failed")
    tts = sherpa.OfflineTts(settings)
print(json.dumps({"python": sys._base_executable,
                  "site_packages": sysconfig.get_path("purelib"),
                  "runtime_versions": {"python": sys.version.split()[0],
                    "sherpa_onnx": sherpa.__version__, "numpy": np.__version__,
                    "soundfile": sf.__version__}}, ensure_ascii=False))
'''


def _local_config(config: dict, root: Path) -> dict:
    result = dict(config)
    for field in ("model", "vocoder", "reference_audio"):
        result[field] = str(root / _relative(config[field], field))
    return result


def _probe_runtime(python: Path, config: dict, pack_root: Path) -> dict:
    python = Path(python).expanduser().resolve()
    if not python.is_file():
        raise VoicePackError(f"指定的本机 Python 不存在：{python}")
    if python.is_relative_to(pack_root):
        raise VoicePackError("Python 运行时必须在语音包以外，由本机单独安装")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="2")
    try:
        # -I ignores user-site/PYTHONPATH and avoids importing code from the pack.
        with tempfile.TemporaryDirectory(prefix="keypilot-runtime-check-") as cwd:
            result = subprocess.run([str(python), "-I", "-c", _PROBE],
                input=json.dumps(config, ensure_ascii=True), text=True, encoding="utf-8", errors="replace",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env, timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise VoicePackError("运行时、参考音频或模型加载失败：" + result.stderr.strip()[-1800:])
        runtime = json.loads(result.stdout)
        if not isinstance(runtime, dict):
            raise ValueError("runtime probe returned no object")
        for field in ("python", "site_packages"):
            path = Path(runtime[field]).resolve()
            if not path.exists() or path.is_relative_to(pack_root):
                raise ValueError(f"invalid local runtime {field}")
            runtime[field] = str(path)
        return runtime
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, VoicePackError):
            raise
        raise VoicePackError(f"无法验证语音 Python（需要 numpy、soundfile、sherpa-onnx）：{exc}") from exc


def validate_voice_pack(source: Path, *, python: Path | None = None) -> dict:
    """Validate portable assets; with python also load weights and decode audio."""
    root, config, assets = _read_pack(source)
    result = {"id": config["id"], "name": config["name"], "engine": "zipvoice",
              "asset_count": len(assets), "ready": False,
              "validation": "files_only"}
    if python is not None:
        runtime = _probe_runtime(python, _local_config(config, root), root)
        result.update(ready=True, validation="model_loaded", runtime_versions=runtime["runtime_versions"])
    return result


def import_voice_pack(source: Path, *, python: Path, destination: Path | None = None) -> Path:
    """Copy and validate a pack, then publish voice.json; never overwrite an ID."""
    root, config, assets = _read_pack(source)
    # Check the caller's runtime before copying potentially large model files.
    runtime_path = Path(python).expanduser().resolve()
    if not runtime_path.is_file() or runtime_path.is_relative_to(root):
        raise VoicePackError("请单独选择语音包以外已安装的本机 Python 可执行文件")
    target_root = Path(destination if destination is not None else voice_directory()).expanduser().resolve()
    target = target_root / config["id"]
    if target.exists():
        raise VoicePackError(f"同名语音包已存在，不会覆盖：{config['id']}；请更换包 id")
    if target_root.is_relative_to(root):
        raise VoicePackError("导入目标不能位于源语音包中")
    target_root.mkdir(parents=True, exist_ok=True)
    # Hidden staging folders have no voice.json, hence are never ready/catalogued.
    staging = Path(tempfile.mkdtemp(prefix=".voice-import-", dir=target_root)).resolve()
    try:
        for relative in assets:
            source_file = _inside(root, relative)
            target_file = staging / relative
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
        runtime = _probe_runtime(runtime_path, _local_config(config, staging), root)
        installed = _local_config(config, target)
        installed.update(runtime, ready=True, synthetic_voice=True)
        # Preserve a data-only manifest for inspection, without copying extra files.
        (staging / "portable-voice.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Claim the target atomically. An existing target is never overwritten,
        # including when another importer creates the same ID during validation.
        try:
            target.mkdir()
        except FileExistsError as exc:
            raise VoicePackError(f"同名语音包已存在，不会覆盖：{config['id']}") from exc
        try:
            for child in staging.iterdir():
                shutil.move(str(child), str(target / child.name))
            (target / "voice.json").write_text(json.dumps(installed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            _remove_created_directory(target, target_root)
            raise
        return target / "voice.json"
    except OSError as exc:
        raise VoicePackError(f"无法写入语音包：{exc}") from exc
    finally:
        _remove_created_directory(staging, target_root)


def _remove_created_directory(path: Path, parent: Path) -> None:
    # Only importer-created direct children of the resolved target are removable.
    if path.resolve().parent != parent.resolve() or path.is_symlink():
        raise VoicePackError("拒绝清理导入目录之外的路径")
    if path.exists():
        shutil.rmtree(path)


def create_voice_pack_template(directory: Path, *, identity: str = "my-voice", name: str = "我的自定义音色") -> Path:
    config = voice_pack_template(identity, name)
    directory = Path(directory).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "voice.json"
    try:
        with target.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError as exc:
        raise VoicePackError("voice.json 已存在，模板生成不会覆盖") from exc
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地 ZipVoice 语音包：模板、校验与导入")
    commands = parser.add_subparsers(dest="command", required=True)
    template = commands.add_parser("template", help="创建无音频/无权重的配置模板")
    template.add_argument("directory", type=Path)
    template.add_argument("--id", default="my-voice")
    template.add_argument("--name", default="我的自定义音色")
    validate = commands.add_parser("validate", help="检查文件；指定 --python 还会实际加载模型")
    validate.add_argument("source", type=Path)
    validate.add_argument("--python", type=Path)
    install = commands.add_parser("import", help="验证后复制到用户数据目录，同名不覆盖")
    install.add_argument("source", type=Path)
    install.add_argument("--python", required=True, type=Path)
    install.add_argument("--destination", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "template":
            result = {"manifest": str(create_voice_pack_template(args.directory, identity=args.id, name=args.name)), "ready": False}
        elif args.command == "validate":
            result = validate_voice_pack(args.source, python=args.python)
        else:
            result = {"manifest": str(import_voice_pack(args.source, python=args.python, destination=args.destination)), "ready": True}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (VoicePackError, OSError) as exc:
        print(json.dumps({"error": str(exc), "ready": False}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
