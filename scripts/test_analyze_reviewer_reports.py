#!/usr/bin/env python3
"""Lightweight tests for analyze_reviewer_reports.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("analyze_reviewer_reports.py").resolve()


def report(*, progress_blocks: bool = False, include_progress: bool = True) -> str:
    progress = ""
    if include_progress:
        progress = f"""progress_review:
  adds_executable_or_validation_value: true
  metadata_unlock_is_credible: true
  continues_metadata_streak: false
  blocks_acceptance: {str(progress_blocks).lower()}
  blocking_reasons: []
"""
    return f"""# Review

```yaml
diff_coverage:
  full_diff_reviewed: true
  files_reviewed:
    - src/example.cpp
  unreviewed_files: []
review_decision:
  recommendation: accept
  blocks_acceptance: false
  blocking_reasons: []
{progress}```
"""


class AnalyzeReviewerReportsTests(unittest.TestCase):
    def run_analyzer(self, root: Path, a_text: str, b_text: str) -> subprocess.CompletedProcess[str]:
        a_path = root / "reviewer-a.md"
        b_path = root / "reviewer-b.md"
        out = root / "decisions.json"
        a_path.write_text(a_text, encoding="utf-8")
        b_path.write_text(b_text, encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--reviewer-a",
                str(a_path),
                "--reviewer-b",
                str(b_path),
                "--output",
                str(out),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_accepts_when_progress_review_present_and_nonblocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.run_analyzer(root, report(), report())
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads((root / "decisions.json").read_text(encoding="utf-8"))
            self.assertFalse(payload["reviewer_a_blocks"])
            self.assertFalse(payload["reviewer_a_progress_blocks"])

    def test_blocks_when_progress_review_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.run_analyzer(root, report(progress_blocks=True), report())
            self.assertEqual(result.returncode, 1)
            payload = json.loads((root / "decisions.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["reviewer_a_blocks"])
            self.assertTrue(payload["reviewer_a_progress_blocks"])
            self.assertEqual(payload["blocked_by"], ["reviewer-a"])

    def test_missing_progress_review_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.run_analyzer(root, report(include_progress=False), report())
            self.assertEqual(result.returncode, 1)
            payload = json.loads((root / "decisions.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["reviewer_a_blocks"])
            self.assertIn("missing progress_review YAML block", "\n".join(payload["errors"]))

    def test_echoed_template_before_real_block_is_ignored(self) -> None:
        # The echoed reviewer prompt template uses the placeholder path
        # `path/from/changed_files`; it must not be selected over the real block.
        template = """```yaml
diff_coverage:
  full_diff_reviewed: true
  files_reviewed:
    - path/from/changed_files
  unreviewed_files: []
review_decision:
  recommendation: accept
  blocks_acceptance: false
  blocking_reasons: []
progress_review:
  adds_executable_or_validation_value: true
  metadata_unlock_is_credible: true
  continues_metadata_streak: false
  blocks_acceptance: false
  blocking_reasons: []
```
"""
        a_text = "Prompt template was:\n" + template + "\nMy actual review:\n" + report(progress_blocks=True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.run_analyzer(root, a_text, report())
            # The real (last, non-template) block blocks acceptance, so the
            # echoed accepting template must NOT mask it.
            self.assertEqual(result.returncode, 1)
            payload = json.loads((root / "decisions.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["reviewer_a_blocks"])


if __name__ == "__main__":
    raise SystemExit(unittest.main())
