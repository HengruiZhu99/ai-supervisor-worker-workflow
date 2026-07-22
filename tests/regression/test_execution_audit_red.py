from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.agents.fake import FakeAgentBackend  # noqa: E402
from aiflow.controller.runner import Budgets  # noqa: E402
from aiflow.domain.evidence import EvidenceError, validate_cycle  # noqa: E402
from aiflow.identity.context import resolve_project  # noqa: E402
from aiflow.controller.lifecycle import RunLifecycle  # noqa: E402


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
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    config = path / ".aiflow" / "project.toml"
    config.parent.mkdir()
    config.write_text(
        'schema_version = 1\nproject_id = "execution-audit"\nname = "fixture"\n'
        'profile = "solo"\n[execution]\nallow_parallel_mutating_runs = false\n',
        encoding="utf-8",
    )
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


def common_evidence() -> dict:
    return {
        "green": {"exit_code": 0},
        "regression": {"exit_code": 0},
        "cold_review": {"status": "pass", "reviewer": "cold-self-review"},
        "attempts": 1,
        "questions": 0,
    }


def feature_evidence() -> dict:
    return {
        **common_evidence(),
        "red": {"exit_code": 1, "discriminating": True},
        "observable": "new behavior",
    }


def child_result(
    capsule: dict | Mapping[str, object],
    acceptance_id: str,
    *,
    artifact: str,
    command: list[str],
) -> dict:
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
        "summary": "implemented the bounded feature",
        "findings": [],
        "changed_files": [artifact],
        "commands_run": [command],
        "tests_and_results": [{"command": command, "exit_code": 0}],
        "acceptance_ids_supported": [acceptance_id],
        "evidence_paths": ["evidence/cycle.json"],
        "contract_impact": "closes accepted behavior",
        "residual_risks": [],
        "recommended_next_action": "accept",
        "cycle_kind": "feature",
        "cycle_evidence": feature_evidence(),
        "delivery_evidence": {
            "changed_files": [artifact],
            "expected_artifact": artifact,
            "commands": [command],
            "test_results": [{"exit_code": 0}],
            "fresh_end_to_end": True,
        },
        "closed_acceptance_ids": [acceptance_id],
    }


def analysis_result(capsule: Mapping[str, object]) -> dict:
    identities = {
        key: str(capsule[key])
        for key in ("project_id", "checkout_id", "worktree_id", "run_id", "task_id")
    }
    role = str(capsule["agent_role"])
    return {
        "schema_version": "1",
        **identities,
        "agent_role": role,
        "status": "completed",
        "summary": f"{role} bounded analysis",
        "findings": [],
        "recommended_next_action": "dispatch writer",
    }


def review_result(capsule: Mapping[str, object]) -> dict:
    return {
        **analysis_result(capsule),
        "recommendation": "accept",
        "blocks_acceptance": False,
        "full_diff_reviewed": True,
        "files_reviewed": list(capsule["task"]["allowed_scope"]),
        "unreviewed_files": [],
    }


