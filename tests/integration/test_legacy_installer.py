from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class LegacyInstallerTests(unittest.TestCase):
    def test_installer_delegates_to_transactional_profile_without_copying_runtime(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            result = subprocess.run(
                [str(ROOT / "install.sh"), str(project)],
                cwd=ROOT,
                env={**os.environ, "AIFLOW_PROFILE": "solo"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["profile"], "solo")
            self.assertTrue((project / ".aiflow" / "project.lock").is_file())
            self.assertFalse((project / "scripts" / "worker_loop.sh").exists())


if __name__ == "__main__":
    unittest.main()
