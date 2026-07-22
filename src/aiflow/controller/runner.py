from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Callable


class ControllerOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    IDLE_EXIT = "IDLE_EXIT"


@dataclass(frozen=True)
class Budgets:
    max_wall_time: int = 14_400
    max_tasks: int = 25
    max_attempts: int = 3
    max_idle: int = 900
    max_agent_calls: int = 50

    def __post_init__(self) -> None:
        if any(value <= 0 for value in self.as_dict().values()):
            raise ValueError("every controller budget must be finite and positive")

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


class ControllerRunner:
    """Finite deterministic controller; callers provide one non-blocking step."""

    def __init__(
        self,
        *,
        budgets: Budgets | None = None,
        agent_call: Callable[[dict[str, Any]], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.budgets = budgets or Budgets()
        self.agent_call = agent_call
        self.clock = clock
        self.agent_calls = 0

    def invoke_agent(self, capsule: dict[str, Any]) -> Any:
        if self.agent_call is None:
            raise RuntimeError("no agent caller is configured")
        if self.agent_calls >= self.budgets.max_agent_calls:
            raise RuntimeError("agent-call budget exhausted")
        self.agent_calls += 1
        return self.agent_call(capsule)

    def run(self, step: Callable[[], str]) -> ControllerOutcome:
        started = self.clock()
        completed_tasks = 0
        idle_ticks = 0
        attempts: dict[str, int] = {}
        while completed_tasks < self.budgets.max_tasks:
            if self.clock() - started >= self.budgets.max_wall_time:
                return ControllerOutcome.BUDGET_EXHAUSTED
            state = step()
            terminal = self._terminal(state)
            if terminal is not None:
                return terminal
            if state == "idle":
                idle_ticks += 1
                if idle_ticks >= self.budgets.max_idle:
                    return ControllerOutcome.IDLE_EXIT
                continue
            idle_ticks = 0
            if state == "progress":
                completed_tasks += 1
                continue
            if state.startswith("retry:"):
                signature = state.partition(":")[2]
                attempts[signature] = attempts.get(signature, 0) + 1
                if attempts[signature] >= self.budgets.max_attempts:
                    return ControllerOutcome.BLOCKED
                continue
            return ControllerOutcome.FAILED
        return ControllerOutcome.BUDGET_EXHAUSTED

    @staticmethod
    def _terminal(state: str) -> ControllerOutcome | None:
        return {
            "succeeded": ControllerOutcome.SUCCEEDED,
            "paused": ControllerOutcome.PAUSED,
            "blocked": ControllerOutcome.BLOCKED,
            "failed": ControllerOutcome.FAILED,
        }.get(state)
