from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.identity.context import (  # noqa: E402
    CheckoutRegistry,
    IdentityCollision,
    ThreadIdentityMismatch,
    cache_path,
    resolve_project,
    runtime_path,
    validate_thread_identity,
)
from aiflow.security.environment import scrub_environment  # noqa: E402


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def init_project(path: Path, project_id: str = "project-contract-id") -> None:
    path.mkdir(parents=True)
    git("init", "-q", cwd=path)
    git("config", "user.email", "aiflow-tests@example.invalid", cwd=path)
    git("config", "user.name", "AIFLOW Tests", cwd=path)
    config = path / ".aiflow" / "project.toml"
    config.parent.mkdir()
    config.write_text(
        f'schema_version = 1\nproject_id = "{project_id}"\nname = "fixture"\nprofile = "solo"\n',
        encoding="utf-8",
    )
    git("add", ".aiflow/project.toml", cwd=path)
    git("commit", "-q", "-m", "fixture", cwd=path)


class IdentityIsolationTests(unittest.TestCase):
    def test_inherited_aiflow_environment_does_not_select_another_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project_a, project_b = base / "a", base / "b"
            init_project(project_a, "project-a")
            init_project(project_b, "project-b")
            context = resolve_project(
                cwd=project_b,
                env={
                    "AIFLOW_PROJECT_ROOT": str(project_a),
                    "PATH": os.environ.get("PATH", ""),
                },
            )
            self.assertEqual(context.root, project_b.resolve())
            self.assertEqual(context.project_id, "project-b")

    def test_two_clones_share_project_id_but_not_checkout_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            origin, clone = base / "origin", base / "clone"
            init_project(origin)
            git("clone", "-q", str(origin), str(clone), cwd=base)
            first = resolve_project(explicit_root=origin)
            second = resolve_project(explicit_root=clone)
            self.assertEqual(first.project_id, second.project_id)
            self.assertNotEqual(first.checkout_id, second.checkout_id)

    def test_linked_worktrees_share_checkout_and_have_distinct_worktree_ids(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            main, linked = base / "main", base / "linked"
            init_project(main)
            git("worktree", "add", "-q", "-b", "linked", str(linked), cwd=main)
            primary = resolve_project(explicit_root=main)
            secondary = resolve_project(explicit_root=linked)
            self.assertEqual(primary.checkout_id, secondary.checkout_id)
            self.assertNotEqual(primary.worktree_id, secondary.worktree_id)

    def test_runtime_and_cache_are_checkout_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            init_project(project)
            context = resolve_project(explicit_root=project)
            runtime = runtime_path(
                context, "run-123", env={"XDG_RUNTIME_DIR": str(Path(tmp) / "run")}
            )
            cache = cache_path(
                context, env={"XDG_CACHE_HOME": str(Path(tmp) / "cache")}
            )
            self.assertEqual(
                runtime.parts[-3:], ("aiflow", context.checkout_id, "run-123")
            )
            self.assertEqual(cache.parts[-2:], ("aiflow", context.checkout_id))

    def test_duplicate_checkout_id_at_two_live_roots_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = CheckoutRegistry(Path(tmp) / "registry.json")
            first = Path(tmp) / "one" / ".git"
            second = Path(tmp) / "two" / ".git"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            registry.register("same-checkout", first)
            with self.assertRaises(IdentityCollision):
                registry.register("same-checkout", second)

    def test_thread_cwd_or_checkout_mismatch_is_rejected(self) -> None:
        record = {
            "thread_id": "thread-a",
            "checkout_id": "checkout-a",
            "run_id": "run-a",
            "expected_cwd": "/project/a",
            "worktree_id": "worktree-a",
            "backend": "codex",
        }
        with self.assertRaises(ThreadIdentityMismatch):
            validate_thread_identity(
                record,
                checkout_id="checkout-b",
                run_id="run-a",
                cwd=Path("/project/a"),
                worktree_id="worktree-a",
            )

    def test_environment_scrubbing_removes_inherited_context(self) -> None:
        cleaned = scrub_environment(
            {"PATH": "/bin", "AIFLOW_PROJECT_ROOT": "/wrong", "AIFLOW_TOKEN": "secret"},
            injected={"AIFLOW_CHECKOUT_ID": "checkout", "AIFLOW_RUN_ID": "run"},
        )
        self.assertEqual(cleaned["PATH"], "/bin")
        self.assertEqual(cleaned["AIFLOW_CHECKOUT_ID"], "checkout")
        self.assertEqual(cleaned["AIFLOW_RUN_ID"], "run")
        self.assertNotIn("AIFLOW_PROJECT_ROOT", cleaned)
        self.assertNotIn("AIFLOW_TOKEN", cleaned)


if __name__ == "__main__":
    unittest.main()
