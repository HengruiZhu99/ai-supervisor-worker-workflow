from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts" / "check_job_progress_gate.py"


def progress_block(
    *,
    job_type: str,
    subsystem: str,
    metadata_only: bool,
    unlocks_next: str,
) -> str:
    validation = "schema" if metadata_only else "convergence"
    return f"""# bounded task

progress:
  job_type: {job_type}
  subsystem: {subsystem}
  capability_target: "Close acceptance AC-EXAMPLE-001 with executable evidence"
  new_executable_behavior: {str(not metadata_only).lower()}
  validation_class: {validation}
  unlocks_next: "{unlocks_next}"
  metadata_only: {str(metadata_only).lower()}
"""


class ProgressStarvationRegressionTests(unittest.TestCase):
    def run_gate(self, task: Path, jobs: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(GATE), str(task), "--jobs-dir", str(jobs), "--json"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def accepted_job(self, jobs: Path, job_id: str, subsystem: str) -> None:
        job = jobs / job_id
        job.mkdir(parents=True)
        (job / "status.json").write_text(
            json.dumps({"id": job_id, "state": "accepted"}), encoding="utf-8"
        )
        (job / "task.md").write_text(
            progress_block(
                job_type="metadata",
                subsystem=subsystem,
                metadata_only=True,
                unlocks_next="Implement the named acceptance target after this record",
            ),
            encoding="utf-8",
        )

    def test_area_changes_do_not_reset_no_delivery_debt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / ".ai" / "jobs"
            self.accepted_job(jobs, "J0001", "domain")
            self.accepted_job(jobs, "J0002", "backend")
            target = jobs / "J0003" / "task.md"
            target.parent.mkdir(parents=True)
            target.write_text(
                progress_block(
                    job_type="metadata",
                    subsystem="workflow",
                    metadata_only=True,
                    unlocks_next="Implement the named acceptance target after this record",
                ),
                encoding="utf-8",
            )
            result = self.run_gate(target, jobs)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("NO_ACCEPTANCE_DELTA", result.stdout)

    def test_fake_delivery_without_acceptance_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.md"
            task.write_text(
                progress_block(
                    job_type="implementation",
                    subsystem="other",
                    metadata_only=False,
                    unlocks_next="Claim completion based on the delivery label alone",
                ),
                encoding="utf-8",
            )
            result = self.run_gate(task, root / ".ai" / "jobs")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("acceptance evidence", result.stdout.lower())

    def test_enabler_requires_named_task_id_not_free_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.md"
            task.write_text(
                progress_block(
                    job_type="metadata",
                    subsystem="other",
                    metadata_only=True,
                    unlocks_next="Implement something valuable in a future worker job",
                ),
                encoding="utf-8",
            )
            result = self.run_gate(task, root / ".ai" / "jobs")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("unblocks_task_id", result.stdout)


if __name__ == "__main__":
    unittest.main()
