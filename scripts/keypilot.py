"""Run the source distribution from any working directory; no PATH edits needed."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"


def doctor() -> int:
    from keypilot.assistant_router import SkillRegistry, LocalCommandRouter
    from keypilot.data_paths import user_data_dir
    registry = SkillRegistry(DESKTOP / "skills")
    examples = ["打开计算器", "音量调到百分之三十", "五分钟倒计时"]
    router = LocalCommandRouter(registry)
    checks = {}
    for text in examples:
        call = router.route(text)
        checks[text] = call.skill_id if call else None
    tk_available = importlib.util.find_spec("tkinter") is not None
    report = {
        "python": sys.version.split()[0], "executable": sys.executable,
        "windows": sys.platform == "win32", "tkinter": tk_available,
        "user_data_dir": str(user_data_dir()), "registered_skills": len(registry.skills),
        "route_checks": checks, "executed_actions": 0, "network_requests": 0,
        "optional_dependencies": {name: importlib.util.find_spec(name) is not None
                                  for name in ("edge_tts", "websockets", "tzdata")},
    }
    report["ok"] = bool(report["windows"] and tk_available and all(checks.values()))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def hook_arguments() -> list[str]:
    from keypilot.data_paths import user_data_dir
    from keypilot.edition import WINDOW_TITLE, DICTATION_NAME
    from keypilot.user_settings import save_settings
    config = user_data_dir() / "keyboard-config.json"
    if not config.exists():
        common = {"title_prefix": WINDOW_TITLE, "program": sys.executable,
                  "working_directory": str(DESKTOP)}
        save_settings(config, {
            "trigger": {"virtual_key": "F23", "require_windows": True, "require_shift": True},
            "gestures": {"double_tap_ms": 280, "hold_ms": 600},
            "actions": {
                "tap": {**common, "type": "toggle_local_app", "args": ["-m", "keypilot.assistant_app"]},
                "double_tap": {**common, "type": "toggle_dictation_app", "event_name": DICTATION_NAME,
                               "args": ["-m", "keypilot.assistant_app", "--dictation"]},
                "hold": {"type": "noop"},
            },
        })
    return ["--config", str(config), "--debug"]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="KeyPilot reproducible project entry")
    parser.add_argument("command", choices=["gui", "models", "voices", "doctor", "hook"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args()
    remainder = args.arguments
    sys.path.insert(0, str(DESKTOP))
    if args.command == "doctor":
        return doctor()
    if args.command in {"gui", "hook"} and sys.platform != "win32":
        parser.error("The desktop application requires Windows 10/11.")
    modules = {"gui": "keypilot.assistant_app", "models": "keypilot.local_model_portal",
               "voices": "keypilot.voice_pack_manager", "hook": "keypilot.main"}
    if args.command == "hook" and "--config" not in remainder:
        remainder = hook_arguments() + remainder
    sys.argv = [modules[args.command], *remainder]
    runpy.run_module(modules[args.command], run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
