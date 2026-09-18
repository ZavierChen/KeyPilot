from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from keypilot.actions import show_local_app
    from keypilot.install_layout import application_python
else:
    from .actions import show_local_app
    from .install_layout import application_python


RESIDENT_MUTEX = "Local\\KeyPilot.Repro.CopilotKeyAssistant"
RESIDENT_TASK = "KeyPilot-Repro"


def resident_is_running() -> bool:
    """Check the listener mutex without creating a second resident process."""
    if os.name != "nt":
        return False
    synchronize = 0x00100000
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenMutexW(synchronize, False, RESIDENT_MUTEX)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def ensure_resident(project_dir: Path, timeout_seconds: float = 2.0) -> bool:
    """Restore the Copilot-key listener before showing the portal window."""
    if resident_is_running():
        return True
    hidden = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        scheduled = subprocess.run(
            ["schtasks.exe", "/Run", "/TN", RESIDENT_TASK],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=hidden,
            check=False,
        )
    except OSError:
        scheduled = None
    deadline = time.monotonic() + timeout_seconds
    if scheduled is not None and scheduled.returncode == 0:
        while time.monotonic() < deadline:
            if resident_is_running():
                return True
            time.sleep(0.05)
        if resident_is_running():
            return True
    try:
        subprocess.Popen(
            [sys.executable, str(project_dir / "keypilot" / "main.py")],
            cwd=project_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=hidden,
        )
    except OSError:
        return False
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if resident_is_running():
            return True
        time.sleep(0.05)
    return resident_is_running()


def main() -> int:
    project_dir = Path(__file__).resolve().parent.parent
    # The reproducible edition starts the GUI only; key takeover is opt-in.
    from keypilot.edition import WINDOW_TITLE
    show_local_app(
        WINDOW_TITLE,
        application_python(),
        [str(project_dir / 'keypilot' / 'bootstrap.py')],
        str(project_dir),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
