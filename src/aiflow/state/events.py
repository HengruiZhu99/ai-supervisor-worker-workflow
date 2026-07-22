from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

from aiflow.state.atomic import signed, verify_signed


def make_event(
    *,
    sequence: int,
    state_revision: int,
    event_type: str,
    identities: Mapping[str, str],
    data: Mapping[str, Any],
    occurred_at: str,
    previous_checksum: str,
) -> dict[str, Any]:
    return signed(
        {
            "schema_version": 1,
            "sequence": sequence,
            "state_revision": state_revision,
            "event_type": event_type,
            **identities,
            "occurred_at": occurred_at,
            "previous_checksum": previous_checksum,
            "data": dict(data),
        }
    )


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid event JSON at {path}:{number}: {exc}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"event at {path}:{number} is not an object")
        verify_signed(event, f"event {number}")
        expected_sequence = len(events) + 1
        if event.get("sequence") != expected_sequence:
            raise ValueError(f"event sequence mismatch at {path}:{number}")
        previous = events[-1]["checksum"] if events else ""
        if event.get("previous_checksum") != previous:
            raise ValueError(f"event checksum chain mismatch at {path}:{number}")
        events.append(event)
    return events


def append_event(path: Path, event: Mapping[str, Any]) -> None:
    events = read_events(path)
    if event.get("sequence") != len(events) + 1:
        raise ValueError("refusing non-sequential event append")
    previous = events[-1]["checksum"] if events else ""
    if event.get("previous_checksum") != previous:
        raise ValueError("refusing event with wrong previous checksum")
    verify_signed(event, "appended event")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.chmod(path, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(event), sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def recover_partial_tail(path: Path, evidence_dir: Path) -> Path | None:
    """Preserve and remove only an unterminated invalid final event fragment."""
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        return None
    if not payload or payload.endswith(b"\n"):
        return None
    boundary = payload.rfind(b"\n") + 1
    prefix, tail = payload[:boundary], payload[boundary:]
    if not tail:
        return None
    try:
        json.loads(tail.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    else:
        return None
    temporary = path.with_name(f".{path.name}.recovery")
    temporary.write_bytes(prefix)
    try:
        read_events(temporary)
    finally:
        temporary.unlink(missing_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    backup = evidence_dir / f"EVENTS.partial.{time.time_ns()}"
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(tail)
        handle.flush()
        os.fsync(handle.fileno())
    with path.open("r+b") as handle:
        handle.truncate(boundary)
        handle.flush()
        os.fsync(handle.fileno())
    return backup
