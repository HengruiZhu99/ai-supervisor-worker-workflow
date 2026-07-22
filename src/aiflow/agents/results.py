from __future__ import annotations

from typing import Mapping


class ChildResultError(ValueError):
    """A direct-child result violates identity, schema, or depth-one policy."""


REQUIRED = {
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
}
RECURSION_KEYS = {
    "requested_subagents",
    "spawned_agents",
    "child_threads",
    "delegations",
}


def validate_child_result(
    result: Mapping[str, object], *, identities: Mapping[str, str], task_id: str
) -> None:
    missing = REQUIRED - result.keys()
    if missing:
        raise ChildResultError(f"child result lacks fields: {sorted(missing)}")
    if str(result.get("schema_version", "")) != "1":
        raise ChildResultError("unsupported child result schema")
    if result.get("status") not in {"completed", "blocked", "failed"}:
        raise ChildResultError("invalid child result status")
    if str(result.get("task_id")) != task_id:
        raise ChildResultError("child result task identity mismatch")
    mismatches = [
        key
        for key, expected in identities.items()
        if str(result.get(key, "")) != expected
    ]
    if mismatches:
        raise ChildResultError(f"child result identity mismatch: {sorted(mismatches)}")
    attempted = [key for key in RECURSION_KEYS if result.get(key)]
    if attempted:
        raise ChildResultError(
            f"recursive child delegation is forbidden: {sorted(attempted)}"
        )
