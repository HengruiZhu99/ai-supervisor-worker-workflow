from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_cli(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment["XDG_RUNTIME_DIR"] = str(project.parent / ".runtime")
    return subprocess.run(
        [sys.executable, "-m", "aiflow", "--project-root", str(project), *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class LifecycleCliTests(unittest.TestCase):
    def test_project_and_skill_commands_emit_json_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            initialized = run_cli(project, "project", "init", "--profile", "solo")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            self.assertEqual(json.loads(initialized.stdout)["profile"], "solo")
            verified = run_cli(project, "project", "verify")
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertTrue(json.loads(verified.stdout)["ok"])
            listed = run_cli(project, "skills", "list")
            self.assertEqual(listed.returncode, 0, listed.stderr)
            names = {row["name"] for row in json.loads(listed.stdout)}
            self.assertEqual(
                names,
                {"tdd-solo", "systematic-debugging", "verification-before-completion"},
            )
            self.assertEqual(run_cli(project, "skills", "validate").returncode, 0)

    def test_cli_ignores_inherited_project_root_and_uses_explicit_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first, second = base / "first", base / "second"
            for project in (first, second):
                project.mkdir()
                subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(ROOT / "src")
            environment["AIFLOW_PROJECT_ROOT"] = str(first)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "aiflow",
                    "--project-root",
                    str(second),
                    "project",
                    "init",
                    "--profile",
                    "solo",
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((first / ".aiflow").exists())
            self.assertTrue((second / ".aiflow" / "project.lock").is_file())

    def test_solo_run_cli_has_explicit_finite_resume_and_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            self.assertEqual(run_cli(project, "project", "init", "--profile", "solo").returncode, 0)
            started = run_cli(
                project,
                "run",
                "start",
                "--mode",
                "solo",
                "--objective",
                "bounded change",
                "--acceptance-id",
                "AC-1",
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            run_id = json.loads(started.stdout)["run_id"]
            resumed = run_cli(project, "run", "resume", "--run-id", run_id, "--max-idle", "1")
            self.assertEqual(json.loads(resumed.stdout)["outcome"], "IDLE_EXIT")
            stopped = run_cli(project, "run", "stop", "--run-id", run_id)
            self.assertEqual(json.loads(stopped.stdout)["status"], "STOPPED")

    def test_orchestrated_start_refuses_missing_or_unrestricted_parent_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            self.assertEqual(
                run_cli(project, "project", "init", "--profile", "orchestrated").returncode,
                0,
            )
            base = (
                "run", "start", "--mode", "orchestrated", "--objective", "goal",
                "--acceptance-id", "AC-1",
            )
            missing = run_cli(project, *base)
            self.assertNotEqual(missing.returncode, 0)
            unrestricted = run_cli(
                project, *base, "--parent-sandbox", "danger-full-access"
            )
            self.assertNotEqual(unrestricted.returncode, 0)
            allowed = run_cli(project, *base, "--parent-sandbox", "workspace-write")
            self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_gui_and_read_only_hub_have_nonblocking_validation_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            self.assertEqual(run_cli(project, "project", "init", "--profile", "solo").returncode, 0)
            gui = run_cli(project, "gui", "--check")
            self.assertEqual(gui.returncode, 0, gui.stderr)
            self.assertTrue(json.loads(gui.stdout)["ok"])
            hub = run_cli(project, "hub", "--check", "--project", str(project))
            self.assertEqual(hub.returncode, 0, hub.stderr)
            self.assertTrue(json.loads(hub.stdout)["read_only"])


if __name__ == "__main__":
    unittest.main()
