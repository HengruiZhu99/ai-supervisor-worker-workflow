#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Lightweight tests for check_reviewer_coverage.py robustness.

These pin the historically-fragile behaviors (workflow_improvement_queue
WFI-0001/WFI-0002): a tokenized/malformed fragment or an echoed prompt template
before the final valid block must not fail an otherwise-complete review.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("check_reviewer_coverage.py").resolve()

CHANGED = "M\tsrc/a.cpp\nM\tsrc/b.cpp\n"


def coverage_block(files: list[str], *, full: bool = True, unreviewed: list[str] | None = None) -> str:
    files_yaml = "\n".join(f"    - {path}" for path in files) or "    []"
    if not files:
        files_block = "  files_reviewed: []"
    else:
        files_block = "  files_reviewed:\n" + files_yaml
    unreviewed = unreviewed or []
    unreviewed_block = (
        "  unreviewed_files: []"
        if not unreviewed
        else "  unreviewed_files:\n" + "\n".join(f"    - {p}" for p in unreviewed)
    )
    return (
        "```yaml\n"
        "diff_coverage:\n"
        f"  full_diff_reviewed: {str(full).lower()}\n"
        f"{files_block}\n"
        f"{unreviewed_block}\n"
        "review_decision:\n"
        "  recommendation: accept\n"
        "  blocks_acceptance: false\n"
        "  blocking_reasons: []\n"
        "```\n"
    )


# The echoed reviewer prompt template (placeholder paths) must be ignored.
TEMPLATE = (
    "```yaml\n"
    "diff_coverage:\n"
    "  full_diff_reviewed: true\n"
    "  files_reviewed:\n"
    "    - path/from/changed_files\n"
    "  unreviewed_files: []\n"
    "review_decision:\n"
    "  recommendation: accept\n"
    "  blocks_acceptance: false\n"
    "  blocking_reasons: []\n"
    "```\n"
)


class CheckReviewerCoverageTests(unittest.TestCase):
    def run_check(self, *reports: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changed = root / "changed.txt"
            changed.write_text(CHANGED, encoding="utf-8")
            paths = []
            for i, text in enumerate(reports):
                p = root / f"reviewer-{i}.md"
                p.write_text(text, encoding="utf-8")
                paths.append(str(p))
            return subprocess.run(
                [sys.executable, str(SCRIPT), str(changed), *paths],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )

    def test_complete_coverage_passes(self) -> None:
        report = "# Review\n\n" + coverage_block(["src/a.cpp", "src/b.cpp"])
        result = self.run_check(report)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_echoed_template_before_real_block_is_ignored(self) -> None:
        # WFI-0001/0002: the echoed template must not be selected as the block.
        report = "Prompt was:\n" + TEMPLATE + "\nActual review:\n" + coverage_block(["src/a.cpp", "src/b.cpp"])
        result = self.run_check(report)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_tokenized_fragment_before_valid_block_is_ignored(self) -> None:
        noise = "```yaml\ndiff_cov er age:\n  full_dif f: tru\n```\n"
        report = noise + coverage_block(["src/a.cpp", "src/b.cpp"])
        result = self.run_check(report)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_file_fails(self) -> None:
        report = coverage_block(["src/a.cpp"])  # omits src/b.cpp
        result = self.run_check(report)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing reviewed files", result.stdout)

    def test_unreviewed_nonempty_fails(self) -> None:
        report = coverage_block(["src/a.cpp", "src/b.cpp"], unreviewed=["src/b.cpp"])
        result = self.run_check(report)
        self.assertEqual(result.returncode, 1)
        self.assertIn("unreviewed_files is not empty", result.stdout)

    def test_only_template_block_fails_as_missing(self) -> None:
        # A report that contains ONLY the echoed template has no real coverage.
        result = self.run_check("Prompt:\n" + TEMPLATE)
        self.assertEqual(result.returncode, 1)

    def test_missing_block_fails(self) -> None:
        result = self.run_check("# Review\n\nLooks fine to me.\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing diff_coverage block", result.stdout)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
