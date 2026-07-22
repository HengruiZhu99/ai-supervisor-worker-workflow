from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("fixtures") / "athenak_like"
CLI = ROOT / "bin" / "aiflow"


def run(args: list[str], cwd: Path, env=None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )


class SoloCppAcceptanceTests(unittest.TestCase):
    def test_existing_cmake_project_runs_red_green_quality_and_durable_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "athenak-like"
            shutil.copytree(FIXTURE, project)
            run(["git", "init", "-q"], project)
            environment = dict(os.environ)
            environment["XDG_RUNTIME_DIR"] = str(base / "runtime")
            initialized = run(
                [str(CLI), "--project-root", str(project), "project", "init", "--profile", "solo"],
                ROOT,
                environment,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            started = run(
                [
                    str(CLI), "--project-root", str(project), "run", "start", "--mode", "solo",
                    "--objective", "Correct the vector L2 norm", "--acceptance-id", "AC-NORM-001",
                ],
                ROOT,
                environment,
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            run_id = json.loads(started.stdout)["run_id"]

            build = project / "build"
            configured = run(["cmake", "-S", ".", "-B", str(build)], project)
            self.assertEqual(configured.returncode, 0, configured.stderr)
            self.assertEqual(
                run(["cmake", "--build", str(build), "--clean-first"], project).returncode,
                0,
            )
            red = run(["ctest", "--test-dir", str(build), "--output-on-failure"], project)
            self.assertNotEqual(red.returncode, 0, "fixture must prove the intended RED result")

            header = project / "include" / "vector_norm.hpp"
            header.write_text(
                header.read_text().replace(
                    "return squared;  // Intentional RED fixture defect; the acceptance test corrects it.",
                    "return std::sqrt(squared);",
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                run(["cmake", "--build", str(build), "--clean-first"], project).returncode,
                0,
            )
            green = run(["ctest", "--test-dir", str(build), "--output-on-failure"], project)
            self.assertEqual(green.returncode, 0, green.stdout + green.stderr)
            quality = run(
                [str(CLI), "--project-root", str(project), "quality", "check"], ROOT, environment
            )
            self.assertEqual(quality.returncode, 0, quality.stdout + quality.stderr)
            stopped = run(
                [
                    str(CLI), "--project-root", str(project), "run", "stop", "--run-id", run_id,
                ],
                ROOT,
                environment,
            )
            self.assertEqual(json.loads(stopped.stdout)["status"], "STOPPED")


if __name__ == "__main__":
    unittest.main()
