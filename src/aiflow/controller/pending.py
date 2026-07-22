from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Mapping

from aiflow.agents.results import validate_child_result
from aiflow.controller.attestation import AttestationError
from aiflow.integration.recovery import orphaned_result, recover_pending_checkout
from aiflow.state.store import RunStore


Persist = Callable[..., None]


def update_prepared_record(record: dict[str, Any], details: Mapping[str, Any]) -> None:
    integration = record.get("integration")
    if record.get("status") != "INTEGRATION_PENDING" or not isinstance(
        integration, dict
    ):
        raise AttestationError("integration preparation has no durable intent")
    integration.update({str(key): value for key, value in details.items()})


def mark_reconciliation_required(record: dict[str, Any], exc: Exception) -> None:
    record["failure_signature"] = hashlib.sha256(
        f"{type(exc).__name__}:{exc}".encode()
    ).hexdigest()[:16]
    record["status"] = "BLOCKED"


def pending_record_matches(workspace: Path, record: Mapping[str, Any]) -> bool:
    integration = record.get("integration", {})
    return bool(
        record.get("status") == "INTEGRATION_PENDING"
        and isinstance(integration, Mapping)
        and recover_pending_checkout(workspace, integration)
    )


def adopt_orphaned_integration(
    store: RunStore,
    records: list[dict[str, Any]],
    *,
    agent_id: str,
    persist: Persist,
) -> str | None:
    for record in (item for item in records if item.get("status") == "READY"):
        attempt = int(record.get("attempts", 0)) + 1
        try:
            orphaned = orphaned_result(
                store, record, agent_id=agent_id, attempt=attempt
            )
            if orphaned is None:
                continue
            result, inbox, integration = orphaned
            validate_child_result(
                result,
                identities=store.context.identity_fields(store.run_id),
                task_id=str(record["id"]),
            )
            record["status"] = "INTEGRATION_PENDING"
            record["integration"] = integration
            relative = str(inbox.relative_to(store.path))
            record["evidence"] = sorted(
                {str(value) for value in record.get("evidence", [])} | {relative}
            )
            persist(
                event_type="task_integration_adopted",
                evidence=list(record["evidence"]),
            )
        except Exception as exc:
            mark_reconciliation_required(record, exc)
            persist(event_type="integration_reconciliation_required")
            return "blocked"
        return "adopted"
    return None


def terminal_state(records: list[dict[str, Any]]) -> str:
    return (
        "succeeded"
        if records and all(record.get("status") == "ACCEPTED" for record in records)
        else "blocked"
    )
