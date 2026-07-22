from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.quality.checker import QualityChecker  # noqa: E402


def init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


class QualityCheckerTests(unittest.TestCase):
    def test_baseline_freezes_existing_oversize_and_rejects_growth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init(root)
            source = root / "legacy.py"
            source.write_text(
                "\n".join(f"x_{i} = {i}" for i in range(451)), encoding="utf-8"
            )
            checker = QualityChecker(root)
            baseline = checker.baseline()
            self.assertEqual(baseline["files"]["legacy.py"]["logical_lines"], 451)
            self.assertTrue(checker.check()["ok"])
            source.write_text(source.read_text() + "\nx_more = 1\n", encoding="utf-8")
            result = checker.check()
            self.assertFalse(result["ok"])
            self.assertIn("no-growth", " ".join(result["errors"]))

    def test_function_complexity_and_tiny_forwarder_are_not_line_limit_loopholes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init(root)
            (root / "branchy.py").write_text(
                "def branchy(x):\n"
                + "\n".join(f"    if x == {i}: x += 1" for i in range(13))
                + "\n    return x\n",
                encoding="utf-8",
            )
            (root / "forwarder.py").write_text(
                "from branchy import branchy\n", encoding="utf-8"
            )
            result = QualityChecker(root).check()
            joined = "\n".join(result["errors"])
            self.assertIn("complexity hard limit", joined)
            self.assertIn("tiny forwarder", joined)

    def test_expired_exception_and_deprecation_contract_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init(root)
            config = root / ".aiflow"
            config.mkdir()
            (config / "quality.toml").write_text(
                """schema_version = 1
[[exception]]
owner = "maintainers"
reason = "temporary"
scope = "legacy.py"
created = "1999-01-01"
expires = "2000-01-01"
removal_target = "split module"
""",
                encoding="utf-8",
            )
            (config / "deprecations.toml").write_text(
                """schema_version = 1
[[deprecation]]
id = "old"
symbol_or_path = "old.py"
replacement = "new.py"
introduced_version = "0.1.0"
removal_version = "0.2.0"
removal_deadline = "2000-01-01"
owner = "maintainers"
compat_tests = ["tests/test_old.py"]
remaining_call_sites = 0
""",
                encoding="utf-8",
            )
            result = QualityChecker(root).check()
            joined = "\n".join(result["errors"])
            self.assertIn("expired quality exception", joined)
            self.assertIn("expired deprecation", joined)

    def test_core_to_compat_dependency_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init(root)
            source = root / "src" / "aiflow" / "domain" / "bad.py"
            source.parent.mkdir(parents=True)
            source.write_text("from aiflow.compat import legacy\n", encoding="utf-8")
            result = QualityChecker(root).check()
            self.assertIn("core import of compat", "\n".join(result["errors"]))

    def test_deprecation_usage_count_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init(root)
            config = root / ".aiflow"
            config.mkdir()
            (root / "caller.py").write_text('LEGACY = "old.py"\n', encoding="utf-8")
            (config / "deprecations.toml").write_text(
                """schema_version = 1
[[deprecation]]
id = "old"
symbol_or_path = "old.py"
replacement = "new.py"
introduced_version = "0.1.0"
removal_version = "9.0.0"
removal_deadline = "2099-01-01"
owner = "maintainers"
compat_tests = ["tests/test_old.py"]
remaining_call_sites = 0
""",
                encoding="utf-8",
            )
            result = QualityChecker(root).check()
            self.assertIn("usage count mismatch", "\n".join(result["errors"]))


if __name__ == "__main__":
    unittest.main()
