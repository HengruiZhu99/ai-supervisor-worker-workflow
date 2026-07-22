from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from aiflow.controller.lifecycle import RunLifecycle
from aiflow.controller.runner import Budgets
from aiflow.integration.transaction import IntegrationResult, IntegrationTransaction
from tests.helpers.execution_backends import OrchestratedBackend
from tests.integration.test_integration_transaction import repository
from tests.regression.test_final_audit_red import (
    context_for,
    git,
    init_project,
    runtime,
)
from tests.regression.test_p12_terminal_hardening_red import artifact_command


class P12IntegrationRefreshRegressionTests(unittest.TestCase):
    def test_target_ref_update_is_an_atomic_compare_and_swap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            base, candidate = repository(root)
            transaction = IntegrationTransaction(root)
            original_apply = transaction._apply_target
            external: list[str] = []

            def race(*args: Any):
                git(root, "commit", "--allow-empty", "-qm", "external move")
                external.append(git(root, "rev-parse", "HEAD").stdout.strip())
                return original_apply(*args)

            with mock.patch.object(transaction, "_apply_target", side_effect=race):
                result = transaction.apply(candidate, method="merge", base_sha=base)
            self.assertFalse(result.ok)
            self.assertEqual(git(root, "rev-parse", "HEAD").stdout.strip(), external[0])

    def test_tracked_edit_racing_target_refresh_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            base, candidate = repository(root)

            def edit_target() -> None:
                (root / "value.txt").write_text("USER WORK\n", encoding="utf-8")

            result = IntegrationTransaction(root, before_apply=edit_target).apply(
                candidate,
                method="merge",
                base_sha=base,
            )
            self.assertFalse(result.ok)
            self.assertEqual(
                (root / "value.txt").read_text(encoding="utf-8"), "USER WORK\n"
            )
            self.assertEqual(git(root, "rev-parse", "HEAD").stdout.strip(), base)
            self.assertFalse((root / "candidate.txt").exists())

    def test_edit_in_final_refresh_window_is_preserved_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            base, candidate = repository(root)
            transaction = IntegrationTransaction(root)
            original_git = transaction._git
            raced = False

            def edit_before_refresh(cwd: Path, *args: str):
                nonlocal raced
                if (
                    cwd.resolve() == root.resolve()
                    and args
                    and args[0] == "read-tree"
                    and "-u" in args
                    and not raced
                ):
                    (root / "value.txt").write_text(
                        "LATE USER WORK\n", encoding="utf-8"
                    )
                    raced = True
                return original_git(cwd, *args)

            with mock.patch.object(
                transaction, "_git", side_effect=edit_before_refresh
            ):
                result = transaction.apply(candidate, method="merge", base_sha=base)
            self.assertFalse(result.ok)
            self.assertEqual(
                (root / "value.txt").read_text(encoding="utf-8"),
                "LATE USER WORK\n",
            )
            self.assertEqual(git(root, "rev-parse", "HEAD").stdout.strip(), base)

    def test_branch_switch_in_final_refresh_window_rolls_back_bound_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            base, candidate = repository(root)
            git(root, "branch", "other", base)
            transaction = IntegrationTransaction(root)
            original_git = transaction._git
            raced = False

            def switch_before_refresh(cwd: Path, *args: str):
                nonlocal raced
                if (
                    cwd.resolve() == root.resolve()
                    and args
                    and args[0] == "read-tree"
                    and "-u" in args
                    and not raced
                ):
                    git(root, "switch", "-q", "other")
                    raced = True
                return original_git(cwd, *args)

            with mock.patch.object(
                transaction, "_git", side_effect=switch_before_refresh
            ):
                result = transaction.apply(candidate, method="merge", base_sha=base)
            self.assertFalse(result.ok)
            self.assertEqual(git(root, "rev-parse", "main").stdout.strip(), base)
            self.assertEqual(git(root, "rev-parse", "other").stdout.strip(), base)
            self.assertFalse((root / "candidate.txt").exists())

    def test_target_symbolic_ref_is_bound_before_candidate_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            base, candidate = repository(root)
            git(root, "branch", "other")

            def switch_branch() -> None:
                git(root, "switch", "-q", "other")

            result = IntegrationTransaction(root, before_apply=switch_branch).apply(
                candidate,
                method="merge",
                base_sha=base,
            )
            self.assertFalse(result.ok)
            self.assertEqual(git(root, "rev-parse", "main").stdout.strip(), base)
            self.assertEqual(git(root, "rev-parse", "other").stdout.strip(), base)

    def test_post_cas_interruption_recovers_from_durable_pending_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            context = context_for(root, tmp)
            command = artifact_command("T0001.txt")
            lifecycle = RunLifecycle(context, runtime_env=runtime(tmp))
            started = lifecycle.start(
                mode="orchestrated",
                objective="recover post-CAS interruption",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "recover post-CAS interruption",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "allowed_scope": ["T0001.txt"],
                        "pre_commands": [command],
                        "commands": [command],
                    },
                ),
            )
            original = IntegrationTransaction.apply
            interrupted = False

            def apply_then_interrupt(
                transaction: IntegrationTransaction, *args: Any, **kwargs: Any
            ) -> IntegrationResult:
                nonlocal interrupted
                result = original(transaction, *args, **kwargs)
                if result.ok and not interrupted:
                    interrupted = True
                    raise RuntimeError("simulated interruption after atomic ref update")
                return result

            with mock.patch.object(
                IntegrationTransaction, "apply", new=apply_then_interrupt
            ):
                result = RunLifecycle(
                    context,
                    runtime_env=runtime(tmp),
                    agent_backend=OrchestratedBackend(root, command),
                ).resume(
                    started["run_id"],
                    budgets=Budgets(max_tasks=2, max_attempts=2, max_idle=1),
                )
            self.assertEqual(result["status"], "SUCCEEDED", result)
            self.assertTrue((root / "T0001.txt").is_file())
            accepted = lifecycle.status(started["run_id"])["tasks"][0]
            writer_path = Path(accepted["integration"]["writer_worktree_path"])
            self.assertFalse(writer_path.exists())

    def test_true_post_cas_pre_refresh_crash_resumes_exact_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            context = context_for(root, tmp)
            command = artifact_command("T0001.txt")
            lifecycle = RunLifecycle(context, runtime_env=runtime(tmp))
            started = lifecycle.start(
                mode="orchestrated",
                objective="recover an exact stale checkout",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "recover an exact stale checkout",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "allowed_scope": ["T0001.txt"],
                        "pre_commands": [command],
                        "commands": [command],
                    },
                ),
            )
            original_git = IntegrationTransaction._git
            crashed = False

            def crash_after_cas(
                transaction: IntegrationTransaction, cwd: Path, *args: str
            ):
                nonlocal crashed
                result = original_git(transaction, cwd, *args)
                if args and args[0] == "update-ref" and not crashed:
                    crashed = True
                    raise SystemExit("hard crash after CAS")
                return result

            with (
                mock.patch.object(IntegrationTransaction, "_git", new=crash_after_cas),
                self.assertRaises(SystemExit),
            ):
                RunLifecycle(
                    context,
                    runtime_env=runtime(tmp),
                    agent_backend=OrchestratedBackend(root, command),
                ).resume(started["run_id"])
            pending = lifecycle.status(started["run_id"])["tasks"][0]
            self.assertEqual(pending["status"], "INTEGRATION_PENDING")
            self.assertFalse((root / "T0001.txt").exists())
            self.assertNotEqual(
                git(root, "rev-parse", "HEAD").stdout.strip(),
                pending["integration"]["target_before"],
            )
            result = RunLifecycle(
                context,
                runtime_env=runtime(tmp),
                agent_backend=OrchestratedBackend(root, command),
            ).resume(
                started["run_id"],
                budgets=Budgets(max_tasks=2, max_attempts=1, max_idle=1),
            )
            self.assertEqual(result["status"], "SUCCEEDED", result)
            self.assertTrue((root / "T0001.txt").is_file())


if __name__ == "__main__":
    unittest.main()
