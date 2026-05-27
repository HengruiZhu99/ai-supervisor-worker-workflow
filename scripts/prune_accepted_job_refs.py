#!/usr/bin/env python3
"""Prune accepted worker branches/worktrees after human milestone approval."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


JOB_RE = re.compile(r"\bJ\d{4,}\b")


def run(args: list[str], cwd: Path, check: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"command failed: {' '.join(args)}")
    return result


def git_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    if result.returncode != 0:
        raise SystemExit("must run inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def unique(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def review_is_approved(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(re.search(r"^- Result:\s+`approved`", text, re.MULTILINE))


def jobs_from_review(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return unique(JOB_RE.findall(text))


def approved_review_records(root: Path) -> list[Path]:
    reviews = sorted((root / ".ai" / "supervisor" / "human_reviews").glob("human_review_*.md"))
    return [path for path in reviews if review_is_approved(path)]


def read_status(root: Path, job_id: str) -> dict:
    status_path = root / ".ai" / "jobs" / job_id / "status.json"
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"id": job_id, "state": "missing_or_invalid"}


def branch_exists(root: Path, branch: str) -> bool:
    return run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], root).returncode == 0


def worktree_paths_for_branch(root: Path, branch: str) -> list[Path]:
    result = run(["git", "worktree", "list", "--porcelain"], root)
    if result.returncode != 0:
        return []
    paths = []
    current_path: Path | None = None
    current_branch = ""
    for line in result.stdout.splitlines() + [""]:
        if not line:
            if current_path and current_branch == f"refs/heads/{branch}":
                paths.append(current_path)
            current_path = None
            current_branch = ""
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current_path = Path(value)
        elif key == "branch":
            current_branch = value
    return paths


def prune_job(root: Path, job_id: str, dry_run: bool) -> list[str]:
    status = read_status(root, job_id)
    state = status.get("state", "")
    branch = status.get("branch") or f"ai/{job_id}"
    messages = []

    if state != "accepted":
        return [f"skip {job_id}: state is {state!r}, not accepted"]

    default_worktree = root / ".worktrees" / job_id
    worktree_paths = unique([str(path) for path in worktree_paths_for_branch(root, branch)])
    if default_worktree.exists() and str(default_worktree) not in worktree_paths:
        worktree_paths.append(str(default_worktree))

    for worktree in worktree_paths:
        path = Path(worktree)
        if path.resolve() == root:
            messages.append(f"skip worktree for {job_id}: refusing to remove repository root")
            continue
        if dry_run:
            messages.append(f"would remove worktree {path}")
            continue
        result = run(["git", "worktree", "remove", "--force", str(path)], root)
        if result.returncode == 0:
            messages.append(f"removed worktree {path}")
        else:
            messages.append(f"failed to remove worktree {path}: {result.stderr.strip() or result.stdout.strip()}")

    if branch_exists(root, branch):
        if dry_run:
            messages.append(f"would delete branch {branch}")
        else:
            still_attached = [path for path in worktree_paths_for_branch(root, branch) if path.resolve() != root]
            if still_attached:
                messages.append(f"skip branch {branch}: still attached to worktree(s) {', '.join(map(str, still_attached))}")
                return messages
            result = run(["git", "branch", "-D", branch], root)
            if result.returncode == 0:
                messages.append(f"deleted branch {branch}")
            else:
                messages.append(f"failed to delete branch {branch}: {result.stderr.strip() or result.stdout.strip()}")
    else:
        messages.append(f"branch {branch} already absent")

    return messages or [f"nothing to prune for {job_id}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-record", action="append", default=[], help="approved human review record to prune from")
    parser.add_argument("--all-approved-reviews", action="store_true", help="prune jobs listed in every approved review record")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = git_root()
    records = [Path(path) for path in args.review_record]
    if args.all_approved_reviews:
        records.extend(approved_review_records(root))
    records = unique([str((root / path).resolve() if not path.is_absolute() else path.resolve()) for path in records])

    if not records:
        print("No review records supplied.")
        return 0

    job_ids: list[str] = []
    for record_text in records:
        record = Path(record_text)
        if not record.exists():
            print(f"skip missing review record: {record}")
            continue
        if not review_is_approved(record):
            print(f"skip non-approved review record: {record}")
            continue
        job_ids.extend(jobs_from_review(record))

    job_ids = unique(job_ids)
    if not job_ids:
        print("No accepted job ids found in approved review records.")
        return 0

    for job_id in job_ids:
        for message in prune_job(root, job_id, args.dry_run):
            print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
