from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.release.artifact import build_artifact, verify_artifact  # noqa: E402
from aiflow.skills.installer import InstallError, ProjectInstaller  # noqa: E402
import aiflow.skills.installer as installer_module  # noqa: E402


def project(path: Path) -> ProjectInstaller:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return ProjectInstaller(path, distribution_root=ROOT)


class InstallerArtifactAuditRegressionTests(unittest.TestCase):
    def test_init_refuses_to_overwrite_preexisting_unowned_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            installer = project(root)
            target = root / ".agents" / "skills" / "tdd-solo" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("user-owned\n", encoding="utf-8")
            with self.assertRaises(InstallError):
                installer.init("solo")
            self.assertEqual(target.read_text(encoding="utf-8"), "user-owned\n")

    def test_failed_init_rolls_back_every_written_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            installer = project(root)
            original = installer_module._atomic_bytes
            calls = 0

            def fail_third(path: Path, content: bytes) -> None:
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("injected write failure")
                original(path, content)

            with mock.patch.object(
                installer_module, "_atomic_bytes", side_effect=fail_third
            ):
                with self.assertRaises(OSError):
                    installer.init("solo")
            self.assertFalse((root / ".aiflow" / "project.lock").exists())
            self.assertFalse((root / ".agents").exists())
            self.assertFalse((root / ".aiflow" / "project.toml").exists())

    def test_profile_downgrade_removes_only_unchanged_old_profile_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            installer = project(root)
            installer.init("full")
            old_only = root / ".agents" / "skills" / "release-readiness" / "SKILL.md"
            self.assertTrue(old_only.exists())
            installer.upgrade("solo")
            self.assertFalse(old_only.exists())
            self.assertTrue(
                (root / ".agents" / "skills" / "tdd-solo" / "SKILL.md").exists()
            )

    def test_project_command_customization_survives_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            installer = project(root)
            installer.init("solo")
            config = root / ".aiflow" / "project.toml"
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "test_focused = []",
                    'test_focused = ["ctest", "--output-on-failure"]',
                ),
                encoding="utf-8",
            )
            installer.upgrade("science")
            self.assertIn(
                'test_focused = ["ctest", "--output-on-failure"]', config.read_text()
            )

    def test_rollback_refuses_post_upgrade_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            installer = project(root)
            installer.init("solo")
            upgraded = installer.upgrade("full")
            changed = root / ".agents" / "skills" / "release-readiness" / "SKILL.md"
            changed.write_text(changed.read_text() + "\nuser edit\n", encoding="utf-8")
            with self.assertRaises(InstallError):
                installer.rollback(upgraded["transaction_id"])
            self.assertIn("user edit", changed.read_text())

    def test_verifier_rejects_unmanifested_and_traversal_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(build_artifact(ROOT, Path(tmp))["artifact"])
            with zipfile.ZipFile(artifact, "a") as archive:
                archive.writestr("unmanifested.txt", "not declared")
                archive.writestr("../traversal.txt", "unsafe")
            checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
            artifact.with_suffix(artifact.suffix + ".sha256").write_text(
                f"{checksum}  {artifact.name}\n", encoding="utf-8"
            )
            result = verify_artifact(artifact)
            self.assertFalse(result["ok"])
            self.assertTrue(any("unmanifested" in error for error in result["errors"]))
            self.assertTrue(
                any("unsafe archive path" in error for error in result["errors"])
            )

    def test_builder_rejects_source_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            distribution = base / "distribution"
            for relative in ("src/aiflow", ".agents", ".codex"):
                shutil.copytree(ROOT / relative, distribution / relative)
            external = base / "outside-secret.txt"
            external.write_text("outside", encoding="utf-8")
            link = distribution / ".agents" / "skills" / "tdd-solo" / "escape.txt"
            link.symlink_to(external)
            with self.assertRaises(ValueError):
                build_artifact(distribution, base / "dist")


if __name__ == "__main__":
    unittest.main()
