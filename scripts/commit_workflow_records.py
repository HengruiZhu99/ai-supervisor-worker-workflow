#!/usr/bin/env python3
"""Commit AI workflow audit records without mixing in implementation files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


DEFAULT_MESSAGE = "workflow: record ai workflow state"
SUPERVISOR_PATHS = [
    ".ai/metrics",
    ".ai/supervisor/human_reviews",
    "docs",
    "skills",
]
JOB_ID_RE = re.compile(r"(J\d{4,})")


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def git_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    if result.returncode != 0:
        raise SystemExit("commit_workflow_records.py must run inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def job_state(status_path: Path) -> str:
    try:
        return str(json.loads(status_path.read_text(encoding="utf-8")).get("state", ""))
    except (OSError, json.JSONDecodeError):
        return "invalid"


def stable_job_ids(root: Path) -> set[str]:
    stable = set()
    for status_path in sorted((root / ".ai" / "jobs").glob("J*/status.json")):
        if job_state(status_path) not in {"running", "reviewing"}:
            stable.add(status_path.parent.name)
    return stable


def commit_doc_paths(root: Path, stable_jobs: set[str]) -> list[str]:
    paths = []
    for path in sorted((root / ".ai" / "commit_docs").glob("*.md")):
        match = JOB_ID_RE.search(path.name)
        if match and match.group(1) in stable_jobs:
            paths.append(str(path.relative_to(root)))
    return paths


def supervisor_markdown_paths(root: Path, include_design_prompt: bool) -> list[str]:
    paths = []
    supervisor_dir = root / ".ai" / "supervisor"
    for path in sorted(supervisor_dir.glob("*.md")):
        if path.name == "design_prompt.md" and not include_design_prompt:
            continue
        paths.append(str(path.relative_to(root)))
    for path in [
        ".ai/supervisor/HUMAN_REVIEW_REQUIRED.md",
        ".ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md",
        ".ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md",
    ]:
        if path not in paths:
            paths.append(path)
    return paths


def existing_pathspecs(root: Path, include_design_prompt: bool) -> list[str]:
    pathspecs = []
    for job_id in sorted(stable_job_ids(root)):
        pathspecs.append(f".ai/jobs/{job_id}")
    pathspecs.extend(commit_doc_paths(root, stable_job_ids(root)))
    pathspecs.extend(supervisor_markdown_paths(root, include_design_prompt))
    pathspecs.extend(SUPERVISOR_PATHS)

    existing = []
    for path in pathspecs:
        if (root / path).exists():
            existing.append(path)
            continue
        tracked = run(["git", "ls-files", "--error-unmatch", path], root)
        if tracked.returncode == 0:
            existing.append(path)
    return existing


def has_staged_changes(root: Path, pathspecs: list[str]) -> bool:
    result = run(["git", "diff", "--cached", "--quiet", "--", *pathspecs], root)
    return result.returncode == 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--allow-empty", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-design-prompt", action="store_true")
    args = parser.parse_args()

    root = git_root()
    pathspecs = existing_pathspecs(root, args.include_design_prompt)
    if not pathspecs:
        print("No workflow record paths exist.")
        return 0

    add_args = ["git", "add", "-A", "--", *pathspecs]
    if args.dry_run:
        print("Would run: " + " ".join(add_args))
        return 0

    add_result = run(add_args, root)
    if add_result.returncode != 0:
        print(add_result.stderr or add_result.stdout or "failed to stage workflow records")
        return add_result.returncode

    if not has_staged_changes(root, pathspecs) and not args.allow_empty:
        print("No workflow record changes to commit.")
        return 0

    commit_args = ["git", "commit", "-m", args.message, "--", *pathspecs]
    if args.allow_empty:
        commit_args.insert(2, "--allow-empty")
    commit_result = run(commit_args, root)
    output = "\n".join(part for part in [commit_result.stdout.strip(), commit_result.stderr.strip()] if part)
    if output:
        print(output)
    return commit_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
