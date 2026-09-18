"""Read-only command-line entry point for model adapters and professor demos."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .assistant_router import SkillRegistry
from .local_model import LocalModelBridge, LocalModelConfig, LocalModelError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地模型门户：导出契约、发现模型与只读路由测试")
    parser.add_argument("--protocol", choices=("ollama", "openai-compatible"), default="ollama")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="")
    parser.add_argument("--json-mode", choices=("schema", "json", "prompt"), default="schema")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--api-key-env", default="")
    parser.add_argument("--skills-dir", type=Path, default=Path(__file__).resolve().parent.parent / "skills")
    commands = parser.add_subparsers(dest="command", required=True)
    contract = commands.add_parser("contract", help="离线导出模型可见的操作契约")
    contract.add_argument("--output", type=Path)
    commands.add_parser("models", help="连接服务并列出已安装/已加载的模型")
    probe = commands.add_parser("probe", help="让模型提出 Skill 候选，仅校验，不执行")
    probe.add_argument("--text", required=True)
    validate = commands.add_parser("validate-response", help="离线校验外部模型的 JSON 回包")
    validate.add_argument("--file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        registry = SkillRegistry(args.skills_dir)
        if not registry.skills:
            raise LocalModelError("没有加载到 Skill，请检查 --skills-dir。")
        bridge = LocalModelBridge(registry, LocalModelConfig(
            args.protocol, args.endpoint, args.model, args.json_mode, args.timeout, args.api_key_env))
        if args.command == "contract":
            result = bridge.contract()
        elif args.command == "models":
            result = {"models": bridge.list_models(), "protocol": args.protocol}
        elif args.command == "probe":
            result = bridge.probe(args.text)
        else:
            result = bridge.inspect_response(json.loads(args.file.read_text(encoding="utf-8-sig")))
        serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.command == "contract" and args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized, encoding="utf-8")
        else:
            print(serialized, end="")
        return 2 if result.get("valid") is False else 0
    except (LocalModelError, OSError, json.JSONDecodeError, TypeError) as exc:
        print(json.dumps({"error": str(exc), "execution": "not_executed"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
