from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.agents.review import Finding, ReviewTracker, reviewers_for_risk  # noqa: E402


class ReviewPolicyTests(unittest.TestCase):
    def test_risk_policy_has_cold_solo_one_normal_and_two_high_risk_reviewers(
        self,
    ) -> None:
        self.assertEqual(reviewers_for_risk("solo"), ("cold-self-review",))
        self.assertEqual(reviewers_for_risk("normal"), ("engineering-reviewer",))
        self.assertEqual(
            reviewers_for_risk("scientific"),
            ("scientific-reviewer", "engineering-reviewer"),
        )

    def test_same_blocking_finding_gets_two_revisions_one_root_cause_then_blocks(
        self,
    ) -> None:
        finding = Finding(
            id="SCI-001",
            severity="high",
            evidence="wrong unit conversion",
            acceptance_impact=("AC-1",),
            resolution="correct conversion and add dimensional test",
        )
        tracker = ReviewTracker()
        self.assertEqual(tracker.record(finding), "REVISE")
        self.assertEqual(tracker.record(finding), "ROOT_CAUSE_REVIEW")
        self.assertEqual(tracker.record(finding), "BLOCKED")

    def test_nonblocking_or_resolved_finding_does_not_bounce(self) -> None:
        finding = Finding(
            id="ENG-001",
            severity="low",
            evidence="name is unclear",
            acceptance_impact=(),
            resolution="optional rename",
        )
        self.assertEqual(ReviewTracker().record(finding), "ADVISORY")


if __name__ == "__main__":
    unittest.main()
