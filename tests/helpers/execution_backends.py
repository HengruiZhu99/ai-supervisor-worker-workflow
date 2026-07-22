from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def completed_result(
    capsule: Mapping[str, Any],
    acceptance_ids: list[str],
    *,
    artifact: str,
    command: list[str],
) -> dict[str, Any]:
    identities = {
        key: str(capsule[key])
        for key in ("project_id", "checkout_id", "worktree_id", "run_id")
    }
    cycle = {
        "red": {"exit_code": 1, "discriminating": True},
        "green": {"exit_code": 0},
        "regression": {"exit_code": 0},
        "cold_review": {"status": "pass", "reviewer": "cold-self-review"},
        "attempts": 1,
        "questions": 0,
        "observable": "new behavior",
    }
    return {
        "schema_version": "1",
        **identities,
        "task_id": str(capsule["task_id"]),
        "agent_role": "implementation-worker",
        "status": "completed",
        "summary": "completed bounded task",
        "findings": [],
        "changed_files": [artifact],
        "commands_run": [command],
        "tests_and_results": [{"command": command, "exit_code": 0}],
        "acceptance_ids_supported": acceptance_ids,
        "evidence_paths": ["evidence/cycle.json"],
        "contract_impact": "bounded",
        "residual_risks": [],
        "recommended_next_action": "accept",
        "cycle_kind": "feature",
        "cycle_evidence": cycle,
        "delivery_evidence": {
            "changed_files": [artifact],
            "expected_artifact": artifact,
            "commands": [command],
            "test_results": [{"command": command, "exit_code": 0}],
            "fresh_end_to_end": True,
        },
        "closed_acceptance_ids": acceptance_ids,
    }


class OrchestratedBackend:
    def __init__(self, root: Path, command: list[str]) -> None:
        self.root = root
        self.command = command
        self.actions: list[tuple[str, str]] = []
        self.writer_directory = ""

    def __call__(self, capsule: Mapping[str, Any]) -> Mapping[str, Any]:
        action = str(capsule["action"])
        role = str(capsule["agent_role"])
        self.actions.append((action, role))
        identities = {
            key: capsule[key]
            for key in (
                "project_id",
                "checkout_id",
                "worktree_id",
                "run_id",
                "task_id",
            )
        }
        if action == "analyze_task":
            return {
                "schema_version": "1",
                **identities,
                "agent_role": role,
                "status": "completed",
                "summary": f"{role} bounded analysis",
                "findings": [],
                "recommended_next_action": "dispatch writer",
            }
        if action == "execute_task":
            return self._execute(capsule)
        if action == "review_task":
            return self._review(capsule, identities, role)
        raise AssertionError(action)

    def _execute(self, capsule: Mapping[str, Any]) -> Mapping[str, Any]:
        self.writer_directory = str(capsule["working_directory"])
        worktree = Path(self.writer_directory)
        if worktree.resolve() == self.root.resolve():
            raise AssertionError("orchestrated writer used the target checkout")
        task_id = str(capsule["task_id"])
        artifact = (
            "src/orchestrated.txt"
            if task_id == "T0001"
            and capsule["task"]["objective"] == "reviewed isolated change"
            else f"{task_id}.txt"
        )
        target = worktree / artifact
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("done\n", encoding="utf-8")
        return completed_result(
            capsule,
            [str(value) for value in capsule["task"]["acceptance_ids"]],
            artifact=artifact,
            command=[str(part) for part in capsule["task"]["commands"][0]],
        )

    def _review(
        self,
        capsule: Mapping[str, Any],
        identities: Mapping[str, Any],
        role: str,
    ) -> Mapping[str, Any]:
        if (
            Path(str(capsule["working_directory"])).resolve()
            != Path(self.writer_directory).resolve()
        ):
            raise AssertionError("reviewer did not inspect the writer worktree")
        return {
            "schema_version": "1",
            **identities,
            "agent_role": role,
            "status": "completed",
            "recommendation": "accept",
            "blocks_acceptance": False,
            "findings": [],
            "full_diff_reviewed": True,
            "files_reviewed": list(capsule["task"]["allowed_scope"]),
            "unreviewed_files": [],
        }
