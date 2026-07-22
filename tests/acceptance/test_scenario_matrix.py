from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.agents.fake import FakeAgentBackend  # noqa: E402
from aiflow.agents.review import Finding, ReviewTracker  # noqa: E402
from aiflow.controller.runner import Budgets, ControllerOutcome, ControllerRunner  # noqa: E402
from aiflow.domain.evidence import validate_cycle  # noqa: E402
from aiflow.domain.progress import ProgressPolicy, Task, TaskContractError, ValueClass  # noqa: E402
from aiflow.domain.routing import recommend_mode  # noqa: E402
from aiflow.identity.context import cache_path, resolve_project, runtime_path  # noqa: E402
from aiflow.integration.transaction import GateCommands, IntegrationTransaction  # noqa: E402
from aiflow.skills.installer import ProjectInstaller  # noqa: E402
from aiflow.state.handoff import HandoffError, verify_handoff  # noqa: E402
from aiflow.state.lifecycle import RunLifecycle  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=True,
    ).stdout.strip()


def project(path: Path, profile: str = "solo") -> None:
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "acceptance@example.invalid")
    git(path, "config", "user.name", "Acceptance Tests")
    ProjectInstaller(path, distribution_root=ROOT).init(profile)
    git(path, "add", ".")
    git(path, "commit", "-qm", "fixture")


def evidence(kind: str) -> dict:
    base = {
        "red": {"exit_code": 1, "discriminating": True},
        "green": {"exit_code": 0}, "regression": {"exit_code": 0},
        "cold_review": {"status": "pass", "reviewer": "cold-self-review"},
        "attempts": 1, "questions": 0,
    }
    additions = {
        "feature": {"observable": "new behavior"},
        "bug": {"reproduction": "old failure"},
        "refactor": {"characterization": "golden result", "behavior_equivalent": True},
        "numerical": {
            "reference": "analytic", "units": "dimensionless", "dimensions": 3,
            "shapes": [[3]], "tolerance": {"absolute": 1e-12, "relative": 1e-10},
            "convergence": {"observed_order": 2.0, "minimum_order": 1.9},
        },
        "performance": {
            "baseline_metric": 10.0, "candidate_metric": 10.1, "max_regression": .05,
            "metric": "milliseconds", "samples": 5,
        },
        "portability": {"backends": {"serial": "pass", "openmp": "pass"}},
    }
    return {**base, **additions[kind]}


def delivery(task_id: str, acceptance: str, dependency: tuple[str, ...] = ()) -> Task:
    return Task(
        id=task_id, objective=task_id, value_class=ValueClass.DELIVERY,
        acceptance_ids=(acceptance,), dependencies=dependency, allowed_scope=("src/",),
        commands=(("test",),), evidence=("evidence.json",), expected_diff_budget=10,
    )


def accepted_file(name: str) -> dict:
    return {
        "changed_files": [name], "expected_artifact": name,
        "commands": [["test"]], "test_results": [{"exit_code": 0}],
        "fresh_end_to_end": True,
    }


