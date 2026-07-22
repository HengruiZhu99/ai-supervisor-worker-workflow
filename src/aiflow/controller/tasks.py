from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Mapping, Sequence

from aiflow.domain.progress import ProgressPolicy, Task, ValueClass


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
    try:
        config = tomllib.loads(
            (root / ".aiflow" / "project.toml").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return []
    commands = config.get("commands", {})
    if not isinstance(commands, Mapping):
        return []
    result: list[list[str]] = []
    for name in ("build", "test_focused", "test_regression"):
        result.extend(_command_arrays(commands.get(name, [])))
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
        record = {
            "id": str(spec.get("id", f"T{index:04d}")),
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
            "allowed_scope": [str(value) for value in spec.get("allowed_scope", [])],
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
