#!/usr/bin/env python3
"""Summarize accepted-job progress accounting for milestone review."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_job_progress_gate import (  # noqa: E402
    METADATA_LIKE_TYPES,
    Progress,
    extract_progress_block,
    infer_legacy_progress,
    progress_from_block,
)


STATUS_KEYS = {
    "progress_job_type",
    "progress_subsystem",
    "progress_validation_class",
    "progress_metadata_only",
    "progress_new_executable_behavior",
    "progress_capability_target",
    "progress_unlocks_next",
}
EXCEPTION_TYPES = {"human_approved_planning_source", "subsystem_deferred"}
JOB_ID_RE = re.compile(r"^J(?P<num>\d{4,})$")


@dataclass(frozen=True)
class JobProgress:
    job_id: str
    title: str
    state: str
    progress: Progress


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def job_number(job_id: str) -> int | None:
    match = JOB_ID_RE.match(job_id)
    return int(match.group("num")) if match else None


def in_job_range(job_id: str, from_job: str, to_job: str) -> bool:
    number = job_number(job_id)
    if number is None:
        return True
    from_number = job_number(from_job) if from_job else None
    to_number = job_number(to_job) if to_job else None
    if from_number is not None and number < from_number:
        return False
    if to_number is not None and number > to_number:
        return False
    return True


def progress_from_status(status: dict, source: str) -> Progress | None:
    if not STATUS_KEYS.issubset(status):
        return None
    return Progress(
        job_type=str(status.get("progress_job_type", "")),
        subsystem=str(status.get("progress_subsystem", "")),
        capability_target=str(status.get("progress_capability_target", "")),
        new_executable_behavior=parse_bool(status.get("progress_new_executable_behavior")),
        validation_class=str(status.get("progress_validation_class", "")),
        unlocks_next=str(status.get("progress_unlocks_next", "")),
        metadata_only=parse_bool(status.get("progress_metadata_only")),
        exception_type=str(status.get("progress_exception_type", "none") or "none"),
        exception_record=str(status.get("progress_exception_record", "") or ""),
        source=source,
    )


def load_status(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"id": path.parent.name, "state": "invalid"}


def load_job_progress(job_dir: Path) -> JobProgress | None:
    status_path = job_dir / "status.json"
    if not status_path.exists():
        return None
    status = load_status(status_path)
    progress = progress_from_status(status, str(status_path))
    if progress is None:
        task_path = job_dir / "task.md"
        if task_path.exists():
            block = extract_progress_block(task_path.read_text(encoding="utf-8", errors="replace"))
            if block is not None:
                parsed, errors = progress_from_block(block, str(task_path))
                if parsed is not None and not errors:
                    progress = parsed
    if progress is None:
        progress = infer_legacy_progress(job_dir, status)
    return JobProgress(
        job_id=str(status.get("id") or job_dir.name),
        title=str(status.get("title") or ""),
        state=str(status.get("state") or ""),
        progress=progress,
    )


def selected_jobs(jobs_dir: Path, states: set[str], from_job: str, to_job: str) -> list[JobProgress]:
    jobs: list[JobProgress] = []
    for job_dir in sorted(path for path in jobs_dir.glob("J*") if path.is_dir()):
        job = load_job_progress(job_dir)
        if job is None:
            continue
        if job.state not in states:
            continue
        if not in_job_range(job.job_id, from_job, to_job):
            continue
        jobs.append(job)
    return jobs


def summarize(jobs: list[JobProgress]) -> dict[str, object]:
    counts = {
        "total": len(jobs),
        "implementation": 0,
        "numerical_test": 0,
        "backend_test": 0,
        "metadata_like": 0,
        "new_executable_behavior": 0,
        "exceptions": 0,
    }
    rows = []
    for job in jobs:
        progress = job.progress
        if progress.job_type in {"implementation", "numerical_test", "backend_test"}:
            counts[progress.job_type] += 1
        if progress.metadata_like:
            counts["metadata_like"] += 1
        if progress.new_executable_behavior:
            counts["new_executable_behavior"] += 1
        if progress.exception_type in EXCEPTION_TYPES:
            counts["exceptions"] += 1
        rows.append(
            {
                "id": job.job_id,
                "title": job.title,
                "state": job.state,
                "job_type": progress.job_type,
                "subsystem": progress.subsystem,
                "validation_class": progress.validation_class,
                "new_executable_behavior": progress.new_executable_behavior,
                "metadata_only": progress.metadata_only,
                "exception_type": progress.exception_type,
                "exception_record": progress.exception_record,
                "unlocks_next": progress.unlocks_next,
            }
        )
    metadata_only = counts["total"] > 0 and counts["metadata_like"] == counts["total"]
    has_exception = counts["exceptions"] > 0
    warnings = []
    if metadata_only and not has_exception:
        warnings.append(
            "selected accepted jobs appear metadata-only and have no "
            "human-approved planning/source exception"
        )
    return {"counts": counts, "jobs": rows, "warnings": warnings}


def print_table(payload: dict[str, object]) -> None:
    counts = payload["counts"]
    assert isinstance(counts, dict)
    print("# Progress Accounting")
    print()
    print(f"- Jobs counted: {counts['total']}")
    print(f"- Implementation jobs: {counts['implementation']}")
    print(f"- Numerical test jobs: {counts['numerical_test']}")
    print(f"- Backend/device/MPI test jobs: {counts['backend_test']}")
    print(f"- Metadata/audit/docs/visualization/planning jobs: {counts['metadata_like']}")
    print(f"- Jobs with new executable behavior: {counts['new_executable_behavior']}")
    print(f"- Explicit progress exceptions: {counts['exceptions']}")
    warnings = payload["warnings"]
    if isinstance(warnings, list) and warnings:
        print()
        print("## Warnings")
        for warning in warnings:
            print(f"- {warning}")
    rows = payload["jobs"]
    if not isinstance(rows, list) or not rows:
        return
    print()
    print("## Jobs")
    print()
    headers = ["job", "type", "subsystem", "validation", "new_exec", "metadata", "exception"]
    values = [
        [
            str(row["id"]),
            str(row["job_type"]),
            str(row["subsystem"]),
            str(row["validation_class"]),
            str(row["new_executable_behavior"]).lower(),
            str(row["metadata_only"]).lower(),
            str(row["exception_type"]),
        ]
        for row in rows
        if isinstance(row, dict)
    ]
    widths = [max(len(headers[index]), *(len(row[index]) for row in values)) for index in range(len(headers))]
    print("  ".join(headers[index].ljust(widths[index]) for index in range(len(headers))))
    print("  ".join("-" * width for width in widths))
    for row in values:
        print("  ".join(row[index].ljust(widths[index]) for index in range(len(row))))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-dir", type=Path, default=Path(".ai/jobs"))
    parser.add_argument("--state", action="append", default=["accepted"])
    parser.add_argument("--from-job", default="")
    parser.add_argument("--to-job", default="")
    parser.add_argument("--strict", action="store_true", help="exit nonzero on accounting warnings")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a markdown table")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    jobs = selected_jobs(args.jobs_dir, set(args.state), args.from_job, args.to_job)
    payload = summarize(jobs)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_table(payload)
    warnings = payload.get("warnings", [])
    return 1 if args.strict and warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
