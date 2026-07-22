from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.integration.transaction import GateCommands, IntegrationTransaction  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.strip()


def repository(root: Path) -> tuple[str, str]:
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "integration@example.invalid")
    git(root, "config", "user.name", "Integration Tests")
    (root / "value.txt").write_text("base\n", encoding="utf-8")
    git(root, "add", "value.txt")
    git(root, "commit", "-q", "-m", "base")
    base = git(root, "rev-parse", "HEAD")
    git(root, "switch", "-q", "-c", "candidate")
    (root / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    git(root, "add", "candidate.txt")
    git(root, "commit", "-q", "-m", "candidate")
    candidate = git(root, "rev-parse", "HEAD")
    git(root, "switch", "-q", "main")
    return base, candidate


def passing() -> tuple[str, ...]:
    return (sys.executable, "-c", "raise SystemExit(0)")


class IntegrationTransactionTests(unittest.TestCase):
    def transaction(self, root: Path, **overrides) -> IntegrationTransaction:
        commands = GateCommands(
            focused=(passing(),), regression=(passing(),), quality=(passing(),)
        )
        return IntegrationTransaction(
            root, gates=overrides.pop("gates", commands), **overrides
        )

    def test_merge_and_duplicate_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            base, candidate = repository(root)
            result = self.transaction(root).apply(
                candidate, method="merge", base_sha=base
            )
            self.assertTrue(result.ok, result.reason)
            self.assertTrue((root / "candidate.txt").is_file())
            self.assertEqual(git(root, "status", "--porcelain"), "")
            duplicate = self.transaction(root).apply(
                candidate, method="merge", base_sha=base
            )
            self.assertFalse(duplicate.ok)
            self.assertEqual(duplicate.reason, "duplicate integration")

    def test_cherry_pick_applies_after_all_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            base, candidate = repository(root)
            result = self.transaction(root).apply(
                candidate, method="cherry-pick", base_sha=base
            )
            self.assertTrue(result.ok, result.reason)
            self.assertEqual((root / "candidate.txt").read_text(), "candidate\n")

    def test_each_preapply_gate_failure_leaves_target_unchanged(self) -> None:
        failing = (sys.executable, "-c", "raise SystemExit(7)")
        for failed_gate in ("focused", "regression", "quality"):
            with (
                self.subTest(failed_gate=failed_gate),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp) / "repo"
                base, candidate = repository(root)
                values = {
                    "focused": (passing(),),
                    "regression": (passing(),),
                    "quality": (passing(),),
                }
                values[failed_gate] = (failing,)
                gates = GateCommands(**values)
                result = self.transaction(root, gates=gates).apply(
                    candidate, method="merge", base_sha=base
                )
                self.assertFalse(result.ok)
                self.assertIn(failed_gate, result.reason)
                self.assertEqual(git(root, "rev-parse", "HEAD"), base)
                self.assertFalse((root / "candidate.txt").exists())

    def test_conflict_and_dirty_target_fail_without_candidate_application(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            base, candidate = repository(root)
            (root / "value.txt").write_text("target\n", encoding="utf-8")
            git(root, "add", "value.txt")
            git(root, "commit", "-q", "-m", "target change")
            target = git(root, "rev-parse", "HEAD")
            git(root, "switch", "-q", "candidate")
            (root / "value.txt").write_text("candidate conflict\n", encoding="utf-8")
            git(root, "add", "value.txt")
            git(root, "commit", "-q", "-m", "conflict")
            candidate = git(root, "rev-parse", "HEAD")
            git(root, "switch", "-q", "main")
            conflict = self.transaction(root).apply(
                candidate, method="merge", base_sha=base
            )
            self.assertFalse(conflict.ok)
            self.assertIn("conflict", conflict.reason)
            self.assertEqual(git(root, "rev-parse", "HEAD"), target)
            (root / "dirty.txt").write_text("user work\n", encoding="utf-8")
            dirty = self.transaction(root).apply(
                candidate, method="merge", base_sha=base
            )
            self.assertEqual(dirty.reason, "dirty target")

    def test_target_head_cas_and_interruption_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            base, candidate = repository(root)

            def move_target() -> None:
                git(root, "commit", "--allow-empty", "-q", "-m", "external move")

            moved = self.transaction(root, before_apply=move_target).apply(
                candidate, method="merge", base_sha=base
            )
            self.assertFalse(moved.ok)
            self.assertEqual(moved.reason, "target HEAD changed")
            self.assertFalse((root / "candidate.txt").exists())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            base, candidate = repository(root)
            interrupted = self.transaction(
                root, before_apply=lambda: (_ for _ in ()).throw(KeyboardInterrupt())
            ).apply(candidate, method="merge", base_sha=base)
            self.assertFalse(interrupted.ok)
            self.assertEqual(interrupted.reason, "user interruption")
            self.assertEqual(git(root, "rev-parse", "HEAD"), base)


if __name__ == "__main__":
    unittest.main()
