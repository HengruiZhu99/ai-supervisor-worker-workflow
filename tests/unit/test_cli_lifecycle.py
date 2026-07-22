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


if __name__ == "__main__":
    unittest.main()
