from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.agents.results import ChildResultError, validate_child_result  # noqa: E402


def valid_result() -> dict[str, object]:
    return {
        "schema_version": 1,
        "project_id": "project",
        "checkout_id": "checkout",
        "worktree_id": "worktree",
        "run_id": "run",
        "task_id": "T0001",
        "agent_role": "implementation-worker",
        "status": "completed",
        "summary": "bounded implementation",
        "findings": [],
        "changed_files": ["src/change.py"],
        "commands_run": [["python3", "-m", "unittest"]],
        "tests_and_results": [{"exit_code": 0}],
        "acceptance_ids_supported": ["AC-1"],
        "evidence_paths": ["evidence/result.json"],
        "contract_impact": "none",
        "residual_risks": [],
        "recommended_next_action": "controller validates result",
    }


class ChildResultTests(unittest.TestCase):
    def test_valid_identity_bound_result_passes(self) -> None:
        result = valid_result()
        validate_child_result(
            result,
            identities={
                "project_id": "project", "checkout_id": "checkout",
                "worktree_id": "worktree", "run_id": "run",
            },
            task_id="T0001",
        )

    def test_recursive_delegation_or_wrong_identity_fails_closed(self) -> None:
        recursive = valid_result()
        recursive["requested_subagents"] = ["another-worker"]
        with self.assertRaises(ChildResultError):
            validate_child_result(recursive, identities={}, task_id="T0001")
        wrong = valid_result()
        wrong["checkout_id"] = "another-checkout"
        with self.assertRaises(ChildResultError):
            validate_child_result(
                wrong,
                identities={"checkout_id": "checkout"},
                task_id="T0001",
            )


if __name__ == "__main__":
    unittest.main()
