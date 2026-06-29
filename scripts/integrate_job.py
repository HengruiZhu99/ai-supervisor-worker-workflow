#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Verify and optionally integrate a reviewed worker job branch."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def git_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    if result.returncode != 0:
        raise SystemExit("integrate_job.py must run inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def load_status(root: Path, job_id: str) -> tuple[Path, dict]:
    job = root / ".ai" / "jobs" / job_id
    status_path = job / "status.json"
    if not status_path.exists():
        raise SystemExit(f"status file does not exist: {status_path}")
    return job, json.loads(status_path.read_text(encoding="utf-8"))


def require_clean_main(root: Path) -> list[str]:
    result = run(["git", "status", "--porcelain"], root)
    if result.returncode != 0:
        return [result.stderr.strip() or "git status failed"]
    if result.stdout.strip():
        return ["main worktree has uncommitted changes; integrate only from a clean checkout"]
    return []


def progress_gate(root: Path, job: Path) -> tuple[dict | None, list[str]]:
    task = job / "task.md"
    if not task.exists():
        return None, [f"{job.name}: missing task.md for progress gate"]
    script = root / "scripts" / "check_job_progress_gate.py"
    result = run(
        [sys.executable, str(script), str(task), "--jobs-dir", str(root / ".ai" / "jobs"), "--json"],
        root,
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    try:
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    if result.returncode != 0:
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if isinstance(errors, list) and errors:
            return payload, [str(error) for error in errors]
        return payload, [output or f"{job.name}: progress gate failed"]
    fields = payload.get("status_fields") if isinstance(payload, dict) else None
    if not isinstance(fields, dict) or not fields:
        return payload, [f"{job.name}: progress gate did not emit status_fields"]
    return payload, []


def verify(root: Path, job: Path, status: dict) -> list[str]:
    errors: list[str] = []
    job_id = status.get("id") or job.name
    state = status.get("state")
    base_sha = status.get("base_sha")
    branch = status.get("branch")
    commit = status.get("commit")
    attempt = status.get("attempt")
    if state not in {"ready_for_review", "accepted"}:
        errors.append(f"{job_id}: state is {state!r}, expected ready_for_review before integration")
    for key, value in [("base_sha", base_sha), ("branch", branch), ("commit", commit), ("attempt", attempt)]:
        if value in {"", None}:
            errors.append(f"{job_id}: missing {key}")
    if status.get("tests_passed") is not True:
        errors.append(f"{job_id}: tests_passed is not true")
    if status.get("reviewers_enabled") is True and status.get("reviewers_complete") is not True:
        errors.append(f"{job_id}: reviewers_complete is not true")
    if status.get("reviewer_a_blocks") is True or status.get("reviewer_b_blocks") is True:
        errors.append(f"{job_id}: at least one reviewer blocks acceptance")
    if status.get("post_test_dirty") is True:
        errors.append(f"{job_id}: post_test_dirty is true")
    if status.get("attempt_consistency_exit") not in {0, None}:
        errors.append(f"{job_id}: attempt consistency check failed")
    if base_sha and commit:
        ancestor = run(["git", "merge-base", "--is-ancestor", str(base_sha), str(commit)], root)
        if ancestor.returncode != 0:
            errors.append(f"{job_id}: base_sha is not an ancestor of commit")
    if branch:
        exists = run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], root)
        if exists.returncode != 0:
            errors.append(f"{job_id}: branch does not exist: {branch}")
    if attempt:
        for required in [
            job / f"changed_files.attempt-{attempt}.txt",
            job / f"diffstat.attempt-{attempt}.txt",
            job / "report.md",
        ]:
            if not required.exists():
                errors.append(f"{job_id}: missing artifact {required}")
    progress_payload, progress_errors = progress_gate(root, job)
    errors.extend(progress_errors)
    if progress_payload:
        fields = progress_payload.get("status_fields", {})
        if isinstance(fields, dict):
            for key, value in fields.items():
                if key in status and status.get(key) != value:
                    errors.append(
                        f"{job_id}: stored {key}={status.get(key)!r} does not match "
                        f"progress gate value {value!r}"
                    )
    return errors


def print_summary(root: Path, job: Path, status: dict) -> None:
    job_id = status.get("id") or job.name
    base_sha = status.get("base_sha")
    commit = status.get("commit")
    branch = status.get("branch")
    print(f"job={job_id}")
    print(f"state={status.get('state')}")
    print(f"branch={branch}")
    print(f"base_sha={base_sha}")
    print(f"commit={commit}")
    progress_fields = {
        key: status.get(key, "")
        for key in [
            "progress_job_type",
            "progress_subsystem",
            "progress_validation_class",
            "progress_new_executable_behavior",
            "progress_metadata_only",
            "progress_exception_type",
        ]
        if key in status
    }
    if progress_fields:
        print("progress=" + json.dumps(progress_fields, sort_keys=True))
    if base_sha and commit:
        stat = run(["git", "diff", "--stat", f"{base_sha}..{commit}"], root)
        if stat.stdout:
            print()
            print(stat.stdout.rstrip())


def integrate(root: Path, status: dict, method: str) -> int:
    branch = str(status["branch"])
    job_id = str(status.get("id") or branch)
    if method == "merge":
        result = run(["git", "merge", "--no-ff", branch, "-m", f"integrate {job_id}"], root)
    elif method == "ff-only":
        result = run(["git", "merge", "--ff-only", branch], root)
    else:
        result = run(["git", "cherry-pick", f"{status['base_sha']}..{status['commit']}"], root)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", help="job id such as J0001")
    parser.add_argument("--apply", action="store_true", help="integrate after verification")
    parser.add_argument("--method", choices=["merge", "ff-only", "cherry-pick"], default="merge")
    args = parser.parse_args()

    root = git_root()
    job, status = load_status(root, args.job_id)
    errors = verify(root, job, status)
    if args.apply:
        errors.extend(require_clean_main(root))
    print_summary(root, job, status)
    if errors:
        print()
        print("Integration check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    if not args.apply:
        print()
        print("Integration check passed. Re-run with --apply to integrate.")
        return 0
    return integrate(root, status, args.method)


if __name__ == "__main__":
    raise SystemExit(main())
