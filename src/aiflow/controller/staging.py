from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from aiflow.agents.results import validate_child_result
from aiflow.controller.attestation import AttestationError
from aiflow.integration.recovery import git_head
from aiflow.state.store import RunStore


Persist = Callable[..., None]


def stage_integration(
    store: RunStore,
    workspace: Path,
    mutable: dict[str, Any],
    *,
    task_id: str,
    attempt: int,
    result: Mapping[str, Any],
    candidate: str,
    base_sha: str,
    identities: Mapping[str, str],
    agent_id: str,
    persist: Persist,
) -> tuple[dict[str, str], Path]:
    validate_child_result(result, identities=identities, task_id=task_id)
    target_before = git_head(workspace)
    staged_result = dict(result)
    orchestration = staged_result.get("orchestration", {})
    if not isinstance(orchestration, Mapping):
        raise AttestationError("integration orchestration metadata is invalid")
    staged_result["orchestration"] = {
        **dict(orchestration),
        "target_before": target_before,
    }
    inbox = store.write_inbox_result(
        task_id=task_id,
        agent_id=f"{agent_id}-{attempt}",
        result=staged_result,
    )
    relative = str(inbox.relative_to(store.path))
    mutable["status"] = "INTEGRATION_PENDING"
    mutable["evidence"] = sorted(
        {str(value) for value in mutable.get("evidence", [])} | {relative}
    )
    mutable["integration"] = {
        "candidate": candidate,
        "base_sha": base_sha,
        "target_before": target_before,
        "inbox": relative,
        "attempt": attempt,
        "writer_worktree_path": str(orchestration.get("writer_worktree_path", "")),
    }
    persist(event_type="task_integration_prepared", evidence=list(mutable["evidence"]))
    return {"target_before": target_before, "inbox": relative}, inbox