class ScenarioMatrixAcceptanceTests(unittest.TestCase):
    def test_01_successful_solo_feature(self) -> None:
        self.assertEqual(validate_cycle("feature", evidence("feature"))["status"], "VERIFIED")

    def test_02_bug_fix_reproduces_before_green(self) -> None:
        self.assertEqual(validate_cycle("bug", evidence("bug"))["status"], "VERIFIED")

    def test_03_refactor_preserves_characterized_behavior(self) -> None:
        self.assertEqual(validate_cycle("refactor", evidence("refactor"))["status"], "VERIFIED")

    def test_04_numerical_and_portability_evidence(self) -> None:
        self.assertEqual(validate_cycle("numerical", evidence("numerical"))["status"], "VERIFIED")
        self.assertEqual(validate_cycle("portability", evidence("portability"))["status"], "VERIFIED")

    def test_05_performance_guard(self) -> None:
        self.assertEqual(validate_cycle("performance", evidence("performance"))["status"], "VERIFIED")

    def test_06_orchestration_recommendation_and_fake_backend(self) -> None:
        decision = recommend_mode(task_count=4, milestones=2, independent_writes=2)
        backend = FakeAgentBackend({"route": [{"status": "ok", "mode": decision.mode}]})
        self.assertEqual(backend.run({"action": "route"})["mode"], "orchestrated")
        self.assertEqual(backend.calls, 1)

    def test_07_successful_multi_milestone_program(self) -> None:
        first, second = delivery("T1", "AC-1"), delivery("T2", "AC-2", ("T1",))
        policy = ProgressPolicy(open_acceptance_ids={"AC-1", "AC-2"}, tasks=[first, second])
        policy.accept("T1", closed_acceptance_ids={"AC-1"}, evidence=accepted_file("src/one.cpp"))
        policy.accept("T2", closed_acceptance_ids={"AC-2"}, evidence=accepted_file("src/two.cpp"))
        self.assertTrue(policy.milestone_can_close())

    def test_08_repeated_metadata_attempt_is_blocked(self) -> None:
        policy = ProgressPolicy(open_acceptance_ids={"AC-1"}, tasks=[delivery("T1", "AC-1")])
        with self.assertRaises(TaskContractError):
            policy.accept("T1", closed_acceptance_ids={"AC-1"}, evidence=accepted_file("docs/claim.md"))

    def test_09_same_failure_is_bounded(self) -> None:
        runner = ControllerRunner(budgets=Budgets(max_attempts=2, max_idle=1))
        self.assertEqual(runner.run(lambda: "retry:same-signature"), ControllerOutcome.BLOCKED)

    def test_10_reviewer_ping_pong_is_bounded(self) -> None:
        finding = Finding("SCI-1", "high", "wrong units", ("AC-1",), "fix conversion")
        tracker = ReviewTracker()
        self.assertEqual([tracker.record(finding) for _ in range(3)][-1], "BLOCKED")

    def test_11_process_restart_reads_durable_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            project(root)
            context = resolve_project(explicit_root=root)
            environment = {"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime")}
            started = RunLifecycle(context, runtime_env=environment).start(mode="solo", objective="resume")
            restarted = RunLifecycle(resolve_project(explicit_root=root), runtime_env=environment)
            self.assertEqual(restarted.status(started["run_id"])["status"], "PAUSED")

    def test_12_stale_handoff_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            project(root)
            context = resolve_project(explicit_root=root)
            lifecycle = RunLifecycle(context, runtime_env={"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime")})
            run = lifecycle.start(mode="solo", objective="handoff")
            exported = lifecycle.handoff(run["run_id"], expected_revision=run["state_revision"])
            (root / ".aiflow" / "project.toml").write_text((root / ".aiflow" / "project.toml").read_text() + "\n# drift\n")
            with self.assertRaises(HandoffError):
                verify_handoff(Path(exported["handoff_path"]), context)

    def test_13_target_drift_leaves_candidate_unapplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            git(root, "init", "-q", "-b", "main")
            git(root, "config", "user.email", "acceptance@example.invalid")
            git(root, "config", "user.name", "Acceptance Tests")
            (root / "base.txt").write_text("base\n")
            git(root, "add", "."); git(root, "commit", "-qm", "base")
            base = git(root, "rev-parse", "HEAD")
            git(root, "switch", "-qc", "candidate")
            (root / "candidate.txt").write_text("candidate\n")
            git(root, "add", "."); git(root, "commit", "-qm", "candidate")
            candidate = git(root, "rev-parse", "HEAD")
            git(root, "switch", "-q", "main")
            passing = ((sys.executable, "-c", "raise SystemExit(0)"),)
            transaction = IntegrationTransaction(
                root, gates=GateCommands(passing, passing, passing),
                before_apply=lambda: git(root, "commit", "--allow-empty", "-qm", "drift"),
            )
            result = transaction.apply(candidate, method="merge", base_sha=base)
            self.assertEqual(result.reason, "target HEAD changed")
            self.assertFalse((root / "candidate.txt").exists())

    def test_14_cross_project_contamination_is_resisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "first", Path(tmp) / "second"
            project(first); project(second)
            one = resolve_project(explicit_root=first, env={"AIFLOW_PROJECT_ROOT": str(second)})
            two = resolve_project(explicit_root=second)
            environment = {"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime"), "XDG_CACHE_HOME": str(Path(tmp) / "cache")}
            self.assertNotEqual(runtime_path(one, "run", env=environment), runtime_path(two, "run", env=environment))
            self.assertNotEqual(cache_path(one, env=environment), cache_path(two, env=environment))

    def test_15_idle_run_uses_zero_model_calls(self) -> None:
        backend = FakeAgentBackend({})
        runner = ControllerRunner(budgets=Budgets(max_idle=1), agent_call=backend.run)
        self.assertEqual(runner.run(lambda: "idle"), ControllerOutcome.IDLE_EXIT)
        self.assertEqual(backend.calls, 0)


if __name__ == "__main__":
    unittest.main()
