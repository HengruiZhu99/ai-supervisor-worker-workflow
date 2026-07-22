from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from aiflow.skills.installer import ProjectInstaller


ROOT = Path(__file__).resolve().parents[2]


class HpcProfileTests(unittest.TestCase):
    def test_hpc_profile_is_read_only_and_site_portable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            ProjectInstaller(project, distribution_root=ROOT).init("hpc")
            site = (project / ".aiflow" / "site.toml").read_text()
            self.assertIn("monitor_read_only = true", site)
            self.assertIn("min_poll_seconds = 5", site)
            self.assertIn('setup_script = ""', site)
            for cluster_specific in ("/lustre", "/gpfs", "/scratch", "nersc", "frontier"):
                self.assertNotIn(cluster_specific, site.lower())


if __name__ == "__main__":
    unittest.main()
