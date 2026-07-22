from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from aiflow.release.artifact import build_artifact, verify_artifact


ROOT = Path(__file__).resolve().parents[2]


class OfflineArtifactTests(unittest.TestCase):
    def test_zipapp_runs_offline_and_initializes_a_solo_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "dist"
            result = build_artifact(ROOT, destination)
            artifact = Path(result["artifact"])
            checksum = Path(result["checksum_file"])
            self.assertTrue(artifact.is_file())
            self.assertEqual(
                hashlib.sha256(artifact.read_bytes()).hexdigest(),
                checksum.read_text().split()[0],
            )
            self.assertTrue(verify_artifact(artifact)["ok"])
            with zipfile.ZipFile(artifact) as archive:
                names = archive.namelist()
            self.assertFalse(
                any(".git/" in name or "RUN.json" in name for name in names)
            )
            version = subprocess.run(
                [str(artifact), "--version"],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "PIP_NO_INDEX": "1"},
            )
            self.assertEqual(version.returncode, 0, version.stderr)
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            initialized = subprocess.run(
                [
                    str(artifact),
                    "--project-root",
                    str(project),
                    "project",
                    "init",
                    "--profile",
                    "solo",
                ],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "PIP_NO_INDEX": "1", "NO_PROXY": "*"},
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            verified = subprocess.run(
                [str(artifact), "--project-root", str(project), "project", "verify"],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "PIP_NO_INDEX": "1", "NO_PROXY": "*"},
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertTrue(json.loads(verified.stdout)["ok"])

    def test_cli_exposes_build_and_verify_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            built = subprocess.run(
                [
                    str(ROOT / "bin" / "aiflow"),
                    "package",
                    "build",
                    "--distribution-root",
                    str(ROOT),
                    "--output-dir",
                    tmp,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            artifact = json.loads(built.stdout)["artifact"]
            verified = subprocess.run(
                [str(ROOT / "bin" / "aiflow"), "package", "verify", artifact],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertTrue(json.loads(verified.stdout)["ok"])

    def test_archive_manifest_refuses_tampering_or_forbidden_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = build_artifact(ROOT, Path(tmp))
            artifact = Path(result["artifact"])
            artifact.write_bytes(artifact.read_bytes() + b"tamper")
            self.assertFalse(verify_artifact(artifact)["ok"])


if __name__ == "__main__":
    unittest.main()
