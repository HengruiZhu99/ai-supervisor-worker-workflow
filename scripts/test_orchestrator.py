#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""End-to-end tests for the orchestrator round loop using a fake runner.

These tests never launch a real agent: a scripted runner returns canned
panelist responses so the round loop, early-stop, escalation, exit codes, and
artifact writing can be verified deterministically.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import orchestrator as orch
import consensus_core as cc


def reviewer_text(verdict: str, agreement: str, *, dissent: str = "") -> str:
    dissent_block = "  dissent_reasons: []" if not dissent else f"  dissent_reasons:\n    - {dissent}"
    return f"""
Review prose here.

```yaml
diff_coverage:
  full_diff_reviewed: true
  files_reviewed:
    - src/foo.cpp
  unreviewed_files: []
review_decision:
  recommendation: {verdict}
  blocks_acceptance: {str(verdict != 'accept').lower()}
  blocking_reasons: []
progress_review:
  adds_executable_or_validation_value: true
  metadata_unlock_is_credible: true
  continues_metadata_streak: false
  blocks_acceptance: false
  blocking_reasons: []
consensus_vote:
  verdict: {verdict}
  agreement: {agreement}
  confidence: high
  key_points:
    - rationale
{dissent_block}
```
"""


def make_panel():
    return [
        orch.Panelist(id="reviewer-1", model="m1"),
        orch.Panelist(id="reviewer-2", model="m2"),
        orch.Panelist(id="reviewer-3", model="m3"),
    ]


def scripted_runner(script):
    """script: dict[round_index] -> dict[panelist_id] -> (verdict, agreement[, dissent])."""
    captured_prompts: list[tuple[str, int, str]] = []

    def run(panelist, prompt_text, round_index):
        captured_prompts.append((panelist.id, round_index, prompt_text))
        spec = script[round_index][panelist.id]
        dissent = spec[2] if len(spec) > 2 else ""
        text = reviewer_text(spec[0], spec[1], dissent=dissent)
        return orch.RunResult(text=text, exit_code=0)

    run.captured_prompts = captured_prompts
    return run


