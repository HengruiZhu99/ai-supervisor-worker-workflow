from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from aiflow.security.process import run_owned_process


class AttestationError(ValueError):
    """A child claim is not supported by controller-observed workspace evidence."""


def _relative(value: object) -> str:
    rendered = str(value).replace("\\", "/")
    path = PurePosixPath(rendered)
    if not rendered or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise AttestationError(f"unsafe workspace evidence path: {value!r}")
    return path.as_posix()


def _git_paths(root: Path) -> list[str]:
    completed = run_owned_process(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=root,
        timeout=30,
    )
    if completed.returncode:
        raise AttestationError(
            f"cannot inventory task workspace: {completed.stderr.strip()}"
        )
    return sorted({_relative(value) for value in completed.stdout.split("\0") if value})


def workspace_snapshot(root: Path) -> dict[str, str]:
    root = root.resolve()
    snapshot: dict[str, str] = {}
    for relative in _git_paths(root):
        path = root / relative
        if path.is_symlink():
            payload = b"symlink\0" + os.readlink(path).encode()
        elif path.is_file():
            payload = b"file\0" + path.read_bytes()
        else:
            payload = b"missing\0"
        snapshot[relative] = hashlib.sha256(payload).hexdigest()
    return snapshot


def changed_paths(before: Mapping[str, str], after: Mapping[str, str]) -> set[str]:
    return {
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    }


def _within_scope(path: str, scopes: Sequence[str]) -> bool:
    normalized = PurePosixPath(path)
    return any(
        normalized == PurePosixPath(scope) or PurePosixPath(scope) in normalized.parents
        for scope in scopes
    )


def _commands(value: object) -> list[list[str]]:
    if not isinstance(value, (list, tuple)):
        return []
    commands: list[list[str]] = []
    for command in value:
        if not isinstance(command, (list, tuple)) or not command:
            raise AttestationError("task commands must be non-empty argument arrays")
        commands.append([str(part) for part in command])
    return commands


def _validate_delta(
    root: Path,
    before: Mapping[str, str],
    result: Mapping[str, Any],
    task: Mapping[str, Any],
) -> tuple[set[str], set[str], str]:
    observed = changed_paths(before, workspace_snapshot(root))
    claimed = {_relative(path) for path in result.get("changed_files", [])}
    delivery = result.get("delivery_evidence", {})
    if not isinstance(delivery, Mapping):
        raise AttestationError("delivery evidence must be an object")
    expected = _relative(delivery.get("expected_artifact", ""))
    if expected not in claimed or expected not in observed:
        raise AttestationError(
            "expected artifact was not changed in the task workspace"
        )
    artifact = root / expected
    if artifact.is_symlink() or not artifact.is_file():
        raise AttestationError("expected artifact must be a present regular file")
    if not claimed <= observed:
        raise AttestationError(
            "child changed-file claims exceed the observed workspace delta"
        )
    _validate_scope_and_budget(observed, task)
    return observed, claimed, expected


def _validate_scope_and_budget(observed: set[str], task: Mapping[str, Any]) -> None:
    scopes = [_relative(scope) for scope in task.get("allowed_scope", [])]
    if scopes and any(not _within_scope(path, scopes) for path in observed):
        raise AttestationError("observed task delta escapes the allowed scope")
    budget = int(task.get("expected_diff_budget", 0))
    if budget and len(observed) > budget:
        raise AttestationError(
            f"task diff budget exceeded: {len(observed)} files changed, budget {budget}"
        )


def _run_commands(
    root: Path,
    task: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    timeout: float,
    injected: Mapping[str, str],
) -> tuple[list[list[str]], list[dict[str, Any]]]:
    configured = _commands(task.get("commands", []))
    if not configured:
        raise AttestationError("delivery acceptance requires controller-owned commands")
    if _commands(result.get("commands_run", [])) != configured:
        raise AttestationError(
            "child command claims do not match the durable task contract"
        )
    results = [
        _run_command(root, command, timeout=timeout, injected=injected)
        for command in configured
    ]
    if any(item["exit_code"] != 0 for item in results):
        raise AttestationError("a controller-owned task command failed")
    return configured, results


