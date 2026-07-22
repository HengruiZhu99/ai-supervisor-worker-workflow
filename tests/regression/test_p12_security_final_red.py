from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.controller.lifecycle import RunLifecycle  # noqa: E402
from aiflow.controller.worktrees import TaskWorktree, WorktreeError  # noqa: E402
from aiflow.identity.context import resolve_project  # noqa: E402
from aiflow.integration import transaction  # noqa: E402
from aiflow.security.permissions import (  # noqa: E402
    PermissionBoundaryError,
    validate_orchestrated_parent,
)
from aiflow.skills.installer import ProjectInstaller  # noqa: E402
from aiflow.state.atomic import atomic_write_json, signed  # noqa: E402
from aiflow.state.locks import owned_directory_lock  # noqa: E402
from aiflow.state.store import StateError  # noqa: E402


def git(path: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=path, check=True, capture_output=True)


def project(path: Path) -> None:
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.name", "P12 Security Test")
    git(path, "config", "user.email", "security@example.invalid")
    ProjectInstaller(path, distribution_root=ROOT).init("orchestrated")
    git(path, "add", ".")
    git(path, "commit", "-qm", "fixture")


def foreign_owner() -> dict[str, object]:
    return signed(
        {
            "schema_version": 1,
            "host_id": "host-foreign",
            "boot_id": "boot-foreign",
            "pid": 1,
            "process_start_time": "foreign-process",
        }
    )


class P12SecurityFinalRegressionTests(unittest.TestCase):
    def test_orchestration_requires_observed_effective_parent_permissions(self) -> None:
        with self.assertRaises(PermissionBoundaryError):
            validate_orchestrated_parent("orchestrated", "workspace-write", env={})

    def test_foreign_host_guards_are_ambiguous_and_never_stolen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            lock = base / "foreign.lock"
            lock.mkdir()
            atomic_write_json(lock / "OWNER.json", foreign_owner())
            with self.assertRaises(StateError):
                with owned_directory_lock(lock, timeout=0.01, orphan_grace=0):
                    pass
            self.assertTrue(lock.is_dir())

            root = base / "project"
            project(root)
            context = resolve_project(
                explicit_root=root,
                env={"XDG_STATE_HOME": str(base / "state")},
            )
            environment = {"XDG_RUNTIME_DIR": str(base / "runtime")}
            lifecycle = RunLifecycle(context, runtime_env=environment)
            first = lifecycle.start(mode="solo", objective="first")
            second = lifecycle.start(mode="solo", objective="second")
            lease = {
                **foreign_owner(),
                **context.identity_fields(second["run_id"]),
            }
            atomic_write_json(context.state_root / "MUTATING_RUN.json", signed(lease))
            with self.assertRaises(StateError):
                with lifecycle.checkout_mutation(first["run_id"]):
                    pass
            self.assertTrue((context.state_root / "MUTATING_RUN.json").is_file())

    def test_retry_refuses_a_dirty_preexisting_writer_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "project"
            project(root)
            context = resolve_project(
                explicit_root=root,
                env={"XDG_STATE_HOME": str(base / "state")},
            )
            runtime = base / "runtime"
            first = TaskWorktree(context, "run-security", "T0001", runtime).create()
            assert first.path is not None
            (first.path / "outside-scope.txt").write_text(
                "preserve\n", encoding="utf-8"
            )
            with self.assertRaises(WorktreeError):
                TaskWorktree(context, "run-security", "T0001", runtime).create()

    def test_integration_default_runner_uses_owned_process_groups(self) -> None:
        completed = subprocess.CompletedProcess(["true"], 0, "", "")
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                transaction,
                "run_owned_process",
                return_value=completed,
                create=True,
            ) as owned:
                result = transaction.run_command(["true"], Path(tmp))
        self.assertEqual(result.returncode, 0)
        owned.assert_called_once()


if __name__ == "__main__":
    unittest.main()
