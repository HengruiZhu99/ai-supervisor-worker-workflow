#!/usr/bin/env python3
"""Lightweight tests for summarize_progress_accounting.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("summarize_progress_accounting.py").resolve()


def write_job(
    jobs_dir: Path,
    job_id: str,
    *,
    job_type: str,
    metadata_only: bool,
    new_executable: bool,
    exception_type: str = "none",
    exception_record: str = "",
) -> None:
    job = jobs_dir / job_id
    job.mkdir(parents=True)
    status = {
        "id": job_id,
        "title": f"{job_type} job",
        "state": "accepted",
        "progress_job_type": job_type,
        "progress_subsystem": "workflow",
        "progress_validation_class": "schema" if metadata_only else "convergence",
        "progress_metadata_only": metadata_only,
        "progress_new_executable_behavior": new_executable,
        "progress_capability_target": f"{job_type} target",
        "progress_unlocks_next": "Run the named implementation or validation job",
        "progress_exception_type": exception_type,
        "progress_exception_record": exception_record,
    }
    (job / "status.json").write_text(json.dumps(status) + "\n", encoding="utf-8")


class SummarizeProgressAccountingTests(unittest.TestCase):
    def run_summary(self, jobs_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--jobs-dir", str(jobs_dir), *extra],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_mixed_progress_passes_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / ".ai" / "jobs"
            write_job(jobs_dir, "J0001", job_type="metadata", metadata_only=True, new_executable=False)
            write_job(jobs_dir, "J0002", job_type="implementation", metadata_only=False, new_executable=True)
            result = self.run_summary(jobs_dir, "--strict", "--json")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["counts"]["implementation"], 1)
            self.assertFalse(payload["warnings"])

    def test_metadata_only_without_exception_fails_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / ".ai" / "jobs"
            write_job(jobs_dir, "J0001", job_type="metadata", metadata_only=True, new_executable=False)
            result = self.run_summary(jobs_dir, "--strict", "--json")
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["counts"]["metadata_like"], 1)
            self.assertTrue(payload["warnings"])

    def test_metadata_only_with_exception_passes_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / ".ai" / "jobs"
            write_job(
                jobs_dir,
                "J0001",
                job_type="planning",
                metadata_only=True,
                new_executable=False,
                exception_type="human_approved_planning_source",
                exception_record=".ai/supervisor/human_reviews/human_review_20260603T000000Z.md",
            )
            result = self.run_summary(jobs_dir, "--strict", "--json")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["counts"]["exceptions"], 1)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
