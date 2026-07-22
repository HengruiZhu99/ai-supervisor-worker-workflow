from __future__ import annotations

import hashlib
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from aiflow.identity.context import ProjectContext
from aiflow.state.atomic import atomic_write_json, read_json, signed, verify_signed


class HandoffError(ValueError):
    """A portable handoff is stale, corrupt, or belongs to another project."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(context: ProjectContext, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(context.root), *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise HandoffError(result.stderr.strip() or "Git state is unavailable")
    return result.stdout.strip()


def create_handoff(
    context: ProjectContext,
    run: Mapping[str, Any],
    tasks: Mapping[str, Any],
) -> dict[str, Any]:
    run_id = str(run["run_id"])
    identity = context.identity_fields(run_id)
    if any(str(run.get(key, "")) != value for key, value in identity.items()):
        raise HandoffError("run identity does not match the selected checkout")
    contract = context.root / ".aiflow" / "project.toml"
    command = shlex.join(
        [
            "aiflow",
            "--project-root",
            str(context.root),
            "run",
            "resume",
            "--run-id",
            run_id,
        ]
    )
    payload = signed(
        {
            "schema_version": 1,
            **identity,
            "state_revision": int(run["state_revision"]),
            "git_head": _git(context, "rev-parse", "HEAD"),
            "git_branch": _git(context, "rev-parse", "--abbrev-ref", "HEAD"),
            "contract_path": ".aiflow/project.toml",
            "contract_sha256": _sha256(contract),
            "run": dict(run),
            "tasks": list(tasks.get("tasks", [])),
            "resume_command": command,
            "status": "HANDOFF_READY",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        }
    )
    path = context.root / ".aiflow" / "handoffs" / f"{run_id}.json"
    atomic_write_json(path, payload)
    return {**payload, "handoff_path": str(path)}


def verify_handoff(path: Path, context: ProjectContext) -> dict[str, Any]:
    try:
        payload = read_json(path)
        verify_signed(payload, "handoff")
    except (OSError, ValueError) as exc:
        raise HandoffError(str(exc)) from exc
    expected = context.identity_fields(str(payload.get("run_id", "")))
    mismatches = [
        key for key, value in expected.items() if str(payload.get(key, "")) != value
    ]
    if mismatches:
        raise HandoffError("handoff identity mismatch: " + ", ".join(mismatches))
    if str(payload.get("git_head", "")) != _git(context, "rev-parse", "HEAD"):
        raise HandoffError("handoff Git HEAD is stale")
    contract = context.root / str(payload.get("contract_path", ""))
    if not contract.is_file() or str(payload.get("contract_sha256", "")) != _sha256(
        contract
    ):
        raise HandoffError("handoff project contract is stale")
    run_path = context.state_root / "runs" / expected["run_id"] / "RUN.json"
    current = read_json(run_path)
    if int(payload.get("state_revision", -1)) != int(current.get("state_revision", -2)):
        raise HandoffError("handoff state revision is stale")
    return payload
