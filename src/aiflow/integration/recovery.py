from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

from aiflow.security.process import run_owned_process
from aiflow.state.atomic import read_json, verify_signed
from aiflow.state.store import RunStore


class IntegrationRecoveryError(RuntimeError):
    """A durable prepared integration cannot be reconciled safely."""


def git_head(root: Path) -> str:
    completed = run_owned_process(["git", "rev-parse", "HEAD"], cwd=root, timeout=10)
    if completed.returncode or not completed.stdout.strip():
        raise IntegrationRecoveryError("cannot capture integration target HEAD")
    return completed.stdout.strip()


def _git_value(root: Path, *arguments: str) -> str:
    completed = run_owned_process(["git", *arguments], cwd=root, timeout=10)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _gate_evidence_valid(value: object) -> bool:
    return isinstance(value, list) and all(
        any(str(item).startswith(f"{label}:") for item in value)
        for label in ("focused", "regression", "quality")
    )


def _exact_writer_candidate(worktree: Path, base_sha: str, candidate: str) -> bool:
    status = run_owned_process(
        ["git", "status", "--porcelain"], cwd=worktree, timeout=10
    )
    ancestry = run_owned_process(
        ["git", "merge-base", "--is-ancestor", base_sha, candidate],
        cwd=worktree,
        timeout=10,
    )
    return bool(
        _git_value(worktree, "rev-parse", "HEAD") == candidate
        and status.returncode == 0
        and not status.stdout.strip()
        and ancestry.returncode == 0
    )


def pending_integration_matches(root: Path, integration: Mapping[str, Any]) -> bool:
    integrated = str(integration.get("integrated_commit", ""))
    tested_tree = str(integration.get("tested_tree", ""))
    target_before = str(integration.get("target_before", ""))
    target_ref = str(integration.get("target_ref", ""))
    transaction_id = str(integration.get("transaction_id", ""))
    gate_evidence = integration.get("gate_evidence", [])
    if not all(
        re.fullmatch(r"[0-9a-f]{40,64}", value)
        for value in (integrated, tested_tree, target_before)
    ):
        return False
    expected_id = hashlib.sha256(
        f"{target_ref}\0{target_before}\0{integrated}\0{tested_tree}".encode()
    ).hexdigest()
    if transaction_id != expected_id:
        return False
    if not _gate_evidence_valid(gate_evidence):
        return False
    symbolic = _git_value(root, "symbolic-ref", "-q", "HEAD") or "HEAD"
    status = run_owned_process(["git", "status", "--porcelain"], cwd=root, timeout=10)
    return bool(
        symbolic == target_ref
        and git_head(root) == integrated
        and _git_value(root, "rev-parse", "HEAD^{tree}") == tested_tree
        and status.returncode == 0
        and not status.stdout.strip()
    )


def pending_result(
    store: RunStore, record: Mapping[str, Any]
) -> tuple[dict[str, Any], Path, Mapping[str, Any]]:
    integration = record.get("integration", {})
    if not isinstance(integration, Mapping):
        raise IntegrationRecoveryError("pending integration metadata is invalid")
    relative = Path(str(integration.get("inbox", "")))
    inbox = (store.path / relative).resolve()
    if store.path.resolve() not in inbox.parents or not inbox.is_file():
        raise IntegrationRecoveryError("pending integration inbox escaped the run")
    result = read_json(inbox)
    verify_signed(result, "pending integration inbox")
    return result, inbox, integration


def orphaned_result(
    store: RunStore,
    record: Mapping[str, Any],
    *,
    agent_id: str,
    attempt: int,
) -> tuple[dict[str, Any], Path, dict[str, Any]] | None:
    relative = (
        Path("inbox")
        / str(record.get("id", ""))
        / (f"{agent_id}-{attempt}")
        / "result.json"
    )
    inbox = (store.path / relative).resolve()
    if store.path.resolve() not in inbox.parents:
        raise IntegrationRecoveryError("orphaned integration inbox escaped the run")
    if not inbox.exists():
        return None
    result = read_json(inbox)
    verify_signed(result, "orphaned integration inbox")
    orchestration = result.get("orchestration")
    if not isinstance(orchestration, Mapping):
        raise IntegrationRecoveryError("orphaned integration metadata is invalid")
    candidate = str(orchestration.get("candidate", ""))
    base_sha = str(orchestration.get("base_sha", ""))
    target_before = str(orchestration.get("target_before", ""))
    if not all(
        re.fullmatch(r"[0-9a-f]{40,64}", value)
        for value in (candidate, base_sha, target_before)
    ):
        raise IntegrationRecoveryError(
            "orphaned integration commit identity is invalid"
        )
    if git_head(store.context.root) != target_before:
        raise IntegrationRecoveryError("orphaned integration target has drifted")
    worktree = Path(str(orchestration.get("writer_worktree_path", ""))).resolve()
    parent = (store.runtime / "agent-worktrees").resolve()
    if parent not in worktree.parents or not worktree.is_dir():
        raise IntegrationRecoveryError("orphaned writer worktree is unavailable")
    if not _exact_writer_candidate(worktree, base_sha, candidate):
        raise IntegrationRecoveryError(
            "orphaned writer candidate is not exact and clean"
        )
    integration = {
        "candidate": candidate,
        "base_sha": base_sha,
        "target_before": target_before,
        "inbox": str(relative),
        "attempt": attempt,
        "writer_worktree_path": str(worktree),
    }
    return result, inbox, integration


def retire_writer_worktree(store: RunStore, integration: Mapping[str, Any]) -> None:
    raw = str(integration.get("writer_worktree_path", ""))
    if not raw:
        return
    path = Path(raw).resolve()
    parent = (store.runtime / "agent-worktrees").resolve()
    if parent not in path.parents:
        raise IntegrationRecoveryError("pending writer worktree escaped runtime scope")
    if not path.exists():
        return
    removed = run_owned_process(
        ["git", "worktree", "remove", str(path)],
        cwd=store.context.root,
        timeout=60,
    )
    if removed.returncode:
        raise IntegrationRecoveryError("pending writer worktree cleanup failed")
