from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class FiniteExecutionRegressionTests(unittest.TestCase):
    def test_legacy_loops_are_finite_shims(self) -> None:
        findings: list[str] = []
        for name in ("worker_loop.sh", "supervisor_loop.sh", "modulator_loop.sh"):
            path = ROOT / "scripts" / name
            text = path.read_text(encoding="utf-8")
            if re.search(r"\bwhile\s+true\b", text):
                findings.append(f"{name}: permanent while true")
            logical = [
                line for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            if len(logical) > 160:
                findings.append(f"{name}: {len(logical)} logical lines")
        self.assertEqual(findings, [], "; ".join(findings))

    def test_worker_and_test_timeout_defaults_are_finite(self) -> None:
        text = (ROOT / "scripts" / "worker_loop.sh").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"WORKER_TIMEOUT=.*:-0")
        self.assertNotRegex(text, r"TEST_TIMEOUT=.*:-0")

    def test_finite_controller_module_exists(self) -> None:
        controller = ROOT / "src" / "aiflow" / "controller" / "runner.py"
        self.assertTrue(
            controller.exists(),
            "finite controller/idle watchdog is missing; legacy loops poll forever",
        )


if __name__ == "__main__":
    unittest.main()
