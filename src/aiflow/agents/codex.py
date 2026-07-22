from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from aiflow.security.process import run_owned_process


RESULT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "schema_version",
        "project_id",
        "checkout_id",
        "worktree_id",
        "run_id",
        "task_id",
        "agent_role",
        "status",
        "summary",
        "findings",
        "changed_files",
        "commands_run",
        "tests_and_results",
        "acceptance_ids_supported",
        "evidence_paths",
        "contract_impact",
        "residual_risks",
        "recommended_next_action",
        "cycle_kind",
        "cycle_evidence",
        "delivery_evidence",
        "closed_acceptance_ids",
    ],
    "properties": {
        "schema_version": {"const": "1"},
        "status": {"enum": ["completed", "blocked", "failed"]},
    },
    "additionalProperties": True,
}

ANALYSIS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "schema_version",
        "project_id",
        "checkout_id",
        "worktree_id",
        "run_id",
        "task_id",
        "agent_role",
        "status",
        "summary",
        "findings",
        "recommended_next_action",
    ],
    "additionalProperties": True,
}

REVIEW_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "schema_version",
        "project_id",
        "checkout_id",
        "worktree_id",
        "run_id",
        "task_id",
        "agent_role",
        "status",
        "recommendation",
        "blocks_acceptance",
        "findings",
        "full_diff_reviewed",
        "files_reviewed",
        "unreviewed_files",
    ],
    "additionalProperties": True,
}

ROLE_MODELS = {
    "codebase-mapper": "gpt-5.6-terra",
    "docs-researcher": "gpt-5.6-terra",
    "ui-auditor": "gpt-5.6-terra",
    "task-router": "gpt-5.6-luna",
    "test-architect": "gpt-5.6-sol",
    "implementation-worker": "gpt-5.6-sol",
    "scientific-reviewer": "gpt-5.6-sol",
    "engineering-reviewer": "gpt-5.6-sol",
    "release-auditor": "gpt-5.6-sol",
}


class CodexAgentBackend:
    """Bounded live Codex adapter; mandatory CI substitutes FakeAgentBackend."""

    def __init__(
        self,
        workspace: Path,
        *,
        model: str = "",
        reasoning_effort: str = "high",
        timeout: int = 14_400,
    ) -> None:
        self.workspace = workspace.resolve()
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout

    @staticmethod
    def _prompt(capsule: Mapping[str, Any]) -> str:
        mode = str(capsule.get("mode", "solo"))
        role = str(capsule.get("agent_role", "implementation-worker"))
        action = str(capsule.get("action", "execute_task"))
        if mode == "solo":
            instruction = (
                "Use $tdd-solo to execute exactly this durable task. "
                "Do not launch subagents."
            )
        else:
            instruction = (
                "The sole parent controller is applying $aiflow-autonomous. "
                f"Act only as its bounded direct-child {role} for action {action}. "
                "Do not launch or request subagents and do not mutate canonical AIFLOW state."
            )
        return (
            instruction
            + " Work only in the named checkout/worktree, preserve user work, "
            "and obey the bounded test-first cycle for its task kind. Finish by returning only a JSON "
            "object matching the supplied output schema; identity fields and acceptance evidence must "
            "match the capsule exactly.\n\nTASK CAPSULE\n"
            + json.dumps(dict(capsule), indent=2, sort_keys=True)
        )

    def _workspace(self, capsule: Mapping[str, Any]) -> Path:
        candidate = Path(
            str(capsule.get("working_directory", self.workspace))
        ).resolve()
        if not candidate.is_dir():
            raise RuntimeError("agent working directory does not exist")

        def common(path: Path) -> Path:
            completed = run_owned_process(
                ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                cwd=path,
                timeout=10,
            )
            if completed.returncode:
                raise RuntimeError("agent working directory is not a Git worktree")
            return Path(completed.stdout.strip()).resolve()

        if common(candidate) != common(self.workspace):
            raise RuntimeError("agent working directory belongs to another checkout")
        return candidate

    @staticmethod
    def _schema(action: str) -> dict[str, Any]:
        if action == "analyze_task":
            return ANALYSIS_SCHEMA
        if action == "review_task":
            return REVIEW_SCHEMA
        return RESULT_SCHEMA

    def run(self, capsule: Mapping[str, Any]) -> dict[str, Any]:
        action = str(capsule.get("action", "execute_task"))
        role = str(capsule.get("agent_role", "implementation-worker"))
        workspace = self._workspace(capsule)
        with tempfile.TemporaryDirectory(prefix="aiflow-codex-result-") as temporary:
            directory = Path(temporary)
            schema = directory / "result.schema.json"
            output = directory / "result.json"
            schema.write_text(
                json.dumps(self._schema(action), indent=2), encoding="utf-8"
            )
            command = [
                "codex",
                "--ask-for-approval",
                "never",
                "--sandbox",
                "workspace-write" if action == "execute_task" else "read-only",
                "exec",
                "-C",
                str(workspace),
                "-m",
                self.model or ROLE_MODELS.get(role, "gpt-5.6-sol"),
                "-c",
                f'model_reasoning_effort="{self.reasoning_effort}"',
                "-c",
                "agents.enabled=false",
                "--output-schema",
                str(schema),
                "--output-last-message",
                str(output),
                "-",
            ]
            injected = {
                "AIFLOW_PROJECT_ID": str(capsule["project_id"]),
                "AIFLOW_CHECKOUT_ID": str(capsule["checkout_id"]),
                "AIFLOW_WORKTREE_ID": str(capsule["worktree_id"]),
                "AIFLOW_RUN_ID": str(capsule["run_id"]),
                "AIFLOW_TASK_ID": str(capsule["task_id"]),
                "AIFLOW_MODE": str(capsule["mode"]),
                "AIFLOW_PROJECT_ROOT": str(self.workspace),
                "AIFLOW_WORKTREE_ROOT": str(workspace),
            }
            completed = run_owned_process(
                command,
                cwd=workspace,
                injected=injected,
                timeout=self.timeout,
                input_text=self._prompt(capsule),
            )
            if completed.returncode != 0:
                detail = completed.stderr.strip()[-2000:] or "no stderr"
                raise RuntimeError(
                    f"Codex worker exited {completed.returncode}: {detail}"
                )
            try:
                result = json.loads(output.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"Codex worker returned invalid structured output: {exc}"
                ) from exc
            if not isinstance(result, dict):
                raise RuntimeError("Codex worker result must be a JSON object")
            return result
