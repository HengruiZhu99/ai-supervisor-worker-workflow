from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    evidence: str
    acceptance_impact: tuple[str, ...]
    resolution: str

    def __post_init__(self) -> None:
        if not self.id or self.severity not in {"critical", "high", "medium", "low"}:
            raise ValueError("finding requires a stable ID and valid severity")
        if not self.evidence or not self.resolution:
            raise ValueError("finding requires evidence and a resolution")

    @property
    def blocks_acceptance(self) -> bool:
        return self.severity in {"critical", "high"} and bool(self.acceptance_impact)


def reviewers_for_risk(risk: str) -> tuple[str, ...]:
    policies = {
        "solo": ("cold-self-review",),
        "normal": ("engineering-reviewer",),
        "scientific": ("scientific-reviewer", "engineering-reviewer"),
        "concurrency": ("scientific-reviewer", "engineering-reviewer"),
    }
    try:
        return policies[risk]
    except KeyError as exc:
        raise ValueError(f"unknown review risk: {risk}") from exc


class ReviewTracker:
    """Bound revisions for one normalized blocking finding."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def record(self, finding: Finding) -> str:
        if not finding.blocks_acceptance:
            return "ADVISORY"
        count = self._counts.get(finding.id, 0) + 1
        self._counts[finding.id] = count
        if count == 1:
            return "REVISE"
        if count == 2:
            return "ROOT_CAUSE_REVIEW"
        return "BLOCKED"