class ExecutionAuditRegressionTests(unittest.TestCase):
    def test_refactor_uses_passing_characterization_without_fake_red(self) -> None:
        evidence = {
            **common_evidence(),
            "characterization": {"exit_code": 0, "discriminating": True},
            "behavior_equivalent": True,
        }
        self.assertEqual(validate_cycle("refactor", evidence)["status"], "VERIFIED")

    def test_test_only_cycle_is_supported_with_discriminating_negative_control(
        self,
    ) -> None:
        evidence = {
            **common_evidence(),
            "negative_control": {"exit_code": 1, "discriminating": True},
            "oracle": "analytic identity",
        }
        self.assertEqual(validate_cycle("test", evidence)["status"], "VERIFIED")

    def test_invalid_numerical_and_performance_claims_fail_closed(self) -> None:
        numerical = {
            **common_evidence(),
            "reference": "analytic",
            "oracle_provenance": "doi:10.example/fixture",
            "units": "dimensionless",
            "dimensions": 3,
            "shapes": [[3]],
            "tolerance": {"absolute": -1.0, "relative": -1.0, "justification": "bad"},
            "convergence": {
                "levels": 3,
                "observed_order": float("nan"),
                "minimum_order": 1.9,
            },
            "deterministic_seed": 0,
        }
        performance = {
            **common_evidence(),
            "baseline_metric": 10.0,
            "candidate_metric": float("nan"),
            "max_regression": 0.05,
            "metric": "milliseconds",
            "direction": "lower-is-better",
            "samples": 5,
            "warmups": 1,
            "comparability": "same input and resources",
            "equivalent_work": True,
            "output_equivalent": True,
        }
        with self.assertRaises(EvidenceError):
            validate_cycle("numerical", numerical)
        with self.assertRaises(EvidenceError):
            validate_cycle("performance", performance)

    def test_portability_requires_structured_backend_provenance(self) -> None:
        evidence = {
            **common_evidence(),
            "backends": {"serial": "pass", "openmp": "pass"},
        }
        with self.assertRaises(EvidenceError):
            validate_cycle("portability", evidence)

    def test_fake_backend_executes_through_durable_lifecycle_and_closes_acceptance(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            context = resolve_project(
                explicit_root=root, env={"XDG_STATE_HOME": str(Path(tmp) / "state")}
            )
            environment = {"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime")}
            command = [sys.executable, "-c", "pass"]
            started = RunLifecycle(context, runtime_env=environment).start(
                mode="solo",
                objective="bounded feature",
                acceptance_ids=("AC-FEATURE-1",),
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "bounded feature",
                        "kind": "feature",
                        "acceptance_ids": ["AC-FEATURE-1"],
                        "pre_commands": [missing_artifact("src/feature.cpp")],
                        "commands": [command],
                        "allowed_scope": ["src/feature.cpp"],
                    },
                ),
            )

            def execute(capsule):
                artifact = root / "src" / "feature.cpp"
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text("int feature() { return 1; }\n", encoding="utf-8")
                return child_result(
                    capsule,
                    "AC-FEATURE-1",
                    artifact="src/feature.cpp",
                    command=command,
                )

            backend = FakeAgentBackend(
                {"execute_task": [execute], "review_task": [review_result]}
            )
            lifecycle = RunLifecycle(
                context,
                runtime_env=environment,
                agent_backend=backend.run,
                agent_id="fake-worker",
            )
            result = lifecycle.resume(
                started["run_id"], budgets=Budgets(max_tasks=1, max_idle=1)
            )
            self.assertEqual(result["status"], "SUCCEEDED")
            self.assertEqual(result["outcome"], "SUCCEEDED")
            self.assertEqual(result["acceptance_ids_closed"], ["AC-FEATURE-1"])
            self.assertEqual(
                lifecycle.status(started["run_id"])["tasks"][0]["status"], "ACCEPTED"
            )
            self.assertEqual(backend.calls, 2)

    def test_fake_backend_runs_two_dependent_orchestrated_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            context = resolve_project(
                explicit_root=root, env={"XDG_STATE_HOME": str(Path(tmp) / "state")}
            )
            environment = {"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime")}
            command = [sys.executable, "-c", "pass"]
            lifecycle = RunLifecycle(context, runtime_env=environment)
            started = lifecycle.start(
                mode="orchestrated",
                objective="two milestones",
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

            def execute(capsule):
                task_id = str(capsule["task_id"])
                worktree = Path(str(capsule["working_directory"]))
                (worktree / f"{task_id}.txt").write_text("done\n", encoding="utf-8")
                return child_result(
                    capsule,
                    f"AC-{task_id[-1]}",
                    artifact=f"{task_id}.txt",
                    command=command,
                )

            backend = FakeAgentBackend(
                {
                    "analyze_task": [analysis_result] * 4,
                    "execute_task": [execute, execute],
                    "review_task": [review_result, review_result],
                }
            )
            resumed = RunLifecycle(
                context,
                runtime_env=environment,
                agent_backend=backend.run,
                agent_id="fake-worker",
            ).resume(started["run_id"], budgets=Budgets(max_tasks=3, max_idle=1))
            self.assertEqual(resumed["status"], "SUCCEEDED")
            self.assertEqual(resumed["acceptance_ids_closed"], ["AC-1", "AC-2"])
            self.assertEqual(backend.calls, 8)


if __name__ == "__main__":
    unittest.main()
