from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UPDATE = ROOT / "scripts" / "update_job_status.py"


class StateConcurrencyRegressionTests(unittest.TestCase):
    def test_mutation_without_expected_revision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / "status.json"
            original = {"state_revision": 7, "value": "current"}
            status.write_text(json.dumps(original), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(UPDATE), str(status), "value=stale-write"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(json.loads(status.read_text(encoding="utf-8")), original)

    def test_stale_expected_revision_reports_cas_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / "status.json"
            status.write_text(
                json.dumps({"state_revision": 7, "value": "current"}), encoding="utf-8"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(UPDATE),
                    "--expected-revision",
                    "6",
                    str(status),
                    "value=stale-write",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stale revision", (result.stdout + result.stderr).lower())

    def test_single_writer_state_engine_exists(self) -> None:
        engine = ROOT / "src" / "aiflow" / "state" / "store.py"
        self.assertTrue(
            engine.exists(),
            "single-writer state engine with leases/intents/recovery is missing",
        )


if __name__ == "__main__":
    unittest.main()
