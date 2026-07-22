from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from typing import Any, Mapping

from aiflow.controller.execution import AgentBackend, TaskExecutionEngine
from aiflow.controller.runner import Budgets, ControllerRunner
from aiflow.controller.watchdog import DeterministicWatchdog
from aiflow.controller.tasks import (
    bounded_default_contract,
    project_commands,
    project_pre_commands,
    task_records,
)
from aiflow.identity.context import ProjectContext
from aiflow.identity.context import validate_thread_identity
from aiflow.state.atomic import atomic_write_json, read_json, signed, verify_signed
from aiflow.state.store import RunStore, StateError
from aiflow.state.handoff import create_handoff
from aiflow.state.leases import maintain_controller
from aiflow.state.locks import owned_directory_lock
from aiflow.state.ownership import owner_is_live, owner_is_local


DefaultContract = tuple[list[list[str]], list[list[str]], list[str]] | None


class RunLifecycle:
    def __init__(
        self,
        context: ProjectContext,
        *,
        runtime_env: Mapping[str, str] | None = None,
        agent_backend: AgentBackend | None = None,
        agent_id: str = "codex-worker",
        watchdog: DeterministicWatchdog | None = None,
        controller_ttl_seconds: float = 120.0,
        heartbeat_interval_seconds: float = 30.0,
    ) -> None:
        self.context = context
        self.runtime_env = runtime_env
        self.agent_backend = agent_backend
        self.agent_id = agent_id
        self.watchdog = watchdog
        self.controller_ttl_seconds = controller_ttl_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds

    def store(self, run_id: str) -> RunStore:
        return RunStore(self.context, run_id, runtime_env=self.runtime_env)

    def _claim(self, store: RunStore) -> str:
        controller_id = f"controller-{uuid.uuid4()}"
        store.claim_controller(
            controller_id,
            ttl_seconds=self.controller_ttl_seconds,
            **store.local_process_identity(),
        )
        return controller_id

    @contextmanager
    def checkout_mutation(self, run_id: str):
        root = self.context.state_root
        root.mkdir(parents=True, exist_ok=True)
        guard = root / ".mutation.lock"
        lease = root / "MUTATING_RUN.json"
        with owned_directory_lock(guard, timeout=0.25):
            if lease.exists():
                current = read_json(lease)
                verify_signed(current, "checkout mutation lease")
                if current.get("run_id") != run_id:
                    if not owner_is_local(current):
                        raise StateError(
                            "checkout mutation lease belongs to an ambiguous foreign host/boot"
                        )
                    if owner_is_live(current):
                        raise StateError(
                            f"checkout mutation is already owned by run {current.get('run_id')}"
                        )
                    lease.unlink()
            identity = self.store(run_id).local_process_identity()
            atomic_write_json(
                lease,
                signed(
                    {
                        "schema_version": 1,
                        **self.context.identity_fields(run_id),
                        **identity,
                        "claimed_at": time.time_ns(),
                    }
                ),
            )
            try:
                yield
            finally:
                if lease.exists():
                    try:
                        current = read_json(lease)
                    except (OSError, ValueError, json.JSONDecodeError):
                        current = {}
                    if current.get("run_id") == run_id:
                        lease.unlink(missing_ok=True)

    def _validate_saved_thread(self, store: RunStore) -> None:
        record = store.path / "context" / "CODEX_THREAD.json"
        if not record.exists():
            return
        validate_thread_identity(
            read_json(record),
            checkout_id=self.context.checkout_id,
            run_id=store.run_id,
            cwd=self.context.root,
            worktree_id=self.context.worktree_id,
        )

    def _prepare_tasks(
        self,
        task_specs: tuple[Mapping[str, Any], ...],
        task_kind: str,
        allowed_scope: tuple[str, ...] | None,
    ) -> tuple[list[dict[str, Any]], DefaultContract]:
        if task_specs:
            return task_records(task_specs, worktree_id=self.context.worktree_id), None
        contract = (
            bounded_default_contract(self.context.root, task_kind, allowed_scope)
            if allowed_scope is not None
            else None
        )
        return [], contract

    def _default_tasks(
        self,
        store: RunStore,
        objective: str,
        acceptance_ids: tuple[str, ...],
        task_kind: str,
        allowed_scope: tuple[str, ...] | None,
        contract: DefaultContract,
    ) -> list[dict[str, Any]]:
        configured = contract or (
            project_pre_commands(self.context.root, task_kind),
            project_commands(self.context.root),
            list(allowed_scope or ()),
        )
        pre_commands, commands, scopes = configured
        return task_records(
            (
                {
                    "id": "T0001",
                    "objective": objective.strip(),
                    "kind": task_kind,
                    "acceptance_ids": list(
                        acceptance_ids or (f"AC-RUN-{store.run_id[:8].upper()}",)
                    ),
                    "pre_commands": pre_commands,
                    "allowed_scope": scopes,
                },
            ),
            worktree_id=self.context.worktree_id,
            defaults=commands,
        )

    def start(
        self,
        *,
        mode: str,
        objective: str,
        acceptance_ids: tuple[str, ...] = (),
        task_kind: str = "feature",
        task_specs: tuple[Mapping[str, Any], ...] = (),
        allowed_scope: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        if mode not in {"solo", "orchestrated"}:
            raise ValueError(f"unknown run mode: {mode}")
        if not objective.strip():
            raise ValueError("run objective is required")
        if mode == "solo" and len(task_specs) > 1:
            raise ValueError("Solo mode accepts exactly one bounded task")
        tasks, default_contract = self._prepare_tasks(
            task_specs, task_kind, allowed_scope
        )
        store = RunStore.create(self.context, mode=mode, runtime_env=self.runtime_env)
        controller = self._claim(store)
        if not tasks:
            tasks = self._default_tasks(
                store,
                objective,
                acceptance_ids,
                task_kind,
                allowed_scope,
                default_contract,
            )
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
        self._validate_saved_thread(store)
        with self.checkout_mutation(run_id):
            controller = self._claim(store)
            try:
                current = store.read_run()
                revision = int(current["state_revision"])
                if expected_revision is not None and revision != expected_revision:
                    from aiflow.state.store import RevisionConflict

                    raise RevisionConflict(
                        f"stale revision {expected_revision}; current revision is {revision}"
                    )
                store.transition(
                    revision,
                    {"status": "RUNNING"},
                    event_type="run_resumed",
                    controller_id=controller,
                )
                selected = budgets or Budgets()
                try:
                    with maintain_controller(
                        store,
                        controller,
                        ttl_seconds=self.controller_ttl_seconds,
                        interval_seconds=self.heartbeat_interval_seconds,
                    ):
                        if self.agent_backend is None:
                            outcome = ControllerRunner(budgets=selected).run(
                                lambda: "idle"
                            )
                            closed = tuple(current.get("acceptance_ids_closed", []))
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
                except Exception as exc:
                    from aiflow.controller.runner import ControllerOutcome

                    try:
                        store.heartbeat_controller(
                            controller, ttl_seconds=self.controller_ttl_seconds
                        )
                    except Exception:
                        pass
                    outcome = ControllerOutcome.FAILED
                    closed = tuple(current.get("acceptance_ids_closed", []))
                    failure_detail = f"{type(exc).__name__}: {exc}"[:1000]
                else:
                    failure_detail = ""
                status = "SUCCEEDED" if outcome.value == "SUCCEEDED" else "PAUSED"
                if outcome.value in {"BLOCKED", "FAILED", "BUDGET_EXHAUSTED"}:
                    status = outcome.value
                final = store.transition(
                    int(store.read_run()["state_revision"]),
                    {
                        "status": status,
                        "terminal_reason": outcome.value,
                        "acceptance_ids_closed": list(closed),
                        "failure_detail": failure_detail,
                    },
                    event_type="controller_exit",
                    controller_id=controller,
                )
            finally:
                store.release_controller(controller)
        return {**final, "outcome": outcome.value}

    def stop(
        self, run_id: str, *, expected_revision: int | None = None
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
            return store.transition(
                revision,
                {"status": "STOPPED", "terminal_reason": "STOPPED_BY_USER"},
                event_type="run_stopped",
                controller_id=controller,
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
        return sorted(
            result, key=lambda item: (str(item["created_at"]), str(item["run_id"]))
        )
