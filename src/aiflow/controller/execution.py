from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from aiflow.agents.results import validate_child_result
from aiflow.controller.runner import Budgets, ControllerOutcome, ControllerRunner
from aiflow.controller.watchdog import DeterministicWatchdog
from aiflow.domain.evidence import validate_cycle
from aiflow.domain.progress import ProgressPolicy, Task, ValueClass
from aiflow.state.store import RunStore


AgentBackend = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _task(record: Mapping[str, Any]) -> Task:
    return Task(
        id=str(record["id"]),
        objective=str(record["objective"]),
        value_class=ValueClass(str(record.get("value_class", "delivery"))),
        acceptance_ids=tuple(str(value) for value in record.get("acceptance_ids", [])),
        dependencies=tuple(str(value) for value in record.get("dependencies", [])),
        unblocks_task_id=str(record.get("unblocks_task_id", "")),
        allowed_scope=tuple(str(value) for value in record.get("allowed_scope", [])),
        worktree=str(record.get("worktree", "")),
        commands=tuple(tuple(str(part) for part in command) for command in record.get("commands", [])),
        evidence=tuple(str(value) for value in record.get("evidence", [])),
        expected_diff_budget=int(record.get("expected_diff_budget", 0)),
    )


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
    ) -> None:
        self.store = store
        self.controller_id = controller_id
        self.agent_id = agent_id
        self.watchdog = watchdog or DeterministicWatchdog()
        self.runner = ControllerRunner(budgets=budgets, agent_call=lambda capsule: backend(capsule))
        records = self.store.read_tasks()["tasks"]
        self.records: list[dict[str, Any]] = [dict(record) for record in records]
        open_ids = {
            str(value)
            for record in self.records
            for value in record.get("acceptance_ids", [])
            if record.get("status") != "ACCEPTED"
        }
        ready = [_task(record) for record in self.records if record.get("status") != "ACCEPTED"]
        self.policy = ProgressPolicy(open_acceptance_ids=open_ids, tasks=ready)
        self.closed = {
            str(value)
            for record in self.records
            if record.get("status") == "ACCEPTED"
            for value in record.get("acceptance_ids", [])
        }

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
        signature = hashlib.sha256(f"{type(exc).__name__}:{exc}".encode()).hexdigest()[:16]
        record["attempts"] = int(record.get("attempts", 0)) + 1
        record["failure_signature"] = signature
        record["status"] = "READY"
        self._persist(event_type="task_attempt_failed")
        self.watchdog.observe(
            {
                "kind": "no_progress",
                "task_id": record["id"],
                "failure_signature": signature,
                "attempt": record["attempts"],
            }
        )
        return f"retry:{signature}"

    def _step(self) -> str:
        try:
            task = self.policy.next_task()
        except Exception:
            return "succeeded" if self.records and all(
                record.get("status") == "ACCEPTED" for record in self.records
            ) else "blocked"
        record = self._record(task.id)
        attempt = int(record.get("attempts", 0)) + 1
        capsule = {
            "action": "execute_task",
            **self.store.context.identity_fields(self.store.run_id),
            "task_id": task.id,
            "mode": self.store.read_run()["mode"],
            "task": dict(record),
            "attempt": attempt,
            "agent_id": self.agent_id,
        }
        try:
            result = dict(self.runner.invoke_agent(capsule))
            identities = self.store.context.identity_fields(self.store.run_id)
            validate_child_result(result, identities=identities, task_id=task.id)
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
            inbox = self.store.write_inbox_result(
                task_id=task.id,
                agent_id=f"{self.agent_id}-{attempt}",
                result=result,
            )
        except Exception as exc:
            return self._failure(record, exc)
        record["attempts"] = attempt
        record["failure_signature"] = ""
        record["status"] = "ACCEPTED"
        record["evidence"] = sorted(
            {str(value) for value in record.get("evidence", [])} | {str(inbox.relative_to(self.store.path))}
        )
        self.closed.update(claimed)
        self._persist(event_type="task_accepted", evidence=list(record["evidence"]))
        return "succeeded" if all(item.get("status") == "ACCEPTED" for item in self.records) else "progress"

    def run(self) -> ExecutionResult:
        outcome = self.runner.run(self._step)
        return ExecutionResult(outcome, tuple(sorted(self.closed)))
