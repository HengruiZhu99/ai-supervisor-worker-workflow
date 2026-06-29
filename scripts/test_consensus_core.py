#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Unit tests for the pure consensus logic in ``consensus_core``."""

from __future__ import annotations

import unittest

import consensus_core as cc


def reviewer_report(recommendation: str, agreement: str, *, blocks: bool = False, dissent: str = "") -> str:
    dissent_block = "  dissent_reasons: []" if not dissent else f"  dissent_reasons:\n    - {dissent}"
    return f"""
Some prose from the reviewer.

```yaml
diff_coverage:
  full_diff_reviewed: true
  files_reviewed:
    - src/foo.cpp
  unreviewed_files: []
review_decision:
  recommendation: {recommendation}
  blocks_acceptance: {str(blocks).lower()}
  blocking_reasons: []
progress_review:
  adds_executable_or_validation_value: true
  metadata_unlock_is_credible: true
  continues_metadata_streak: false
  blocks_acceptance: false
  blocking_reasons: []
consensus_vote:
  verdict: {recommendation}
  agreement: {agreement}
  confidence: high
  key_points:
    - looks correct
{dissent_block}
```
"""


class ParseVoteTests(unittest.TestCase):
    def test_parses_reviewer_accept(self) -> None:
        vote = cc.parse_vote(reviewer_report("accept", "agree"), cc.REVIEWER_SCHEMA, "reviewer-1", "m", 1)
        self.assertEqual(vote["verdict"], "accept")
        self.assertEqual(vote["agreement"], "agree")
        self.assertFalse(vote["blocks_acceptance"])
        self.assertEqual(vote["parse_errors"], [])

    def test_revise_blocks(self) -> None:
        vote = cc.parse_vote(reviewer_report("revise", "disagree", dissent="tolerance too loose"), cc.REVIEWER_SCHEMA, "reviewer-2", "m", 1)
        self.assertEqual(vote["verdict"], "revise")
        self.assertTrue(vote["blocks_acceptance"])
        self.assertIn("tolerance too loose", vote["dissent_reasons"])

    def test_reject_maps_to_revise(self) -> None:
        vote = cc.parse_vote(reviewer_report("reject", "disagree", dissent="bug"), cc.REVIEWER_SCHEMA, "reviewer-3", "m", 1)
        self.assertEqual(vote["verdict"], "revise")

    def test_missing_block_blocks_and_errors(self) -> None:
        vote = cc.parse_vote("no machine block here", cc.REVIEWER_SCHEMA, "reviewer-1", "m", 1)
        self.assertTrue(vote["blocks_acceptance"])
        self.assertTrue(vote["parse_errors"])

    def test_disagree_without_reason_gets_placeholder(self) -> None:
        text = """
```yaml
consensus_vote:
  verdict: dispatch_next
  agreement: disagree
  key_points: []
  dissent_reasons: []
```
"""
        vote = cc.parse_vote(text, cc.SUPERVISOR_SCHEMA, "panel-1", "m", 2)
        self.assertEqual(vote["dissent_reasons"], ["disagreement without stated reason"])


class EvaluateRoundTests(unittest.TestCase):
    def _votes(self, specs: list[tuple[str, str]]) -> list[dict]:
        return [
            {"panelist": f"p{i}", "model": "m", "verdict": v, "agreement": a, "dissent_reasons": [], "blocks_acceptance": v != "accept", "blocking_reasons": [], "parse_errors": [], "key_points": []}
            for i, (v, a) in enumerate(specs)
        ]

    def test_round0_unanimous_verdict_converges(self) -> None:
        ev = cc.evaluate_round(self._votes([("accept", "initial")] * 3), 0)
        self.assertTrue(ev["converged"])

    def test_round0_split_does_not_converge(self) -> None:
        ev = cc.evaluate_round(self._votes([("accept", "initial"), ("revise", "initial"), ("accept", "initial")]), 0)
        self.assertFalse(ev["converged"])
        self.assertTrue(ev["majority_ok"])
        self.assertEqual(ev["majority_verdict"], "accept")

    def test_compare_round_requires_agreement_flag(self) -> None:
        # Same verdict but not everyone set agreement=agree -> not converged.
        ev = cc.evaluate_round(self._votes([("accept", "agree"), ("accept", "initial"), ("accept", "agree")]), 1)
        self.assertFalse(ev["converged"])

    def test_compare_round_converges(self) -> None:
        ev = cc.evaluate_round(self._votes([("accept", "agree")] * 3), 1)
        self.assertTrue(ev["converged"])

    def test_unknown_verdict_breaks_unanimity(self) -> None:
        ev = cc.evaluate_round(self._votes([("accept", "agree"), ("unknown", "agree"), ("accept", "agree")]), 1)
        self.assertFalse(ev["verdict_unanimous"])
        self.assertFalse(ev["converged"])


