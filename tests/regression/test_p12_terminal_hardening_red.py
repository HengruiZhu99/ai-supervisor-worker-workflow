from __future__ import annotations

import json
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.controller.attestation import (  # noqa: E402
    AttestationError,
    attest_preconditions,
)
from aiflow.api.service import ApiService  # noqa: E402
from aiflow.controller.lifecycle import RunLifecycle  # noqa: E402
from aiflow.controller.runner import Budgets  # noqa: E402
from aiflow.integration.transaction import (  # noqa: E402
    IntegrationResult,
    IntegrationTransaction,
)
from aiflow.security.process import run_owned_process  # noqa: E402
from tests.helpers.execution_backends import (  # noqa: E402
    OrchestratedBackend,
    completed_result,
)
from tests.integration.test_integration_transaction import (  # noqa: E402
    repository,
)
from tests.regression.test_final_audit_red import (  # noqa: E402
    context_for,
    git,
    init_project,
    runtime,
    solo_review,
)


def artifact_command(path: str) -> list[str]:
    return [
        sys.executable,
        "-c",
        f"from pathlib import Path; assert Path({path!r}).is_file()",
    ]


class P12TerminalHardeningRegressionTests(unittest.TestCase):
    def test_precondition_must_leave_nonignored_workspace_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            command = [
                sys.executable,
                "-c",
                "from pathlib import Path; Path('outside.txt').write_text('escape'); raise SystemExit(1)",
            ]
            with self.assertRaises(AttestationError):
                attest_preconditions(
                    root,
                    {"kind": "feature", "pre_commands": [command]},
                    timeout=5,
                    injected={},
                )

    def test_precondition_cannot_change_tracked_executable_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            script = root / "outside.sh"
            script.write_text("#!/bin/sh\n", encoding="utf-8")
            git(root, "add", "outside.sh")
            git(root, "commit", "-qm", "tracked script")
            command = [
                sys.executable,
                "-c",
                "from pathlib import Path; Path('outside.sh').chmod(0o755); raise SystemExit(1)",
            ]
            with self.assertRaises(AttestationError):
                attest_preconditions(
                    root,
                    {"kind": "feature", "pre_commands": [command]},
                    timeout=5,
                    injected={},
                )

    def test_precondition_cannot_advance_a_tracked_gitlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            dependency = root / "vendor" / "dependency"
            dependency.mkdir(parents=True)
            git(dependency, "init", "-q")
            git(dependency, "config", "user.name", "Dependency Test")
            git(dependency, "config", "user.email", "dependency@example.invalid")
            (dependency / "value.txt").write_text("one\n", encoding="utf-8")
            git(dependency, "add", "value.txt")
            git(dependency, "commit", "-qm", "one")
            first = git(dependency, "rev-parse", "HEAD").stdout.strip()
            (dependency / "value.txt").write_text("two\n", encoding="utf-8")
            git(dependency, "commit", "-am", "two", "-q")
            second = git(dependency, "rev-parse", "HEAD").stdout.strip()
            git(dependency, "checkout", "-q", "--detach", first)
            git(
                root,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{first},vendor/dependency",
            )
            git(root, "commit", "-qm", "tracked dependency")
            checkout = [
                "git",
                "-C",
                "vendor/dependency",
                "checkout",
                "-q",
                "--detach",
                second,
            ]
            failing = [
                sys.executable,
                "-c",
                (
                    "import subprocess; "
                    f"subprocess.run({checkout!r}, check=True); "
                    "raise SystemExit(1)"
                ),
            ]
            with self.assertRaises(AttestationError):
                attest_preconditions(
                    root,
                    {"kind": "feature", "pre_commands": [failing]},
                    timeout=5,
                    injected={},
                )

    def test_timeout_always_kills_the_owned_group_after_grace(self) -> None:
        process = mock.Mock()
        process.pid = 4321
        process.returncode = -signal.SIGTERM
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["fixture"], 0.1),
            ("", ""),
        ]
        process.wait.return_value = process.returncode
        with (
            mock.patch(
                "aiflow.security.process.subprocess.Popen", return_value=process
            ),
            mock.patch("aiflow.security.process.os.killpg") as kill_group,
        ):
            completed = run_owned_process(["fixture"], cwd=Path.cwd(), timeout=0.1)
        self.assertEqual(completed.returncode, 124)
        self.assertIn(mock.call(process.pid, signal.SIGKILL), kill_group.call_args_list)

    def test_unrelated_failure_is_not_discriminating_red(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            context = context_for(root, tmp)
            post = [sys.executable, "-c", "pass"]
            started = RunLifecycle(context, runtime_env=runtime(tmp)).start(
                mode="solo",
                objective="reject unrelated red",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "reject unrelated red",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "allowed_scope": ["feature.txt"],
                        "pre_commands": [[sys.executable, "-c", "raise SystemExit(1)"]],
                        "commands": [post],
                    },
                ),
            )

            def backend(capsule: Mapping[str, Any]) -> Mapping[str, Any]:
                if capsule["action"] == "review_task":
                    return solo_review(capsule)
                (root / "feature.txt").write_text("done\n", encoding="utf-8")
                return completed_result(
                    capsule, ["AC-1"], artifact="feature.txt", command=post
                )

            result = RunLifecycle(
                context, runtime_env=runtime(tmp), agent_backend=backend
            ).resume(started["run_id"], budgets=Budgets(max_attempts=1, max_idle=1))
            self.assertNotEqual(result["status"], "SUCCEEDED")

    def test_acceptance_is_durable_before_orchestrated_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            context = context_for(root, tmp)
            command = artifact_command("T0001.txt")
            lifecycle = RunLifecycle(context, runtime_env=runtime(tmp))
            started = lifecycle.start(
                mode="orchestrated",
                objective="durable pre-apply acceptance",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "durable pre-apply acceptance",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "allowed_scope": ["T0001.txt"],
                        "pre_commands": [command],
                        "commands": [command],
                    },
                ),
            )
            observed: list[bool] = []

            def inspect_before_apply(
                *_args: object, **_kwargs: object
            ) -> IntegrationResult:
                task = lifecycle.status(started["run_id"])["tasks"][0]
                observed.append(
                    task["status"] == "INTEGRATION_PENDING" and bool(task["evidence"])
                )
                return IntegrationResult(False, "fixture stop", "", "")

            with mock.patch(
                "aiflow.controller.orchestration.IntegrationTransaction.apply",
                side_effect=inspect_before_apply,
            ):
                RunLifecycle(
                    context,
                    runtime_env=runtime(tmp),
                    agent_backend=OrchestratedBackend(root, command),
                ).resume(
                    started["run_id"],
                    budgets=Budgets(max_attempts=1, max_idle=1),
                )
            self.assertEqual(observed, [True])

    def test_target_ref_update_is_an_atomic_compare_and_swap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            base, candidate = repository(root)
            transaction = IntegrationTransaction(root)
            original_apply = transaction._apply_target
            external: list[str] = []

            def race(*args: Any) -> bool:
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

    def test_default_task_imports_project_precondition_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            config = root / ".aiflow" / "project.toml"
            command = artifact_command("feature.txt")
            encoded = json.dumps(command)
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "test_regression = []",
                    f"test_regression = []\ntest_red = {encoded}",
                ),
                encoding="utf-8",
            )
            lifecycle = RunLifecycle(context_for(root, tmp), runtime_env=runtime(tmp))
            started = lifecycle.start(
                mode="solo", objective="configured task", acceptance_ids=("AC-1",)
            )
            task = lifecycle.status(started["run_id"])["tasks"][0]
            self.assertEqual(task["pre_commands"], [command])

    def test_gui_api_creates_an_executable_bounded_default_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            command = artifact_command("feature.txt")
            config = root / ".aiflow" / "project.toml"
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "test_focused = []",
                    f"test_red = {json.dumps(command)}\ntest_focused = {json.dumps(command)}",
                ),
                encoding="utf-8",
            )
            context = context_for(root, tmp)
            service = ApiService(context, agent_backend=lambda _capsule: {})
            created = service.start(
                {
                    "mode": "solo",
                    "objective": "bounded GUI task",
                    "acceptance_ids": ["AC-1"],
                    "allowed_scope": ["feature.txt"],
                    "checkout_id": context.checkout_id,
                }
            )
            task = service.lifecycle.status(created["run_id"])["tasks"][0]
            self.assertEqual(task["allowed_scope"], ["feature.txt"])
            self.assertEqual(task["pre_commands"], [command])
            self.assertEqual(task["commands"], [command])

    def test_gui_api_rejects_an_incomplete_default_contract_at_intake(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            context = context_for(root, tmp)
            service = ApiService(context, agent_backend=lambda _capsule: {})
            with self.assertRaisesRegex(ValueError, "test_red"):
                service.start(
                    {
                        "mode": "solo",
                        "objective": "incomplete GUI task",
                        "allowed_scope": ["feature.txt"],
                        "checkout_id": context.checkout_id,
                    }
                )
            self.assertEqual(service.lifecycle.list(), [])

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
