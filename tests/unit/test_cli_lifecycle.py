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
    environment["XDG_STATE_HOME"] = str(project.parent / ".state")
    environment["CODEX_PERMISSION_PROFILE"] = ":workspace-write"
    return subprocess.run(
        [sys.executable, "-m", "aiflow", "--project-root", str(project), *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def configure_commands(project: Path) -> None:
    command = [
        sys.executable,
        "-c",
        "from pathlib import Path; assert Path('result.txt').is_file()",
    ]
    config = project / ".aiflow" / "project.toml"
    config.write_text(
        config.read_text(encoding="utf-8")
        .replace("test_red = []", f"test_red = {json.dumps(command)}")
        .replace("test_focused = []", f"test_focused = {json.dumps(command)}")
        .replace(
            "test_regression = []",
            f"test_regression = {json.dumps([sys.executable, '-c', 'raise SystemExit(0)'])}",
        ),
        encoding="utf-8",
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
            self.assertEqual(
                run_cli(project, "project", "init", "--profile", "solo").returncode, 0
            )
            configure_commands(project)
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
                "--allowed-scope",
                "result.txt",
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            run_id = json.loads(started.stdout)["run_id"]
            resumed = run_cli(
                project,
                "run",
                "resume",
                "--run-id",
                run_id,
                "--max-idle",
                "1",
                "--backend",
                "none",
            )
            self.assertEqual(json.loads(resumed.stdout)["outcome"], "IDLE_EXIT")
            stopped = run_cli(project, "run", "stop", "--run-id", run_id)
            self.assertEqual(json.loads(stopped.stdout)["status"], "STOPPED")

    def test_orchestrated_start_refuses_missing_or_unrestricted_parent_preflight(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            self.assertEqual(
                run_cli(
                    project, "project", "init", "--profile", "orchestrated"
                ).returncode,
                0,
            )
            configure_commands(project)
            base = (
                "run",
                "start",
                "--mode",
                "orchestrated",
                "--objective",
                "goal",
                "--acceptance-id",
                "AC-1",
                "--allowed-scope",
                "result.txt",
            )
            missing = run_cli(project, *base)
            self.assertNotEqual(missing.returncode, 0)
            unrestricted = run_cli(
                project, *base, "--parent-sandbox", "danger-full-access"
            )
            self.assertNotEqual(unrestricted.returncode, 0)
            allowed = run_cli(project, *base, "--parent-sandbox", "workspace-write")
            self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_orchestrated_cli_accepts_a_bounded_task_dag_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            self.assertEqual(
                run_cli(
                    project, "project", "init", "--profile", "orchestrated"
                ).returncode,
                0,
            )
            task_file = project / "tasks.json"
            command = [
                sys.executable,
                "-c",
                "from pathlib import Path; assert Path('result.txt').is_file()",
            ]
            task_file.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "T0001",
                                "objective": "first bounded task",
                                "kind": "feature",
                                "acceptance_ids": ["AC-1"],
                                "allowed_scope": ["result.txt"],
                                "pre_commands": [command],
                                "commands": [command],
                            },
                            {
                                "id": "T0002",
                                "objective": "dependent bounded task",
                                "kind": "feature",
                                "acceptance_ids": ["AC-2"],
                                "dependencies": ["T0001"],
                                "allowed_scope": ["result.txt"],
                                "pre_commands": [command],
                                "commands": [command],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            started = run_cli(
                project,
                "run",
                "start",
                "--mode",
                "orchestrated",
                "--objective",
                "bounded program",
                "--parent-sandbox",
                "workspace-write",
                "--task-file",
                str(task_file),
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            status = run_cli(
                project,
                "run",
                "status",
                "--run-id",
                json.loads(started.stdout)["run_id"],
            )
            self.assertEqual(
                [task["id"] for task in json.loads(status.stdout)["tasks"]],
                ["T0001", "T0002"],
            )

    def test_task_dag_rejects_non_executable_entries_before_run_creation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            self.assertEqual(
                run_cli(
                    project, "project", "init", "--profile", "orchestrated"
                ).returncode,
                0,
            )
            command = [
                sys.executable,
                "-c",
                "from pathlib import Path; assert Path('result.txt').is_file()",
            ]
            complete = {
                "id": "T0001",
                "objective": "bounded task",
                "kind": "feature",
                "acceptance_ids": ["AC-1"],
                "allowed_scope": ["result.txt"],
                "pre_commands": [command],
                "commands": [command],
            }
            task_file = project / "tasks.json"
            for missing in ("allowed_scope", "pre_commands", "commands"):
                task_file.write_text(
                    json.dumps(
                        {
                            "tasks": [
                                {
                                    key: value
                                    for key, value in complete.items()
                                    if key != missing
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                rejected = run_cli(
                    project,
                    "run",
                    "start",
                    "--mode",
                    "orchestrated",
                    "--objective",
                    "bounded program",
                    "--parent-sandbox",
                    "workspace-write",
                    "--task-file",
                    str(task_file),
                )
                self.assertNotEqual(rejected.returncode, 0, missing)
            mismatch = {**complete, "pre_commands": [[sys.executable, "-c", "pass"]]}
            task_file.write_text(json.dumps({"tasks": [mismatch]}), encoding="utf-8")
            rejected = run_cli(
                project,
                "run",
                "start",
                "--mode",
                "orchestrated",
                "--objective",
                "bounded program",
                "--parent-sandbox",
                "workspace-write",
                "--task-file",
                str(task_file),
            )
            self.assertNotEqual(rejected.returncode, 0)

    def test_gui_and_read_only_hub_have_nonblocking_validation_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            self.assertEqual(
                run_cli(project, "project", "init", "--profile", "solo").returncode, 0
            )
            gui = run_cli(project, "gui", "--check")
            self.assertEqual(gui.returncode, 0, gui.stderr)
            self.assertTrue(json.loads(gui.stdout)["ok"])
            hub = run_cli(project, "hub", "--check", "--project", str(project))
            self.assertEqual(hub.returncode, 0, hub.stderr)
            self.assertTrue(json.loads(hub.stdout)["read_only"])


if __name__ == "__main__":
    unittest.main()
