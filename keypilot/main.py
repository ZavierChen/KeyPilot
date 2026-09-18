from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
import traceback
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from keypilot.actions import execute_action
    from keypilot.config import load_config
    from keypilot.gestures import GestureRecognizer
    from keypilot.windows_hook import WindowsKeyboardHook
else:
    from .actions import execute_action
    from .config import load_config
    from .gestures import GestureRecognizer
    from .windows_hook import WindowsKeyboardHook


ERROR_ALREADY_EXISTS = 183


def acquire_single_instance() -> object:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    handle = kernel32.CreateMutexW(None, False, "Local\\KeyPilot.CopilotKeyAssistant")
    if not handle:
        raise ctypes.WinError()
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        raise RuntimeError("KeyPilot is already running")
    return handle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configurable Windows Copilot key assistant")
    parser.add_argument("--debug", action="store_true", help="print key and action events")
    parser.add_argument("--config", type=Path, help="path to config.json")
    return parser.parse_args()


def start_time_worker(project_dir: Path) -> None:
    subprocess.Popen(
        [sys.executable, "-m", "keypilot.time_worker"],
        cwd=project_dir,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def main() -> int:
    args = parse_args()
    project_dir = Path(__file__).resolve().parent.parent
    config_path = args.config or project_dir / "config.json"
    mutex = None

    try:
        mutex = acquire_single_instance()
        start_time_worker(project_dir)
        config = load_config(config_path)
        recognizer = GestureRecognizer(
            double_tap_seconds=config.gestures.double_tap_ms / 1000,
            hold_seconds=config.gestures.hold_ms / 1000,
            immediate_tap=config.gestures.immediate_tap,
        )

        def on_gesture(gesture: str) -> None:
            try:
                if args.debug:
                    print(f"[KeyPilot] gesture: {gesture}", flush=True)
                # Reload actions so shortcut/app edits take effect without a restart.
                # Trigger-key and gesture-timing changes still require a restart because
                # those values are owned by the already-installed keyboard hook.
                current_config = load_config(config_path)
                execute_action(current_config.actions[gesture], debug=args.debug)
            except Exception:
                if args.debug:
                    traceback.print_exc()

        WindowsKeyboardHook(
            config.trigger,
            recognizer,
            on_gesture,
            debug=args.debug,
        ).run()
        return 0
    except Exception as exc:
        if args.debug:
            traceback.print_exc()
        else:
            ctypes.windll.user32.MessageBoxW(None, str(exc), "KeyPilot", 0x10)
        return 1
    finally:
        if mutex:
            kernel32 = ctypes.windll.kernel32
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
