from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from aiflow.domain.progress import Task
from aiflow.state.store import RunStore


def execution_capsule(
    store: RunStore,
    task: Task,
    record: Mapping[str, Any],
    *,
    attempt: int,
    mode: str,
    agent_id: str,
    workspace: Path,
) -> dict[str, Any]:
    return {
        "action": "execute_task",
        **store.context.identity_fields(store.run_id),
        "task_id": task.id,
        "mode": mode,
        "task": dict(record),
        "attempt": attempt,
        "agent_id": agent_id,
        "agent_role": "implementation-worker",
        "working_directory": str(workspace),
    }
