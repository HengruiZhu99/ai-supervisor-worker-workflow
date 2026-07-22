from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load_integrator():
    spec = importlib.util.spec_from_file_location(
        "legacy_integrator", ROOT / "scripts" / "integrate_job.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IntegrationTransactionRegressionTests(unittest.TestCase):
    def test_candidate_is_applied_to_temporary_worktree_before_target(self) -> None:
        module = load_integrator()
        status = {
            "branch": "candidate",
            "id": "J0001",
            "base_sha": "base",
            "commit": "candidate-sha",
        }
        completed = module.subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(module, "run", return_value=completed) as run:
            module.integrate(ROOT, status, "merge")
        first_command = run.call_args_list[0].args[0]
        self.assertEqual(
            first_command[:3],
            ["git", "worktree", "add"],
            "candidate is merged directly into the target before integrated-state tests",
        )

    def test_integrator_has_target_head_cas_and_preapply_gates(self) -> None:
        text = (ROOT / "scripts" / "integrate_job.py").read_text(encoding="utf-8")
        self.assertIn("target HEAD changed", text)
        self.assertIn("integration worktree", text)
        self.assertIn("focused", text)
        self.assertIn("regression", text)
        self.assertIn("quality", text)


if __name__ == "__main__":
    unittest.main()
