#!/usr/bin/env python3
"""Interactively process a human milestone review checklist."""

from __future__ import annotations

import argparse
import json
import os
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


def ask_multiline(prompt: str) -> str:
    print(prompt)
    lines = []
    while True:
        line = input("> ")
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def ask_comment() -> str:
    return ask_multiline("Enter comment for the revision job. Finish with a blank line.")


def active_jobs() -> list[str]:
    active = []
    for status_path in sorted(Path(".ai/jobs").glob("J*/status.json")):
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            active.append(f"{status_path.parent.name}: invalid status")
            continue
        state = data.get("state", "")
        if state in {"queued", "running", "reviewing", "rejected", "ready_for_review", "blocked", "review_failed", "review_timeout"}:
            active.append(f"{data.get('id', status_path.parent.name)}: {state}")
    return active


def write_review_record(
    reviews_dir: Path,
    stamp: str,
    gate_path: Path,
    gate_text: str,
    decisions: list[dict[str, str | bool]],
    result_label: str | None = None,
    approval_comment: str = "",
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
    if result == "approved" and approval_comment.strip():
        lines.extend(["", "## Approval Comment", "", approval_comment.strip()])
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


def create_structural_change_request(
    reviews_dir: Path,
    stamp: str,
    gate_path: Path,
    review_record: Path,
    comment: str,
) -> Path:
    request_path = Path(".ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md")
    lines = [
        "# Major Structural Change Request",
        "",
        "This request must be handled by the Codex supervisor, not by a Cursor worker.",
        "",
        "## Supervisor Objective",
        "",
        "Revise the project architecture plan, roadmap, milestone sequence, and workflow records to reflect the human-requested structural change below.",
        "",
        "This is a supervisor-owned planning and architecture revision. Its main output is an updated milestone plan for human review before implementation continues.",
        "",
        "## Scope",
        "",
        "Allowed:",
        "- Supervisor may update roadmap, project brief, ledger, build/dependency policy, and documentation needed to encode the structural decision.",
        "- Create or revise future milestone and worker-job sequencing so implementation follows the new architecture.",
        "- Create or update `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` with a concise summary of the updated milestones, what changed, why it changed, and a `## Human Review To-Do List` checklist.",
        "- Keep any existing accepted reference implementations as reference/test-oracle paths unless the human request explicitly says otherwise.",
        "",
        "Not allowed:",
        "- Do not dispatch a worker job to perform roadmap, project brief, ledger, or milestone-sequence edits.",
        "- Do not start broad scientific implementation work in this supervisor revision.",
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
        "## Completion Contract",
        "",
        "The supervisor should record:",
        "1. Summary of roadmap/project-brief/ledger changes",
        "2. Validation run and results",
        "3. Human review gate path",
        "4. Proposed next small worker jobs after human approval",
        "5. Known limitations or decisions still requiring human review",
    ]
    text = "\n".join(lines).rstrip() + "\n"
    request_path.write_text(text, encoding="utf-8")
    archive_copy = reviews_dir / f"structural_change_request_{stamp}.md"
    archive_copy.write_text(text, encoding="utf-8")
    return request_path


def create_human_review_action_request(
    reviews_dir: Path,
    stamp: str,
    gate_path: Path,
    review_record: Path,
    decisions: list[dict[str, str | bool]],
) -> Path:
    request_path = Path(".ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md")
    failed = [item for item in decisions if not item["passed"]]
    lines = [
        "# Human Review Action Request",
        "",
        "This request must be handled by the Codex supervisor before any Cursor worker job is created.",
        "",
        "## Supervisor Objective",
        "",
        "Read the failed human milestone review items, classify the concerns, and decide the next safe workflow action.",
        "",
        "## Required Supervisor Behavior",
        "",
        "- Do not pass the raw failed checklist directly to Cursor.",
        "- Decide whether each concern is implementation work, test/validation work, documentation work, supervisor-owned planning/scope work, or a human clarification need.",
        "- If implementation is needed, create exactly one small, self-contained worker job for the next actionable piece.",
        "- If concerns should be split, create only the first small worker job and record the planned sequence in the ledger.",
        "- If supervisor-owned planning records must change, update them yourself and open a new human review gate before dispatching implementation.",
        "- If the concern is ambiguous, open a human review/clarification gate instead of guessing.",
        "- Archive or remove `.ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md` only after a new worker job or human gate exists.",
        "",
        "## Review Context",
        "",
        f"- Archived milestone gate: `{gate_path}`",
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
            "## Completion Contract",
            "",
            "The supervisor should record:",
            "1. Classification of the human concerns",
            "2. Whether a worker job, revised human gate, or clarification gate was created",
            "3. Path to any created job or gate",
            "4. Validation or checks run for supervisor-owned changes",
            "5. Known limitations or follow-up sequence",
        ]
    )
    text = "\n".join(lines).rstrip() + "\n"
    request_path.write_text(text, encoding="utf-8")
    archive_copy = reviews_dir / f"human_review_action_request_{stamp}.md"
    archive_copy.write_text(text, encoding="utf-8")
    return request_path


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


def pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
    except OSError:
        return False
    return state != "Z"


def read_pid(path: Path) -> int | None:
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid_running(pid) else None


def default_loop_env(name: str) -> dict[str, str]:
    if name == "worker_loop":
        return {
            "CURSOR_MODEL": os.environ.get("CURSOR_MODEL", "gpt-5.5-high"),
            "CURSOR_TIMEOUT": os.environ.get("CURSOR_TIMEOUT", "3600"),
            "CURSOR_REVIEWERS_ENABLED": os.environ.get("CURSOR_REVIEWERS_ENABLED", "1"),
            "CURSOR_REVIEW_TIMEOUT": os.environ.get("CURSOR_REVIEW_TIMEOUT", "2400"),
            "CURSOR_REVIEWER_A_MODEL": os.environ.get("CURSOR_REVIEWER_A_MODEL", "claude-opus-4-7-thinking-high"),
            "CURSOR_REVIEWER_B_MODEL": os.environ.get("CURSOR_REVIEWER_B_MODEL", "gpt-5.3-codex-high"),
            "WORKER_AUTO_RELAUNCH_FAILURE": "1",
        }
    return {
        "CODEX_MODEL": os.environ.get("CODEX_MODEL", "gpt-5.5"),
        "CODEX_REASONING_EFFORT": os.environ.get("CODEX_REASONING_EFFORT", "high"),
        "SUPERVISOR_POLL_SECONDS": os.environ.get("SUPERVISOR_POLL_SECONDS", "10"),
        "SUPERVISOR_VERBOSE": os.environ.get("SUPERVISOR_VERBOSE", "1"),
        "SUPERVISOR_AUTO_RELAUNCH_FAILURE": "1",
    }


