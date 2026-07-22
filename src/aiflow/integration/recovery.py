from __future__ import annotations

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


def candidate_is_integrated(root: Path, candidate: str) -> bool:
    completed = run_owned_process(
        ["git", "merge-base", "--is-ancestor", candidate, "HEAD"],
        cwd=root,
        timeout=10,
    )
    return completed.returncode == 0


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
