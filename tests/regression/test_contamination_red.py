from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


class ProjectContaminationRegressionTests(unittest.TestCase):
    def test_inherited_project_a_environment_cannot_redirect_project_b(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        try:
            sys.modules.pop("aiflow", None)
            module = importlib.import_module("aiflow")
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                project_a = base / "project-a"
                project_b = base / "project-b"
                for project in (project_a, project_b):
                    project.mkdir()
                    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
                with (
                    mock.patch.dict(
                        os.environ, {"AIFLOW_PROJECT_ROOT": str(project_a)}, clear=False
                    ),
                    mock.patch.object(Path, "cwd", return_value=project_b),
                ):
                    with mock.patch.object(module.subprocess, "run") as run:
                        run.return_value = subprocess.CompletedProcess(
                            [], 0, stdout=f"{project_b}\n", stderr=""
                        )
                        resolved = module.git_root()
                self.assertEqual(resolved, project_b.resolve())
        finally:
            sys.path.remove(str(SCRIPTS))
            sys.modules.pop("aiflow", None)

    def test_generic_entrypoints_contain_no_project_or_host_tokens(self) -> None:
        targets = [
            SCRIPTS / "aiflow.py",
            SCRIPTS / "agent_wrapper.py",
            SCRIPTS / "worker_loop.sh",
        ]
        forbidden = ("BBHK", "oneAPI", "sycl-intel-b580", "/Users/")
        findings: list[str] = []
        for path in targets:
            text = path.read_text(encoding="utf-8")
            findings.extend(
                f"{path.name}: {token}" for token in forbidden if token in text
            )
        self.assertEqual(
            findings, [], "generic-core contamination: " + ", ".join(findings)
        )


if __name__ == "__main__":
    unittest.main()
