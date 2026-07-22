from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _command_matrix(value: object) -> list[list[str]] | None:
    if not isinstance(value, list) or not value:
        return None
    if not all(
        isinstance(command, list)
        and command
        and all(isinstance(part, str) and part for part in command)
        for command in value
    ):
        return None
    return [[str(part) for part in command] for command in value]


def _validate_task_contract(task: dict[str, Any], index: int) -> None:
    label = str(task.get("id", f"entry {index}"))
    scopes = task.get("allowed_scope")
    if (
        not isinstance(scopes, list)
        or not scopes
        or not all(isinstance(scope, str) and scope for scope in scopes)
    ):
        raise ValueError(f"task {label} requires a non-empty allowed_scope")
    pre_commands = _command_matrix(task.get("pre_commands"))
    commands = _command_matrix(task.get("commands"))
    if pre_commands is None:
        raise ValueError(f"task {label} requires non-empty pre_commands")
    if commands is None:
        raise ValueError(f"task {label} requires non-empty commands")
    if not any(command in commands for command in pre_commands):
        raise ValueError(
            f"task {label} must rerun a pre-change causal command after the change"
        )


def load_task_specs(value: str) -> tuple[dict[str, Any], ...]:
    if not value:
        return ()
    path = Path(value).expanduser().resolve()
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("task DAG file exceeds 1 MiB")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read task DAG {path}: {exc}") from exc
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list) or not tasks or len(tasks) > 100:
        raise ValueError("task DAG requires between 1 and 100 task objects")
    if any(not isinstance(task, dict) for task in tasks):
        raise ValueError("every task DAG entry must be an object")
    for index, task in enumerate(tasks, start=1):
        _validate_task_contract(task, index)
    return tuple(dict(task) for task in tasks)


def add_budgets(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-wall-time", type=int, default=14_400)
    parser.add_argument("--max-tasks", type=int, default=25)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--max-idle", type=int, default=900)
    parser.add_argument("--max-agent-calls", type=int, default=50)


def add_run_start_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", choices=("solo", "orchestrated"), default="solo")
    parser.add_argument("--objective", required=True)
    parser.add_argument("--acceptance-id", action="append", default=[])
    parser.add_argument(
        "--allowed-scope",
        action="append",
        default=[],
        help="bounded repository-relative path for a default task (repeatable)",
    )
    parser.add_argument(
        "--task-file",
        default="",
        help="JSON executable task contract (one Solo task or up to 100 orchestrated tasks)",
    )
    parser.add_argument(
        "--task-kind",
        choices=(
            "feature",
            "bug",
            "bugfix",
            "refactor",
            "test",
            "numerical",
            "performance",
            "portability",
        ),
        default="feature",
    )
    parser.add_argument(
        "--parent-sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default="",
    )


def add_handoff_actions(actions: argparse._SubParsersAction) -> None:
    for name in ("pause", "handoff"):
        action = actions.add_parser(name)
        action.add_argument("--run-id", default="")
    verify = actions.add_parser("verify-handoff")
    verify.add_argument("path")


def add_quality_commands(commands: argparse._SubParsersAction, command: object) -> None:
    quality = commands.add_parser(
        "quality", help="run deterministic architecture gates"
    )
    actions = quality.add_subparsers(dest="quality_action", required=True)
    actions.add_parser("baseline")
    check = actions.add_parser("check")
    check.add_argument(
        "--diff-base",
        default="HEAD",
        help="explicit Git base for source-diff budgets (CI must pass the PR/push base)",
    )
    quality.set_defaults(func=command)
