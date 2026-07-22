from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.skills.installer import InstallError, ProjectInstaller, profile_skills  # noqa: E402


def init_git(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


class ProjectLifecycleTests(unittest.TestCase):
    def test_profile_graph_is_explicit_and_does_not_install_every_skill(self) -> None:
        solo = profile_skills("solo")
        science = profile_skills("science")
        full = profile_skills("full")
        self.assertEqual(solo[0], "tdd-solo")
        self.assertIn("scientific-code-review", science)
        self.assertNotIn("aiflow-autonomous", science)
        self.assertIn("aiflow-autonomous", full)
        self.assertGreater(len(full), len(science))
        with self.assertRaises(InstallError):
            profile_skills("unknown")

    def test_init_is_idempotent_and_lock_contains_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            init_git(project)
            installer = ProjectInstaller(project, distribution_root=ROOT)
            first = installer.init("solo")
            second = installer.init("solo")
            self.assertEqual(first, second)
            lock = json.loads((project / ".aiflow" / "project.lock").read_text())
            self.assertEqual(lock["profile"], "solo")
            self.assertEqual(lock["installation_mode"], "vendor")
            self.assertIn(".aiflow/project.toml", lock["managed_files"])
            self.assertIn(".agents/skills/tdd-solo/SKILL.md", lock["managed_files"])
            self.assertTrue(installer.verify()["ok"])

    def test_verify_detects_drift_and_uninstall_preserves_modified_managed_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            init_git(project)
            installer = ProjectInstaller(project, distribution_root=ROOT)
            installer.init("solo")
            skill = project / ".agents" / "skills" / "tdd-solo" / "SKILL.md"
            skill.write_text(skill.read_text() + "\nuser-owned note\n", encoding="utf-8")
            status = installer.verify()
            self.assertFalse(status["ok"])
            self.assertIn(".agents/skills/tdd-solo/SKILL.md", status["modified"])
            result = installer.uninstall()
            self.assertIn(".agents/skills/tdd-solo/SKILL.md", result["preserved_modified"])
            self.assertTrue(skill.is_file())
            self.assertFalse((project / ".aiflow" / "quality.toml").exists())

    def test_upgrade_and_rollback_are_transactional_and_backup_aware(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            init_git(project)
            installer = ProjectInstaller(project, distribution_root=ROOT)
            installer.init("solo")
            before = (project / ".aiflow" / "project.lock").read_text()
            upgrade = installer.upgrade("science")
            self.assertEqual(upgrade["profile"], "science")
            self.assertTrue(Path(upgrade["backup"]).is_dir())
            installer.rollback(upgrade["transaction_id"])
            self.assertEqual((project / ".aiflow" / "project.lock").read_text(), before)
            self.assertTrue(installer.verify()["ok"])

    def test_link_mode_requires_immutable_source_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            init_git(project)
            installer = ProjectInstaller(project, distribution_root=ROOT)
            with self.assertRaises(InstallError):
                installer.init("solo", installation_mode="link")

    def test_every_profile_installs_and_verifies_only_its_selected_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for profile in ("solo", "science", "hpc", "orchestrated", "full"):
                project = base / profile
                init_git(project)
                installer = ProjectInstaller(project, distribution_root=ROOT)
                installer.init(profile)
                self.assertTrue(installer.verify()["ok"])
                installed = {
                    path.name
                    for path in (project / ".agents" / "skills").iterdir()
                    if path.is_dir()
                }
                self.assertEqual(installed, set(profile_skills(profile)))
                lock = json.loads((project / ".aiflow" / "project.lock").read_text())
                if profile in {"orchestrated", "full"}:
                    self.assertEqual(len(lock["custom_agent_hashes"]), 9)
                    self.assertTrue((project / ".codex" / "config.toml").is_file())
                else:
                    self.assertEqual(lock["custom_agent_hashes"], {})
                    self.assertFalse((project / ".codex").exists())


if __name__ == "__main__":
    unittest.main()
