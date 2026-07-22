from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from aiflow.controller.attestation import AttestationError
from aiflow.integration.recovery import pending_integration_matches


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
        and pending_integration_matches(workspace, integration)
    )


def terminal_state(records: list[dict[str, Any]]) -> str:
    return (
        "succeeded"
        if records and all(record.get("status") == "ACCEPTED" for record in records)
        else "blocked"
    )
