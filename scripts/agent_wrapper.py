#!/usr/bin/env python3
"""List and run pluggable AI agent wrappers.

Wrapper extensions live under:

  agent_wrappers/<wrapper-id>/wrapper.json

Built-in wrapper ids are implemented in this script. A future wrapper can add a
`command` array to its JSON config; placeholders such as `{workspace}`,
`{prompt_file}`, `{model}`, `{role}`, `{output_format}`, and
`{reasoning_effort}` are expanded before execution.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def wrappers_dir() -> Path:
    return package_root() / "agent_wrappers"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_wrappers() -> list[dict]:
    wrappers = []
    for config_path in sorted(wrappers_dir().glob("*/wrapper.json")):
        try:
            data = read_json(config_path)
        except (OSError, json.JSONDecodeError) as exc:
            data = {
                "id": config_path.parent.name,
                "label": config_path.parent.name,
                "roles": [],
                "error": str(exc),
            }
        data.setdefault("id", config_path.parent.name)
        data.setdefault("label", data["id"])
        data.setdefault("roles", [])
        data["config_path"] = str(config_path)
        data["available"] = bool(data.get("executable") and shutil.which(str(data["executable"])))
        wrappers.append(data)
    return wrappers


def find_wrapper(wrapper_id: str) -> dict:
    for wrapper in load_wrappers():
        if wrapper.get("id") == wrapper_id:
            return wrapper
    raise SystemExit(f"unknown agent wrapper: {wrapper_id}")


def normalize_cursor_model(model: str) -> str:
    if model == "gpt-5.5":
        return "gpt-5.5-high"
    if model == "gpt-5.3-codex":
        return "gpt-5.3-codex-high"
    if model == "claude-opus-4.8-thinking-high":
        return "claude-opus-4-8-thinking-high"
    if model in {"fable", "fable-high", "fable-1m-high"}:
        return "claude-fable-5-thinking-high"
    if model in {"fable-xhigh", "fable-1m-xhigh", "fable-extra-high"}:
        return "claude-fable-5-thinking-xhigh"
    return model


def split_extra_args(value: str) -> list[str]:
    return shlex.split(value) if value.strip() else []


def run_cursor_agent(args: argparse.Namespace) -> int:
    model = normalize_cursor_model(args.model)
    command = [
        "cursor-agent",
        "-p",
        "--trust",
    ]
    if args.role == "reviewer":
        command.extend(["--mode", "ask"])
    command.extend(["--workspace", args.workspace])
    if args.output_format:
        command.extend(["--output-format", args.output_format])
        if args.output_format == "stream-json" and args.stream_partial_output:
            command.append("--stream-partial-output")
    if model:
        command.extend(["--model", model])
    command.extend(split_extra_args(args.extra_args))
    command.append(Path(args.prompt_file).read_text(encoding="utf-8"))
    return subprocess.call(command)


def run_codex(args: argparse.Namespace) -> int:
    command = [
        "codex",
        "--ask-for-approval",
        "never",
        "--sandbox",
        "danger-full-access",
        "exec",
        "-C",
        args.workspace,
    ]
    if args.model:
        command.extend(["-m", args.model])
    if args.reasoning_effort:
        command.extend(["-c", f'model_reasoning_effort="{args.reasoning_effort}"'])
    command.extend(split_extra_args(args.extra_args))
    command.append("-")
    with Path(args.prompt_file).open("rb") as prompt:
        return subprocess.call(command, stdin=prompt)


def expand_custom_command(wrapper: dict, args: argparse.Namespace) -> list[str]:
    template = wrapper.get("command")
    if not isinstance(template, list) or not template:
        raise SystemExit(f"wrapper {wrapper.get('id')} has no built-in runner or command template")
    mapping = {
        "role": args.role,
        "workspace": args.workspace,
        "prompt_file": args.prompt_file,
        "model": args.model,
        "output_format": args.output_format,
        "reasoning_effort": args.reasoning_effort,
        "extra_args": args.extra_args,
    }
    return [str(part).format(**mapping) for part in template]


def run_custom(wrapper: dict, args: argparse.Namespace) -> int:
    command = expand_custom_command(wrapper, args)
    return subprocess.call(command)


def cmd_list(args: argparse.Namespace) -> int:
    wrappers = load_wrappers()
    if args.role:
        wrappers = [wrapper for wrapper in wrappers if args.role in wrapper.get("roles", [])]
    if args.json:
        print(json.dumps({"wrappers": wrappers}, indent=2, sort_keys=True))
        return 0
    for wrapper in wrappers:
        roles = ",".join(wrapper.get("roles", []))
        models = ",".join(wrapper.get("models", []))
        available = "yes" if wrapper.get("available") else "no"
        print(f"{wrapper.get('id')}\t{wrapper.get('label')}\troles={roles}\tavailable={available}\tmodels={models}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    wrapper = find_wrapper(args.wrapper)
    roles = set(wrapper.get("roles", []))
    if args.role not in roles:
        raise SystemExit(f"wrapper {args.wrapper} does not support role {args.role}")
    executable = wrapper.get("executable")
    if executable and not shutil.which(str(executable)):
        raise SystemExit(f"required executable for wrapper {args.wrapper} not found in PATH: {executable}")
    if args.wrapper == "cursor-agent":
        return run_cursor_agent(args)
    if args.wrapper == "codex":
        return run_codex(args)
    return run_custom(wrapper, args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list available wrappers")
    list_parser.add_argument("--role", default="")
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(func=cmd_list)

    run_parser = subparsers.add_parser("run", help="run an agent wrapper")
    run_parser.add_argument(
        "--role",
        required=True,
        choices=["worker", "reviewer", "supervisor", "modulator", "chat"],
    )
    run_parser.add_argument("--wrapper", required=True)
    run_parser.add_argument("--model", default="")
    run_parser.add_argument("--workspace", required=True)
    run_parser.add_argument("--prompt-file", required=True)
    run_parser.add_argument("--output-format", default="")
    run_parser.add_argument("--stream-partial-output", action="store_true")
    run_parser.add_argument("--reasoning-effort", default="")
    run_parser.add_argument("--extra-args", default="")
    run_parser.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
