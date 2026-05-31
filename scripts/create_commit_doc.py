#!/usr/bin/env python3
"""Create markdown documentation for a worker attempt commit."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def run_git(args: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        ["git", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output = result.stdout.strip()
    if result.returncode != 0 and result.stderr.strip():
        output = result.stderr.strip()
    return result.returncode, output


def read_text(path: str | None) -> str:
    if not path:
        return ""
    file_path = Path(path)
    try:
        return file_path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"Unable to read {file_path}: {exc}"


def tail_text(path: str | None, lines: int = 80) -> str:
    text = read_text(path)
    if not text:
        return ""
    split = text.splitlines()
    return "\n".join(split[-lines:])


def extract_section(summary: str, names: tuple[str, ...]) -> str:
    lines = summary.splitlines()
    capture = False
    captured = []
    for line in lines:
        stripped = line.strip().lower()
        is_heading = stripped.startswith("#")
        if is_heading:
            heading_text = stripped.lstrip("#").strip()
            if any(name in heading_text for name in names):
                capture = True
                continue
            if capture:
                break
        elif capture:
            captured.append(line)
    return "\n".join(captured).strip()


def read_json(path: str | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--test-command", required=True)
    parser.add_argument("--test-exit", required=True, type=int)
    parser.add_argument("--test-log", required=True)
    parser.add_argument("--summary-file", default="")
    parser.add_argument("--handoff-json", default="")
    args = parser.parse_args()

    commit = args.commit
    _, subject = run_git(["show", "-s", "--format=%s", commit])
    _, commit_date = run_git(["show", "-s", "--format=%cI", commit])
    _, files_changed = run_git(["diff-tree", "--no-commit-id", "--name-only", "-r", commit])
    _, diff_stat = run_git(["show", "--stat", "--oneline", "--no-renames", commit])
    commit_range = f"{args.base_sha}..{commit}" if args.base_sha else commit
    _, attempt_commits = run_git(["log", "--oneline", "--decorate", commit_range])
    _, attempt_files = run_git(["diff", "--name-status", commit_range])
    _, attempt_stat = run_git(["diff", "--stat", commit_range])

    handoff = read_json(args.handoff_json)
    if handoff:
        summary = str(handoff.get("summary", "")).strip()
        limitations = "\n\n".join(
            value for value in [
                str(handoff.get("known_limitations", "")).strip(),
                str(handoff.get("suggested_follow_up", "")).strip(),
            ]
            if value
        )
        workflow_friction = str(handoff.get("workflow_friction", "")).strip() or "None reported."
        skill_suggestions = str(handoff.get("skill_suggestions", "")).strip() or "None reported."
    else:
        summary = read_text(args.summary_file)
        limitations = extract_section(summary, ("known limitations", "follow-up", "follow up"))
        workflow_friction = "See legacy summary above."
        skill_suggestions = "See legacy summary above."
    log_tail = tail_text(args.test_log)

    docs_dir = Path(".ai/commit_docs")
    docs_dir.mkdir(parents=True, exist_ok=True)
    out_path = docs_dir / f"{args.job_id}_attempt-{args.attempt}_{commit}.md"

    body = f"""# Commit Documentation: {args.job_id} Attempt {args.attempt}

## Job id

{args.job_id}

## Attempt

{args.attempt}

## Branch

{args.branch}

## Attempt commit range

{commit_range}

## Commit hash

{commit}

## Commit subject

{subject or "Unknown"}

## Commit date

{commit_date or "Unknown"}

## Files changed

```text
{files_changed or "Unknown"}
```

## Attempt commits

```text
{attempt_commits or "Unknown"}
```

## Attempt files changed

```text
{attempt_files or "Unknown"}
```

## Diff stat

```text
{diff_stat or "Unknown"}
```

## Attempt diff stat

```text
{attempt_stat or "Unknown"}
```

## Test command

```bash
{args.test_command}
```

## Test exit code

{args.test_exit}

## Test log path

{args.test_log}

## Test log tail

```text
{log_tail or "No test log available."}
```

## Worker Handoff

- Structured handoff: `{args.handoff_json or "not available"}`
- Handoff quality: `{handoff.get("handoff_quality", "unknown") if handoff else "legacy raw summary"}`

## Worker Handoff Summary

{summary or "No structured summary available."}

## Known limitations / follow-up

{limitations or "None reported."}

## Workflow Friction

{workflow_friction}

## Skill Suggestions

{skill_suggestions}
"""
    out_path.write_text(body, encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
