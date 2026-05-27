#!/usr/bin/env python3
"""Atomically update a job status.json file."""

from __future__ import annotations

import json
import os
import sys
import tempfile
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


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "Usage: python3 scripts/update_job_status.py STATUS_JSON key=value ...",
            file=sys.stderr,
        )
        return 2

    status_path = Path(sys.argv[1])
    if not status_path.exists():
        print(f"status file does not exist: {status_path}", file=sys.stderr)
        return 1

    with status_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    for item in sys.argv[2:]:
        if "=" not in item:
            print(f"expected key=value argument: {item}", file=sys.stderr)
            return 2
        key, raw_value = item.split("=", 1)
        if not key:
            print(f"empty key in argument: {item}", file=sys.stderr)
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