class SynthesizeTests(unittest.TestCase):
    panel = [
        {"panelist": "reviewer-1", "wrapper": "cursor-agent", "model": "a"},
        {"panelist": "reviewer-2", "wrapper": "cursor-agent", "model": "b"},
        {"panelist": "reviewer-3", "wrapper": "cursor-agent", "model": "c"},
    ]

    def _round(self, index: int, specs: list[tuple[str, str]]) -> dict:
        votes = []
        for i, (verdict, agreement) in enumerate(specs):
            votes.append(
                cc.parse_vote(reviewer_report(verdict, agreement), cc.REVIEWER_SCHEMA, f"reviewer-{i+1}", "m", index)
            )
        return {"round": index, "votes": votes}

    def test_unanimous_accept_not_blocked(self) -> None:
        rounds = [self._round(0, [("accept", "initial")] * 3), self._round(1, [("accept", "agree")] * 3)]
        consensus = cc.synthesize(panel=self.panel, rounds=rounds, schema=cc.REVIEWER_SCHEMA, max_rounds=3, quorum=cc.QUORUM_UNANIMOUS)
        self.assertTrue(consensus["converged"])
        self.assertEqual(consensus["verdict"], "accept")
        self.assertFalse(consensus["blocks_acceptance"])

    def test_unanimous_revise_blocks(self) -> None:
        rounds = [self._round(1, [("revise", "agree")] * 3)]
        consensus = cc.synthesize(panel=self.panel, rounds=rounds, schema=cc.REVIEWER_SCHEMA, max_rounds=3, quorum=cc.QUORUM_UNANIMOUS)
        self.assertTrue(consensus["converged"])
        self.assertEqual(consensus["verdict"], "revise")
        self.assertTrue(consensus["blocks_acceptance"])

    def test_no_consensus_escalates(self) -> None:
        rounds = [self._round(1, [("accept", "disagree"), ("revise", "disagree"), ("accept", "agree")])]
        consensus = cc.synthesize(panel=self.panel, rounds=rounds, schema=cc.REVIEWER_SCHEMA, max_rounds=2, quorum=cc.QUORUM_UNANIMOUS)
        self.assertFalse(consensus["converged"])
        self.assertEqual(consensus["method"], "no_consensus")
        self.assertTrue(consensus["blocks_acceptance"])

    def test_majority_quorum_accepts(self) -> None:
        rounds = [self._round(1, [("accept", "agree"), ("accept", "agree"), ("revise", "disagree")])]
        consensus = cc.synthesize(panel=self.panel, rounds=rounds, schema=cc.REVIEWER_SCHEMA, max_rounds=2, quorum=cc.QUORUM_MAJORITY)
        self.assertEqual(consensus["method"], "majority")
        self.assertEqual(consensus["verdict"], "accept")
        # Majority accept does not block, but records the minority dissent.
        self.assertFalse(consensus["blocks_acceptance"])
        self.assertTrue(consensus["dissents"])

    def test_reviewer_decisions_mapping(self) -> None:
        rounds = [self._round(1, [("accept", "agree")] * 3)]
        consensus = cc.synthesize(panel=self.panel, rounds=rounds, schema=cc.REVIEWER_SCHEMA, max_rounds=2, quorum=cc.QUORUM_UNANIMOUS)
        mapped = cc.consensus_to_reviewer_decisions(consensus)
        self.assertTrue(mapped["reviewers_complete"])
        self.assertEqual(mapped["blocked_by"], [])
        self.assertEqual(mapped["reviewer_a_recommendation"], "accept")
        self.assertFalse(mapped["reviewer_b_blocks"])

    def test_reviewer_decisions_no_consensus_blocked_by(self) -> None:
        rounds = [self._round(1, [("accept", "disagree"), ("revise", "disagree"), ("revise", "agree")])]
        consensus = cc.synthesize(panel=self.panel, rounds=rounds, schema=cc.REVIEWER_SCHEMA, max_rounds=1, quorum=cc.QUORUM_UNANIMOUS)
        mapped = cc.consensus_to_reviewer_decisions(consensus)
        self.assertFalse(mapped["reviewers_complete"])
        self.assertIn("consensus:no_consensus", mapped["blocked_by"])


