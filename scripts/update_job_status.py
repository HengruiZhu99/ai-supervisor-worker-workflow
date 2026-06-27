#!/usr/bin/env python3
"""Atomically update a job status.json file."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import argparse
from datetime import datetime, timezone
from pathlib import Path


TERMINAL_STATES = {"accepted", "cancelled", "superseded"}


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


def load_status_fields(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"failed to read status fields JSON {path}: {exc}") from exc
    fields = payload.get("status_fields", payload)
    if not isinstance(fields, dict):
        raise SystemExit(f"status fields JSON must contain an object: {path}")
    return fields


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-state",
        action="store_true",
        help="allow explicit state=... updates; prefer transition_job.py for manual state changes",
    )
    parser.add_argument(
        "--allow-terminal-state-overwrite",
        action="store_true",
        help=(
            "allow changing an existing terminal state; intended only for explicit "
            "manual state repair"
        ),
    )
    parser.add_argument(
        "--merge-status-fields",
        action="append",
        default=[],
        metavar="JSON",
        help="merge status_fields from a JSON file, such as check_job_progress_gate.py --json output",
    )
    parser.add_argument("status_json")
    parser.add_argument("updates", nargs="*", help="key=value fields")
    args = parser.parse_args()

    status_path = Path(args.status_json)
    if not status_path.exists():
        print(f"status file does not exist: {status_path}", file=sys.stderr)
        return 1

    try:
        with status_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        # A corrupt status.json must fail loudly with an actionable message
        # instead of an uncaught traceback that stalls the loop on a confusing
        # stack trace. Recovery is a deliberate manual repair of the file.
        print(
            f"corrupt status file {status_path} is not valid JSON: {exc}; "
            "repair the file manually before retrying",
            file=sys.stderr,
        )
        return 4
    if not isinstance(data, dict):
        print(
            f"status file {status_path} must contain a JSON object, got "
            f"{type(data).__name__}",
            file=sys.stderr,
        )
        return 4

    old_state = str(data.get("state", ""))

    def validate_state_update(value: object) -> int:
        if not args.allow_state:
            print(
                "refusing state update without --allow-state; use transition_job.py "
                "for manual state changes",
                file=sys.stderr,
            )
            return 2
        new_state = str(value)
        if (
            old_state in TERMINAL_STATES
            and new_state != old_state
            and not args.allow_terminal_state_overwrite
        ):
            print(
                f"refusing to change terminal state {old_state!r} to {new_state!r} "
                "without --allow-terminal-state-overwrite",
                file=sys.stderr,
            )
            return 3
        return 0

    for fields_path in args.merge_status_fields:
        for key, value in load_status_fields(Path(fields_path)).items():
            if not isinstance(key, str) or not key:
                print(f"invalid status key in {fields_path}: {key!r}", file=sys.stderr)
                return 2
            if key == "state":
                state_validation = validate_state_update(value)
                if state_validation:
                    return state_validation
            data[key] = value

    for item in args.updates:
        if "=" not in item:
            print(f"expected key=value argument: {item}", file=sys.stderr)
            return 2
        key, raw_value = item.split("=", 1)
        if not key:
            print(f"empty key in argument: {item}", file=sys.stderr)
            return 2
        value = parse_value(raw_value)
        if key == "state":
            state_validation = validate_state_update(value)
            if state_validation:
                return state_validation
        data[key] = value

    data["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    status_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{status_path.name}.", suffix=".tmp", dir=str(status_path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, status_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
