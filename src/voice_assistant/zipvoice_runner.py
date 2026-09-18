"""Run an isolated ZipVoice checkout while keeping the existing CUDA Torch first."""
from __future__ import annotations

import argparse
import runpy
import site
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--deps", type=Path, required=True)
    parser.add_argument("module")
    args, remainder = parser.parse_known_args()
    # addsitedir appends after the active venv's site-packages, so the known-good
    # CUDA Torch wins over any transitive Torch wheel downloaded into --deps.
    site.addsitedir(str(args.deps.resolve()))
    sys.path.insert(0, str(args.repo.resolve()))
    sys.argv = [args.module, *remainder]
    runpy.run_module(args.module, run_name="__main__")


if __name__ == "__main__":
    main()
