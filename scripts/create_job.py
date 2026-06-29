#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Create the next queued AI worker job."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("create_job.py must be run from inside a Git repository")
    root = Path(result.stdout.strip()).resolve()
    if Path.cwd().resolve() != root:
        raise SystemExit(f"run create_job.py from the repository root: {root}")
    return root


def next_job_id(jobs_dir: Path) -> str:
    jobs_dir.mkdir(parents=True, exist_ok=True)
    used = set()
    for path in jobs_dir.iterdir():
        if path.is_dir() and path.name.startswith("J"):
            suffix = path.name[1:]
            if suffix.isdigit():
                used.add(int(suffix))
    candidate = 1
    while candidate in used:
        candidate += 1
    return f"J{candidate:04d}"


def resolve_ref(ref: str, root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"failed to resolve base ref {ref!r}: {result.stderr.strip()}")
    return result.stdout.strip()


def run_progress_gate(root: Path, task_source: Path, jobs_dir: Path) -> dict[str, object]:
    gate = root / "scripts" / "check_job_progress_gate.py"
    result = subprocess.run(
        [sys.executable, str(gate), str(task_source), "--jobs-dir", str(jobs_dir), "--json"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.stdout.rstrip() or "job progress gate failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"job progress gate emitted invalid JSON: {exc}") from exc
    fields = payload.get("status_fields")
    if not isinstance(fields, dict) or not fields:
        raise SystemExit("job progress gate did not emit status_fields")
    return fields


ACTIVE_JOB_STATES = {"queued", "running", "needs_review", "reviewing", "blocked"}


def active_jobs(jobs_dir: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if not jobs_dir.exists():
        return found
    for status_path in sorted(jobs_dir.glob("J*/status.json")):
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        state = str(data.get("state", ""))
        if state in ACTIVE_JOB_STATES:
            found.append((str(data.get("id", status_path.parent.name)), state))
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--test-command", required=True)
    parser.add_argument("--task-file", required=True)
    parser.add_argument(
        "--allow-concurrent",
        action="store_true",
        help=(
            "Create the job even though another job is in an active state. "
            "Without this flag, creation is refused while any job is queued/"
            "running/under review, which prevents accidental duplicate "
            "dispatch (e.g. the 2026-06-11 J0305 duplicate of running J0304)."
        ),
    )
    args = parser.parse_args()

    root = git_root()
    base_sha = resolve_ref(args.base_ref, root)
    task_source = Path(args.task_file)
    if not task_source.exists():
        raise SystemExit(f"task file does not exist: {task_source}")

    jobs_dir = root / ".ai" / "jobs"
    # Parallel dispatch can also be enabled globally (e.g. by the supervisor loop
    # or dashboard) via AI_WORKFLOW_ALLOW_CONCURRENT=1, without passing the flag
    # on every invocation.
    allow_concurrent = args.allow_concurrent or os.environ.get("AI_WORKFLOW_ALLOW_CONCURRENT") == "1"
    blockers = active_jobs(jobs_dir)
    if not allow_concurrent:
        if blockers:
            summary = ", ".join(f"{job_id}={state}" for job_id, state in blockers)
            raise SystemExit(
                "refusing to create a new job while active jobs exist: "
                f"{summary}. Resolve them first or pass --allow-concurrent "
                "(or set AI_WORKFLOW_ALLOW_CONCURRENT=1) if parallel dispatch is "
                "intentional."
            )
    else:
        # Even in concurrent mode, keep dispatch bounded so a runaway supervisor
        # cannot flood the worker pool. AI_WORKFLOW_MAX_PARALLEL_JOBS=0 (default)
        # leaves it unbounded; set it to match WORKER_MAX_PARALLEL_JOBS.
        try:
            max_parallel = int(os.environ.get("AI_WORKFLOW_MAX_PARALLEL_JOBS", "0"))
        except ValueError:
            max_parallel = 0
        if max_parallel > 0 and len(blockers) >= max_parallel:
            summary = ", ".join(f"{job_id}={state}" for job_id, state in blockers)
            raise SystemExit(
                f"refusing to create a new job: {len(blockers)} active jobs "
                f">= AI_WORKFLOW_MAX_PARALLEL_JOBS={max_parallel} ({summary}). "
                "Wait for an active job to finish or raise the cap."
            )
    progress_fields = run_progress_gate(root, task_source, jobs_dir)
    job_id = next_job_id(jobs_dir)
    job_dir = jobs_dir / job_id
    job_dir.mkdir()

    task_text = task_source.read_text(encoding="utf-8")
    (job_dir / "task.md").write_text(task_text, encoding="utf-8")

    now = utc_now()
    status = {
        "id": job_id,
        "title": args.title,
        "state": "queued",
        "attempt": 0,
        "base_ref": args.base_ref,
        "base_sha": base_sha,
        "branch": f"ai/{job_id}",
        "test_command": args.test_command,
        "created_at": now,
        "updated_at": now,
        "progress_gate_exit": 0,
        "progress_gate_checked_at": now,
    }
    status.update(progress_fields)
    (job_dir / "status.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(job_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