def start_loop(name: str) -> str:
    runs_dir = Path(".ai/supervisor_runs")
    runs_dir.mkdir(parents=True, exist_ok=True)
    pid_path = runs_dir / f"{name}.pid"
    existing = read_pid(pid_path)
    if existing:
        return f"{name} already running with pid {existing}"

    script_name = "worker_loop.sh" if name == "worker_loop" else "supervisor_loop.sh"
    script_path = Path("scripts") / script_name
    if not script_path.exists():
        return f"{name} not started: missing {script_path}"

    env = os.environ.copy()
    env.update(default_loop_env(name))
    max_restarts = env.get("AI_WORKFLOW_LOOP_MAX_RESTARTS", "3")
    restart_delay = env.get("AI_WORKFLOW_LOOP_RESTART_DELAY", "5")
    wrapper = f"""
set -u
trap 'exit 0' TERM INT
attempt=0
while :; do
  "{script_path}"
  status=$?
  if [ "$status" -eq 0 ]; then
    exit 0
  fi
  if [ "$attempt" -ge "{max_restarts}" ]; then
    echo "{name} exited with status $status after $attempt restart(s)" >&2
    exit "$status"
  fi
  attempt=$((attempt + 1))
  echo "{name} exited with status $status; relaunching ($attempt/{max_restarts}) after {restart_delay}s" >&2
  sleep "{restart_delay}"
done
"""
    log_path = runs_dir / f"{name}.log"
    with log_path.open("ab") as handle:
        handle.write(f"\n--- launched {datetime.now(timezone.utc).isoformat()} ---\n".encode("utf-8"))
        proc = subprocess.Popen(
            ["bash", "-lc", wrapper],
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_path.write_text(str(proc.pid) + "\n", encoding="utf-8")
    return f"{name} started with pid {proc.pid}"


def auto_start_loops() -> str:
    supervisor = start_loop("supervisor_loop")
    worker = start_loop("worker_loop")
    return f"{supervisor}\n{worker}"


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
        print(f"Reviewing {len(items)} item(s). Answer every item; failed items will become one supervisor action request.")
        for index, item in enumerate(items, 1):
            print(f"\n{index}. {item}")
            passed = ask_yes_no("Pass")
            comment = "" if passed else ask_comment()
            decisions.append({"item": item, "passed": passed, "comment": comment})

    failed = [item for item in decisions if not item["passed"]]
    approval_comment = ""
    if not structural_requested and not failed:
        approval_comment = ask_multiline(
            "Optional approval comment for the milestone record. Finish with a blank line, or press Enter to skip."
        )

    stamp = utc_stamp()
    reviews_dir = Path(".ai/supervisor/human_reviews")
    review_record = write_review_record(
        reviews_dir,
        stamp,
        gate_path,
        gate_text,
        decisions,
        "structural_change_requested" if structural_requested else None,
        approval_comment,
    )
    archived_gate = reviews_dir / f"HUMAN_REVIEW_REQUIRED_{stamp}.md"
    shutil.move(str(gate_path), archived_gate)

    if structural_requested:
        request_path = create_structural_change_request(
            reviews_dir, stamp, archived_gate, review_record, structural_comment
        )
        append_ledger(
            f"- Human milestone review requested a major structural change. Record: `{review_record}`. Supervisor structural request: `{request_path}`."
        )
        print("\nMajor structural change requested.")
        print(f"Review record: {review_record}")
        print(f"Archived gate: {archived_gate}")
        print(f"Supervisor structural request: {request_path}")
        print("\nWorkflow record commit:")
        print(commit_workflow_records("workflow: record major structural change request"))
        print("\nAuto-start loops:")
        print(auto_start_loops())
        return 0

    if not failed:
        prune_output = prune_accepted_job_refs(review_record)
        ledger_message = f"- Human milestone review approved all items. Record: `{review_record}`.\n"
        if approval_comment.strip():
            ledger_message += "- Approval comment:\n" + "\n".join(
                f"  {line}" for line in approval_comment.strip().splitlines()
            ) + "\n"
        ledger_message += "- Accepted job branch/worktree pruning:\n" + "\n".join(
            f"  - {line}" for line in prune_output.splitlines()
        )
        append_ledger(ledger_message)
        print(f"\nApproved. Review record: {review_record}")
        print(f"Archived gate: {archived_gate}")
        print("\nAccepted job branch/worktree pruning:")
        print(prune_output)
        print("\nWorkflow record commit:")
        print(commit_workflow_records("workflow: record human milestone approval"))
        print("\nAuto-start loops:")
        print(auto_start_loops())
        return 0

    request_path = create_human_review_action_request(
        reviews_dir, stamp, archived_gate, review_record, decisions
    )
    append_ledger(
        f"- Human milestone review requested changes. Record: `{review_record}`. Supervisor action request: `{request_path}`."
    )

    print("\nChanges requested.")
    print(f"Review record: {review_record}")
    print(f"Archived gate: {archived_gate}")
    print(f"Supervisor action request: {request_path}")
    print("\nWorkflow record commit:")
    print(commit_workflow_records("workflow: record human milestone review action request"))
    print("\nAuto-start loops:")
    print(auto_start_loops())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
