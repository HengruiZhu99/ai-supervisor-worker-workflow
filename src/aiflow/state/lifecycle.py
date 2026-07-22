from __future__ import annotations

import os
import re
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from aiflow.controller.runner import Budgets, ControllerRunner
from aiflow.identity.context import ProjectContext
from aiflow.state.store import RunStore
from aiflow.state.handoff import create_handoff


def _safe(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", value)
    return cleaned[:128] or "unknown"


class RunLifecycle:
    def __init__(
        self, context: ProjectContext, *, runtime_env: Mapping[str, str] | None = None
    ) -> None:
        self.context = context
        self.runtime_env = runtime_env

    def store(self, run_id: str) -> RunStore:
        return RunStore(self.context, run_id, runtime_env=self.runtime_env)

    def _claim(self, store: RunStore) -> str:
        controller_id = f"controller-{uuid.uuid4()}"
        store.claim_controller(
            controller_id,
            host_id=_safe(socket.gethostname()),
            boot_id=f"boot-{uuid.getnode():x}",
            pid=os.getpid(),
            process_start_time=str(time.time_ns()),
            ttl_seconds=120,
        )
        return controller_id

    def start(
        self,
        *,
        mode: str,
        objective: str,
        acceptance_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        if mode not in {"solo", "orchestrated"}:
            raise ValueError(f"unknown run mode: {mode}")
        if not objective.strip():
            raise ValueError("run objective is required")
        store = RunStore.create(self.context, mode=mode, runtime_env=self.runtime_env)
        controller = self._claim(store)
        task = {
            "id": "T0001",
            "objective": objective.strip(),
            "value_class": "delivery",
            "acceptance_ids": list(acceptance_ids),
            "dependencies": [],
            "unblocks_task_id": "",
            "allowed_scope": [],
            "worktree": self.context.worktree_id,
            "commands": [],
            "evidence": [],
            "expected_diff_budget": 0,
            "status": "READY",
            "attempts": 0,
            "failure_signature": "",
        }
        try:
            run = store.transition(
                0,
                {"status": "PAUSED", "objective": objective.strip()},
                event_type="run_initialized",
                task_updates={"tasks": [task]},
                controller_id=controller,
            )
        finally:
            store.release_controller(controller)
        return run

    def status(self, run_id: str) -> dict[str, Any]:
        store = self.store(run_id)
        run = store.read_run()
        return {**run, "tasks": store.read_tasks()["tasks"]}

    def resume(
        self,
        run_id: str,
        *,
        budgets: Budgets | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        store = self.store(run_id)
        store.recover()
        controller = self._claim(store)
        try:
            current = store.read_run()
            revision = int(current["state_revision"])
            if expected_revision is not None and revision != expected_revision:
                from aiflow.state.store import RevisionConflict

                raise RevisionConflict(
                    f"stale revision {expected_revision}; current revision is {revision}"
                )
            running = store.transition(
                revision, {"status": "RUNNING"},
                event_type="run_resumed", controller_id=controller,
            )
            outcome = ControllerRunner(budgets=budgets).run(lambda: "idle")
            final = store.transition(
                int(running["state_revision"]),
                {"status": "PAUSED", "terminal_reason": outcome.value},
                event_type="controller_exit",
                controller_id=controller,
            )
        finally:
            store.release_controller(controller)
        return {**final, "outcome": outcome.value}

    def stop(self, run_id: str, *, expected_revision: int | None = None) -> dict[str, Any]:
        store = self.store(run_id)
        store.recover()
        controller = self._claim(store)
        try:
            current = store.read_run()
            revision = int(current["state_revision"])
            if expected_revision is not None and revision != expected_revision:
                from aiflow.state.store import RevisionConflict

                raise RevisionConflict(
                    f"stale revision {expected_revision}; current revision is {revision}"
                )
            return store.transition(
                revision,
                {"status": "STOPPED", "terminal_reason": "STOPPED_BY_USER"},
                event_type="run_stopped", controller_id=controller,
            )
        finally:
            store.release_controller(controller)

    def pause(self, run_id: str, *, expected_revision: int) -> dict[str, Any]:
        store = self.store(run_id)
        store.recover()
        controller = self._claim(store)
        try:
            current = store.read_run()
            revision = int(current["state_revision"])
            if revision != expected_revision:
                from aiflow.state.store import RevisionConflict

                raise RevisionConflict(
                    f"stale revision {expected_revision}; current revision is {revision}"
                )
            return store.transition(
                revision,
                {"status": "PAUSED", "terminal_reason": "PAUSED_BY_USER"},
                event_type="run_paused",
                controller_id=controller,
            )
        finally:
            store.release_controller(controller)

    def handoff(self, run_id: str, *, expected_revision: int) -> dict[str, Any]:
        store = self.store(run_id)
        store.recover()
        controller = self._claim(store)
        try:
            current = store.read_run()
            revision = int(current["state_revision"])
            if revision != expected_revision:
                from aiflow.state.store import RevisionConflict

                raise RevisionConflict(
                    f"stale revision {expected_revision}; current revision is {revision}"
                )
            final = store.transition(
                revision,
                {"status": "PAUSED", "terminal_reason": "HANDOFF_READY"},
                event_type="handoff_exported",
                controller_id=controller,
            )
            return create_handoff(self.context, final, store.read_tasks())
        finally:
            store.release_controller(controller)

    def list(self) -> list[dict[str, Any]]:
        root = self.context.state_root / "runs"
        if not root.is_dir():
            return []
        result = []
        for path in sorted(root.iterdir()):
            if path.is_dir() and (path / "RUN.json").is_file():
                result.append(self.store(path.name).read_run())
        return result
