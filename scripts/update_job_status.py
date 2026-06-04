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

    with status_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    for fields_path in args.merge_status_fields:
        for key, value in load_status_fields(Path(fields_path)).items():
            if key == "state" and not args.allow_state:
                print(
                    "refusing to merge state without --allow-state; use transition_job.py "
                    "for manual state changes",
                    file=sys.stderr,
                )
                return 2
            if not isinstance(key, str) or not key:
                print(f"invalid status key in {fields_path}: {key!r}", file=sys.stderr)
                return 2
            data[key] = value

    for item in args.updates:
        if "=" not in item:
            print(f"expected key=value argument: {item}", file=sys.stderr)
            return 2
        key, raw_value = item.split("=", 1)
        if not key:
            print(f"empty key in argument: {item}", file=sys.stderr)
            return 2
        if key == "state" and not args.allow_state:
            print(
                "refusing state update without --allow-state; use transition_job.py "
                "for manual state changes",
                file=sys.stderr,
            )
            return 2
        data[key] = parse_value(raw_value)

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
