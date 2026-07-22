from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aiflow.controller.lifecycle import RunLifecycle
from aiflow.controller.pending import adopt_orphaned_integration
from tests.regression.test_final_audit_red import (
    context_for,
    init_project,
    runtime,
)
from tests.regression.test_p12_terminal_hardening_red import artifact_command


class P12IntakeRecoveryRegressionTests(unittest.TestCase):
    def test_orphan_probe_scans_every_ready_task_before_redispatch(self) -> None:
        store = mock.Mock()
        records = [
            {"id": "H0001", "status": "READY", "attempts": 0},
            {"id": "T0001", "status": "READY", "attempts": 0},
        ]
        with mock.patch(
            "aiflow.controller.pending.orphaned_result", return_value=None
        ) as probe:
            result = adopt_orphaned_integration(
                store,
                records,
                agent_id="codex-worker",
                persist=mock.Mock(),
            )
        self.assertIsNone(result)
        self.assertEqual(
            [call.args[1]["id"] for call in probe.call_args_list],
            ["H0001", "T0001"],
        )

    def test_default_contract_requires_causal_pre_command_in_post_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            red = artifact_command("feature.txt")
            config = root / ".aiflow" / "project.toml"
            config.write_text(
                config.read_text(encoding="utf-8")
                .replace("test_red = []", f"test_red = {json.dumps(red)}")
                .replace(
                    "test_focused = []",
                    'test_focused = ["python3", "-c", "pass"]',
                ),
                encoding="utf-8",
            )
            lifecycle = RunLifecycle(context_for(root, tmp), runtime_env=runtime(tmp))
            with self.assertRaises(ValueError):
                lifecycle.start(
                    mode="solo",
                    objective="causal task",
                    acceptance_ids=("AC-1",),
                    allowed_scope=("feature.txt",),
                )
            self.assertEqual(lifecycle.list(), [])

    def test_orchestrated_task_specs_require_project_regression_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root, commit=True)
            config = root / ".aiflow" / "project.toml"
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    'test_regression = ["python3", "-c", "raise SystemExit(0)"]',
                    "test_regression = []",
                ),
                encoding="utf-8",
            )
            command = artifact_command("T0001.txt")
            lifecycle = RunLifecycle(context_for(root, tmp), runtime_env=runtime(tmp))
            with self.assertRaises(ValueError):
                lifecycle.start(
                    mode="orchestrated",
                    objective="three-tier task",
                    task_specs=(
                        {
                            "id": "T0001",
                            "objective": "three-tier task",
                            "kind": "feature",
                            "acceptance_ids": ["AC-1"],
                            "allowed_scope": ["T0001.txt"],
                            "pre_commands": [command],
                            "commands": [command],
                        },
                    ),
                )
            self.assertEqual(lifecycle.list(), [])


if __name__ == "__main__":
    unittest.main()
