#!/usr/bin/env python3
"""Lightweight tests for update_job_status.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("update_job_status.py").resolve()


class UpdateJobStatusTests(unittest.TestCase):
    def write_status(self, root: Path) -> Path:
        path = root / "status.json"
        path.write_text(json.dumps({"id": "J0001", "state": "queued"}) + "\n", encoding="utf-8")
        return path

    def run_status(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_non_state_update_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = self.write_status(Path(tmp))
            result = self.run_status(str(status), "tests_passed=true")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(status.read_text(encoding="utf-8"))
            self.assertTrue(data["tests_passed"])
            self.assertEqual(data["state"], "queued")

    def test_state_update_requires_allow_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = self.write_status(Path(tmp))
            result = self.run_status(str(status), "state=running")
            self.assertEqual(result.returncode, 2)
            self.assertIn("refusing state update", result.stderr)
            data = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(data["state"], "queued")

    def test_allow_state_updates_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = self.write_status(Path(tmp))
            result = self.run_status("--allow-state", str(status), "state=running")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(data["state"], "running")

    def test_terminal_state_change_requires_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = self.write_status(Path(tmp))
            status.write_text(
                json.dumps({"id": "J0001", "state": "accepted"}) + "\n",
                encoding="utf-8",
            )
            result = self.run_status("--allow-state", str(status), "state=review_failed")
            self.assertEqual(result.returncode, 3)
            self.assertIn("refusing to change terminal state", result.stderr)
            data = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(data["state"], "accepted")

    def test_terminal_state_override_is_available_for_manual_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = self.write_status(Path(tmp))
            status.write_text(
                json.dumps({"id": "J0001", "state": "accepted"}) + "\n",
                encoding="utf-8",
            )
            result = self.run_status(
                "--allow-state",
                "--allow-terminal-state-overwrite",
                str(status),
                "state=review_failed",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(data["state"], "review_failed")

    def test_merge_status_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status = self.write_status(root)
            fields = root / "progress.json"
            fields.write_text(
                json.dumps(
                    {
                        "status_fields": {
                            "progress_job_type": "implementation",
                            "progress_metadata_only": False,
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = self.run_status(str(status), "--merge-status-fields", str(fields))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(data["progress_job_type"], "implementation")
            self.assertFalse(data["progress_metadata_only"])


if __name__ == "__main__":
    raise SystemExit(unittest.main())
