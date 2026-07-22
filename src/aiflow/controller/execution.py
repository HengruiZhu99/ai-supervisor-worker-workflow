from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from aiflow.agents.results import validate_child_result, validate_role_result
from aiflow.controller.attestation import (
    AttestationError,
    attest_preconditions,
    attest_result,
    changed_paths,
    workspace_snapshot,
)
from aiflow.controller.orchestration import OrchestratedTaskRunner
from aiflow.controller.pending import (
    mark_reconciliation_required,
    pending_record_matches,
    terminal_state,
    update_prepared_record,
)
from aiflow.controller.runner import Budgets, ControllerOutcome, ControllerRunner
from aiflow.controller.watchdog import DeterministicWatchdog
from aiflow.domain.evidence import validate_cycle
from aiflow.controller.tasks import record_to_task
from aiflow.domain.progress import ProgressBlocked, ProgressPolicy, Task
from aiflow.integration.transaction import GateCommands, IntegrationTransaction
from aiflow.integration.recovery import (
    git_head,
    pending_integration_matches,
    pending_result,
    retire_writer_worktree,
)
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
        task_payload = self.store.read_tasks()
        records = task_payload["tasks"]
        self.records: list[dict[str, Any]] = [dict(record) for record in records]
        open_ids = {
            str(value)
            for record in self.records
            for value in record.get("acceptance_ids", [])
            if record.get("status") != "ACCEPTED"
        }
        self.policy = ProgressPolicy(
            open_acceptance_ids=open_ids,
            tasks=[
                record_to_task(
                    {
                        **record,
                        "status": "READY"
                        if record.get("status") == "INTEGRATION_PENDING"
                        else record.get("status", "READY"),
                    }
                )
                for record in self.records
            ],
            state=task_payload.get("progress_state", {}),
        )
        self.closed = {
            str(value)
            for record in self.records
            if record.get("status") == "ACCEPTED"
            for value in record.get("acceptance_ids", [])
        }
        self.mode = str(self.store.read_run()["mode"])
        self._prepared_inbox: Path | None = None

    def _record(self, task_id: str) -> dict[str, Any]:
        return next(record for record in self.records if record["id"] == task_id)

    def _persist(self, *, event_type: str, evidence: list[str] | None = None) -> None:
        revision = int(self.store.read_run()["state_revision"])
        self.store.transition(
            revision,
            {},
            event_type=event_type,
            task_updates={
                "tasks": self.records,
                "progress_state": self.policy.durable_state(),
            },
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
        record.pop("integration", None)
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

    def _next_task(self) -> Task | None:
        try:
            return self.policy.next_task()
        except ProgressBlocked:
            if not self.policy.needs_replan:
                return None
            ready = bool(self.policy.report()["ready_delivery_validation"])
            try:
                self.policy.complete_replan(ready_acceptance_task=ready)
            except ProgressBlocked:
                return None
            self._persist(event_type="progress_replanned")
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
                validate_acceptance=lambda candidate: self.policy.validate_claim(
                    task.id,
                    closed_acceptance_ids={
                        str(value)
                        for value in candidate.get("closed_acceptance_ids", [])
                    },
                    evidence=candidate.get("delivery_evidence", {}),
                ),
                stage_integration=lambda result, candidate, base_sha: (
                    self._stage_integration(
                        task,
                        record,
                        int(capsule["attempt"]),
                        result,
                        candidate,
                        base_sha,
                        identities,
                    )
                ),
                record_prepared=lambda details: self._record_prepared_integration(
                    task.id, details
                ),
            ).execute(record, capsule)
        else:
            injected = {
                f"AIFLOW_{key.upper()}": value for key, value in identities.items()
            }
            injected["AIFLOW_TASK_ID"] = task.id
            pre_results = attest_preconditions(
                self.workspace,
                record,
                timeout=float(self.budgets.max_wall_time),
                injected=injected,
            )
            before = workspace_snapshot(self.workspace)
            result = dict(self.runner.invoke_agent(capsule))
            result = attest_result(
                self.workspace,
                before=before,
                result=result,
                task=record,
                timeout=float(self.budgets.max_wall_time),
                injected=injected,
                pre_results=pre_results,
            )
            result = self._cold_review(result, capsule, identities)
        validate_child_result(result, identities=identities, task_id=task.id)
        return result

    def _stage_integration(
        self,
        task: Task,
        record: Mapping[str, Any],
        attempt: int,
        result: Mapping[str, Any],
        candidate: str,
        base_sha: str,
        identities: Mapping[str, str],
    ) -> Mapping[str, str]:
        validate_child_result(result, identities=identities, task_id=task.id)
        target_before = git_head(self.workspace)
        inbox = self.store.write_inbox_result(
            task_id=task.id,
            agent_id=f"{self.agent_id}-{attempt}",
            result=result,
        )
        relative = str(inbox.relative_to(self.store.path))
        mutable = self._record(str(record["id"]))
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
            "writer_worktree_path": str(
                result.get("orchestration", {}).get("writer_worktree_path", "")
            ),
        }
        self._persist(
            event_type="task_integration_prepared", evidence=list(mutable["evidence"])
        )
        self._prepared_inbox = inbox
        return {"target_before": target_before, "inbox": relative}

    def _record_prepared_integration(
        self, task_id: str, details: Mapping[str, str]
    ) -> None:
        record = self._record(task_id)
        update_prepared_record(record, details)
        self._persist(event_type="task_integration_ready")

    def _cold_review(
        self,
        result: dict[str, Any],
        capsule: Mapping[str, Any],
        identities: Mapping[str, str],
    ) -> dict[str, Any]:
        before = workspace_snapshot(self.workspace)
        review_capsule = {
            **dict(capsule),
            "action": "review_task",
            "agent_role": "implementation-worker",
        }
        review = dict(self.runner.invoke_agent(review_capsule))
        validate_role_result(
            review,
            identities=identities,
            task_id=str(capsule["task_id"]),
            role="implementation-worker",
            action="review_task",
        )
        if changed_paths(before, workspace_snapshot(self.workspace)):
            raise AttestationError("Solo cold review mutated the task workspace")
        observed = set(result["controller_attestation"]["observed_changed_files"])
        covered = {str(path) for path in review.get("files_reviewed", [])}
        if (
            review.get("blocks_acceptance")
            or review.get("recommendation") != "accept"
            or review.get("unreviewed_files")
            or not observed <= covered
        ):
            raise AttestationError(
                "Solo cold review did not cover and accept the delta"
            )
        cycle = dict(result["cycle_evidence"])
        cycle["cold_review"] = {
            "status": "pass",
            "reviewer": "implementation-worker-cold-review",
            "attested": True,
        }
        result["cycle_evidence"] = cycle
        result["controller_attestation"]["cold_review"] = review
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
        result: Mapping[str, Any] | None = None,
    ) -> str:
        record["attempts"] = attempt
        record["failure_signature"] = ""
        record["status"] = "ACCEPTED"
        if result and isinstance(result.get("orchestration"), Mapping):
            record["integration"] = dict(result["orchestration"])
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

    def _recover_pending_integration(self) -> str | None:
        record = next(
            (
                item
                for item in self.records
                if item.get("status") == "INTEGRATION_PENDING"
            ),
            None,
        )
        if record is None:
            return None
        try:
            result, inbox, persisted = pending_result(self.store, record)
            integration = dict(persisted)
            record["integration"] = integration
            candidate = str(integration.get("candidate", ""))
            target_before = str(integration.get("target_before", ""))
            if git_head(self.workspace) == target_before:
                commands = tuple(
                    tuple(command) for command in record.get("commands", [])
                )

                def record_prepared(details: Mapping[str, str]) -> None:
                    integration.update(details)
                    result.setdefault("orchestration", {}).update(details)
                    self._record_prepared_integration(str(record["id"]), details)

                applied = IntegrationTransaction(
                    self.workspace,
                    gates=GateCommands(focused=commands),
                    on_prepared=record_prepared,
                ).apply(
                    candidate,
                    method="merge",
                    base_sha=str(integration.get("base_sha", "")),
                    expected_head=target_before,
                )
                if not applied.ok:
                    raise AttestationError(
                        f"pending integration failed: {applied.reason}"
                    )
                result.setdefault("orchestration", {}).update(
                    {
                        "target_before": applied.target_before,
                        "target_after": applied.target_after,
                        "tested_tree": applied.tested_tree,
                        "target_tree": applied.target_tree,
                    }
                )
            elif not pending_integration_matches(self.workspace, integration):
                raise AttestationError(
                    "pending integration target is ambiguous and needs reconciliation"
                )
            else:
                result.setdefault("orchestration", {}).update(integration)
            task = self.policy.task(str(record["id"]))
            identities = self.store.context.identity_fields(self.store.run_id)
            validate_child_result(result, identities=identities, task_id=task.id)
            claimed = self._validate_acceptance(task, record, result)
            retire_writer_worktree(self.store, integration)
        except Exception as exc:
            mark_reconciliation_required(record, exc)
            self._persist(event_type="integration_reconciliation_required")
            return "blocked"
        return self._finalize_acceptance(
            record,
            attempt=int(integration.get("attempt", 1)),
            inbox=inbox,
            claimed=claimed,
            result=result,
        )

    def _step(self) -> str:
        recovered = self._recover_pending_integration()
        if recovered is not None:
            return recovered
        task = self._next_task()
        if task is None:
            return terminal_state(self.records)
        record = self._record(task.id)
        if int(record.get("attempts", 0)) >= self.budgets.max_attempts:
            record["status"] = "BLOCKED"
            return "blocked"
        attempt = int(record.get("attempts", 0)) + 1
        capsule = self._capsule(task, record, attempt)
        try:
            self._prepared_inbox = None
            identities = self.store.context.identity_fields(self.store.run_id)
            result = self._invoke_result(task, record, capsule, identities)
            claimed = self._validate_acceptance(task, record, result)
            inbox = self._prepared_inbox or self.store.write_inbox_result(
                task_id=task.id,
                agent_id=f"{self.agent_id}-{attempt}",
                result=result,
            )
        except Exception as exc:
            if pending_record_matches(self.workspace, record):
                return "progress"
            return self._failure(record, exc)
        return self._finalize_acceptance(
            record,
            attempt=attempt,
            inbox=inbox,
            claimed=claimed,
            result=result,
        )

    def run(self) -> ExecutionResult:
        outcome = self.runner.run(self._step)
        return ExecutionResult(outcome, tuple(sorted(self.closed)))
