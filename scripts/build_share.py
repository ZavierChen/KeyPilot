"""Create a source-only archive using an allowlist, never the user's data tree."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ("desktop", "src", "tests", "scripts", "docs", "skills", "examples", "requirements", ".github")
ROOT_FILES = ("README.md", "pyproject.toml", ".gitignore", ".env.example", "run.cmd", "THIRD_PARTY_NOTICES.md", "requirements-voice-zipvoice.txt")
SUFFIXES = {".py", ".md", ".json", ".ps1", ".cmd", ".toml", ".txt", ".lock", ".yml", ".yaml", ".ico", ".png"}
EXCLUDE = {"__pycache__", ".pytest_cache", "vendor", "cache", "assistant-settings.json",
           "install-layout.json", "config.json", "portal.json"}


def share_files() -> list[Path]:
    paths = [ROOT / name for name in ROOT_FILES if (ROOT / name).is_file()]
    for name in FOLDERS:
        for path in (ROOT / name).rglob("*"):
            relative = path.relative_to(ROOT)
            if path.is_symlink() or any(part in EXCLUDE or part.endswith('.egg-info') for part in relative.parts):
                continue
            if path.is_file() and path.suffix.lower() in SUFFIXES:
                if path.name == "voice.json" and relative.as_posix() != "examples/voice-pack/voice.json":
                    raise ValueError(f"Local voice packs must never be distributed: {relative}")
                if path.stat().st_size > 5_000_000:
                    raise ValueError(f"Unexpected large source asset: {relative}")
                paths.append(path)
    return sorted(paths)


def main() -> int:
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archive = output / "KeyPilot-Repro-source.zip"
    manifest = {}
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in share_files():
            name = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            if path.suffix.lower() not in {".ico", ".png"}:
                data.decode("utf-8-sig")  # Reject machine-specific text encodings.
            if name == "examples/voice-pack/voice.json":
                template = json.loads(data)
                if template.get("ready") is not False or "python" in template or "speaker_id" in template:
                    raise ValueError("Only an unconfigured voice format template may be shared")
            manifest[name] = hashlib.sha256(data).hexdigest()
            entry = zipfile.ZipInfo("KeyPilot-Repro/" + name, date_time=(2026, 9, 18, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(entry, data)
        entry = zipfile.ZipInfo("KeyPilot-Repro/FILE_MANIFEST.sha256.json", date_time=(2026, 9, 18, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        bundle.writestr(entry, json.dumps(manifest, indent=2))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "KeyPilot-Repro-source.zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(json.dumps({"archive": str(archive), "files": len(manifest), "bytes": archive.stat().st_size,
                      "sha256": digest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
