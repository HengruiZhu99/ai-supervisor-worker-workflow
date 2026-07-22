from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.integration.transaction import GateCommands, IntegrationTransaction  # noqa: E402
from aiflow.quality.checker import QualityChecker  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=True,
    ).stdout.strip()


class QualityIntegrationAuditRegressionTests(unittest.TestCase):
    def test_untracked_source_is_included_in_diff_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "audit@example.invalid")
            git(root, "config", "user.name", "Audit")
            (root / ".aiflow").mkdir()
            (root / ".aiflow" / "quality.toml").write_text(
                "[diff]\nsoft_source_files=1\nsoft_logical_lines=1\nhard_multiplier=1\n",
                encoding="utf-8",
            )
            (root / "seed.txt").write_text("seed\n", encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-qm", "seed")
            (root / "new_source.py").write_text("one = 1\ntwo = 2\n", encoding="utf-8")
            result = QualityChecker(root).check()
            self.assertFalse(result["ok"])
            self.assertTrue(any("diff hard budget" in error for error in result["errors"]))

    def test_layer_violation_and_dependency_cycle_fail_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".aiflow").mkdir()
            (root / ".aiflow" / "quality.toml").write_text("schema_version=1\n", encoding="utf-8")
            (root / ".aiflow" / "deprecations.toml").write_text("schema_version=1\n", encoding="utf-8")
            domain = root / "src" / "aiflow" / "domain"
            api = root / "src" / "aiflow" / "api"
            domain.mkdir(parents=True)
            api.mkdir(parents=True)
            (domain / "rules.py").write_text("from aiflow.api.server import serve\n", encoding="utf-8")
            (api / "server.py").write_text("from aiflow.domain.rules import rule\n", encoding="utf-8")
            result = QualityChecker(root).check()
            self.assertFalse(result["ok"])
            self.assertTrue(any("layer violation" in error for error in result["errors"]))
            self.assertTrue(any("dependency cycle" in error for error in result["errors"]))

    def test_declared_compatibility_test_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".aiflow").mkdir()
            (root / ".aiflow" / "quality.toml").write_text("schema_version=1\n", encoding="utf-8")
            (root / ".aiflow" / "deprecations.toml").write_text(
                """schema_version=1
[[deprecation]]
id="D1"
symbol_or_path="legacy.sh"
replacement="new"
introduced_version="1"
removal_version="2"
removal_deadline="2099-01-01"
owner="team"
compat_tests=["tests/missing_test.py"]
remaining_call_sites=0
""",
                encoding="utf-8",
            )
            result = QualityChecker(root).check()
            self.assertFalse(result["ok"])
            self.assertTrue(any("compatibility test missing" in error for error in result["errors"]))

    def test_integration_records_and_verifies_the_exact_tested_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            git(root, "init", "-q", "-b", "main")
            git(root, "config", "user.email", "audit@example.invalid")
            git(root, "config", "user.name", "Audit")
            (root / "base.txt").write_text("base\n")
            git(root, "add", ".")
            git(root, "commit", "-qm", "base")
            base = git(root, "rev-parse", "HEAD")
            git(root, "switch", "-qc", "candidate")
            (root / "candidate.txt").write_text("candidate\n")
            git(root, "add", ".")
            git(root, "commit", "-qm", "candidate")
            candidate = git(root, "rev-parse", "HEAD")
            git(root, "switch", "-q", "main")
            passing = ((sys.executable, "-c", "raise SystemExit(0)"),)
            result = IntegrationTransaction(
                root, gates=GateCommands(passing, passing, passing)
            ).apply(candidate, method="merge", base_sha=base)
            self.assertTrue(result.ok, result.reason)
            self.assertTrue(result.tested_tree)
            self.assertEqual(result.tested_tree, result.target_tree)

    def test_invalid_git_option_like_ref_is_rejected_before_git_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            git(root, "init", "-q")
            result = IntegrationTransaction(root).apply("--help", method="merge")
            self.assertEqual(result.reason, "invalid candidate ref")

    def test_post_apply_failure_rolls_target_back_to_original_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            git(root, "init", "-q", "-b", "main")
            git(root, "config", "user.email", "audit@example.invalid")
            git(root, "config", "user.name", "Audit")
            (root / "base.txt").write_text("base\n")
            git(root, "add", ".")
            git(root, "commit", "-qm", "base")
            base = git(root, "rev-parse", "HEAD")
            git(root, "switch", "-qc", "candidate")
            (root / "candidate.txt").write_text("candidate\n")
            git(root, "add", ".")
            git(root, "commit", "-qm", "candidate")
            candidate = git(root, "rev-parse", "HEAD")
            git(root, "switch", "-q", "main")

            def corrupt_target() -> None:
                (root / "post-apply.tmp").write_text("dirty")

            result = IntegrationTransaction(root, after_apply=corrupt_target).apply(
                candidate, method="merge", base_sha=base
            )
            self.assertFalse(result.ok)
            self.assertEqual(git(root, "rev-parse", "HEAD"), base)
            self.assertEqual(git(root, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
