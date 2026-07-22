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
from aiflow.state.store import RunStore  # noqa: E402


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


def common_cycle() -> dict[str, Any]:
    return {
        "red": {"exit_code": 1, "discriminating": True},
        "green": {"exit_code": 0},
        "regression": {"exit_code": 0},
        "cold_review": {"status": "pass", "reviewer": "cold-self-review"},
        "attempts": 1,
        "questions": 0,
        "observable": "new behavior",
    }


def completed_result(
    capsule: Mapping[str, Any],
    acceptance_ids: list[str],
    *,
    artifact: str,
    command: list[str],
) -> dict[str, Any]:
    identities = {
        key: str(capsule[key])
        for key in ("project_id", "checkout_id", "worktree_id", "run_id")
    }
    return {
        "schema_version": "1",
        **identities,
        "task_id": str(capsule["task_id"]),
        "agent_role": "implementation-worker",
        "status": "completed",
        "summary": "completed bounded task",
        "findings": [],
        "changed_files": [artifact],
        "commands_run": [command],
        "tests_and_results": [{"command": command, "exit_code": 0}],
        "acceptance_ids_supported": acceptance_ids,
        "evidence_paths": ["evidence/cycle.json"],
        "contract_impact": "bounded",
        "residual_risks": [],
        "recommended_next_action": "accept",
        "cycle_kind": "feature",
        "cycle_evidence": common_cycle(),
        "delivery_evidence": {
            "changed_files": [artifact],
            "expected_artifact": artifact,
            "commands": [command],
            "test_results": [{"command": command, "exit_code": 0}],
            "fresh_end_to_end": True,
        },
        "closed_acceptance_ids": acceptance_ids,
    }


def runtime(tmp: str) -> dict[str, str]:
    return {"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime")}


def context_for(root: Path, tmp: str):
    return resolve_project(
        explicit_root=root,
        env={"XDG_STATE_HOME": str(Path(tmp) / "state")},
    )


class OrchestratedBackend:
    def __init__(self, root: Path, command: list[str]) -> None:
        self.root = root
        self.command = command
        self.actions: list[tuple[str, str]] = []
        self.writer_directory = ""

    def __call__(self, capsule: Mapping[str, Any]) -> Mapping[str, Any]:
        action = str(capsule["action"])
        role = str(capsule["agent_role"])
        self.actions.append((action, role))
        identities = {
            key: capsule[key]
            for key in (
                "project_id",
                "checkout_id",
                "worktree_id",
                "run_id",
                "task_id",
            )
        }
        if action == "analyze_task":
            return {
                "schema_version": "1",
                **identities,
                "agent_role": role,
                "status": "completed",
                "summary": f"{role} bounded analysis",
                "findings": [],
                "recommended_next_action": "dispatch writer",
            }
        if action == "execute_task":
            self.writer_directory = str(capsule["working_directory"])
            worktree = Path(self.writer_directory)
            if worktree.resolve() == self.root.resolve():
                raise AssertionError("orchestrated writer used the target checkout")
            task_id = str(capsule["task_id"])
            artifact = (
                "src/orchestrated.txt"
                if task_id == "T0001"
                and capsule["task"]["objective"] == "reviewed isolated change"
                else f"{task_id}.txt"
            )
            target = worktree / artifact
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("done\n", encoding="utf-8")
            return completed_result(
                capsule,
                [str(value) for value in capsule["task"]["acceptance_ids"]],
                artifact=artifact,
                command=self.command,
            )
        if action == "review_task":
            if (
                Path(str(capsule["working_directory"])).resolve()
                != Path(self.writer_directory).resolve()
            ):
                raise AssertionError("reviewer did not inspect the writer worktree")
            return {
                "schema_version": "1",
                **identities,
                "agent_role": role,
                "status": "completed",
                "recommendation": "accept",
                "blocks_acceptance": False,
                "findings": [],
                "full_diff_reviewed": True,
                "files_reviewed": list(capsule["task"]["allowed_scope"]),
                "unreviewed_files": [],
            }
        raise AssertionError(action)


class FinalExecutionAuditRegressionTests(unittest.TestCase):
    def test_bugfix_alias_is_normalized_to_the_bug_evidence_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            context = context_for(root, tmp)
            started = RunLifecycle(context, runtime_env=runtime(tmp)).start(
                mode="solo", objective="repair defect", task_kind="bugfix"
            )
            task = RunLifecycle(context, runtime_env=runtime(tmp)).status(
                started["run_id"]
            )["tasks"][0]
            self.assertEqual(task["kind"], "bug")

    def test_run_listing_is_chronological_not_identifier_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            context = context_for(root, tmp)
            environment = runtime(tmp)
            RunStore.create(
                context, mode="solo", run_id="z-old", runtime_env=environment
            )
            time.sleep(0.001)
            RunStore.create(
                context, mode="solo", run_id="a-new", runtime_env=environment
            )
            listed = RunLifecycle(context, runtime_env=environment).list()
            self.assertEqual([str(run["run_id"]) for run in listed], ["z-old", "a-new"])

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
                        "commands": [command],
                    },
                ),
            )

            def backend(capsule: Mapping[str, Any]) -> Mapping[str, Any]:
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
                        "commands": [command],
                        "allowed_scope": ["T0001.txt"],
                    },
                    {
                        "id": "T0002",
                        "objective": "second",
                        "kind": "feature",
                        "acceptance_ids": ["AC-2"],
                        "dependencies": ["T0001"],
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
                mode="solo", objective="finite failure", acceptance_ids=("AC-1",)
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
                        "commands": [command],
                    },
                ),
            )

            def backend(capsule: Mapping[str, Any]) -> Mapping[str, Any]:
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
