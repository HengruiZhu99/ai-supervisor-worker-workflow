from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.controller.lifecycle import RunLifecycle  # noqa: E402
from aiflow.identity.context import resolve_project  # noqa: E402
from aiflow.state.store import RunStore  # noqa: E402


def project_context(root: Path, temporary: str):
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    config = root / ".aiflow" / "project.toml"
    config.parent.mkdir()
    config.write_text(
        'schema_version=1\nproject_id="terminal-contract"\n'
        'name="fixture"\nprofile="solo"\n',
        encoding="utf-8",
    )
    return resolve_project(
        explicit_root=root,
        env={"XDG_STATE_HOME": str(Path(temporary) / "state")},
    )


class TerminalContractRegressionTests(unittest.TestCase):
    def test_bugfix_alias_is_normalized_to_the_bug_evidence_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = project_context(Path(tmp) / "project", tmp)
            environment = {"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime")}
            lifecycle = RunLifecycle(context, runtime_env=environment)
            started = lifecycle.start(
                mode="solo", objective="repair defect", task_kind="bugfix"
            )
            self.assertEqual(
                lifecycle.status(started["run_id"])["tasks"][0]["kind"], "bug"
            )

    def test_run_listing_is_chronological_not_identifier_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = project_context(Path(tmp) / "project", tmp)
            environment = {"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime")}
            RunStore.create(
                context, mode="solo", run_id="z-old", runtime_env=environment
            )
            time.sleep(0.001)
            RunStore.create(
                context, mode="solo", run_id="a-new", runtime_env=environment
            )
            listed = RunLifecycle(context, runtime_env=environment).list()
            self.assertEqual([str(run["run_id"]) for run in listed], ["z-old", "a-new"])


if __name__ == "__main__":
    unittest.main()
