from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from keypilot.actions import show_local_app
else:
    from .actions import show_local_app


def main() -> int:
    project_dir = Path(__file__).resolve().parent.parent
    show_local_app(
        "KeyPilot 本地助手",
        "pythonw.exe",
        ["-m", "keypilot.assistant_app"],
        str(project_dir),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
