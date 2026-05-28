#!/usr/bin/env python3
"""Create the next queued AI worker job."""

from __future__ import annotations

import argparse
import json
import subprocess
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--test-command", required=True)
    parser.add_argument("--task-file", required=True)
    args = parser.parse_args()

    root = git_root()
    base_sha = resolve_ref(args.base_ref, root)
    task_source = Path(args.task_file)
    if not task_source.exists():
        raise SystemExit(f"task file does not exist: {task_source}")

    jobs_dir = root / ".ai" / "jobs"
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
    }
    (job_dir / "status.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(job_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
