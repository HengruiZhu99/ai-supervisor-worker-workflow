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


def validate_role_result(
    result: Mapping[str, object],
    *,
    identities: Mapping[str, str],
    task_id: str,
    role: str,
    action: str,
) -> None:
    _validate_role_identity(result, identities=identities, task_id=task_id, role=role)
    validators = {
        "analyze_task": _validate_analysis,
        "review_task": _validate_review,
    }
    validator = validators.get(action)
    if validator is not None:
        validator(result, role)
    elif action == "execute_task":
        validate_child_result(result, identities=identities, task_id=task_id)


def _validate_role_identity(
    result: Mapping[str, object],
    *,
    identities: Mapping[str, str],
    task_id: str,
    role: str,
) -> None:
    common = {"schema_version", "status", "task_id", "agent_role"} | set(identities)
    missing = common - result.keys()
    if missing:
        raise ChildResultError(f"{role} result lacks fields: {sorted(missing)}")
    if result.get("schema_version") != "1" or result.get("status") != "completed":
        raise ChildResultError(f"{role} returned a non-completed result")
    if result.get("task_id") != task_id or result.get("agent_role") != role:
        raise ChildResultError(f"{role} result identity mismatch")
    mismatches = [
        key for key, value in identities.items() if str(result.get(key, "")) != value
    ]
    if mismatches:
        raise ChildResultError(
            f"{role} project identity mismatch: {sorted(mismatches)}"
        )
    attempted = [key for key in RECURSION_KEYS if result.get(key)]
    if attempted:
        raise ChildResultError(f"{role} attempted recursive delegation")


def _validate_analysis(result: Mapping[str, object], role: str) -> None:
    required = {"summary", "findings", "recommended_next_action"}
    if not required <= result.keys():
        raise ChildResultError(f"{role} analysis contract is incomplete")


def _validate_review(result: Mapping[str, object], role: str) -> None:
    required = {
        "recommendation",
        "blocks_acceptance",
        "findings",
        "full_diff_reviewed",
        "files_reviewed",
        "unreviewed_files",
    }
    if not required <= result.keys() or result.get("full_diff_reviewed") is not True:
        raise ChildResultError(f"{role} review coverage contract is incomplete")