class RoundConvergedTests(unittest.TestCase):
    def _votes(self, specs: list[tuple[str, str]]) -> list[dict]:
        return [
            {"panelist": f"p{i}", "model": "m", "verdict": v, "agreement": a, "dissent_reasons": [], "blocks_acceptance": v != "accept", "blocking_reasons": [], "parse_errors": [], "key_points": []}
            for i, (v, a) in enumerate(specs)
        ]

    def test_unanimous_quorum(self) -> None:
        self.assertTrue(cc.round_converged(self._votes([("accept", "agree")] * 3), 1, cc.QUORUM_UNANIMOUS))
        self.assertFalse(cc.round_converged(self._votes([("accept", "agree"), ("revise", "disagree"), ("accept", "agree")]), 1, cc.QUORUM_UNANIMOUS))

    def test_majority_quorum(self) -> None:
        self.assertTrue(cc.round_converged(self._votes([("accept", "agree"), ("accept", "agree"), ("revise", "disagree")]), 1, cc.QUORUM_MAJORITY))
        self.assertFalse(cc.round_converged(self._votes([("accept", "agree"), ("revise", "disagree"), ("needs_supervisor_judgment", "disagree")]), 1, cc.QUORUM_MAJORITY))


class SpecSchemaTests(unittest.TestCase):
    def _vote_text(self, verdict: str, agreement: str) -> str:
        return f"""
Spec review prose.

```yaml
consensus_vote:
  verdict: {verdict}
  agreement: {agreement}
  confidence: high
  key_points:
    - ok
  dissent_reasons: []
```
"""

    def test_spec_schema_registered(self) -> None:
        self.assertIn(cc.SPEC_SCHEMA, cc.SCHEMAS)

    def test_ready_does_not_block(self) -> None:
        vote = cc.parse_vote(self._vote_text("ready", "agree"), cc.SPEC_SCHEMA, "spec-1", "m", 1)
        self.assertEqual(vote["verdict"], "ready")
        self.assertFalse(vote["blocks_acceptance"])

    def test_needs_revision_blocks(self) -> None:
        vote = cc.parse_vote(self._vote_text("needs_revision", "disagree"), cc.SPEC_SCHEMA, "spec-2", "m", 1)
        self.assertEqual(vote["verdict"], "needs_revision")
        self.assertTrue(vote["blocks_acceptance"])

    def test_unanimous_ready_synthesizes_not_blocked(self) -> None:
        panel = [{"panelist": f"spec-{i}", "wrapper": "cursor-agent", "model": "m"} for i in range(3)]
        votes = [cc.parse_vote(self._vote_text("ready", "agree"), cc.SPEC_SCHEMA, f"spec-{i}", "m", 1) for i in range(3)]
        consensus = cc.synthesize(panel=panel, rounds=[{"round": 1, "votes": votes}], schema=cc.SPEC_SCHEMA, max_rounds=2, quorum=cc.QUORUM_UNANIMOUS)
        self.assertTrue(consensus["converged"])
        self.assertEqual(consensus["verdict"], "ready")
        self.assertFalse(consensus["blocks_acceptance"])


if __name__ == "__main__":
    unittest.main()