class OrchestratorLoopTests(unittest.TestCase):
    def _config(self, output_dir, max_rounds=3, quorum=cc.QUORUM_UNANIMOUS, reviewer_out=None):
        return orch.OrchestratorConfig(
            role="reviewer",
            decision_schema=cc.REVIEWER_SCHEMA,
            panel=make_panel(),
            base_prompt="Review the diff.",
            workspace=str(output_dir),
            output_dir=Path(output_dir),
            max_rounds=max_rounds,
            quorum=quorum,
            output_format="plain",
            artifacts={"reviewer_decisions_out": reviewer_out},
        )

    def test_converges_and_stops_early(self) -> None:
        script = {
            0: {"reviewer-1": ("accept", "initial"), "reviewer-2": ("revise", "initial"), "reviewer-3": ("accept", "initial")},
            1: {"reviewer-1": ("accept", "agree"), "reviewer-2": ("accept", "agree"), "reviewer-3": ("accept", "agree")},
            2: {"reviewer-1": ("accept", "agree"), "reviewer-2": ("accept", "agree"), "reviewer-3": ("accept", "agree")},
        }
        runner = scripted_runner(script)
        with tempfile.TemporaryDirectory() as tmp:
            reviewer_out = Path(tmp) / "reviewer_decisions.json"
            consensus = orch.run_consensus(self._config(tmp, reviewer_out=str(reviewer_out)), runner=runner)
            self.assertTrue(consensus["converged"])
            self.assertEqual(consensus["verdict"], "accept")
            self.assertEqual(consensus["rounds_run"], 2)  # stopped after round 1 (index 1)
            self.assertFalse(consensus["blocks_acceptance"])
            self.assertEqual(orch.consensus_exit_code(consensus), 0)
            # Artifacts exist.
            self.assertTrue((Path(tmp) / "consensus.json").exists())
            self.assertTrue((Path(tmp) / "consensus.md").exists())
            for pid in ("reviewer-1", "reviewer-2", "reviewer-3"):
                self.assertTrue((Path(tmp) / f"{pid}.final.md").exists())
            self.assertTrue(reviewer_out.exists())
            mapped = json.loads(reviewer_out.read_text())
            self.assertTrue(mapped["reviewers_complete"])
            self.assertEqual(mapped["blocked_by"], [])

    def test_round0_unanimous_stops_immediately_when_single_round(self) -> None:
        script = {0: {"reviewer-1": ("accept", "initial"), "reviewer-2": ("accept", "initial"), "reviewer-3": ("accept", "initial")}}
        runner = scripted_runner(script)
        with tempfile.TemporaryDirectory() as tmp:
            consensus = orch.run_consensus(self._config(tmp, max_rounds=1), runner=runner)
            self.assertTrue(consensus["converged"])
            self.assertEqual(consensus["rounds_run"], 1)

    def test_no_consensus_runs_all_rounds_and_blocks(self) -> None:
        disagree = {
            "reviewer-1": ("accept", "disagree", "I think it is fine"),
            "reviewer-2": ("revise", "disagree", "tolerance unjustified"),
            "reviewer-3": ("accept", "agree"),
        }
        script = {0: dict(disagree), 1: dict(disagree)}
        runner = scripted_runner(script)
        with tempfile.TemporaryDirectory() as tmp:
            consensus = orch.run_consensus(self._config(tmp, max_rounds=2), runner=runner)
            self.assertFalse(consensus["converged"])
            self.assertEqual(consensus["method"], "no_consensus")
            self.assertTrue(consensus["blocks_acceptance"])
            self.assertEqual(consensus["rounds_run"], 2)
            self.assertEqual(orch.consensus_exit_code(consensus), 1)

    def test_compare_round_prompt_contains_peer_positions(self) -> None:
        script = {
            0: {"reviewer-1": ("accept", "initial"), "reviewer-2": ("revise", "initial", "bug"), "reviewer-3": ("accept", "initial")},
            1: {"reviewer-1": ("accept", "agree"), "reviewer-2": ("accept", "agree"), "reviewer-3": ("accept", "agree")},
        }
        runner = scripted_runner(script)
        with tempfile.TemporaryDirectory() as tmp:
            orch.run_consensus(self._config(tmp), runner=runner)
        # Round-1 prompt for reviewer-1 must reference its peers.
        round1_prompts = [p for (pid, r, p) in runner.captured_prompts if pid == "reviewer-1" and r == 1]
        self.assertTrue(round1_prompts)
        prompt = round1_prompts[0]
        self.assertIn("Peer `reviewer-2`", prompt)
        self.assertIn("compare notes", prompt.lower())
        self.assertIn("bug", prompt)  # peer dissent surfaced

    def test_timeout_propagates(self) -> None:
        def runner(panelist, prompt_text, round_index):
            return orch.RunResult(text="(no block)", exit_code=124)

        with tempfile.TemporaryDirectory() as tmp:
            consensus = orch.run_consensus(self._config(tmp, max_rounds=1), runner=runner)
            self.assertTrue(consensus["timed_out"])
            self.assertEqual(orch.consensus_exit_code(consensus), 124)

    def test_timeout_aborts_early(self) -> None:
        calls = {"n": 0}

        def runner(panelist, prompt_text, round_index):
            calls["n"] += 1
            return orch.RunResult(text="(no block)", exit_code=124)

        with tempfile.TemporaryDirectory() as tmp:
            consensus = orch.run_consensus(self._config(tmp, max_rounds=3), runner=runner)
            self.assertTrue(consensus["timed_out"])
            self.assertEqual(consensus["rounds_run"], 1)  # did not start rounds 2 and 3
            self.assertEqual(calls["n"], 3)  # only the 3 panelists of round 0

    def test_agent_crash_blocks(self) -> None:
        def runner(panelist, prompt_text, round_index):
            return orch.RunResult(text="garbled output, no yaml", exit_code=3)

        with tempfile.TemporaryDirectory() as tmp:
            consensus = orch.run_consensus(self._config(tmp, max_rounds=1), runner=runner)
            self.assertTrue(consensus["blocks_acceptance"])
            self.assertTrue(consensus["errors"])
            self.assertEqual(orch.consensus_exit_code(consensus), 1)


class PanelBuildTests(unittest.TestCase):
    def test_model_overrides_apply_in_order(self) -> None:
        spec = {
            "panelists": [
                {"id": "a", "model": "x"},
                {"id": "b", "model": "y"},
                {"id": "c", "model": "z"},
            ]
        }

        class Args:
            models = "m1,m2,m3"
            wrappers = ""

        panel = orch.build_panel(spec, Args())
        self.assertEqual([p.model for p in panel], ["m1", "m2", "m3"])

    def test_more_models_grow_panel(self) -> None:
        spec = {"panelists": [{"id": "a"}]}

        class Args:
            models = "m1,m2,m3"
            wrappers = ""

        panel = orch.build_panel(spec, Args())
        self.assertEqual(len(panel), 3)


if __name__ == "__main__":
    unittest.main()
