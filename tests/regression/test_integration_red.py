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

        def completed(args, cwd):
            del cwd
            stdout = ""
            returncode = 0
            if args[1:4] == ["symbolic-ref", "-q", "HEAD"]:
                stdout = "refs/heads/codex/test\n"
            elif args[1:] == ["rev-parse", "HEAD"]:
                stdout = "base\n"
            elif args[1:] == [
                "merge-base",
                "--is-ancestor",
                "candidate-sha",
                "base",
            ]:
                returncode = 1
            return module.subprocess.CompletedProcess(
                args, returncode, stdout=stdout, stderr=""
            )

        with mock.patch.object(module, "run", side_effect=completed) as run:
            module.integrate(ROOT, status, "merge")
        calls = run.call_args_list
        self.assertEqual(
            calls[0].args[0][:3],
            ["git", "symbolic-ref", "-q"],
            "the target ref must be bound before candidate gates",
        )
        worktree_index = next(
            index
            for index, call in enumerate(calls)
            if call.args[0][:3] == ["git", "worktree", "add"]
        )
        merge_index, merge_call = next(
            (index, call)
            for index, call in enumerate(calls)
            if call.args[0][1:2] == ["merge"]
        )
        self.assertLess(worktree_index, merge_index)
        self.assertNotEqual(
            Path(merge_call.args[1]).resolve(),
            ROOT.resolve(),
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
