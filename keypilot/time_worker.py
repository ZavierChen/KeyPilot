from __future__ import annotations

import ctypes
import time

from .time_service import TimeTaskScheduler


ERROR_ALREADY_EXISTS = 183


def main() -> int:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\KeyPilot.TimeWorker")
    if not handle:
        return 1
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return 0

    scheduler = TimeTaskScheduler()
    try:
        while True:
            scheduler.poll()
            time.sleep(1.0)
    finally:
        kernel32.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
