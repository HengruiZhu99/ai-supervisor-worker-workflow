#!/usr/bin/env python3
"""Print a compact table of AI worker jobs."""

from __future__ import annotations

import json
from pathlib import Path


COLUMNS = [
    ("job id", "id"),
    ("state", "state"),
    ("attempt", "attempt"),
    ("title", "title"),
    ("tests_passed", "tests_passed"),
    ("branch", "branch"),
    ("updated_at", "updated_at"),
]


def read_status(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return {"id": path.parent.name, "state": f"invalid: {exc}"}


def main() -> int:
    jobs_dir = Path(".ai/jobs")
    if not jobs_dir.exists():
        print("No jobs found")
        return 0

    rows = []
    for job_dir in sorted(path for path in jobs_dir.iterdir() if path.is_dir()):
        status_path = job_dir / "status.json"
        if status_path.exists():
            data = read_status(status_path)
        else:
            data = {"id": job_dir.name, "state": "missing status.json"}
        rows.append([str(data.get(key, "")) for _, key in COLUMNS])

    if not rows:
        print("No jobs found")
        return 0

    headers = [label for label, _ in COLUMNS]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    print("  ".join(headers[index].ljust(widths[index]) for index in range(len(headers))))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(row[index].ljust(widths[index]) for index in range(len(row))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

