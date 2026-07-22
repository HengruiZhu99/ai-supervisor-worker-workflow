from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.agents.codex import CodexAgentBackend  # noqa: E402
from aiflow.controller.lifecycle import RunLifecycle  # noqa: E402
from aiflow.controller.runner import Budgets  # noqa: E402
from aiflow.identity.context import resolve_project  # noqa: E402
from tests.helpers.execution_backends import (  # noqa: E402
    OrchestratedBackend,
    completed_result,
)


def git(path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def init_project(path: Path, *, commit: bool = False) -> None:
    path.mkdir()
    self_config = path / ".aiflow" / "project.toml"
    self_config.parent.mkdir()
    self_config.write_text(
        'schema_version = 1\nproject_id = "final-audit"\nname = "fixture"\n'
        'profile = "orchestrated"\n[commands]\nbuild = []\ntest_focused = []\n'
        "test_regression = []\n[execution]\nallow_parallel_mutating_runs = false\n",
        encoding="utf-8",
    )
    assert git(path, "init", "-q").returncode == 0
    if commit:
        git(path, "config", "user.name", "AIFLOW Test")
        git(path, "config", "user.email", "aiflow@example.invalid")
        git(path, "add", ".aiflow/project.toml")
        assert git(path, "commit", "-qm", "fixture baseline").returncode == 0
        assert git(path, "checkout", "-qb", "codex/test").returncode == 0


def missing_artifact(path: str) -> list[str]:
    return [
        sys.executable,
        "-c",
        f"from pathlib import Path; assert Path({path!r}).is_file()",
    ]


def runtime(tmp: str) -> dict[str, str]:
    return {"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime")}


def context_for(root: Path, tmp: str):
    return resolve_project(
        explicit_root=root,
        env={"XDG_STATE_HOME": str(Path(tmp) / "state")},
    )


def solo_review(capsule: Mapping[str, Any]) -> dict[str, Any]:
    identities = {
        key: str(capsule[key])
        for key in ("project_id", "checkout_id", "worktree_id", "run_id", "task_id")
    }
    return {
        "schema_version": "1",
        **identities,
        "agent_role": "implementation-worker",
        "status": "completed",
        "recommendation": "accept",
        "blocks_acceptance": False,
        "findings": [],
        "full_diff_reviewed": True,
        "files_reviewed": list(capsule["task"].get("allowed_scope", [])),
        "unreviewed_files": [],
    }


