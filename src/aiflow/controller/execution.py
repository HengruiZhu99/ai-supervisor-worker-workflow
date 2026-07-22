from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from aiflow.agents.results import validate_child_result
from aiflow.controller.attestation import attest_result, workspace_snapshot
from aiflow.controller.orchestration import OrchestratedTaskRunner
from aiflow.controller.runner import Budgets, ControllerOutcome, ControllerRunner
from aiflow.controller.watchdog import DeterministicWatchdog
from aiflow.domain.evidence import validate_cycle
from aiflow.controller.tasks import record_to_task
from aiflow.domain.progress import ProgressPolicy, Task
from aiflow.state.store import RunStore


AgentBackend = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass
class ExecutionResult:
    outcome: ControllerOutcome
    acceptance_ids_closed: tuple[str, ...]


class TaskExecutionEngine:
    """Execute durable tasks through one bounded backend and one canonical writer."""

    def __init__(
        self,
        store: RunStore,
        *,
        controller_id: str,
        backend: AgentBackend,
        agent_id: str,
        budgets: Budgets,
        watchdog: DeterministicWatchdog | None = None,
        workspace: Path | None = None,
    ) -> None:
        self.store = store
        self.controller_id = controller_id
        self.agent_id = agent_id
        self.watchdog = watchdog or DeterministicWatchdog()
        self.workspace = (workspace or store.context.root).resolve()
        self.budgets = budgets
        self.runner = ControllerRunner(
            budgets=budgets, agent_call=lambda capsule: backend(capsule)
        )
        records = self.store.read_tasks()["tasks"]
        self.records: list[dict[str, Any]] = [dict(record) for record in records]
        open_ids = {
            str(value)
            for record in self.records
            for value in record.get("acceptance_ids", [])
            if record.get("status") != "ACCEPTED"
        }
        self.policy = ProgressPolicy(
            open_acceptance_ids=open_ids,
            tasks=[record_to_task(record) for record in self.records],
        )
        self.closed = {
            str(value)
            for record in self.records
            if record.get("status") == "ACCEPTED"
            for value in record.get("acceptance_ids", [])
        }
        self.mode = str(self.store.read_run()["mode"])

    def _record(self, task_id: str) -> dict[str, Any]:
        return next(record for record in self.records if record["id"] == task_id)

    def _persist(self, *, event_type: str, evidence: list[str] | None = None) -> None:
        revision = int(self.store.read_run()["state_revision"])
        self.store.transition(
            revision,
            {},
            event_type=event_type,
            task_updates={"tasks": self.records},
            evidence=evidence,
            controller_id=self.controller_id,
        )

    def _failure(self, record: dict[str, Any], exc: Exception) -> str:
        signature = hashlib.sha256(f"{type(exc).__name__}:{exc}".encode()).hexdigest()[
            :16
        ]
        record["attempts"] = int(record.get("attempts", 0)) + 1
        record["failure_signature"] = signature
        blocked = record["attempts"] >= self.budgets.max_attempts
        record["status"] = "BLOCKED" if blocked else "READY"
        self._persist(event_type="task_attempt_failed")
        self.watchdog.observe(
            {
                "kind": "no_progress",
                "task_id": record["id"],
                "failure_signature": signature,
                "attempt": record["attempts"],
            }
        )
        return "blocked" if blocked else f"retry:{signature}"

    def _terminal_state(self) -> str:
        return (
            "succeeded"
            if self.records
            and all(record.get("status") == "ACCEPTED" for record in self.records)
            else "blocked"
        )

    def _next_task(self) -> Task | None:
        try:
            return self.policy.next_task()
        except Exception:
            return None

    def _capsule(
        self, task: Task, record: Mapping[str, Any], attempt: int
    ) -> dict[str, Any]:
        return {
            "action": "execute_task",
            **self.store.context.identity_fields(self.store.run_id),
            "task_id": task.id,
            "mode": self.mode,
            "task": dict(record),
            "attempt": attempt,
            "agent_id": self.agent_id,
            "agent_role": "implementation-worker",
            "working_directory": str(self.workspace),
        }

    def _invoke_result(
        self,
        task: Task,
        record: Mapping[str, Any],
        capsule: dict[str, Any],
        identities: Mapping[str, str],
    ) -> dict[str, Any]:
        if self.mode == "orchestrated":
            result = OrchestratedTaskRunner(
                self.store,
                invoke=self.runner.invoke_agent,
                timeout=float(self.budgets.max_wall_time),
            ).execute(record, capsule)
        else:
            before = workspace_snapshot(self.workspace)
            result = dict(self.runner.invoke_agent(capsule))
            result = attest_result(
                self.workspace,
                before=before,
                result=result,
                task=record,
                timeout=float(self.budgets.max_wall_time),
                injected={
                    f"AIFLOW_{key.upper()}": value for key, value in identities.items()
                },
            )
        validate_child_result(result, identities=identities, task_id=task.id)
        return result

    def _validate_acceptance(
        self, task: Task, record: Mapping[str, Any], result: Mapping[str, Any]
    ) -> set[str]:
        if result.get("status") != "completed":
            raise ValueError(f"agent result is not completed: {result.get('status')}")
        kind = str(result.get("cycle_kind", ""))
        if kind != str(record.get("kind", "feature")):
            raise ValueError("cycle kind does not match the durable task contract")
        validate_cycle(kind, result.get("cycle_evidence", {}))
        claimed = {str(value) for value in result.get("closed_acceptance_ids", [])}
        self.policy.accept(
            task.id,
            closed_acceptance_ids=claimed,
            evidence=result.get("delivery_evidence", {}),
        )
        return claimed

    def _finalize_acceptance(
        self,
        record: dict[str, Any],
        *,
        attempt: int,
        inbox: Path,
        claimed: set[str],
    ) -> str:
        record["attempts"] = attempt
        record["failure_signature"] = ""
        record["status"] = "ACCEPTED"
        record["evidence"] = sorted(
            {str(value) for value in record.get("evidence", [])}
            | {str(inbox.relative_to(self.store.path))}
        )
        self.closed.update(claimed)
        self._persist(event_type="task_accepted", evidence=list(record["evidence"]))
        complete = all(item.get("status") == "ACCEPTED" for item in self.records)
        return (
            "succeeded"
            if complete and not self.policy.open_acceptance_ids
            else "progress"
        )

    def _step(self) -> str:
        task = self._next_task()
        if task is None:
            return self._terminal_state()
        record = self._record(task.id)
        if int(record.get("attempts", 0)) >= self.budgets.max_attempts:
            record["status"] = "BLOCKED"
            return "blocked"
        attempt = int(record.get("attempts", 0)) + 1
        capsule = self._capsule(task, record, attempt)
        try:
            identities = self.store.context.identity_fields(self.store.run_id)
            result = self._invoke_result(task, record, capsule, identities)
            claimed = self._validate_acceptance(task, record, result)
            inbox = self.store.write_inbox_result(
                task_id=task.id,
                agent_id=f"{self.agent_id}-{attempt}",
                result=result,
            )
        except Exception as exc:
            return self._failure(record, exc)
        return self._finalize_acceptance(
            record, attempt=attempt, inbox=inbox, claimed=claimed
        )

    def run(self) -> ExecutionResult:
        outcome = self.runner.run(self._step)
        return ExecutionResult(outcome, tuple(sorted(self.closed)))
