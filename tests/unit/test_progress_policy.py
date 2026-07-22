from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.domain.progress import (  # noqa: E402
    ProgressBlocked,
    ProgressPolicy,
    Task,
    TaskContractError,
    ValueClass,
)


def task(
    task_id: str,
    value: ValueClass,
    *,
    acceptance_ids: tuple[str, ...] = (),
    dependencies: tuple[str, ...] = (),
    unblocks: str = "",
) -> Task:
    return Task(
        id=task_id,
        objective=f"objective {task_id}",
        value_class=value,
        acceptance_ids=acceptance_ids,
        dependencies=dependencies,
        unblocks_task_id=unblocks,
        allowed_scope=("src/",),
        worktree="main",
        commands=(("python3", "-m", "unittest"),),
        evidence=("evidence/result.txt",),
        expected_diff_budget=100,
    )


class ProgressPolicyTests(unittest.TestCase):
    def test_research_is_read_only_and_enabler_names_one_target(self) -> None:
        with self.assertRaises(TaskContractError):
            task("T1", ValueClass.RESEARCH, acceptance_ids=("AC-1",))
        with self.assertRaises(TaskContractError):
            task("T2", ValueClass.ENABLER)
        target = task("T3", ValueClass.DELIVERY, acceptance_ids=("AC-1",))
        enabler = task("T2", ValueClass.ENABLER, unblocks="T3")
        ProgressPolicy(open_acceptance_ids={"AC-1"}, tasks=[enabler, target])

    def test_delivery_priority_beats_housekeeping_and_enabler(self) -> None:
        delivery = task("D1", ValueClass.DELIVERY, acceptance_ids=("AC-1",))
        validation = task("V1", ValueClass.VALIDATION, acceptance_ids=("AC-2",))
        enabler = task("E1", ValueClass.ENABLER, unblocks="D1")
        housekeeping = task("H1", ValueClass.HOUSEKEEPING)
        policy = ProgressPolicy(
            open_acceptance_ids={"AC-1", "AC-2"},
            tasks=[housekeeping, enabler, validation, delivery],
        )
        self.assertEqual(policy.next_task().id, "D1")

    def test_enabler_debt_cannot_be_reset_by_lateral_work(self) -> None:
        blocked = task(
            "D1", ValueClass.DELIVERY, acceptance_ids=("AC-1",), dependencies=("E1",)
        )
        enabler = task("E1", ValueClass.ENABLER, unblocks="D1")
        lateral = task("D2", ValueClass.DELIVERY, acceptance_ids=("AC-2",))
        policy = ProgressPolicy(
            open_acceptance_ids={"AC-1", "AC-2"}, tasks=[enabler, blocked, lateral]
        )
        self.assertEqual(policy.next_task().id, "D2")
        policy.accept("E1", closed_acceptance_ids=set(), evidence={"completion_proof": True})
        self.assertEqual(policy.report()["progress_debt"], "D1")
        self.assertEqual(policy.next_task().id, "D1")

    def test_post_execution_gate_rejects_fake_delivery_metadata(self) -> None:
        delivery = task("D1", ValueClass.DELIVERY, acceptance_ids=("AC-1",))
        policy = ProgressPolicy(open_acceptance_ids={"AC-1"}, tasks=[delivery])
        with self.assertRaises(TaskContractError):
            policy.accept(
                "D1",
                closed_acceptance_ids={"AC-1"},
                evidence={
                    "changed_files": [".ai/jobs/J0001/report.md"],
                    "commands": [],
                    "test_results": [],
                    "expected_artifact": "src/feature.py",
                },
            )

    def test_two_no_delta_checkpoints_replan_once_then_block(self) -> None:
        first = task("H1", ValueClass.HOUSEKEEPING)
        second = task("H2", ValueClass.HOUSEKEEPING)
        policy = ProgressPolicy(open_acceptance_ids={"AC-1"}, tasks=[first, second])
        policy.accept("H1", closed_acceptance_ids=set(), evidence={"changed_files": ["README.md"]})
        outcome = policy.accept(
            "H2", closed_acceptance_ids=set(), evidence={"changed_files": ["docs/note.md"]}
        )
        self.assertEqual(outcome, "REPLAN_REQUIRED")
        with self.assertRaises(ProgressBlocked):
            policy.complete_replan(ready_acceptance_task=False)

    def test_report_is_deterministic_and_milestone_requires_fresh_evidence(self) -> None:
        delivery = task("D1", ValueClass.DELIVERY, acceptance_ids=("AC-1",))
        policy = ProgressPolicy(open_acceptance_ids={"AC-1"}, tasks=[delivery])
        report = policy.report()
        self.assertEqual(
            tuple(report),
            (
                "acceptance_open",
                "acceptance_closed",
                "progress_debt",
                "last_acceptance_delta",
                "ready_delivery_validation",
                "housekeeping_budget_remaining",
            ),
        )
        policy.accept(
            "D1",
            closed_acceptance_ids={"AC-1"},
            evidence={
                "changed_files": ["src/feature.py"],
                "commands": [["python3", "-m", "unittest"]],
                "test_results": [{"exit_code": 0, "tests": 1}],
                "expected_artifact": "src/feature.py",
                "fresh_end_to_end": True,
            },
        )
        self.assertTrue(policy.milestone_can_close())


if __name__ == "__main__":
    unittest.main()
