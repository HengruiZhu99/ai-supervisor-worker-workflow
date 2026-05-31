#!/usr/bin/env python3
"""Render a canonical worker report from facts plus structured handoff JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_text(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def read_json(path: str | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def bool_text(value: str) -> str:
    return "true" if str(value).lower() in {"1", "true", "yes"} else "false"


def section(title: str, body: str) -> str:
    return f"## {title}\n\n{body.strip() if body.strip() else 'None.'}\n\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--worker-exit", required=True)
    parser.add_argument("--worker-error", default="")
    parser.add_argument("--test-command", default="")
    parser.add_argument("--test-exit", required=True)
    parser.add_argument("--test-log", required=True)
    parser.add_argument("--final-commit", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--changed-files", required=True)
    parser.add_argument("--handoff-json", required=True)
    parser.add_argument("--raw-transcript", required=True)
    parser.add_argument("--post-test-dirty", required=True)
    parser.add_argument("--post-test-status", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    handoff = read_json(args.handoff_json)
    changed_files = read_text(args.changed_files)
    worker_error = args.worker_error.strip() or "None."
    test_command = args.test_command.strip() or "No test command specified."
    post_test_status = read_text(args.post_test_status)
    post_test_body = (
        f"post_test_dirty: {bool_text(args.post_test_dirty)}\n\n"
        f"{post_test_status if post_test_status else 'No undeclared post-test dirty files.'}"
    )

    body = f"""# Worker Report: {args.job_id} Attempt {args.attempt}

This report is generated from canonical workflow facts plus the worker's
structured handoff.  The raw worker transcript is intentionally not embedded
because it may contain stale intermediate claims, copied feedback, or token
stream noise.

## Canonical Attempt Facts

- Job id: `{args.job_id}`
- Attempt: `{args.attempt}`
- Base commit: `{args.base_sha}`
- Final commit: `{args.final_commit}`
- Worker exit: `{args.worker_exit}`
- Worker error: {worker_error}
- Test exit: `{args.test_exit}`
- Test log: `{args.test_log}`
- Raw transcript: `{args.raw_transcript}`
- Structured handoff: `{args.handoff_json}`
- Handoff quality: `{handoff.get('handoff_quality', 'unknown')}`

## Test Command

```bash
{test_command}
```

## Changed Files

```text
{changed_files or 'No changed files recorded.'}
```

## Post-Test Dirty Status

```text
{post_test_body}
```

"""
    body += section("Worker Handoff Summary", str(handoff.get("summary", "")))
    body += section("Worker-Reported Files Changed", str(handoff.get("files_changed", "")))
    body += section("Worker-Reported Commits Made", str(handoff.get("commits_made", "")))
    body += section("Worker-Reported Tests", str(handoff.get("tests_run", "")))
    body += section("Scientific Assumptions", str(handoff.get("scientific_assumptions", "")))
    body += section("Known Limitations", str(handoff.get("known_limitations", "")))
    body += section("Suggested Follow-Up", str(handoff.get("suggested_follow_up", "")))
    body += section("Workflow Friction", str(handoff.get("workflow_friction", "")))
    body += section("Skill Suggestions", str(handoff.get("skill_suggestions", "")))
    body += """## Raw Transcript Policy

The raw transcript is kept separately for audit and debugging.  Reviewers and
the supervisor should treat canonical facts in this report, `status.json`, Git
history, test logs, changed-file lists, and diff artifacts as authoritative.
"""

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body.rstrip() + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
