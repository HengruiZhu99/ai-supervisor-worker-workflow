#!/usr/bin/env python3
"""Commit AI workflow audit records without mixing in implementation files."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


DEFAULT_MESSAGE = "workflow: record ai workflow state"
DEFAULT_PATHS = [
    ".ai/jobs",
    ".ai/commit_docs",
    ".ai/supervisor/ledger.md",
    ".ai/supervisor/roadmap.md",
    ".ai/supervisor/HUMAN_REVIEW_REQUIRED.md",
    ".ai/supervisor/human_reviews",
]


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def git_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    if result.returncode != 0:
        raise SystemExit("commit_workflow_records.py must run inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def existing_pathspecs(root: Path) -> list[str]:
    pathspecs = []
    for path in DEFAULT_PATHS:
        if (root / path).exists():
            pathspecs.append(path)
            continue
        tracked = run(["git", "ls-files", "--error-unmatch", path], root)
        if tracked.returncode == 0:
            pathspecs.append(path)
    return pathspecs


def has_staged_changes(root: Path, pathspecs: list[str]) -> bool:
    result = run(["git", "diff", "--cached", "--quiet", "--", *pathspecs], root)
    return result.returncode == 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--allow-empty", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = git_root()
    pathspecs = existing_pathspecs(root)
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
