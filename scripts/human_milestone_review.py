#!/usr/bin/env python3
"""Interactively process a human milestone review checklist."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_ITEMS = [
    "Milestone summary is accurate.",
    "Accepted jobs and commits are reviewable.",
    "Tests and validation are acceptable.",
    "Scientific assumptions, risks, and limitations are acceptable.",
    "Recommended next milestone is acceptable.",
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def git_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        raise SystemExit("human_milestone_review.py must run inside a Git repository")
    root = Path(result.stdout.strip()).resolve()
    if Path.cwd().resolve() != root:
        raise SystemExit(f"run from repository root: {root}")
    return root


def extract_checklist(gate_text: str) -> list[str]:
    items = []
    in_section = False
    saw_section = False
    for line in gate_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("## human review to-do list"):
            in_section = True
            saw_section = True
            continue
        if saw_section and stripped.startswith("## "):
            in_section = False
        if (in_section or not saw_section) and stripped.startswith("- [ ] "):
            items.append(stripped[6:].strip())
    return items or DEFAULT_ITEMS


def ask_yes_no(prompt: str) -> bool:
    while True:
        answer = input(f"{prompt} [yes/no]: ").strip().lower()
        if answer in {"yes", "y"}:
            return True
        if answer in {"no", "n"}:
            return False
        print("Please answer yes or no.")


def ask_comment() -> str:
    print("Enter comment for the revision job. Finish with a blank line.")
    lines = []
    while True:
        line = input("> ")
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def active_jobs() -> list[str]:
    active = []
    for status_path in sorted(Path(".ai/jobs").glob("J*/status.json")):
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            active.append(f"{status_path.parent.name}: invalid status")
            continue
        state = data.get("state", "")
        if state in {"queued", "running", "rejected", "ready_for_review", "blocked"}:
            active.append(f"{data.get('id', status_path.parent.name)}: {state}")
    return active


def write_review_record(
    reviews_dir: Path,
    stamp: str,
    gate_path: Path,
    gate_text: str,
    decisions: list[dict[str, str | bool]],
    result_label: str | None = None,
) -> Path:
    reviews_dir.mkdir(parents=True, exist_ok=True)
    out_path = reviews_dir / f"human_review_{stamp}.md"
    failed = [item for item in decisions if not item["passed"]]
    result = result_label or ("changes_requested" if failed else "approved")
    lines = [
        "# Human Milestone Review Record",
        "",
        f"- Gate file: `{gate_path}`",
        f"- Reviewed at: `{stamp}`",
        f"- Result: `{result}`",
        "",
        "## Checklist Results",
        "",
    ]
    for item in decisions:
        mark = "x" if item["passed"] else " "
        lines.append(f"- [{mark}] {item['item']}")
        if not item["passed"]:
            lines.append("")
            lines.append("  Comment:")
            for comment_line in str(item["comment"]).splitlines() or ["No comment provided."]:
                lines.append(f"  {comment_line}")
            lines.append("")
    lines.extend(["", "## Original Milestone Gate", "", gate_text])
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out_path


def create_revision_task(
    reviews_dir: Path,
    stamp: str,
    gate_path: Path,
    review_record: Path,
    decisions: list[dict[str, str | bool]],
) -> Path:
    failed = [item for item in decisions if not item["passed"]]
    task_path = reviews_dir / f"revision_task_{stamp}.md"
    lines = [
        "# Human Review Revision Job",
        "",
        "## Objective",
        "",
        "Address the human milestone review concerns listed below.",
        "",
        "## Scope",
        "",
        "Allowed:",
        "- Make only the changes required to resolve the failed human review items.",
        "- Update documentation, tests, or workflow records needed to make the milestone reviewable.",
        "",
        "Not allowed:",
        "- Do not start the next milestone.",
        "- Do not broaden scientific scope beyond the reviewed milestone.",
        "- Do not discard accepted work unless explicitly required by the concern.",
        "",
        "## Review Context",
        "",
        f"- Milestone gate: `{gate_path}`",
        f"- Human review record: `{review_record}`",
        "",
        "## Failed Human Review Items",
        "",
    ]
    for index, item in enumerate(failed, 1):
        lines.append(f"### {index}. {item['item']}")
        lines.append("")
        lines.append(str(item["comment"]) or "No comment provided.")
        lines.append("")
    lines.extend(
        [
            "## Required Validation",
            "",
            "Run the validation command from the affected milestone or explain why it cannot run.",
            "",
            "## Worker Report Contract",
            "",
            "Return:",
            "1. Summary",
            "2. Files changed",
            "3. Commits made",
            "4. Tests run and results",
            "5. Human review concerns addressed",
            "6. Known limitations",
            "7. Suggested follow-up",
        ]
    )
    task_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return task_path


def create_structural_change_task(
    reviews_dir: Path,
    stamp: str,
    gate_path: Path,
    review_record: Path,
    comment: str,
) -> Path:
    task_path = reviews_dir / f"structural_change_task_{stamp}.md"
    lines = [
        "# Major Structural Change Revision Job",
        "",
        "## Objective",
        "",
        "Revise the project architecture plan, roadmap, milestone sequence, and workflow records to reflect the human-requested structural change below.",
        "",
        "This is a planning and architecture revision job. Its main output is an updated milestone plan for human review before implementation continues.",
        "",
        "## Scope",
        "",
        "Allowed:",
        "- Update roadmap, project brief, ledger, build/dependency policy, and documentation needed to encode the structural decision.",
        "- Create or revise future milestone and worker-job sequencing so implementation follows the new architecture.",
        "- Create or update `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` with a concise summary of the updated milestones, what changed, why it changed, and a `## Human Review To-Do List` checklist.",
        "- Keep any existing accepted reference implementations as reference/test-oracle paths unless the human request explicitly says otherwise.",
        "",
        "Not allowed:",
        "- Do not start broad scientific implementation work in this revision job.",
        "- Do not create the next implementation worker job.",
        "- Do not discard accepted work unless the structural change explicitly requires it.",
        "- Do not broaden beyond the requested architectural/roadmap correction.",
        "",
        "## Required human review gate",
        "",
        "Before the supervisor resumes implementation after this job, the updated plan must be reviewed by the human.",
        "",
        "Create or update `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` with:",
        "- A short title identifying this as a structural revision review.",
        "- A summary of the structural request.",
        "- A summary of the milestone/roadmap changes made.",
        "- The next proposed milestone and the first few small worker jobs.",
        "- Any risks, unresolved choices, or implementation-order tradeoffs.",
        "- A `## Human Review To-Do List` section with unchecked checklist items.",
        "- Instructions to run `python3 scripts/human_milestone_review.py` or use the dashboard human-review panel.",
        "",
        "## Review Context",
        "",
        f"- Milestone gate: `{gate_path}`",
        f"- Human review record: `{review_record}`",
        "",
        "## Human Structural Change Request",
        "",
        comment or "No structural change details provided.",
        "",
        "## Required Validation",
        "",
        "Run documentation/workflow validation that is relevant to the edited files, and run `python3 scripts/summarize_jobs.py`.",
        "",
        "## Worker Report Contract",
        "",
        "Return:",
        "1. Summary",
        "2. Files changed",
        "3. Commits made",
        "4. Validation run and results",
        "5. Architecture decisions recorded",
        "6. Known limitations",
        "7. Human review gate created or updated",
        "8. Suggested next jobs",
    ]
    task_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return task_path


def create_job(title: str, base_ref: str, test_command: str, task_file: Path) -> str:
    result = run(
        [
            "python3",
            "scripts/create_job.py",
            "--title",
            title,
            "--base-ref",
            base_ref,
            "--test-command",
            test_command,
            "--task-file",
            str(task_file),
        ]
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr or result.stdout or "failed to create revision job")
    return result.stdout.strip()


def append_ledger(message: str) -> None:
    ledger = Path(".ai/supervisor/ledger.md")
    if not ledger.exists():
        return
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write("\n## Human milestone review update\n\n")
        handle.write(message.rstrip() + "\n")


def prune_accepted_job_refs(review_record: Path) -> str:
    script = Path(__file__).resolve().parent / "prune_accepted_job_refs.py"
    if not script.exists():
        return f"Prune skipped: helper not found at {script}"
    result = run(["python3", str(script), "--review-record", str(review_record)])
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    if result.returncode != 0:
        return output or "Prune failed with no output."
    return output or "No accepted job refs needed pruning."


def commit_workflow_records(message: str) -> str:
    script = Path(__file__).resolve().parent / "commit_workflow_records.py"
    if not script.exists():
        return f"Workflow record commit skipped: helper not found at {script}"
    result = run(["python3", str(script), "--message", message])
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    if result.returncode != 0:
        return output or "Workflow record commit failed with no output."
    return output or "No workflow record changes to commit."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", default=".ai/supervisor/HUMAN_REVIEW_REQUIRED.md")
    parser.add_argument("--test-command", default="python3 scripts/summarize_jobs.py")
    parser.add_argument("--title", default="Address human milestone review concerns")
    args = parser.parse_args()

    git_root()
    gate_path = Path(args.gate)
    if not gate_path.exists():
        raise SystemExit(f"human review gate not found: {gate_path}")

    gate_text = gate_path.read_text(encoding="utf-8")
    items = extract_checklist(gate_text)

    decisions: list[dict[str, str | bool]] = []
    print(f"Human milestone review: {gate_path}")
    structural_requested = ask_yes_no(
        "Major structural change request? This supersedes the checklist review"
    )
    structural_comment = ""
    if structural_requested:
        structural_comment = ask_comment()
        decisions.append(
            {
                "item": "Major structural change request superseded checklist review",
                "passed": False,
                "comment": structural_comment,
            }
        )
    else:
        print(f"Reviewing {len(items)} item(s). Answer every item; failed items will become one revision job.")
        for index, item in enumerate(items, 1):
            print(f"\n{index}. {item}")
            passed = ask_yes_no("Pass")
            comment = "" if passed else ask_comment()
            decisions.append({"item": item, "passed": passed, "comment": comment})

    stamp = utc_stamp()
    reviews_dir = Path(".ai/supervisor/human_reviews")
    review_record = write_review_record(
        reviews_dir,
        stamp,
        gate_path,
        gate_text,
        decisions,
        "structural_change_requested" if structural_requested else None,
    )
    archived_gate = reviews_dir / f"HUMAN_REVIEW_REQUIRED_{stamp}.md"
    shutil.move(str(gate_path), archived_gate)

    if structural_requested:
        active = active_jobs()
        if active:
            append_ledger(
                "- Human milestone review requested a major structural change, but no structural revision job was created because active jobs remain: "
                + ", ".join(active)
                + f". Record: `{review_record}`."
            )
            print("\nMajor structural change requested, but active jobs remain. No revision job created:")
            for item in active:
                print(f"- {item}")
            print(f"Review record: {review_record}")
            print(f"Archived gate: {archived_gate}")
            return 1

        base_result = run(["git", "rev-parse", "HEAD"])
        base_ref = base_result.stdout.strip() if base_result.returncode == 0 else "HEAD"
        task_file = create_structural_change_task(
            reviews_dir, stamp, archived_gate, review_record, structural_comment
        )
        job_path = create_job(
            "Address major structural change request",
            base_ref,
            "python3 scripts/summarize_jobs.py",
            task_file,
        )
        append_ledger(
            f"- Human milestone review requested a major structural change. Record: `{review_record}`. Structural revision job created: `{job_path}`."
        )
        print("\nMajor structural change requested.")
        print(f"Review record: {review_record}")
        print(f"Archived gate: {archived_gate}")
        print(f"Structural revision job created: {job_path}")
        print("The structural revision job must update the milestones and open a follow-up human review gate before implementation resumes.")
        print("\nWorkflow record commit:")
        print(commit_workflow_records("workflow: record major structural change request"))
        return 0

    failed = [item for item in decisions if not item["passed"]]
    if not failed:
        prune_output = prune_accepted_job_refs(review_record)
        append_ledger(
            f"- Human milestone review approved all items. Record: `{review_record}`.\n"
            "- Accepted job branch/worktree pruning:\n"
            + "\n".join(f"  - {line}" for line in prune_output.splitlines())
        )
        print(f"\nApproved. Review record: {review_record}")
        print(f"Archived gate: {archived_gate}")
        print("\nAccepted job branch/worktree pruning:")
        print(prune_output)
        print("\nWorkflow record commit:")
        print(commit_workflow_records("workflow: record human milestone approval"))
        return 0

    active = active_jobs()
    if active:
        append_ledger(
            "- Human milestone review requested changes, but no revision job was created because active jobs remain: "
            + ", ".join(active)
            + f". Record: `{review_record}`."
        )
        print("\nChanges requested, but active jobs remain. No revision job created:")
        for item in active:
            print(f"- {item}")
        print(f"Review record: {review_record}")
        print(f"Archived gate: {archived_gate}")
        return 1

    base_result = run(["git", "rev-parse", "HEAD"])
    base_ref = base_result.stdout.strip() if base_result.returncode == 0 else "HEAD"
    task_file = create_revision_task(reviews_dir, stamp, archived_gate, review_record, decisions)
    job_path = create_job(args.title, base_ref, args.test_command, task_file)
    append_ledger(
        f"- Human milestone review requested changes. Record: `{review_record}`. Revision job created: `{job_path}`."
    )

    print("\nChanges requested.")
    print(f"Review record: {review_record}")
    print(f"Archived gate: {archived_gate}")
    print(f"Revision job created: {job_path}")
    print("\nWorkflow record commit:")
    print(commit_workflow_records("workflow: record human milestone review"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
