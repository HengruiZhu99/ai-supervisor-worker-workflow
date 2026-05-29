#!/usr/bin/env python3
"""Append reviewed workflow-improvement proposals or decisions to supervisor records."""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path


QUEUE_PATH = Path(".ai/supervisor/workflow_improvement_queue.md")
DECISIONS_PATH = Path(".ai/supervisor/skill_decisions.md")
VALID_CATEGORIES = {"skill", "template", "script", "protocol", "checklist", "docs", "ledger", "other"}
VALID_SCOPES = {"project", "general", "both", "unknown"}
VALID_STATUSES = {"proposed", "accepted", "created", "updated", "deferred", "rejected"}


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def git_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        raise SystemExit("record_workflow_improvement.py must run inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def next_id(path: Path) -> str:
    prefix = "WFI-"
    highest = 0
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## WFI-"):
                token = line.split()[1]
                try:
                    highest = max(highest, int(token.removeprefix(prefix)))
                except ValueError:
                    pass
    return f"{prefix}{highest + 1:04d}"


def ensure_header(path: Path, title: str, intro: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n{intro.rstrip()}\n\n", encoding="utf-8")


def read_optional(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        return f"Unable to read `{path}`: {exc}"


def append_entry(path: Path, entry_id: str, args: argparse.Namespace, body: str) -> None:
    lines = [
        f"## {entry_id}: {args.title}",
        "",
        f"- Recorded at: `{utc_now()}`",
        f"- Source: `{args.source}`",
        f"- Category: `{args.category}`",
        f"- Scope: `{args.scope}`",
        f"- Status: `{args.status}`",
        "",
        "### Rationale",
        "",
        args.rationale.strip() or "Not provided.",
        "",
        "### Proposed Change",
        "",
        args.proposed_change.strip() or "Not provided.",
        "",
        "### Supervisor Decision",
        "",
        args.decision.strip() or "Pending supervisor decision.",
    ]
    if body:
        lines.extend(["", "### Supporting Notes", "", body])
    lines.append("")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="short title for the improvement")
    parser.add_argument("--source", required=True, help="where the suggestion came from, e.g. job:J0040/reviewer-a")
    parser.add_argument("--category", choices=sorted(VALID_CATEGORIES), required=True)
    parser.add_argument("--scope", choices=sorted(VALID_SCOPES), default="unknown")
    parser.add_argument("--status", choices=sorted(VALID_STATUSES), default="proposed")
    parser.add_argument("--rationale", default="")
    parser.add_argument("--proposed-change", default="")
    parser.add_argument("--decision", default="")
    parser.add_argument("--notes-file", help="optional file with supporting reviewer/worker notes")
    parser.add_argument(
        "--decision-log",
        action="store_true",
        help="also append the entry to .ai/supervisor/skill_decisions.md",
    )
    args = parser.parse_args()

    root = git_root()
    if Path.cwd().resolve() != root:
        raise SystemExit(f"run from repository root: {root}")

    ensure_header(
        QUEUE_PATH,
        "Workflow Improvement Queue",
        "Reviewed proposals for evolving the AI supervisor/worker workflow. "
        "Workers and reviewers may suggest entries, but the Codex supervisor owns decisions and implementation.",
    )
    ensure_header(
        DECISIONS_PATH,
        "Skill and Workflow Evolution Decisions",
        "Durable supervisor decisions about skill creation, workflow-template changes, scripts, and rejected or deferred suggestions.",
    )

    entry_id = next_id(QUEUE_PATH)
    notes = read_optional(args.notes_file)
    append_entry(QUEUE_PATH, entry_id, args, notes)
    if args.decision_log or args.status in {"accepted", "created", "updated", "deferred", "rejected"}:
        append_entry(DECISIONS_PATH, entry_id, args, notes)
    print(QUEUE_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
