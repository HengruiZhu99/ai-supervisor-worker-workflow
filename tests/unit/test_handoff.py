from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from aiflow.identity.context import resolve_project
from aiflow.skills.installer import ProjectInstaller
from aiflow.state.handoff import HandoffError, verify_handoff
from aiflow.controller.lifecycle import RunLifecycle


ROOT = Path(__file__).resolve().parents[2]


def initialize(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "AIFLOW Test"], cwd=path, check=True)
    ProjectInstaller(path, distribution_root=ROOT).init("solo")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=path, check=True)


class HandoffTests(unittest.TestCase):
    def test_export_is_identity_git_contract_and_revision_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project"
            initialize(path)
            context = resolve_project(explicit_root=path)
            lifecycle = RunLifecycle(
                context, runtime_env={"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime")}
            )
            run = lifecycle.start(
                mode="solo", objective="fix norm", acceptance_ids=("AC-1",)
            )
            exported = lifecycle.handoff(
                run["run_id"], expected_revision=run["state_revision"]
            )
            handoff = Path(exported["handoff_path"])
            self.assertTrue(handoff.is_file())
            verified = verify_handoff(handoff, context)
            self.assertEqual(verified["run_id"], run["run_id"])
            self.assertEqual(verified["checkout_id"], context.checkout_id)
            self.assertIn("run resume", verified["resume_command"])
            (path / ".aiflow" / "project.toml").write_text(
                (path / ".aiflow" / "project.toml").read_text()
                + "\n# changed contract\n"
            )
            with self.assertRaises(HandoffError):
                verify_handoff(handoff, context)

    def test_cross_project_handoff_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "first", Path(tmp) / "second"
            initialize(first)
            initialize(second)
            first_context = resolve_project(explicit_root=first)
            lifecycle = RunLifecycle(
                first_context,
                runtime_env={"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime")},
            )
            run = lifecycle.start(mode="solo", objective="bounded task")
            exported = lifecycle.handoff(
                run["run_id"], expected_revision=run["state_revision"]
            )
            with self.assertRaises(HandoffError):
                verify_handoff(
                    Path(exported["handoff_path"]),
                    resolve_project(explicit_root=second),
                )


if __name__ == "__main__":
    unittest.main()
