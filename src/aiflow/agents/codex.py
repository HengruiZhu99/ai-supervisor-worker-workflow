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


class CodexAgentBackend:
    """Bounded live Codex adapter; mandatory CI substitutes FakeAgentBackend."""

    def __init__(
        self,
        workspace: Path,
        *,
        model: str = "gpt-5.6-sol",
        reasoning_effort: str = "high",
        timeout: int = 14_400,
    ) -> None:
        self.workspace = workspace.resolve()
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout

    @staticmethod
    def _prompt(capsule: Mapping[str, Any]) -> str:
        return (
            "Use $tdd-solo to execute exactly the durable task capsule below. "
            "Do not launch subagents. Work only in the named checkout/worktree, preserve user work, "
            "and obey the bounded test-first cycle for its task kind. Finish by returning only a JSON "
            "object matching the supplied output schema; identity fields and acceptance evidence must "
            "match the capsule exactly.\n\nTASK CAPSULE\n"
            + json.dumps(dict(capsule), indent=2, sort_keys=True)
        )

    def run(self, capsule: Mapping[str, Any]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="aiflow-codex-result-") as temporary:
            directory = Path(temporary)
            schema = directory / "result.schema.json"
            output = directory / "result.json"
            schema.write_text(json.dumps(RESULT_SCHEMA, indent=2), encoding="utf-8")
            command = [
                "codex",
                "--ask-for-approval",
                "never",
                "--sandbox",
                "workspace-write",
                "exec",
                "-C",
                str(self.workspace),
                "-m",
                self.model,
                "-c",
                f'model_reasoning_effort="{self.reasoning_effort}"',
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
                "AIFLOW_WORKTREE_ROOT": str(self.workspace),
            }
            completed = run_owned_process(
                command,
                cwd=self.workspace,
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
