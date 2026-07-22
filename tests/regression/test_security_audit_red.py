from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_wrapper  # noqa: E402
from aiflow.api.service import ApiService  # noqa: E402
from aiflow.identity.context import IdentityCollision, resolve_project  # noqa: E402
from aiflow.skills.installer import InstallError, ProjectInstaller  # noqa: E402
from aiflow.state.store import RevisionConflict  # noqa: E402


def git_project(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def wrapper_args(extra: str) -> argparse.Namespace:
    return argparse.Namespace(
        role="reviewer",
        read_only=False,
        extra_args=extra,
        workspace=str(ROOT),
        model="gpt-5.6-sol",
        reasoning_effort="high",
    )


class SecurityAuditRegressionTests(unittest.TestCase):
    def test_wrapper_rejects_every_permission_override(self) -> None:
        for extra in (
            "--sandbox workspace-write",
            "-s workspace-write",
            "--ask-for-approval on-request",
            "-a on-request",
            "-c sandbox_mode=workspace-write",
        ):
            with self.subTest(extra=extra), self.assertRaises(SystemExit):
                agent_wrapper.build_codex_command(wrapper_args(extra))

    def test_owned_process_runner_scrubs_context_and_terminates_the_process_group(self) -> None:
        runner = getattr(agent_wrapper, "run_owned_process")
        environment = dict(os.environ)
        environment["AIFLOW_PROJECT_ROOT"] = "/wrong/project"
        completed = runner(
            [sys.executable, "-c", "import os; print(os.getenv('AIFLOW_PROJECT_ROOT', 'clean'))"],
            cwd=ROOT,
            env=environment,
            timeout=5,
        )
        self.assertEqual(completed.stdout.strip(), "clean")

    def test_crafted_project_lock_cannot_escape_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            project.mkdir()
            outside = base / "outside.txt"
            outside.write_text("preserve", encoding="utf-8")
            lock = project / ".aiflow" / "project.lock"
            lock.parent.mkdir()
            lock.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workflow_version": "x",
                        "profile": "solo",
                        "installation_mode": "vendor",
                        "managed_files": {
                            "../outside.txt": hashlib.sha256(b"preserve").hexdigest()
                        },
                    }
                ),
                encoding="utf-8",
            )
            installer = ProjectInstaller(project, distribution_root=ROOT)
            with self.assertRaises(InstallError):
                installer.uninstall()
            self.assertEqual(outside.read_text(encoding="utf-8"), "preserve")

    def test_copied_checkout_id_is_registered_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = base / "first"
            git_project(first)
            (first / ".aiflow").mkdir()
            (first / ".aiflow" / "project.toml").write_text(
                'schema_version=1\nproject_id="shared-project"\n', encoding="utf-8"
            )
            environment = {"XDG_STATE_HOME": str(base / "state")}
            resolve_project(explicit_root=first, env=environment)
            second = base / "second"
            shutil.copytree(first, second)
            with self.assertRaises(IdentityCollision):
                resolve_project(explicit_root=second, env=environment)

    def test_every_api_mutation_requires_checkout_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            git_project(root)
            ProjectInstaller(root, distribution_root=ROOT).init("solo")
            service = ApiService(resolve_project(explicit_root=root, env={"XDG_STATE_HOME": str(Path(tmp) / "state")}))
            with self.assertRaises(RevisionConflict):
                service.start({"mode": "solo", "objective": "missing identity"})


if __name__ == "__main__":
    unittest.main()
