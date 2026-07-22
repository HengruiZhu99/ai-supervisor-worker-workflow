from __future__ import annotations

import os
import re
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from aiflow.controller.execution import AgentBackend, TaskExecutionEngine
from aiflow.controller.runner import Budgets, ControllerRunner
from aiflow.controller.watchdog import DeterministicWatchdog
from aiflow.identity.context import ProjectContext
from aiflow.state.store import RunStore
from aiflow.state.handoff import create_handoff


def _safe(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", value)
    return cleaned[:128] or "unknown"


class RunLifecycle:
    def __init__(
        self,
        context: ProjectContext,
        *,
        runtime_env: Mapping[str, str] | None = None,
        agent_backend: AgentBackend | None = None,
        agent_id: str = "codex-worker",
        watchdog: DeterministicWatchdog | None = None,
    ) -> None:
        self.context = context
        self.runtime_env = runtime_env
        self.agent_backend = agent_backend
        self.agent_id = agent_id
        self.watchdog = watchdog

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
        task_kind: str = "feature",
        task_specs: tuple[Mapping[str, Any], ...] = (),
    ) -> dict[str, Any]:
        if mode not in {"solo", "orchestrated"}:
            raise ValueError(f"unknown run mode: {mode}")
        if not objective.strip():
            raise ValueError("run objective is required")
        store = RunStore.create(self.context, mode=mode, runtime_env=self.runtime_env)
        controller = self._claim(store)
        specs = task_specs or (
            {
                "id": "T0001",
                "objective": objective.strip(),
                "kind": task_kind,
                "acceptance_ids": list(
                    acceptance_ids or (f"AC-RUN-{store.run_id[:8].upper()}",)
                ),
            },
        )
        tasks = []
        for index, spec in enumerate(specs, start=1):
            task = {
                "id": str(spec.get("id", f"T{index:04d}")),
                "objective": str(spec.get("objective", "")).strip(),
                "kind": str(spec.get("kind", "feature")),
                "value_class": str(spec.get("value_class", "delivery")),
                "acceptance_ids": [str(value) for value in spec.get("acceptance_ids", [])],
                "dependencies": [str(value) for value in spec.get("dependencies", [])],
                "unblocks_task_id": str(spec.get("unblocks_task_id", "")),
                "allowed_scope": [str(value) for value in spec.get("allowed_scope", [])],
                "worktree": self.context.worktree_id,
                "commands": [list(command) for command in spec.get("commands", [])],
                "evidence": [],
                "expected_diff_budget": int(spec.get("expected_diff_budget", 0)),
                "status": "READY",
                "attempts": 0,
                "failure_signature": "",
            }
            if not task["objective"]:
                raise ValueError("every executable task needs an objective")
            tasks.append(task)
        try:
            run = store.transition(
                0,
                {"status": "PAUSED", "objective": objective.strip()},
                event_type="run_initialized",
                task_updates={"tasks": tasks},
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
            selected = budgets or Budgets()
            if self.agent_backend is None:
                outcome = ControllerRunner(budgets=selected).run(lambda: "idle")
                closed: tuple[str, ...] = ()
            else:
                execution = TaskExecutionEngine(
                    store,
                    controller_id=controller,
                    backend=self.agent_backend,
                    agent_id=self.agent_id,
                    budgets=selected,
                    watchdog=self.watchdog,
                ).run()
                outcome = execution.outcome
                closed = execution.acceptance_ids_closed
            status = "SUCCEEDED" if outcome.value == "SUCCEEDED" else "PAUSED"
            if outcome.value in {"BLOCKED", "FAILED", "BUDGET_EXHAUSTED"}:
                status = outcome.value
            final = store.transition(
                int(store.read_run()["state_revision"]),
                {
                    "status": status,
                    "terminal_reason": outcome.value,
                    "acceptance_ids_closed": list(closed),
                },
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
