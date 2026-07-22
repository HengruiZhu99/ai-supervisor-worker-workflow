from __future__ import annotations

import tomllib
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from aiflow.domain.progress import ProgressPolicy, Task, ValueClass
from aiflow.state.identifiers import SAFE_ID


def record_to_task(record: Mapping[str, Any]) -> Task:
    return Task(
        id=str(record["id"]),
        objective=str(record["objective"]),
        value_class=ValueClass(str(record.get("value_class", "delivery"))),
        acceptance_ids=tuple(str(value) for value in record.get("acceptance_ids", [])),
        dependencies=tuple(str(value) for value in record.get("dependencies", [])),
        unblocks_task_id=str(record.get("unblocks_task_id", "")),
        allowed_scope=tuple(str(value) for value in record.get("allowed_scope", [])),
        worktree=str(record.get("worktree", "")),
        pre_commands=tuple(
            tuple(str(part) for part in command)
            for command in record.get("pre_commands", [])
        ),
        commands=tuple(
            tuple(str(part) for part in command)
            for command in record.get("commands", [])
        ),
        evidence=tuple(str(value) for value in record.get("evidence", [])),
        expected_diff_budget=int(record.get("expected_diff_budget", 0)),
        status=str(record.get("status", "READY")),
        attempts=int(record.get("attempts", 0)),
        failure_signature=str(record.get("failure_signature", "")),
    )


def _command_arrays(value: object) -> list[list[str]]:
    if not isinstance(value, list) or not value:
        return []
    if all(isinstance(part, str) for part in value):
        return [[str(part) for part in value]]
    if all(isinstance(item, list) for item in value):
        return [[str(part) for part in item] for item in value if item]
    return []


def project_commands(root: Path) -> list[list[str]]:
    result: list[list[str]] = []
    for name in ("build", "test_focused", "test_regression"):
        result.extend(project_command_group(root, name))
    return result


def project_pre_commands(root: Path, kind: str) -> list[list[str]]:
    key = (
        "test_focused"
        if kind in {"refactor", "performance", "portability"}
        else "test_red"
    )
    return project_command_group(root, key)


def project_command_group(root: Path, name: str) -> list[list[str]]:
    return _command_arrays(_project_command_table(root).get(name, []))


def bounded_default_contract(
    root: Path, kind: str, allowed_scope: Sequence[str]
) -> tuple[list[list[str]], list[list[str]], list[str]]:
    scopes = _safe_scopes(allowed_scope)
    if not scopes:
        raise ValueError("a default run requires at least one explicit allowed scope")
    pre_commands = project_pre_commands(root, kind)
    if not pre_commands:
        key = (
            "test_focused"
            if kind in {"refactor", "performance", "portability"}
            else "test_red"
        )
        raise ValueError(f"project command {key} is required before run creation")
    commands = project_commands(root)
    if not commands:
        raise ValueError(
            "at least one build, test_focused, or test_regression command is required"
        )
    if not project_command_group(root, "test_regression"):
        raise ValueError(
            "project command test_regression is required before run creation"
        )
    if not any(command in commands for command in pre_commands):
        raise ValueError(
            "a project pre-change command must be rerun by the post-change gates"
        )
    return pre_commands, commands, scopes


def _project_command_table(root: Path) -> Mapping[str, Any]:
    try:
        config = tomllib.loads(
            (root / ".aiflow" / "project.toml").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return {}
    commands = config.get("commands", {})
    if not isinstance(commands, Mapping):
        return {}
    return commands


def _safe_task_id(spec: Mapping[str, Any], index: int) -> str:
    task_id = str(spec.get("id", f"T{index:04d}"))
    if not SAFE_ID.fullmatch(task_id):
        raise ValueError(f"unsafe task ID: {task_id!r}")
    return task_id


def _safe_scopes(values: Sequence[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        rendered = str(value).replace("\\", "/")
        path = PurePosixPath(rendered)
        if (
            not rendered
            or path.is_absolute()
            or "." in path.parts
            or ".." in path.parts
        ):
            raise ValueError(f"unsafe allowed scope: {value!r}")
        result.append(path.as_posix())
    return result


def task_records(
    specs: Sequence[Mapping[str, Any]],
    *,
    worktree_id: str,
    defaults: Sequence[Sequence[str]] = (),
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, spec in enumerate(specs, start=1):
        requested_kind = str(spec.get("kind", "feature"))
        kind = "bug" if requested_kind == "bugfix" else requested_kind
        commands = spec.get("commands", defaults)
        task_id = _safe_task_id(spec, index)
        record = {
            "id": task_id,
            "objective": str(spec.get("objective", "")).strip(),
            "kind": kind,
            "risk": str(
                spec.get(
                    "risk",
                    "scientific"
                    if kind in {"numerical", "performance", "portability"}
                    else "normal",
                )
            ),
            "value_class": str(spec.get("value_class", "delivery")),
            "acceptance_ids": [str(value) for value in spec.get("acceptance_ids", [])],
            "dependencies": [str(value) for value in spec.get("dependencies", [])],
            "unblocks_task_id": str(spec.get("unblocks_task_id", "")),
            "allowed_scope": _safe_scopes(spec.get("allowed_scope", [])),
            "worktree": worktree_id,
            "pre_commands": [
                [str(part) for part in command]
                for command in spec.get("pre_commands", [])
            ],
            "commands": [[str(part) for part in command] for command in commands],
            "evidence_contract": dict(spec.get("evidence_contract", {})),
            "evidence": [],
            "expected_diff_budget": int(spec.get("expected_diff_budget", 0)),
            "status": "READY",
            "attempts": 0,
            "failure_signature": "",
        }
        if not record["objective"]:
            raise ValueError("every executable task needs an objective")
        records.append(record)
    validate_task_records(records)
    return records


def validate_task_records(records: Sequence[Mapping[str, Any]]) -> None:
    acceptance = {
        str(value) for record in records for value in record.get("acceptance_ids", [])
    }
    ProgressPolicy(
        open_acceptance_ids=acceptance,
        tasks=[record_to_task(record) for record in records],
    )
