from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aiflow.controller.execution import TaskExecutionEngine
from aiflow.controller.lifecycle import RunLifecycle
from aiflow.controller.runner import Budgets
from aiflow.integration.transaction import IntegrationTransaction
from aiflow.state.atomic import read_json
from tests.helpers.execution_backends import OrchestratedBackend
from tests.regression.test_final_audit_red import (
    context_for,
    git,
    init_project,
    runtime,
)
from tests.regression.test_p12_terminal_hardening_red import artifact_command


class P12RecoveryIdentityRegressionTests(unittest.TestCase):
    def test_writer_worktree_remains_until_acceptance_is_durable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            context = context_for(root, tmp)
            command = artifact_command("T0001.txt")
            lifecycle = RunLifecycle(context, runtime_env=runtime(tmp))
            started = lifecycle.start(
                mode="orchestrated",
                objective="retain recovery material",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "retain recovery material",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "allowed_scope": ["T0001.txt"],
                        "pre_commands": [command],
                        "commands": [command],
                    },
                ),
            )
            with (
                mock.patch.object(
                    TaskExecutionEngine,
                    "_finalize_acceptance",
                    side_effect=SystemExit("crash before durable acceptance"),
                ),
                self.assertRaises(SystemExit),
            ):
                RunLifecycle(
                    context,
                    runtime_env=runtime(tmp),
                    agent_backend=OrchestratedBackend(root, command),
                ).resume(started["run_id"])
            pending = lifecycle.status(started["run_id"])["tasks"][0]
            self.assertEqual(pending["status"], "INTEGRATION_PENDING")
            writer = Path(pending["integration"]["writer_worktree_path"])
            self.assertTrue(writer.is_dir())

            result = RunLifecycle(
                context,
                runtime_env=runtime(tmp),
                agent_backend=OrchestratedBackend(root, command),
            ).resume(
                started["run_id"],
                budgets=Budgets(max_tasks=2, max_attempts=1, max_idle=1),
            )
            self.assertEqual(result["status"], "SUCCEEDED", result)
            self.assertFalse(writer.exists())

    def test_orphaned_signed_inbox_is_adopted_before_writer_redispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            context = context_for(root, tmp)
            command = artifact_command("T0001.txt")
            lifecycle = RunLifecycle(context, runtime_env=runtime(tmp))
            started = lifecycle.start(
                mode="orchestrated",
                objective="recover the durable candidate",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "recover the durable candidate",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "allowed_scope": ["T0001.txt"],
                        "pre_commands": [command],
                        "commands": [command],
                    },
                ),
            )
            persist = TaskExecutionEngine._persist

            def interrupt_after_inbox(
                engine: TaskExecutionEngine,
                *,
                event_type: str,
                evidence: list[str] | None = None,
            ) -> None:
                if event_type == "task_integration_prepared":
                    raise KeyboardInterrupt("crash after durable inbox write")
                persist(engine, event_type=event_type, evidence=evidence)

            with (
                mock.patch.object(
                    TaskExecutionEngine, "_persist", interrupt_after_inbox
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                RunLifecycle(
                    context,
                    runtime_env=runtime(tmp),
                    agent_backend=OrchestratedBackend(root, command),
                ).resume(started["run_id"])

            status = lifecycle.status(started["run_id"])
            self.assertEqual(status["tasks"][0]["status"], "READY")
            inbox = list(
                lifecycle.store(started["run_id"]).path.glob(
                    "inbox/T0001/*/result.json"
                )
            )
            self.assertEqual(len(inbox), 1)
            writer_worktree = Path(
                str(read_json(inbox[0])["orchestration"]["writer_worktree_path"])
            )
            self.assertTrue(writer_worktree.is_dir())
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
            self.assertFalse(writer_worktree.exists())

    def test_candidate_ancestry_without_exact_tested_tree_never_accepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            context = context_for(root, tmp)
            command = artifact_command("T0001.txt")
            lifecycle = RunLifecycle(context, runtime_env=runtime(tmp))
            started = lifecycle.start(
                mode="orchestrated",
                objective="reject reverted candidate ancestry",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "reject reverted candidate ancestry",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "allowed_scope": ["T0001.txt"],
                        "pre_commands": [command],
                        "commands": [command],
                    },
                ),
            )
            with (
                mock.patch.object(
                    IntegrationTransaction,
                    "apply",
                    side_effect=KeyboardInterrupt("stop after durable prepare"),
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                RunLifecycle(
                    context,
                    runtime_env=runtime(tmp),
                    agent_backend=OrchestratedBackend(root, command),
                ).resume(started["run_id"])

            pending = lifecycle.status(started["run_id"])["tasks"][0]
            candidate = str(pending["integration"]["candidate"])
            git(root, "merge", "--no-ff", "-qm", "external candidate", candidate)
            git(root, "revert", "-m", "1", "--no-edit", "HEAD")
            self.assertFalse((root / "T0001.txt").exists())

            result = RunLifecycle(
                context,
                runtime_env=runtime(tmp),
                agent_backend=OrchestratedBackend(root, command),
            ).resume(
                started["run_id"],
                budgets=Budgets(max_tasks=2, max_attempts=2, max_idle=1),
            )
            self.assertNotEqual(result["status"], "SUCCEEDED", result)
            self.assertFalse((root / "T0001.txt").exists())

    def test_unsafe_task_id_is_rejected_before_run_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            lifecycle = RunLifecycle(context_for(root, tmp), runtime_env=runtime(tmp))
            with self.assertRaises(ValueError):
                lifecycle.start(
                    mode="solo",
                    objective="reject unsafe task identity",
                    task_specs=(
                        {
                            "id": "../escape",
                            "objective": "reject unsafe task identity",
                            "acceptance_ids": ["AC-1"],
                        },
                    ),
                )
            self.assertEqual(lifecycle.list(), [])


if __name__ == "__main__":
    unittest.main()
