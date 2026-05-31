#!/usr/bin/env python3
"""Check worker attempt artifacts against canonical worker-loop facts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


NO_COMMIT_RE = re.compile(
    r"\b(no|without)\s+(new\s+)?commits?\b"
    r"|\bno\s+(retry\s+)?commit\s+(was\s+)?created\b"
    r"|\bchanges\s+are\s+left\s+unstaged/uncommitted\b"
    r"|\buncommitted-only\s+work\b",
    re.I,
)
NO_TEST_RE = re.compile(r"\b(no|without)\s+(tests?|validation)\s+(ran|run|executed)\b|tests?\s+not\s+run", re.I)


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def git_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    if result.returncode != 0:
        raise SystemExit("check_attempt_consistency.py must run inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def commit_count(root: Path, base_sha: str, commit: str) -> int:
    if not base_sha or not commit:
        return 0
    try:
        result = run(["git", "rev-list", "--count", f"{base_sha}..{commit}"], root)
    except OSError:
        return 0
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip() or "0")
    except ValueError:
        return 0


def test_log_has_command(text: str) -> bool:
    return any(line.startswith("$ ") for line in text.splitlines())


def consistency_claim_text(text: str) -> str:
    """Return report/doc text worth scanning for attempt-level claims.

    Cursor report capture can include raw token streams, prompt text, old
    rejected attempts, and large copied file contents before the final report.
    The worker loop appends canonical facts after ``## Worker exit``; prefer
    that suffix when available so stale transcript noise does not override
    status.json, the Git attempt range, and the test log.
    """

    marker = "\n## Worker exit"
    index = text.rfind(marker)
    if index != -1:
        return text[index:]
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, help="job directory, for example .ai/jobs/J0001")
    parser.add_argument("--status", required=True, help="status.json path")
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--test-log", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = git_root()
    job_dir = root / args.job
    status = read_json(root / args.status)
    report_text = consistency_claim_text(read_text(root / args.report))
    test_log_text = read_text(root / args.test_log)
    docs = sorted((root / ".ai" / "commit_docs").glob(f"{job_dir.name}_attempt-{args.attempt}_*.md"))
    doc_text = "\n\n".join(consistency_claim_text(read_text(path)) for path in docs)
    docs_names = "\n".join(path.name for path in docs)

    issues: list[str] = []
    commits_in_attempt = commit_count(root / args.worktree, args.base_sha, args.commit)
    status_commit = str(status.get("commit", ""))
    status_test_exit = status.get("test_exit")

    if status_commit and status_commit != args.commit:
        issues.append(f"status.json commit `{status_commit}` differs from final commit `{args.commit}`.")

    if commits_in_attempt > 0:
        if NO_COMMIT_RE.search(report_text):
            issues.append("worker report suggests no commit/uncommitted work, but git history has commits in the attempt range.")
        if NO_COMMIT_RE.search(doc_text) or re.search(r"(no_commit|uncommitted)", docs_names, re.I):
            issues.append("commit documentation suggests no commit/uncommitted work, but git history has commits in the attempt range.")

    if status_test_exit is not None and test_log_has_command(test_log_text):
        if NO_TEST_RE.search(report_text):
            issues.append("worker report says tests/validation did not run, but canonical test log contains a command.")
        if NO_TEST_RE.search(doc_text):
            issues.append("commit documentation says tests/validation did not run, but canonical test log contains a command.")

    if status.get("tests_passed") is True and str(status_test_exit) not in {"0", "0.0"}:
        issues.append("status.json has tests_passed=true but test_exit is not zero.")
    if status.get("tests_passed") is False and str(status_test_exit) == "0":
        issues.append("status.json has tests_passed=false but test_exit is zero.")

    output_lines = [
        "# Attempt Consistency Check",
        "",
        f"- Job: `{job_dir.name}`",
        f"- Attempt: `{args.attempt}`",
        f"- Base SHA: `{args.base_sha}`",
        f"- Commit: `{args.commit}`",
        f"- Commits in attempt range: `{commits_in_attempt}`",
        f"- Test exit: `{status_test_exit}`",
        f"- Commit docs: `{', '.join(path.name for path in docs) or 'none'}`",
        "",
    ]
    if issues:
        output_lines.extend(["## Issues", ""])
        output_lines.extend(f"- {issue}" for issue in issues)
    else:
        output_lines.extend(["## Result", "", "No consistency issues detected."])
    out_path = root / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(output_lines).rstrip() + "\n", encoding="utf-8")
    print(out_path)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