class FinalExecutionAuditRegressionTests(unittest.TestCase):
    def test_invalid_dependency_graph_is_rejected_before_run_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            context = context_for(root, tmp)
            lifecycle = RunLifecycle(context, runtime_env=runtime(tmp))
            with self.assertRaises(ValueError):
                lifecycle.start(
                    mode="orchestrated",
                    objective="invalid graph",
                    task_specs=(
                        {
                            "id": "T0001",
                            "objective": "invalid graph",
                            "kind": "feature",
                            "acceptance_ids": ["AC-1"],
                            "dependencies": ["DOES-NOT-EXIST"],
                        },
                    ),
                )
            self.assertEqual(lifecycle.list(), [])

    def test_child_report_cannot_attest_a_missing_artifact_or_unexecuted_command(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            context = context_for(root, tmp)
            command = [
                sys.executable,
                "-c",
                "from pathlib import Path; assert Path('src/feature.cpp').is_file()",
            ]
            started = RunLifecycle(context, runtime_env=runtime(tmp)).start(
                mode="solo",
                objective="bounded feature",
                acceptance_ids=("AC-1",),
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "bounded feature",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "pre_commands": [command],
                        "commands": [command],
                        "allowed_scope": ["src/feature.cpp"],
                        "expected_diff_budget": 1,
                    },
                ),
            )

            def lying_backend(capsule: Mapping[str, Any]) -> Mapping[str, Any]:
                return completed_result(
                    capsule, ["AC-1"], artifact="src/feature.cpp", command=command
                )

            lifecycle = RunLifecycle(
                context, runtime_env=runtime(tmp), agent_backend=lying_backend
            )
            result = lifecycle.resume(
                started["run_id"], budgets=Budgets(max_attempts=1, max_idle=1)
            )
            self.assertNotEqual(result["status"], "SUCCEEDED")
            self.assertFalse((root / "src" / "feature.cpp").exists())
            self.assertNotEqual(
                lifecycle.status(started["run_id"])["tasks"][0]["status"],
                "ACCEPTED",
            )

    def test_delivery_task_cannot_succeed_with_an_empty_acceptance_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            context = context_for(root, tmp)
            command = [sys.executable, "-c", "pass"]
            started = RunLifecycle(context, runtime_env=runtime(tmp)).start(
                mode="solo",
                objective="must close acceptance",
                acceptance_ids=("AC-OPEN",),
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "must close acceptance",
                        "kind": "feature",
                        "acceptance_ids": ["AC-OPEN"],
                        "pre_commands": [missing_artifact("feature.txt")],
                        "commands": [command],
                        "allowed_scope": ["feature.txt"],
                    },
                ),
            )

            def backend(capsule: Mapping[str, Any]) -> Mapping[str, Any]:
                if capsule["action"] == "review_task":
                    return solo_review(capsule)
                artifact = root / "feature.txt"
                artifact.write_text("implemented\n", encoding="utf-8")
                return completed_result(
                    capsule, [], artifact="feature.txt", command=command
                )

            lifecycle = RunLifecycle(
                context, runtime_env=runtime(tmp), agent_backend=backend
            )
            result = lifecycle.resume(
                started["run_id"], budgets=Budgets(max_attempts=1, max_idle=1)
            )
            self.assertNotEqual(result["status"], "SUCCEEDED")
            self.assertEqual(result.get("acceptance_ids_closed", []), [])

    def test_dependent_tasks_resume_after_a_finite_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            context = context_for(root, tmp)
            command = [sys.executable, "-c", "pass"]
            lifecycle = RunLifecycle(context, runtime_env=runtime(tmp))
            started = lifecycle.start(
                mode="orchestrated",
                objective="two checkpoints",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "first",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "pre_commands": [missing_artifact("T0001.txt")],
                        "commands": [command],
                        "allowed_scope": ["T0001.txt"],
                    },
                    {
                        "id": "T0002",
                        "objective": "second",
                        "kind": "feature",
                        "acceptance_ids": ["AC-2"],
                        "dependencies": ["T0001"],
                        "pre_commands": [missing_artifact("T0002.txt")],
                        "commands": [command],
                        "allowed_scope": ["T0002.txt"],
                    },
                ),
            )

            backend = OrchestratedBackend(root, command)
            resumed = RunLifecycle(
                context, runtime_env=runtime(tmp), agent_backend=backend
            )
            first = resumed.resume(
                started["run_id"], budgets=Budgets(max_tasks=1, max_idle=1)
            )
            self.assertEqual(first["outcome"], "BUDGET_EXHAUSTED", first)
            second = resumed.resume(
                started["run_id"], budgets=Budgets(max_tasks=1, max_idle=1)
            )
            self.assertEqual(second["status"], "SUCCEEDED")
            self.assertEqual(second["acceptance_ids_closed"], ["AC-1", "AC-2"])

    def test_failure_attempt_budget_is_durable_across_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            context = context_for(root, tmp)
            started = RunLifecycle(context, runtime_env=runtime(tmp)).start(
                mode="solo",
                objective="finite failure",
                acceptance_ids=("AC-1",),
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "finite failure",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "pre_commands": [missing_artifact("failure.txt")],
                        "commands": [[sys.executable, "-c", "pass"]],
                        "allowed_scope": ["failure.txt"],
                    },
                ),
            )
            calls = 0

            def backend(capsule: Mapping[str, Any]) -> Mapping[str, Any]:
                nonlocal calls
                calls += 1
                return {"status": "failed", "task_id": capsule["task_id"]}

            resumed = RunLifecycle(
                context, runtime_env=runtime(tmp), agent_backend=backend
            )
            first = resumed.resume(
                started["run_id"], budgets=Budgets(max_attempts=1, max_idle=1)
            )
            second = resumed.resume(
                started["run_id"], budgets=Budgets(max_attempts=1, max_idle=1)
            )
            self.assertEqual(first["outcome"], "BLOCKED")
            self.assertEqual(second["outcome"], "BLOCKED")
            self.assertEqual(calls, 1)

    def test_controller_heartbeats_during_a_blocking_backend_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            context = context_for(root, tmp)
            command = [sys.executable, "-c", "pass"]
            started = RunLifecycle(context, runtime_env=runtime(tmp)).start(
                mode="solo",
                objective="long task",
                acceptance_ids=("AC-1",),
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "long task",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "pre_commands": [missing_artifact("long.txt")],
                        "commands": [command],
                        "allowed_scope": ["long.txt"],
                    },
                ),
            )

            def backend(capsule: Mapping[str, Any]) -> Mapping[str, Any]:
                if capsule["action"] == "review_task":
                    return solo_review(capsule)
                time.sleep(0.2)
                (root / "long.txt").write_text("done", encoding="utf-8")
                return completed_result(
                    capsule, ["AC-1"], artifact="long.txt", command=command
                )

            resumed = RunLifecycle(
                context,
                runtime_env=runtime(tmp),
                agent_backend=backend,
                controller_ttl_seconds=0.1,
                heartbeat_interval_seconds=0.02,
            ).resume(started["run_id"], budgets=Budgets(max_idle=1))
            self.assertEqual(resumed["status"], "SUCCEEDED")

    def test_orchestrated_lane_uses_roles_worktree_review_and_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            context = context_for(root, tmp)
            command = [
                sys.executable,
                "-c",
                "from pathlib import Path; assert Path('src/orchestrated.txt').read_text() == 'done\\n'",
            ]
            started = RunLifecycle(context, runtime_env=runtime(tmp)).start(
                mode="orchestrated",
                objective="reviewed isolated change",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "reviewed isolated change",
                        "kind": "feature",
                        "risk": "normal",
                        "acceptance_ids": ["AC-ORCH"],
                        "allowed_scope": ["src/orchestrated.txt"],
                        "pre_commands": [missing_artifact("src/orchestrated.txt")],
                        "commands": [command],
                        "expected_diff_budget": 1,
                    },
                ),
            )
            backend = OrchestratedBackend(root, command)
            result = RunLifecycle(
                context, runtime_env=runtime(tmp), agent_backend=backend
            ).resume(started["run_id"], budgets=Budgets(max_agent_calls=8, max_idle=1))
            self.assertEqual(result["status"], "SUCCEEDED")
            self.assertEqual(
                backend.actions,
                [
                    ("analyze_task", "codebase-mapper"),
                    ("analyze_task", "test-architect"),
                    ("execute_task", "implementation-worker"),
                    ("review_task", "engineering-reviewer"),
                ],
            )
            self.assertEqual(
                (root / "src" / "orchestrated.txt").read_text(encoding="utf-8"),
                "done\n",
            )
            self.assertEqual(git(root, "status", "--short").stdout, "")

    def test_codex_prompt_and_sandbox_are_mode_and_role_specific(self) -> None:
        solo = CodexAgentBackend._prompt(
            {
                "mode": "solo",
                "action": "execute_task",
                "agent_role": "implementation-worker",
            }
        )
        orchestrated = CodexAgentBackend._prompt(
            {
                "mode": "orchestrated",
                "action": "analyze_task",
                "agent_role": "codebase-mapper",
            }
        )
        self.assertIn("$tdd-solo", solo)
        self.assertIn("$aiflow-autonomous", orchestrated)
        self.assertNotIn("Use $tdd-solo", orchestrated)


if __name__ == "__main__":
    unittest.main()
