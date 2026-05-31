#!/usr/bin/env python3
"""Validate and apply a job state transition."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_TRANSITIONS = {
    "queued": {"running", "cancelled", "superseded"},
    "rejected": {"running", "cancelled", "superseded"},
    "running": {"implemented", "reviewing", "ready_for_review", "blocked", "queued", "cancelled", "superseded"},
    "implemented": {"reviewing", "ready_for_review", "blocked", "cancelled", "superseded"},
    "reviewing": {"ready_for_review", "review_failed", "review_timeout", "blocked", "cancelled", "superseded"},
    "ready_for_review": {"accepted", "rejected", "reviewing", "cancelled", "superseded"},
    "review_failed": {"reviewing", "ready_for_review", "rejected", "blocked", "cancelled", "superseded"},
    "review_timeout": {"reviewing", "rejected", "blocked", "cancelled", "superseded"},
    "blocked": {"queued", "rejected", "reviewing", "cancelled", "superseded"},
    "accepted": set(),
    "cancelled": set(),
    "superseded": set(),
}

CLEAR_ON_RUNNING = [
    "worker_error",
    "supervisor_decision",
    "review_decision",
    "review_notes",
    "reviewed_at",
    "reviewer_a_exit",
    "reviewer_b_exit",
    "reviewer_coverage_exit",
    "reviewer_decision_exit",
    "reviewers_complete",
    "reviewer_a_blocks",
    "reviewer_b_blocks",
    "review_blocked_by",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_value(raw: str):
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def write_json_atomic(path: Path, data: dict) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("status_json")
    parser.add_argument("state")
    parser.add_argument("updates", nargs="*", help="extra key=value fields")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--reason-code", default="")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    status_path = Path(args.status_json)
    if not status_path.exists():
        raise SystemExit(f"status file does not exist: {status_path}")
    data = json.loads(status_path.read_text(encoding="utf-8"))
    old_state = str(data.get("state", ""))
    new_state = args.state
    if new_state not in ALLOWED_TRANSITIONS:
        raise SystemExit(f"unknown target state: {new_state}")
    if not args.force and old_state and new_state != old_state and new_state not in ALLOWED_TRANSITIONS.get(old_state, set()):
        raise SystemExit(f"invalid transition: {old_state} -> {new_state}")

    if new_state == "running":
        for key in CLEAR_ON_RUNNING:
            data.pop(key, None)

    for item in args.updates:
        if "=" not in item:
            raise SystemExit(f"expected key=value update, got {item!r}")
        key, raw = item.split("=", 1)
        data[key] = parse_value(raw)

    data["state"] = new_state
    if args.reason_code:
        data["last_transition_reason_code"] = args.reason_code
    if args.reason:
        data["last_transition_reason"] = args.reason
    data["previous_state"] = old_state
    data["updated_at"] = utc_now()
    write_json_atomic(status_path, data)
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
