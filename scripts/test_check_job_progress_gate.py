#!/usr/bin/env python3
"""Lightweight tests for check_job_progress_gate.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("check_job_progress_gate.py").resolve()


def progress_block(
    *,
    job_type: str = "implementation",
    subsystem: str = "operators",
    capability_target: str = "Chebyshev derivative runtime operator",
    new_executable_behavior: str = "true",
    validation_class: str = "convergence",
    unlocks_next: str = "Run the Chebyshev derivative convergence backend test job",
    metadata_only: str = "false",
) -> str:
    return f"""# Job J0001: Example

## Progress Classification

```yaml
progress:
  job_type: {job_type}
  subsystem: {subsystem}
  capability_target: "{capability_target}"
  new_executable_behavior: {new_executable_behavior}
  validation_class: {validation_class}
  unlocks_next: "{unlocks_next}"
  metadata_only: {metadata_only}
```
"""


def upstream_trace() -> str:
    return """
## Upstream Trace

- Failing milestone/gate: M32 real single-BH GH stationarity gate.
- Measured symptom: Edge/corner interpatch growth reaches nonfinite state before the required run time.
- Suspected upstream cause: Current strong-form collocation boundary coupling lacks a discrete energy estimate at multi-face intersections.
- Public reference or derivation source: Public SpECTRE GH upwind penalty documentation and a project SBP-SAT derivation.
- Algorithmic decision or implementation change expected: Select the two-sided characteristic penalty structure for the next implementation slice.
- Validation close/falsify criterion: Linear wave and GH interface tests reduce the edge/corner growth while preserving face-interior behavior.
- Why this is not peripheral cleanup: The task directly chooses the boundary algorithm blocking M32 closure.
"""


class ProgressGateTests(unittest.TestCase):
    def run_gate(self, task: Path, jobs_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(task), "--jobs-dir", str(jobs_dir)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def write_job(
        self,
        root: Path,
        job_id: str,
        *,
        state: str = "accepted",
        task_text: str | None = None,
        title: str = "metadata job",
    ) -> Path:
        job_dir = root / ".ai" / "jobs" / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "status.json").write_text(
            json.dumps({"id": job_id, "state": state, "title": title}) + "\n",
            encoding="utf-8",
        )
        if task_text is not None:
            (job_dir / "task.md").write_text(task_text, encoding="utf-8")
        return job_dir

    def test_valid_implementation_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / ".ai" / "jobs"
            task = root / "task.md"
            task.write_text(progress_block(), encoding="utf-8")
            result = self.run_gate(task, jobs_dir)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_metadata_with_concrete_unlock_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / ".ai" / "jobs"
            task = root / "task.md"
            task.write_text(
                progress_block(
                    job_type="metadata",
                    subsystem="domain",
                    capability_target="BBH domain interface manifest",
                    new_executable_behavior="false",
                    validation_class="schema",
                    unlocks_next="Implement the BBH domain construction test from this manifest",
                    metadata_only="true",
                ),
                encoding="utf-8",
            )
            result = self.run_gate(task, jobs_dir)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_metadata_without_unlock_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / ".ai" / "jobs"
            task = root / "task.md"
            task.write_text(
                progress_block(
                    job_type="metadata",
                    subsystem="domain",
                    capability_target="BBH domain interface manifest",
                    new_executable_behavior="false",
                    validation_class="schema",
                    unlocks_next="future work",
                    metadata_only="true",
                ),
                encoding="utf-8",
            )
            result = self.run_gate(task, jobs_dir)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unlocks_next", result.stdout)

    def test_implementation_with_no_validation_class_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / ".ai" / "jobs"
            task = root / "task.md"
            task.write_text(progress_block(validation_class="none"), encoding="utf-8")
            result = self.run_gate(task, jobs_dir)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("implementation jobs must not use validation_class=none", result.stdout)

    def test_numerical_test_requires_identity_or_convergence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / ".ai" / "jobs"
            task = root / "task.md"
            task.write_text(
                progress_block(
                    job_type="numerical_test",
                    capability_target="Chebyshev derivative identity test",
                    validation_class="schema",
                    unlocks_next="Use the identity test as the operator validation gate",
                ),
                encoding="utf-8",
            )
            result = self.run_gate(task, jobs_dir)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("numerical_test jobs must use validation_class identity or convergence", result.stdout)

    def test_backend_test_requires_backend_validation_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / ".ai" / "jobs"
            task = root / "task.md"
            task.write_text(
                progress_block(
                    job_type="backend_test",
                    subsystem="backend",
                    capability_target="Kokkos backend parity test",
                    validation_class="convergence",
                    unlocks_next="Run the backend matrix parity validation job",
                ),
                encoding="utf-8",
            )
            result = self.run_gate(task, jobs_dir)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("backend_test jobs must use validation_class backend_matrix or mpi_device", result.stdout)

    def test_metadata_validation_exception_requires_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / ".ai" / "jobs"
            task = root / "task.md"
            text = progress_block(
                job_type="metadata",
                subsystem="domain",
                capability_target="BBH domain interface manifest",
                new_executable_behavior="false",
                validation_class="identity",
                unlocks_next="Implement the BBH domain construction test from this manifest",
                metadata_only="true",
            ).replace(
                "  metadata_only: true\n",
                "  metadata_only: true\n  progress_exception_type: human_approved_planning_source\n",
            )
            task.write_text(text, encoding="utf-8")
            result = self.run_gate(task, jobs_dir)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("progress_exception_record is required", result.stdout)

    def test_json_output_contains_status_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / ".ai" / "jobs"
            task = root / "task.md"
            task.write_text(progress_block(), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(task), "--jobs-dir", str(jobs_dir), "--json"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status_fields"]["progress_job_type"], "implementation")

    def test_missing_progress_block_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / ".ai" / "jobs"
            task = root / "task.md"
            task.write_text("# Job J0001: Missing progress\n", encoding="utf-8")
            result = self.run_gate(task, jobs_dir)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing required progress", result.stdout)

    def test_three_consecutive_metadata_jobs_for_same_subsystem_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / ".ai" / "jobs"
            previous = progress_block(
                job_type="metadata",
                subsystem="domain",
                capability_target="BBH domain metadata fixture",
                new_executable_behavior="false",
                validation_class="schema",
                unlocks_next="Implement the BBH runtime domain construction test",
                metadata_only="true",
            )
            self.write_job(root, "J0001", task_text=previous, title="domain metadata")
            self.write_job(root, "J0002", task_text=previous, title="domain metadata")
            target_dir = root / ".ai" / "jobs" / "J0003"
            target_dir.mkdir(parents=True)
            target = target_dir / "task.md"
            target.write_text(previous, encoding="utf-8")
            result = self.run_gate(target, jobs_dir)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("streak limit exceeded", result.stdout)

    def write_priority_lock(self, root: Path, *, active_after: str = "J0002") -> None:
        lock = root / ".ai" / "supervisor" / "ROOT_CAUSE_PRIORITY_LOCK.md"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(
            "# Root-Cause Priority Lock\n\n"
            f"active_after_job: {active_after}\n",
            encoding="utf-8",
        )

    def test_priority_lock_requires_upstream_trace_for_new_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / ".ai" / "jobs"
            self.write_priority_lock(root, active_after="J0002")
            target_dir = jobs_dir / "J0003"
            target_dir.mkdir(parents=True)
            task = target_dir / "task.md"
            task.write_text(progress_block(), encoding="utf-8")
            result = self.run_gate(task, jobs_dir)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Upstream Trace", result.stdout)

    def test_priority_lock_accepts_concrete_upstream_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / ".ai" / "jobs"
            self.write_priority_lock(root, active_after="J0002")
            target_dir = jobs_dir / "J0003"
            target_dir.mkdir(parents=True)
            task = target_dir / "task.md"
            task.write_text(progress_block() + upstream_trace(), encoding="utf-8")
            result = self.run_gate(task, jobs_dir)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_priority_lock_does_not_block_exempt_active_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / ".ai" / "jobs"
            self.write_priority_lock(root, active_after="J0003")
            target_dir = jobs_dir / "J0003"
            target_dir.mkdir(parents=True)
            task = target_dir / "task.md"
            task.write_text(progress_block(), encoding="utf-8")
            result = self.run_gate(task, jobs_dir)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
