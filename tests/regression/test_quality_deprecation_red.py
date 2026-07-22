from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "bin" / "aiflow"


class QualityDeprecationRegressionTests(unittest.TestCase):
    def run_quality(self, project: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(CLI), "--project-root", str(project), "quality", "check"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_legacy_worker_loop_is_now_a_thin_shim(self) -> None:
        lines = (
            (ROOT / "scripts" / "worker_loop.sh")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        logical = [
            line for line in lines if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertLessEqual(
            len(logical), 160, "oversized legacy worker loop still owns core logic"
        )

    def test_new_oversized_file_fails_with_specific_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            source = project / "oversized.py"
            source.write_text(
                "\n".join(f"value_{i} = {i}" for i in range(451)), encoding="utf-8"
            )
            result = self.run_quality(project)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hard limit", (result.stdout + result.stderr).lower())
            self.assertIn("oversized.py", result.stdout + result.stderr)

    def test_expired_deprecation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            config = project / ".aiflow" / "deprecations.toml"
            config.parent.mkdir()
            config.write_text(
                """schema_version = 1
[[deprecation]]
id = "expired"
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
            result = self.run_quality(project)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "expired deprecation", (result.stdout + result.stderr).lower()
            )

    def test_new_core_import_of_compat_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            source = project / "src" / "aiflow" / "domain" / "bad.py"
            source.parent.mkdir(parents=True)
            source.write_text("from aiflow.compat import legacy\n", encoding="utf-8")
            result = self.run_quality(project)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "core import of compat", (result.stdout + result.stderr).lower()
            )


if __name__ == "__main__":
    unittest.main()
