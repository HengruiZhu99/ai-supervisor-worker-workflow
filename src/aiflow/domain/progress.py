from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Mapping


class TaskContractError(ValueError):
    """A task or its claimed evidence violates the progress contract."""


class ProgressBlocked(RuntimeError):
    """The deterministic no-progress breaker reached a terminal block."""


class ValueClass(StrEnum):
    DELIVERY = "delivery"
    VALIDATION = "validation"
    ENABLER = "enabler"
    HOUSEKEEPING = "housekeeping"
    RESEARCH = "research"


@dataclass
class Task:
    id: str
    objective: str
    value_class: ValueClass
    acceptance_ids: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    unblocks_task_id: str = ""
    allowed_scope: tuple[str, ...] = ()
    worktree: str = ""
    pre_commands: tuple[tuple[str, ...], ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()
    evidence: tuple[str, ...] = ()
    expected_diff_budget: int = 0
    status: str = "READY"
    attempts: int = 0
    failure_signature: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.objective:
            raise TaskContractError("task id and objective are required")
        if self.expected_diff_budget < 0:
            raise TaskContractError("expected diff budget cannot be negative")
        self._validate_value_contract()

    def _validate_value_contract(self) -> None:
        if self.value_class in {ValueClass.DELIVERY, ValueClass.VALIDATION}:
            if not self.acceptance_ids:
                raise TaskContractError(
                    "delivery/validation must target acceptance IDs"
                )
        elif self.acceptance_ids:
            raise TaskContractError(f"{self.value_class} cannot claim acceptance IDs")
        if self.value_class is ValueClass.ENABLER and not self.unblocks_task_id:
            raise TaskContractError("enabler must name exactly one task it unblocks")
        if self.value_class is not ValueClass.ENABLER and self.unblocks_task_id:
            raise TaskContractError("only an enabler may set unblocks_task_id")
        if self.value_class is ValueClass.RESEARCH and (
            self.pre_commands or self.commands or self.allowed_scope
        ):
            raise TaskContractError(
                "research is read-only controller evidence, not a mutating task"
            )


@dataclass
class ProgressPolicy:
    open_acceptance_ids: set[str]
    tasks: Iterable[Task]
    housekeeping_budget: int = 1
    state: Mapping[str, Any] | None = None
    _tasks: dict[str, Task] = field(init=False, default_factory=dict)
    _accepted: set[str] = field(init=False, default_factory=set)
    _closed: set[str] = field(init=False, default_factory=set)
    _progress_debt: str = field(init=False, default="")
    _last_delta: tuple[str, ...] = field(init=False, default=())
    _no_delta: int = field(init=False, default=0)
    _replan_pending: bool = field(init=False, default=False)
    _fresh_end_to_end: bool = field(init=False, default=False)
    _housekeeping_used: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.open_acceptance_ids = set(self.open_acceptance_ids)
        self._load_tasks()
        self._validate_graph()
        self._derive_accepted_state()
        self._restore_state()

    def _load_tasks(self) -> None:
        for item in self.tasks:
            if item.id in self._tasks:
                raise TaskContractError(f"duplicate task ID: {item.id}")
            self._tasks[item.id] = item
            if item.status == "ACCEPTED":
                self._accepted.add(item.id)
                self._closed.update(item.acceptance_ids)
                self.open_acceptance_ids.difference_update(item.acceptance_ids)

    def _validate_graph(self) -> None:
        known_acceptance = self.open_acceptance_ids | self._closed
        for item in self._tasks.values():
            missing = set(item.dependencies) - self._tasks.keys()
            if missing:
                raise TaskContractError(
                    f"task {item.id} has unknown dependencies: {sorted(missing)}"
                )
            if item.unblocks_task_id and item.unblocks_task_id not in self._tasks:
                raise TaskContractError(
                    f"enabler {item.id} targets unknown task {item.unblocks_task_id}"
                )
            unknown = set(item.acceptance_ids) - known_acceptance
            if unknown:
                raise TaskContractError(
                    f"task {item.id} targets unknown acceptance IDs: {sorted(unknown)}"
                )

    def _derive_accepted_state(self) -> None:
        unresolved_enablers = [
            item.unblocks_task_id
            for item in self._tasks.values()
            if item.status == "ACCEPTED"
            and item.value_class is ValueClass.ENABLER
            and item.unblocks_task_id not in self._accepted
        ]
        if len(set(unresolved_enablers)) > 1:
            raise TaskContractError("accepted state contains competing progress debt")
        self._progress_debt = unresolved_enablers[0] if unresolved_enablers else ""
        self._housekeeping_used = sum(
            item.status == "ACCEPTED" and item.value_class is ValueClass.HOUSEKEEPING
            for item in self._tasks.values()
        )

    def _restore_state(self) -> None:
        state = self.state or {}
        if not isinstance(state, Mapping):
            raise TaskContractError("durable progress state must be an object")
        self._restore_debt(state)
        self._restore_breaker(state)
        self._restore_usage(state)

    def _restore_debt(self, state: Mapping[str, Any]) -> None:
        progress_debt = str(state.get("progress_debt") or self._progress_debt)
        if progress_debt:
            if progress_debt not in self._tasks or progress_debt in self._accepted:
                raise TaskContractError("durable progress debt target is invalid")
            if self._progress_debt and progress_debt != self._progress_debt:
                raise TaskContractError(
                    "durable progress debt contradicts accepted tasks"
                )
        self._progress_debt = progress_debt

    def _restore_breaker(self, state: Mapping[str, Any]) -> None:
        last_delta = tuple(str(value) for value in state.get("last_delta", ()))
        if not set(last_delta) <= self._closed:
            raise TaskContractError("durable acceptance delta is not closed")
        self._last_delta = last_delta
        self._no_delta = int(state.get("no_delta", 0))
        if self._no_delta < 0:
            raise TaskContractError("durable no-delta count cannot be negative")
        self._replan_pending = bool(state.get("replan_pending", False))
        if self._replan_pending and self._no_delta < 2:
            raise TaskContractError("durable replan lacks a no-delta trigger")
        self._fresh_end_to_end = bool(state.get("fresh_end_to_end", False))

    def _restore_usage(self, state: Mapping[str, Any]) -> None:
        persisted_housekeeping = int(
            state.get("housekeeping_used", self._housekeeping_used)
        )
        if persisted_housekeeping < self._housekeeping_used:
            raise TaskContractError("durable housekeeping usage lost accepted work")
        self._housekeeping_used = persisted_housekeeping

    def _ready(self, item: Task) -> bool:
        return item.status == "READY" and set(item.dependencies) <= self._accepted

    def task(self, task_id: str) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise TaskContractError(f"unknown task: {task_id}") from exc

    def next_task(self) -> Task:
        if self._replan_pending:
            raise ProgressBlocked("NO_ACCEPTANCE_DELTA requires a controller replan")
        if self._progress_debt:
            target = self._tasks[self._progress_debt]
            if self._ready(target):
                return target
            raise ProgressBlocked(f"progress debt target is not ready: {target.id}")
        rank = {
            ValueClass.DELIVERY: 0,
            ValueClass.VALIDATION: 1,
            ValueClass.ENABLER: 2,
            ValueClass.HOUSEKEEPING: 3,
            ValueClass.RESEARCH: 4,
        }
        ready = [item for item in self._tasks.values() if self._ready(item)]
        ready = [
            item
            for item in ready
            if item.value_class is not ValueClass.HOUSEKEEPING
            or self._housekeeping_used < self.housekeeping_budget
        ]
        if not ready:
            raise ProgressBlocked("no ready acceptance-closing task")
        return sorted(ready, key=lambda item: (rank[item.value_class], item.id))[0]

    @staticmethod
    def _assert_delivery_evidence(item: Task, evidence: Mapping[str, Any]) -> None:
        changed = [str(path) for path in evidence.get("changed_files", [])]
        expected = str(evidence.get("expected_artifact", ""))
        commands = evidence.get("commands", [])
        results = evidence.get("test_results", [])
        metadata_only = bool(changed) and all(
            path.startswith((".ai/", ".aiflow/", "docs/")) for path in changed
        )
        if metadata_only or not expected or expected not in changed:
            raise TaskContractError(
                f"{item.id} evidence does not contain its expected artifact"
            )
        if not commands or not results:
            raise TaskContractError(f"{item.id} lacks executable evidence")
        if any(int(result.get("exit_code", 1)) != 0 for result in results):
            raise TaskContractError(f"{item.id} evidence contains a failing command")

    def accept(
        self,
        task_id: str,
        *,
        closed_acceptance_ids: set[str],
        evidence: Mapping[str, Any],
    ) -> str:
        try:
            item = self._tasks[task_id]
        except KeyError as exc:
            raise TaskContractError(f"unknown task: {task_id}") from exc
        claimed = set(closed_acceptance_ids)
        self._validate_acceptance(item, claimed, evidence)
        self._record_acceptance(item, claimed, evidence)
        if self._no_delta >= 2:
            self._replan_pending = True
            return "REPLAN_REQUIRED"
        return "ACCEPTED"

    def validate_claim(
        self,
        task_id: str,
        *,
        closed_acceptance_ids: set[str],
        evidence: Mapping[str, Any],
    ) -> None:
        try:
            item = self._tasks[task_id]
        except KeyError as exc:
            raise TaskContractError(f"unknown task: {task_id}") from exc
        self._validate_acceptance(item, set(closed_acceptance_ids), evidence)

    def _validate_acceptance(
        self, item: Task, claimed: set[str], evidence: Mapping[str, Any]
    ) -> None:
        if item.status != "READY" or not set(item.dependencies) <= self._accepted:
            raise TaskContractError(f"task is not ready: {item.id}")
        valid = (
            claimed <= set(item.acceptance_ids) and claimed <= self.open_acceptance_ids
        )
        if not valid:
            raise TaskContractError(
                "acceptance delta is outside the task/open contract"
            )
        if item.value_class in {ValueClass.DELIVERY, ValueClass.VALIDATION}:
            required = set(item.acceptance_ids) & self.open_acceptance_ids
            if not required or claimed != required:
                raise TaskContractError(
                    f"{item.id} must close its complete open acceptance contract"
                )
            self._assert_delivery_evidence(item, evidence)
        if item.value_class is ValueClass.ENABLER and not evidence.get(
            "completion_proof"
        ):
            raise TaskContractError("enabler acceptance requires completion proof")

    def _record_acceptance(
        self, item: Task, claimed: set[str], evidence: Mapping[str, Any]
    ) -> None:
        item.status = "ACCEPTED"
        self._accepted.add(item.id)
        self._last_delta = tuple(sorted(claimed))
        self._closed.update(claimed)
        self.open_acceptance_ids.difference_update(claimed)
        self._fresh_end_to_end = bool(claimed and evidence.get("fresh_end_to_end"))
        self._no_delta = 0 if claimed else self._no_delta + 1
        if item.value_class is ValueClass.ENABLER:
            if self._progress_debt:
                raise TaskContractError(
                    "cannot accept a second enabler while progress debt exists"
                )
            self._progress_debt = item.unblocks_task_id
        if self._progress_debt == item.id:
            self._progress_debt = ""
        if item.value_class is ValueClass.HOUSEKEEPING:
            self._housekeeping_used += 1

    def complete_replan(self, *, ready_acceptance_task: bool) -> None:
        if not self._replan_pending:
            raise TaskContractError("no replan is pending")
        if not ready_acceptance_task:
            raise ProgressBlocked(
                "NO_ACCEPTANCE_DELTA: no acceptance-closing task became ready"
            )
        self._replan_pending = False
        self._no_delta = 0

    @property
    def needs_replan(self) -> bool:
        return self._replan_pending

    def report(self) -> dict[str, Any]:
        ready = sorted(
            item.id
            for item in self._tasks.values()
            if self._ready(item)
            and item.value_class in {ValueClass.DELIVERY, ValueClass.VALIDATION}
        )
        return {
            "acceptance_open": sorted(self.open_acceptance_ids),
            "acceptance_closed": sorted(self._closed),
            "progress_debt": self._progress_debt or None,
            "last_acceptance_delta": list(self._last_delta),
            "ready_delivery_validation": ready,
            "housekeeping_budget_remaining": max(
                0, self.housekeeping_budget - self._housekeeping_used
            ),
        }

    def durable_state(self) -> dict[str, Any]:
        return {
            "progress_debt": self._progress_debt or None,
            "last_delta": list(self._last_delta),
            "no_delta": self._no_delta,
            "replan_pending": self._replan_pending,
            "fresh_end_to_end": self._fresh_end_to_end,
            "housekeeping_used": self._housekeeping_used,
        }

    def milestone_can_close(self) -> bool:
        return bool(self._closed and self._fresh_end_to_end and not self._progress_debt)
