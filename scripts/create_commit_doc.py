#!/usr/bin/env python3
"""Create markdown documentation for a worker attempt commit."""

from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--test-command", required=True)
    parser.add_argument("--test-exit", required=True, type=int)
    parser.add_argument("--test-log", required=True)
    parser.add_argument("--summary-file", required=True)
    args = parser.parse_args()

    commit = args.commit
    _, subject = run_git(["show", "-s", "--format=%s", commit])
    _, commit_date = run_git(["show", "-s", "--format=%cI", commit])
    _, files_changed = run_git(["diff-tree", "--no-commit-id", "--name-only", "-r", commit])
    _, diff_stat = run_git(["show", "--stat", "--oneline", "--no-renames", commit])

    summary = read_text(args.summary_file)
    limitations = extract_section(summary, ("known limitations", "follow-up", "follow up"))
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

## Diff stat

```text
{diff_stat or "Unknown"}
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

## Summary

{summary or "No summary file available."}

## Known limitations / follow-up

{limitations or "See summary above."}
"""
    out_path.write_text(body, encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

