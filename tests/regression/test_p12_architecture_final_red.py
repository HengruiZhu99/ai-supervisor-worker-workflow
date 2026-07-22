from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.agents.codex import CodexAgentBackend  # noqa: E402
from aiflow.controller.lifecycle import RunLifecycle  # noqa: E402
from aiflow.controller.runner import Budgets  # noqa: E402
from aiflow.domain.progress import ProgressPolicy, Task, ValueClass  # noqa: E402
from tests.helpers.execution_backends import (  # noqa: E402
    OrchestratedBackend,
    completed_result,
)
from tests.regression.test_final_audit_red import (  # noqa: E402
    context_for,
    git,
    init_project,
    runtime,
)


class WrongAcceptanceBackend(OrchestratedBackend):
    def __call__(self, capsule: Mapping[str, Any]) -> Mapping[str, Any]:
        result = dict(super().__call__(capsule))
        if capsule["action"] == "execute_task":
            result["closed_acceptance_ids"] = ["AC-WRONG"]
            result["acceptance_ids_supported"] = ["AC-WRONG"]
        return result


class UncoveredReviewBackend(OrchestratedBackend):
    def __call__(self, capsule: Mapping[str, Any]) -> Mapping[str, Any]:
        result = dict(super().__call__(capsule))
        if capsule["action"] == "review_task":
            result["files_reviewed"] = []
        return result


