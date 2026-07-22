from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("fixtures") / "athenak_like"
CLI = ROOT / "bin" / "aiflow"
sys.path.insert(0, str(ROOT / "src"))

from aiflow.controller.lifecycle import RunLifecycle  # noqa: E402
from aiflow.controller.runner import Budgets  # noqa: E402
from aiflow.identity.context import resolve_project  # noqa: E402
from aiflow.state.atomic import read_json  # noqa: E402


def run(args: list[str], cwd: Path, env=None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def configure_commands(config: Path, commands: list[list[str]]) -> None:
    content = config.read_text(encoding="utf-8")
    for name, command in zip(
        ("build", "test_focused", "test_regression"), commands, strict=True
    ):
        content = content.replace(f"{name} = []", f"{name} = {json.dumps(command)}")
    config.write_text(content, encoding="utf-8")


class SoloCppBackend:
    def __init__(self, project: Path, commands: list[list[str]]) -> None:
        self.project = project
        self.commands = commands
        self.calls = 0

    def __call__(self, capsule: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls += 1
        if capsule["mode"] != "solo":
            raise AssertionError("Solo backend received an unexpected capsule")
        identities = {
            key: str(capsule[key])
            for key in ("project_id", "checkout_id", "worktree_id", "run_id")
        }
        if capsule["action"] == "review_task":
            return {
                "schema_version": "1",
                **identities,
                "task_id": str(capsule["task_id"]),
                "agent_role": "implementation-worker",
                "status": "completed",
                "recommendation": "accept",
                "blocks_acceptance": False,
                "findings": [],
                "full_diff_reviewed": True,
                "files_reviewed": ["include/vector_norm.hpp"],
                "unreviewed_files": [],
            }
        if capsule["action"] != "execute_task":
            raise AssertionError("Solo backend received an unexpected action")
        header = self.project / "include" / "vector_norm.hpp"
        header.write_text(
            header.read_text(encoding="utf-8").replace(
                "return squared;  // Intentional RED fixture defect; the acceptance test corrects it.",
                "return std::sqrt(squared);",
            ),
            encoding="utf-8",
        )
        acceptance_ids = [str(value) for value in capsule["task"]["acceptance_ids"]]
        return {
            "schema_version": "1",
            **identities,
            "task_id": str(capsule["task_id"]),
            "agent_role": "implementation-worker",
            "status": "completed",
            "summary": "corrected vector L2 norm after a discriminating RED",
            "findings": [],
            "changed_files": ["include/vector_norm.hpp"],
            "commands_run": self.commands,
            "tests_and_results": [{"command": command} for command in self.commands],
            "acceptance_ids_supported": acceptance_ids,
            "evidence_paths": ["include/vector_norm.hpp"],
            "contract_impact": "the norm now returns sqrt(sum(x_i^2))",
            "residual_risks": [],
            "recommended_next_action": "accept",
            "cycle_kind": "feature",
            "cycle_evidence": {
                "red": {"exit_code": 1, "discriminating": True},
                "green": {"exit_code": 0},
                "regression": {"exit_code": 0},
                "cold_review": {
                    "status": "pass",
                    "reviewer": "cold-self-review",
                },
                "attempts": 1,
                "questions": 0,
                "observable": "vector norm returns the analytic 3-4-5 result",
            },
            "delivery_evidence": {
                "changed_files": ["include/vector_norm.hpp"],
                "expected_artifact": "include/vector_norm.hpp",
                "commands": self.commands,
                "fresh_end_to_end": True,
            },
            "closed_acceptance_ids": acceptance_ids,
        }


class SoloCppAcceptanceTests(unittest.TestCase):
    def test_existing_cmake_project_closes_acceptance_through_solo_controller(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "athenak-like"
            shutil.copytree(FIXTURE, project)
            run(["git", "init", "-q"], project)
            environment = dict(os.environ)
            environment["XDG_RUNTIME_DIR"] = str(base / "runtime")
            initialized = run(
                [
                    str(CLI),
                    "--project-root",
                    str(project),
                    "project",
                    "init",
                    "--profile",
                    "solo",
                ],
                ROOT,
                environment,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            commands = [
                ["cmake", "-S", ".", "-B", "build"],
                ["cmake", "--build", "build", "--clean-first"],
                ["ctest", "--test-dir", "build", "--output-on-failure"],
            ]
            config = project / ".aiflow" / "project.toml"
            configure_commands(config, commands)
            context = resolve_project(
                explicit_root=project,
                env={"XDG_STATE_HOME": str(base / "state")},
            )
            runtime_env = {"XDG_RUNTIME_DIR": str(base / "runtime")}
            started = RunLifecycle(context, runtime_env=runtime_env).start(
                mode="solo",
                objective="Correct the vector L2 norm",
                acceptance_ids=("AC-NORM-001",),
                task_kind="feature",
                task_specs=(
                    {
                        "id": "T0001",
                        "objective": "Correct the vector L2 norm",
                        "kind": "feature",
                        "acceptance_ids": ["AC-NORM-001"],
                        "allowed_scope": ["include/vector_norm.hpp"],
                        "pre_commands": commands,
                        "commands": commands,
                        "expected_diff_budget": 1,
                    },
                ),
            )
            backend = SoloCppBackend(project, commands)
            lifecycle = RunLifecycle(
                context,
                runtime_env=runtime_env,
                agent_backend=backend,
                agent_id="cpp-acceptance-worker",
            )
            completed = lifecycle.resume(
                started["run_id"], budgets=Budgets(max_tasks=1, max_idle=1)
            )
            self.assertEqual(completed["status"], "SUCCEEDED", completed)
            self.assertEqual(completed["acceptance_ids_closed"], ["AC-NORM-001"])
            self.assertEqual(
                backend.calls,
                2,
                "Solo mode uses one writer call and one cold read-only review call",
            )
            task = lifecycle.status(started["run_id"])["tasks"][0]
            self.assertEqual(task["status"], "ACCEPTED")
            inbox = read_json(
                lifecycle.store(started["run_id"]).path / task["evidence"][0]
            )
            self.assertTrue(inbox["controller_attestation"]["commands"])
            self.assertNotEqual(
                inbox["controller_attestation"]["pre_commands"][-1]["exit_code"],
                0,
            )
            self.assertTrue(
                all(
                    result["exit_code"] == 0
                    for result in inbox["controller_attestation"]["commands"]
                )
            )
            quality = run(
                [str(CLI), "--project-root", str(project), "quality", "check"],
                ROOT,
                environment,
            )
            self.assertEqual(quality.returncode, 0, quality.stdout + quality.stderr)


if __name__ == "__main__":
    unittest.main()
