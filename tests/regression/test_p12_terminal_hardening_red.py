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


if __name__ == "__main__":
    unittest.main()
