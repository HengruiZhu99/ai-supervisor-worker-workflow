from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.controller.runner import Budgets, ControllerOutcome, ControllerRunner  # noqa: E402
from aiflow.controller.watchdog import DeterministicWatchdog  # noqa: E402
from aiflow.identity.context import resolve_project  # noqa: E402
from aiflow.controller.lifecycle import RunLifecycle  # noqa: E402


def init_project(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    config = path / ".aiflow" / "project.toml"
    config.parent.mkdir()
    config.write_text(
        'schema_version = 1\nproject_id = "controller-project"\nname = "fixture"\nprofile = "solo"\n',
        encoding="utf-8",
    )


class ControllerTests(unittest.TestCase):
    def test_all_budgets_are_finite_and_idle_path_makes_zero_model_calls(self) -> None:
        budgets = Budgets()
        self.assertTrue(all(value > 0 for value in budgets.as_dict().values()))
        calls: list[str] = []
        runner = ControllerRunner(
            budgets=Budgets(max_wall_time=5, max_tasks=2, max_attempts=2, max_idle=1, max_agent_calls=2),
            agent_call=lambda _: calls.append("model"),
        )
        outcome = runner.run(lambda: "idle")
        self.assertEqual(outcome, ControllerOutcome.IDLE_EXIT)
        self.assertEqual(calls, [])

    def test_unchanged_actionable_watchdog_event_is_diagnosed_once(self) -> None:
        calls: list[dict[str, object]] = []
        watchdog = DeterministicWatchdog(diagnose=lambda capsule: calls.append(capsule))
        event = {"kind": "process_death", "task_id": "T1", "evidence": "same"}
        self.assertEqual(watchdog.observe(event), "DIAGNOSED")
        self.assertEqual(watchdog.observe(event), "DUPLICATE_EVENT")
        changed = {**event, "evidence": "changed"}
        self.assertEqual(watchdog.observe(changed), "DIAGNOSED")
        self.assertEqual(len(calls), 2)

    def test_solo_run_start_status_resume_idle_and_stop_are_durable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            context = resolve_project(explicit_root=root)
            lifecycle = RunLifecycle(context, runtime_env={"XDG_RUNTIME_DIR": str(Path(tmp) / "run")})
            started = lifecycle.start(
                mode="solo", objective="bounded feature", acceptance_ids=("AC-1",)
            )
            self.assertEqual(started["status"], "PAUSED")
            run_id = started["run_id"]
            self.assertEqual(lifecycle.status(run_id)["tasks"][0]["objective"], "bounded feature")
            resumed = lifecycle.resume(run_id, budgets=Budgets(max_idle=1))
            self.assertEqual(resumed["outcome"], "IDLE_EXIT")
            stopped = lifecycle.stop(run_id)
            self.assertEqual(stopped["status"], "STOPPED")

    def test_controller_budget_exhaustion_is_terminal(self) -> None:
        runner = ControllerRunner(
            budgets=Budgets(max_wall_time=5, max_tasks=1, max_attempts=2, max_idle=2, max_agent_calls=1)
        )
        self.assertEqual(runner.run(lambda: "progress"), ControllerOutcome.BUDGET_EXHAUSTED)


if __name__ == "__main__":
    unittest.main()
