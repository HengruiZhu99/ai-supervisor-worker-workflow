from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteDecision:
    mode: str
    reasons: tuple[str, ...]


def recommend_mode(
    *, task_count: int, milestones: int, independent_writes: int
) -> RouteDecision:
    if min(task_count, milestones, independent_writes) < 0:
        raise ValueError("routing counts cannot be negative")
    reasons = []
    if task_count > 1:
        reasons.append("multiple bounded tasks")
    if milestones > 1:
        reasons.append("multiple milestones")
    if independent_writes > 1:
        reasons.append("independent write lanes")
    if reasons:
        return RouteDecision("orchestrated", tuple(reasons))
    return RouteDecision("solo", ("one bounded task",))