def attest_preconditions(
    root: Path,
    task: Mapping[str, Any],
    *,
    timeout: float,
    injected: Mapping[str, str],
) -> list[dict[str, Any]]:
    configured = _commands(task.get("pre_commands", []))
    if not configured:
        raise AttestationError(
            "acceptance requires controller-owned pre-change commands"
        )
    results = [
        _run_command(root.resolve(), command, timeout=timeout, injected=injected)
        for command in configured
    ]
    kind = str(task.get("kind", "feature"))
    passing_baseline = kind in {"refactor", "performance", "portability"}
    if passing_baseline and any(item["exit_code"] != 0 for item in results):
        raise AttestationError(f"{kind} pre-change baseline must pass")
    if not passing_baseline and all(item["exit_code"] == 0 for item in results):
        raise AttestationError(f"{kind} pre-change negative control must fail")
    return results


def _run_command(
    root: Path,
    command: list[str],
    *,
    timeout: float,
    injected: Mapping[str, str],
) -> dict[str, Any]:
    completed = run_owned_process(
        command,
        cwd=root,
        injected=injected,
        timeout=max(0.1, timeout),
    )
    return {
        "command": command,
        "exit_code": int(completed.returncode),
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "attested_by": "controller",
    }


def _controller_cycle(
    task: Mapping[str, Any],
    *,
    expected: str,
    pre_results: Sequence[Mapping[str, Any]],
    post_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    kind = str(task.get("kind", "feature"))
    attempt = int(task.get("attempts", 0)) + 1
    cycle: dict[str, Any] = {
        "green": {"exit_code": int(post_results[0]["exit_code"]), "attested": True},
        "regression": {
            "exit_code": int(post_results[-1]["exit_code"]),
            "attested": True,
        },
        "attempts": attempt,
        "questions": 0,
    }
    first_failure = next(
        (item for item in pre_results if int(item["exit_code"]) != 0),
        pre_results[0],
    )
    if kind in {"feature", "bug"}:
        cycle["red"] = {
            "exit_code": int(first_failure["exit_code"]),
            "discriminating": True,
            "attested": True,
        }
        cycle["observable" if kind == "feature" else "reproduction"] = expected
    elif kind == "refactor":
        cycle["characterization"] = {
            "exit_code": int(pre_results[0]["exit_code"]),
            "discriminating": True,
            "attested": True,
        }
        cycle["behavior_equivalent"] = True
    elif kind == "test":
        cycle["negative_control"] = {
            "exit_code": int(first_failure["exit_code"]),
            "discriminating": True,
            "attested": True,
        }
        contract = task.get("evidence_contract", {})
        oracle = (
            contract.get("oracle", expected)
            if isinstance(contract, Mapping)
            else expected
        )
        cycle["oracle"] = str(oracle)
    else:
        contract = task.get("evidence_contract", {})
        if not isinstance(contract, Mapping):
            raise AttestationError("scientific evidence contract must be an object")
        cycle.update(dict(contract))
    return cycle


def attest_result(
    root: Path,
    *,
    before: Mapping[str, str],
    result: Mapping[str, Any],
    task: Mapping[str, Any],
    timeout: float,
    injected: Mapping[str, str],
    pre_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    root = root.resolve()
    observed, claimed, expected = _validate_delta(root, before, result, task)
    configured, results = _run_commands(
        root, task, result, timeout=timeout, injected=injected
    )
    attested = dict(result)
    attested["cycle_evidence"] = _controller_cycle(
        task,
        expected=expected,
        pre_results=pre_results,
        post_results=results,
    )
    attested["delivery_evidence"] = {
        "changed_files": sorted(claimed),
        "expected_artifact": expected,
        "commands": configured,
        "test_results": results,
        "fresh_end_to_end": True,
        "observed_changed_files": sorted(observed),
    }
    if str(task.get("value_class", "delivery")) == "enabler":
        attested["delivery_evidence"]["completion_proof"] = True
    attested["tests_and_results"] = results
    attested["controller_attestation"] = {
        "workspace": str(root),
        "observed_changed_files": sorted(observed),
        "commands": results,
        "pre_commands": [dict(item) for item in pre_results],
    }
    return attested