class P12ArchitectureFinalRegressionTests(unittest.TestCase):
    def test_forged_red_and_cold_review_cannot_close_solo_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            context = context_for(root, tmp)
            command = [sys.executable, "-c", "pass"]
            started = RunLifecycle(context, runtime_env=runtime(tmp)).start(
                mode="solo",
                objective="forged cycle",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "forged cycle",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "commands": [command],
                        "allowed_scope": ["forged.txt"],
                    },
                ),
            )

            def backend(capsule: Mapping[str, Any]) -> Mapping[str, Any]:
                (root / "forged.txt").write_text("done\n", encoding="utf-8")
                return completed_result(
                    capsule, ["AC-1"], artifact="forged.txt", command=command
                )

            result = RunLifecycle(
                context, runtime_env=runtime(tmp), agent_backend=backend
            ).resume(started["run_id"], budgets=Budgets(max_attempts=1, max_idle=1))
            self.assertNotEqual(result["status"], "SUCCEEDED")

    def test_rejected_acceptance_never_integrates_the_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            git(root, "checkout", "-qb", "codex/audit-test")
            context = context_for(root, tmp)
            red = [
                sys.executable,
                "-c",
                "from pathlib import Path; assert Path('src/orchestrated.txt').is_file()",
            ]
            command = red
            started = RunLifecycle(context, runtime_env=runtime(tmp)).start(
                mode="orchestrated",
                objective="reviewed isolated change",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "reviewed isolated change",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "allowed_scope": ["src/orchestrated.txt"],
                        "pre_commands": [red],
                        "commands": [command],
                    },
                ),
            )
            before = git(root, "rev-parse", "HEAD").stdout.strip()
            result = RunLifecycle(
                context,
                runtime_env=runtime(tmp),
                agent_backend=WrongAcceptanceBackend(root, command),
            ).resume(started["run_id"], budgets=Budgets(max_attempts=1, max_idle=1))
            self.assertNotEqual(result["status"], "SUCCEEDED")
            self.assertEqual(git(root, "rev-parse", "HEAD").stdout.strip(), before)
            self.assertFalse((root / "src" / "orchestrated.txt").exists())

    def test_incomplete_review_coverage_never_integrates_the_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            context = context_for(root, tmp)
            command = [
                sys.executable,
                "-c",
                "from pathlib import Path; assert Path('T0001.txt').is_file()",
            ]
            started = RunLifecycle(context, runtime_env=runtime(tmp)).start(
                mode="orchestrated",
                objective="review every changed file",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "review every changed file",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "allowed_scope": ["T0001.txt"],
                        "pre_commands": [command],
                        "commands": [command],
                    },
                ),
            )
            before = git(root, "rev-parse", "HEAD").stdout.strip()
            result = RunLifecycle(
                context,
                runtime_env=runtime(tmp),
                agent_backend=UncoveredReviewBackend(root, command),
            ).resume(started["run_id"], budgets=Budgets(max_attempts=1, max_idle=1))
            self.assertNotEqual(result["status"], "SUCCEEDED")
            self.assertEqual(git(root, "rev-parse", "HEAD").stdout.strip(), before)

    def test_automatic_orchestration_refuses_a_default_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            git(root, "branch", "-M", "main")
            context = context_for(root, tmp)
            command = [sys.executable, "-c", "pass"]
            started = RunLifecycle(context, runtime_env=runtime(tmp)).start(
                mode="orchestrated",
                objective="reviewed isolated change",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "reviewed isolated change",
                        "kind": "feature",
                        "acceptance_ids": ["AC-1"],
                        "allowed_scope": ["src/orchestrated.txt"],
                        "pre_commands": [[sys.executable, "-c", "raise SystemExit(1)"]],
                        "commands": [command],
                    },
                ),
            )
            before = git(root, "rev-parse", "HEAD").stdout.strip()
            result = RunLifecycle(
                context,
                runtime_env=runtime(tmp),
                agent_backend=OrchestratedBackend(root, command),
            ).resume(started["run_id"], budgets=Budgets(max_attempts=1, max_idle=1))
            self.assertNotEqual(result["status"], "SUCCEEDED")
            self.assertEqual(git(root, "rev-parse", "HEAD").stdout.strip(), before)

    def test_accepted_enabler_reconstructs_durable_progress_debt(self) -> None:
        tasks = [
            Task(
                id="E",
                objective="enable target",
                value_class=ValueClass.ENABLER,
                unblocks_task_id="Z",
                status="ACCEPTED",
            ),
            Task(
                id="A",
                objective="lateral",
                value_class=ValueClass.DELIVERY,
                acceptance_ids=("AC-A",),
            ),
            Task(
                id="Z",
                objective="debt target",
                value_class=ValueClass.DELIVERY,
                acceptance_ids=("AC-Z",),
                dependencies=("E",),
            ),
        ]
        resumed = ProgressPolicy(open_acceptance_ids={"AC-A", "AC-Z"}, tasks=tasks)
        self.assertEqual(resumed.report()["progress_debt"], "Z")
        self.assertEqual(resumed.next_task().id, "Z")

    def test_no_delta_breaker_survives_controller_restart(self) -> None:
        tasks = [
            Task(
                id=f"H{index}",
                objective=f"housekeeping {index}",
                value_class=ValueClass.HOUSEKEEPING,
            )
            for index in (1, 2)
        ]
        policy = ProgressPolicy(
            open_acceptance_ids={"AC-OPEN"},
            tasks=tasks,
            housekeeping_budget=2,
        )
        self.assertEqual(
            policy.accept("H1", closed_acceptance_ids=set(), evidence={}),
            "ACCEPTED",
        )
        self.assertEqual(
            policy.accept("H2", closed_acceptance_ids=set(), evidence={}),
            "REPLAN_REQUIRED",
        )

        resumed = ProgressPolicy(
            open_acceptance_ids={"AC-OPEN"},
            tasks=tasks,
            housekeeping_budget=2,
            state=policy.durable_state(),
        )
        with self.assertRaisesRegex(Exception, "replan"):
            resumed.next_task()

    def test_codex_child_process_disables_recursive_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            capsule = {
                "action": "analyze_task",
                "mode": "orchestrated",
                "agent_role": "codebase-mapper",
                "project_id": "p",
                "checkout_id": "c",
                "worktree_id": "w",
                "run_id": "r",
                "task_id": "t",
                "working_directory": str(root),
            }
            seen: list[str] = []

            def owned(command, **kwargs):
                del kwargs
                if command[0] == "git":
                    return subprocess.CompletedProcess(command, 0, str(root), "")
                seen.extend(command)
                output = Path(command[command.index("--output-last-message") + 1])
                output.write_text(
                    '{"schema_version":"1","status":"completed"}',
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch("aiflow.agents.codex.run_owned_process", side_effect=owned):
                CodexAgentBackend(root).run(capsule)
            self.assertIn("agents.enabled=false", seen)

    def test_ci_fetches_the_explicit_diff_base(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("fetch-depth: 0", workflow)

    def test_solo_rejects_a_multi_task_program(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            lifecycle = RunLifecycle(context_for(root, tmp), runtime_env=runtime(tmp))
            with self.assertRaises(ValueError):
                lifecycle.start(
                    mode="solo",
                    objective="not a solo task",
                    task_specs=(
                        {
                            "id": "T0001",
                            "objective": "first",
                            "acceptance_ids": ["AC-1"],
                        },
                        {
                            "id": "T0002",
                            "objective": "second",
                            "acceptance_ids": ["AC-2"],
                        },
                    ),
                )


if __name__ == "__main__":
    unittest.main()
