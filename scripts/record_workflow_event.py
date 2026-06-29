#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Append a structured workflow event record."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


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


def git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("record_workflow_event.py must run inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def safe_token(value: str) -> str:
    value = value.strip() or "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "unknown"


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def write_json_atomic(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=["failure", "human_intervention", "review_block", "state_transition", "info"])
    parser.add_argument("--role", required=True, choices=["worker", "reviewer", "supervisor", "human", "workflow"])
    parser.add_argument("--reason-code", required=True)
    parser.add_argument("--reason", default="")
    parser.add_argument("--job-id", default="")
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--state", default="")
    parser.add_argument("--blocked-by", action="append", default=[])
    parser.add_argument("--human-intervention-required", action="store_true")
    parser.add_argument("--human-intervention-type", default="")
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--metadata", action="append", default=[], help="extra key=value metadata")
    args = parser.parse_args()

    root = git_root()
    timestamp = utc_now()
    metadata = {}
    for item in args.metadata:
        if "=" not in item:
            raise SystemExit(f"expected --metadata key=value, got {item!r}")
        key, raw = item.split("=", 1)
        metadata[key] = parse_value(raw)

    event_id = "_".join(
        [
            timestamp.replace(":", "").replace("-", ""),
            safe_token(args.job_id or "global"),
            safe_token(args.reason_code),
        ]
    )
    record = {
        "schema_version": 1,
        "event_id": event_id,
        "timestamp": timestamp,
        "kind": args.kind,
        "role": args.role,
        "reason_code": args.reason_code,
        "reason": args.reason,
        "job_id": args.job_id,
        "attempt": args.attempt,
        "state": args.state,
        "blocked_by": args.blocked_by,
        "human_intervention_required": args.human_intervention_required,
        "human_intervention_type": args.human_intervention_type,
        "paths": args.path,
        "metadata": metadata,
    }
    out_path = root / ".ai" / "metrics" / "events" / f"{event_id}.json"
    write_json_atomic(out_path, record)
    append_jsonl(root / ".ai" / "metrics" / "events.jsonl", record)
    print(out_path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
