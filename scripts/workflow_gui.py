#!/usr/bin/env python3
"""Serve a local dashboard for the AI supervisor/worker workflow."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = PACKAGE_ROOT / "gui"
DEFAULT_LOG_DISPLAY_LINES = 10_000
ACTIVE_JOB_STATES = {
    "queued",
    "running",
    "implemented",
    "reviewing",
    "rejected",
    "ready_for_review",
    "blocked",
    "review_failed",
    "review_timeout",
}
TERMINAL_JOB_STATES = {"accepted", "cancelled", "superseded"}


def env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(100, value)


LOG_DISPLAY_LINES = env_int("AI_WORKFLOW_GUI_LOG_LINES", DEFAULT_LOG_DISPLAY_LINES)


def run(args: list[str], cwd: Path) -> tuple[int, str, str]:
    result = subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def read_text(path: Path, limit: int = 80_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > limit:
        return text[:limit] + "\n\n[truncated]\n"
    return text


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def tail(path: Path, lines: int = 80) -> str:
    if not path:
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return "".join(deque(handle, maxlen=max(1, lines))).rstrip()
    except OSError:
        return ""


def runs_dir(root: Path) -> Path:
    path = root / ".ai" / "supervisor_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pid_file(root: Path, name: str) -> Path:
    return runs_dir(root) / f"{name}.pid"


def log_file(root: Path, name: str) -> Path:
    return runs_dir(root) / f"{name}.log"


def workflow_package_commit() -> str:
    code, out, _ = run(["git", "rev-parse", "--short", "HEAD"], PACKAGE_ROOT)
    return out if code == 0 and out else "unknown"


def logged_workflow_commit(log_tail: str) -> str:
    matches = re.findall(r"workflow_commit=([0-9a-fA-F]+|unknown)", log_tail)
    return matches[-1] if matches else ""


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


def control_info(root: Path, name: str) -> dict:
    pid = read_pid(pid_file(root, name))
    log = log_file(root, name)
    log_tail = tail(log, LOG_DISPLAY_LINES)
    expected_commit = workflow_package_commit()
    running_commit = logged_workflow_commit(log_tail)
    version_warning = ""
    if pid is not None and expected_commit != "unknown" and running_commit and running_commit != expected_commit:
        version_warning = "running loop uses older workflow version; restart recommended"
    return {
        "pid": pid,
        "running": pid is not None,
        "pid_file": str(pid_file(root, name).relative_to(root)),
        "log_file": str(log.relative_to(root)),
        "log_tail": log_tail,
        "log_display_lines": LOG_DISPLAY_LINES,
        "workflow_commit": running_commit,
        "expected_workflow_commit": expected_commit,
        "version_warning": version_warning,
    }


def parse_gate_checklist(gate_text: str) -> list[str]:
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
    return items


def git_info(root: Path) -> dict:
    _, branch, _ = run(["git", "branch", "--show-current"], root)
    _, head, _ = run(["git", "rev-parse", "--short", "HEAD"], root)
    _, status, _ = run(["git", "status", "--short"], root)
    _, remotes, _ = run(["git", "remote", "-v"], root)
    return {
        "branch": branch or "(detached)",
        "head": head,
        "dirty_count": len([line for line in status.splitlines() if line.strip()]),
        "status": status,
        "remotes": remotes,
    }


def jobs(root: Path) -> list[dict]:
    jobs_dir = root / ".ai" / "jobs"
    out = []
    for status_path in sorted(jobs_dir.glob("J*/status.json")):
        data = read_json(status_path)
        job_dir = status_path.parent
        attempt = data.get("attempt", 0)
        data["_path"] = str(job_dir.relative_to(root))
        data["_files"] = sorted(path.name for path in job_dir.iterdir() if path.is_file())
        data["_report_tail"] = tail(job_dir / "report.md", 60)
        data["_test_tail"] = tail(job_dir / f"test.attempt-{attempt}.log", 60)
        data["_cursor_tail"] = tail(job_dir / f"cursor_final.attempt-{attempt}.md", 60)
        data["_task_text"] = read_text(job_dir / "task.md", 40_000)
        reviews_dir = job_dir / "reviews"
        data["_reviewer_a_tail"] = tail(reviews_dir / f"reviewer-a.attempt-{attempt}.md", 80)
        data["_reviewer_b_tail"] = tail(reviews_dir / f"reviewer-b.attempt-{attempt}.md", 80)
        out.append(data)
    return out


def reviewer_state(root: Path, job_rows: list[dict]) -> dict:
    priority = {
        "reviewing": 0,
        "review_failed": 1,
        "review_timeout": 2,
        "ready_for_review": 3,
        "accepted": 4,
        "rejected": 5,
        "blocked": 6,
    }
    candidates = [
        job for job in job_rows
        if job.get("_reviewer_a_tail") or job.get("_reviewer_b_tail") or job.get("state") == "reviewing"
    ]
    if not candidates:
        return {
            "title": "No reviewer reports yet.",
            "job_id": "",
            "reviewer_a": "",
            "reviewer_b": "",
            "reviewer_a_path": "",
            "reviewer_b_path": "",
        }
    def job_number(job: dict) -> int:
        match = re.search(r"J(\d+)", str(job.get("id", "")))
        return int(match.group(1)) if match else -1

    candidates.sort(key=lambda job: (priority.get(str(job.get("state")), 9), -job_number(job)))
    job = candidates[0]
    attempt = job.get("attempt", 0)
    job_id = str(job.get("id", ""))
    return {
        "title": f"{job_id} reviewer reports",
        "job_id": job_id,
        "state": job.get("state", ""),
        "reviewer_a_model": job.get("reviewer_a_model", ""),
        "reviewer_b_model": job.get("reviewer_b_model", ""),
        "reviewer_a_exit": job.get("reviewer_a_exit", ""),
        "reviewer_b_exit": job.get("reviewer_b_exit", ""),
        "reviewer_a": job.get("_reviewer_a_tail") or "Reviewer A has not emitted a report yet.",
        "reviewer_b": job.get("_reviewer_b_tail") or "Reviewer B has not emitted a report yet.",
        "reviewer_a_path": f".ai/jobs/{job_id}/reviews/reviewer-a.attempt-{attempt}.md" if job_id else "",
        "reviewer_b_path": f".ai/jobs/{job_id}/reviews/reviewer-b.attempt-{attempt}.md" if job_id else "",
    }


def criterion_is_active(item_text: str, active_contexts: list[str]) -> bool:
    if not active_contexts:
        return False
    normalized_item = item_text.lower()
    code_spans = re.findall(r"`([^`]+)`", item_text)
    for context in active_contexts:
        normalized_context = context.lower()
        for span in code_spans:
            if span.lower() in normalized_context:
                return True
        words = [word for word in re.findall(r"[a-zA-Z0-9_./+-]+", normalized_item) if len(word) >= 5]
        if words and sum(1 for word in words if word in normalized_context) >= min(2, len(words)):
            return True
    return False


def human_gate_milestone(gate_text: str) -> str:
    lines = gate_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "## Milestone":
            for value in lines[index + 1 :]:
                value = value.strip()
                if value:
                    return value.rstrip(".")
        match = re.match(r"^##\s+(M\d+:.+)$", line.strip())
        if match:
            return match.group(1).rstrip(".")
    return ""


def same_milestone(left: str, right: str) -> bool:
    if not left or not right:
        return False
    left = left.strip().rstrip(".").lower()
    right = right.strip().rstrip(".").lower()
    if left == right:
        return True
    left_id = re.match(r"^(m\d+)\b", left)
    right_id = re.match(r"^(m\d+)\b", right)
    return bool(left_id and right_id and left_id.group(1) == right_id.group(1))


def parse_roadmap(
    text: str,
    active_contexts: list[str] | None = None,
    pending_human_milestone: str = "",
) -> list[dict]:
    active_contexts = active_contexts or []
    milestones = []
    current: dict | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                milestones.append(current)
            current = {"title": line[3:].strip(), "items": [], "done": 0, "total": 0}
            continue
        if current and re.match(r"^-\s+\[[ xX]\]", line.strip()):
            roadmap_done = "[x]" in line.lower()
            item_text = line.strip()[6:].strip()
            pending_human = roadmap_done and same_milestone(current["title"], pending_human_milestone)
            done = roadmap_done and not pending_human
            active = pending_human or ((not done) and criterion_is_active(item_text, active_contexts))
            current["items"].append(
                {
                    "text": item_text,
                    "done": done,
                    "active": active,
                    "pending_human_review": pending_human,
                    "roadmap_done": roadmap_done,
                }
            )
            current["total"] += 1
            if done:
                current["done"] += 1
            if active:
                current["active"] = current.get("active", 0) + 1
    if current:
        milestones.append(current)
    return milestones


def active_job_contexts(job_rows: list[dict]) -> list[str]:
    contexts = []
    for job in job_rows:
        if job.get("state") not in ACTIVE_JOB_STATES:
            continue
        contexts.append(
            "\n".join(
                [
                    str(job.get("id", "")),
                    str(job.get("title", "")),
                    str(job.get("_task_text", "")),
                ]
            )
        )
    return contexts


def supervisor_state(root: Path, job_rows: list[dict] | None = None) -> dict:
    job_rows = job_rows or []
    supervisor = root / ".ai" / "supervisor"
    roadmap = read_text(supervisor / "roadmap.md")
    ledger = read_text(supervisor / "ledger.md")
    project_brief = read_text(supervisor / "project_brief.md")
    gate_path = supervisor / "HUMAN_REVIEW_REQUIRED.md"
    gate_text = read_text(gate_path)
    structural_request_path = supervisor / "STRUCTURAL_CHANGE_REQUESTED.md"
    structural_request_text = read_text(structural_request_path)
    human_review_action_path = supervisor / "HUMAN_REVIEW_ACTION_REQUESTED.md"
    human_review_action_text = read_text(human_review_action_path)
    runs_dir = root / ".ai" / "supervisor_runs"
    run_logs = sorted(runs_dir.glob("supervisor.*.log"))
    latest_log = run_logs[-1] if run_logs else None
    review_records = sorted((supervisor / "human_reviews").glob("human_review_*.md"))
    latest_review = review_records[-1] if review_records else None
    latest_review_text = read_text(latest_review) if latest_review else ""
    latest_review_result = ""
    match = re.search(r"^- Result:\s+`([^`]+)`", latest_review_text, re.MULTILINE)
    if match:
        latest_review_result = match.group(1)
    return {
        "roadmap": roadmap,
        "milestones": parse_roadmap(
            roadmap,
            active_job_contexts(job_rows),
            human_gate_milestone(gate_text) if gate_path.exists() else "",
        ),
        "ledger": ledger,
        "project_brief": project_brief,
        "human_gate_exists": gate_path.exists(),
        "human_gate": gate_text,
        "human_gate_checklist": parse_gate_checklist(gate_text) if gate_path.exists() else [],
        "structural_request_exists": structural_request_path.exists(),
        "structural_request": structural_request_text,
        "human_review_action_exists": human_review_action_path.exists(),
        "human_review_action": human_review_action_text,
        "latest_human_review": str(latest_review.relative_to(root)) if latest_review else "",
        "latest_human_review_result": latest_review_result,
        "latest_supervisor_log": str(latest_log.relative_to(root)) if latest_log else "",
        "latest_supervisor_tail": tail(latest_log, LOG_DISPLAY_LINES) if latest_log else "",
    }


def active_job_summary(job_rows: list[dict]) -> dict | None:
    priority = {
        "running": 0,
        "implemented": 1,
        "reviewing": 2,
        "queued": 3,
        "rejected": 4,
        "ready_for_review": 5,
        "review_failed": 6,
        "review_timeout": 7,
        "blocked": 8,
    }
    candidates = [job for job in job_rows if job.get("state") in priority]
    if not candidates:
        return None
    candidates.sort(key=lambda job: priority.get(job.get("state"), 99))
    job = candidates[0]
    return {
        "id": job.get("id"),
        "title": job.get("title"),
        "state": job.get("state"),
        "attempt": job.get("attempt", 0),
        "branch": job.get("branch"),
        "path": job.get("_path"),
        "test_command": job.get("test_command", ""),
        "timed_out": job.get("timed_out", False),
        "worker_error": job.get("worker_error", ""),
    }


def worker_display_log(root: Path, job_rows: list[dict], fallback: dict) -> dict:
    job = active_job_summary(job_rows)
    if not job:
        return {
            "log_tail": fallback.get("log_tail", ""),
            "log_file": fallback.get("log_file", ""),
            "log_display_lines": fallback.get("log_display_lines", LOG_DISPLAY_LINES),
            "log_label": "Worker Loop Log",
        }

    job_dir = root / ".ai" / "jobs" / str(job.get("id"))
    attempt = job.get("attempt", 0)
    if job.get("state") == "reviewing":
        reviews_dir = job_dir / "reviews"
        reviewer_b = tail(reviews_dir / f"reviewer-b.attempt-{attempt}.md", LOG_DISPLAY_LINES)
        reviewer_a = tail(reviews_dir / f"reviewer-a.attempt-{attempt}.md", LOG_DISPLAY_LINES)
        if reviewer_b or reviewer_a:
            report_name = f"reviewer-b.attempt-{attempt}.md" if reviewer_b else f"reviewer-a.attempt-{attempt}.md"
            return {
                "log_tail": reviewer_b or reviewer_a,
                "log_file": str((reviews_dir / report_name).relative_to(root)),
                "log_display_lines": LOG_DISPLAY_LINES,
                "log_label": "Cursor Reviewer Output",
            }
    cursor_out = job_dir / f"cursor_final.attempt-{attempt}.md"
    cursor_err = job_dir / f"cursor_stderr.attempt-{attempt}.log"
    cursor_tail = tail(cursor_out, LOG_DISPLAY_LINES)
    stderr_tail = tail(cursor_err, LOG_DISPLAY_LINES)
    if cursor_tail:
        log_tail = cursor_tail
        log_file_value = str(cursor_out.relative_to(root))
    elif stderr_tail:
        log_tail = stderr_tail
        log_file_value = str(cursor_err.relative_to(root))
    else:
        log_tail = (
            f"Cursor is running {job.get('id')} attempt {attempt}, but it has not emitted stdout/stderr yet.\n"
            "Some cursor-agent versions only write final text when the agent finishes.\n\n"
            f"Fallback worker loop log:\n{fallback.get('log_tail', '')}"
        ).rstrip()
        log_file_value = str(cursor_out.relative_to(root))
    return {
        "log_tail": log_tail,
        "log_file": log_file_value,
        "log_display_lines": LOG_DISPLAY_LINES,
        "log_label": "Cursor Worker Output",
    }


def supervisor_preparing_human_review(supervisor: dict, job_rows: list[dict]) -> bool:
    if supervisor.get("human_gate_exists"):
        return False
    if supervisor.get("latest_human_review_result") == "approved":
        return False
    if any(job.get("state") in ACTIVE_JOB_STATES for job in job_rows):
        return False
    ledger = str(supervisor.get("ledger", "")).lower()
    review_phrases = [
        "pending human milestone review",
        "pending renewed human milestone review",
        "human review gate is open",
        "reopened the m",
    ]
    return any(phrase in ledger for phrase in review_phrases)


def activity_state(job_rows: list[dict], processes: dict, controls: dict, supervisor: dict) -> dict:
    active = active_job_summary(job_rows)
    ready_job = next((job for job in job_rows if job.get("state") == "ready_for_review"), None)
    review_failed_job = next((job for job in job_rows if job.get("state") in {"review_failed", "review_timeout"}), None)
    codex_active = bool(processes.get("codex"))
    supervisor_running = bool(controls.get("supervisor", {}).get("running"))
    worker_running = bool(controls.get("worker", {}).get("running"))
    human_gate_exists = bool(supervisor.get("human_gate_exists"))
    structural_request_exists = bool(supervisor.get("structural_request_exists"))
    human_review_action_exists = bool(supervisor.get("human_review_action_exists"))
    preparing_human_review = codex_active and supervisor_preparing_human_review(supervisor, job_rows)

    if human_gate_exists:
        summary = "Wait for Human Milestone Review."
    elif structural_request_exists:
        summary = (
            "Supervisor is preparing a structural plan revision."
            if codex_active
            else "Structural plan revision is waiting for the supervisor."
        )
    elif human_review_action_exists:
        summary = (
            "Supervisor is preparing a human-review revision plan."
            if codex_active
            else "Human-review revision request is waiting for the supervisor."
        )
    elif ready_job:
        summary = (
            f"Supervisor is reviewing {ready_job.get('id', 'a job')}."
            if codex_active
            else f"{ready_job.get('id', 'A job')} is ready for supervisor review."
        )
    elif review_failed_job:
        summary = f"Reviewer stage failed on {review_failed_job.get('id', 'a job')}; supervisor action is needed."
    elif active and active.get("state") in {"implemented", "reviewing"}:
        summary = f"Cursor reviewers are reviewing {active.get('id', 'a job')}."
    elif active and active.get("timed_out"):
        summary = f"Worker timed out on {active.get('id', 'a job')}."
    elif active and active.get("state") in {"queued", "running", "rejected"}:
        summary = f"Worker is working on {active.get('id', 'a job')}."
    elif active and active.get("state") == "blocked":
        summary = f"Worker is blocked on {active.get('id', 'a job')}."
    elif preparing_human_review:
        summary = "Supervisor is preparing a human review."
    elif codex_active:
        summary = "Supervisor is preparing the next worker job."
    elif worker_running or supervisor_running:
        summary = "Worker and supervisor are waiting for the next workflow event."
    else:
        summary = "Workflow is idle."

    offline = []
    if not worker_running:
        offline.append("worker loop")
    if not supervisor_running:
        offline.append("supervisor loop")
    if offline:
        summary = f"{summary} Offline: {', '.join(offline)}."

    if active:
        if active.get("state") == "ready_for_review":
            worker_text = f"Cursor finished {active.get('id')} attempt {active.get('attempt')}; awaiting supervisor review."
        elif active.get("state") in {"implemented", "reviewing"}:
            worker_text = f"Cursor reviewers are reviewing {active.get('id')} attempt {active.get('attempt')}."
        elif active.get("timed_out"):
            worker_text = f"Cursor timed out on {active.get('id')} attempt {active.get('attempt')}: {active.get('worker_error')}"
        elif active.get("state") in {"review_failed", "review_timeout"}:
            worker_text = f"Reviewer stage failed on {active.get('id')} attempt {active.get('attempt')}; see reviewer logs and status fields."
        elif active.get("state") == "blocked":
            worker_text = f"Worker blocked on {active.get('id')} attempt {active.get('attempt')}; supervisor review or feedback is needed."
        else:
            worker_text = (
                f"Cursor is handling {active.get('id')} attempt {active.get('attempt')}: "
                f"{active.get('title')} ({active.get('state')})."
            )
    elif worker_running:
        worker_text = "Worker loop is live and waiting for queued or rejected jobs."
    else:
        worker_text = "Worker loop is idle."

    if structural_request_exists:
        supervisor_text = "Supervisor must revise roadmap/project brief/ledger itself and open a follow-up human review gate."
    elif human_review_action_exists:
        supervisor_text = "Supervisor must classify human review concerns and create a small worker job, revised gate, or clarification gate."
    elif active and active.get("state") in {"queued", "running", "implemented", "reviewing", "rejected"}:
        supervisor_text = f"Supervisor is waiting for worker state changes on {active.get('id')}."
    elif any(job.get("state") == "ready_for_review" for job in job_rows):
        supervisor_text = "Supervisor should review a job that is ready_for_review."
    elif any(job.get("state") in {"review_failed", "review_timeout"} for job in job_rows):
        supervisor_text = "Supervisor should inspect reviewer failure artifacts and decide whether to retry, reject, or open a gate."
    elif preparing_human_review:
        supervisor_text = "Supervisor is preparing the milestone review summary and checklist."
    elif codex_active:
        supervisor_text = "Supervisor is actively planning, reviewing, or dispatching work."
    elif supervisor_running:
        supervisor_text = "Supervisor loop is live and watching job state."
    else:
        supervisor_text = "Supervisor loop is idle."

    return {
        "summary": summary,
        "worker": worker_text,
        "supervisor": supervisor_text,
        "active_job": active,
        "process_counts": {key: len(value) for key, value in processes.items()},
    }


def worktrees(root: Path) -> list[dict]:
    code, out, _ = run(["git", "worktree", "list", "--porcelain"], root)
    if code != 0:
        return []
    entries = []
    current: dict = {}
    for line in out.splitlines():
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        entries.append(current)
    for entry in entries:
        path = Path(entry.get("worktree", ""))
        if path.exists():
            _, status, _ = run(["git", "status", "--short"], path)
            entry["dirty_count"] = len([line for line in status.splitlines() if line.strip()])
            entry["status"] = status
            try:
                entry["display_path"] = str(path.relative_to(root))
            except ValueError:
                entry["display_path"] = str(path)
    return entries


def project_tree(root: Path, max_depth: int = 6, max_entries: int = 2_000) -> dict:
    ignored = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".DS_Store"}
    counter = 0
    truncated = False

    def walk(path: Path, depth: int) -> list[dict]:
        nonlocal counter, truncated
        if truncated or depth > max_depth:
            return []
        try:
            entries = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        except OSError:
            return []

        children = []
        for entry in entries:
            if entry.name in ignored:
                continue
            if counter >= max_entries:
                truncated = True
                break
            try:
                rel = entry.relative_to(root)
            except ValueError:
                continue
            counter += 1
            if entry.is_dir():
                node = {
                    "type": "dir",
                    "name": entry.name,
                    "path": str(rel),
                    "children": walk(entry, depth + 1),
                }
                if truncated:
                    node["truncated"] = True
                children.append(node)
            elif entry.is_file():
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = None
                children.append({"type": "file", "name": entry.name, "path": str(rel), "size": size})
        return children

    return {
        "type": "dir",
        "name": root.name,
        "path": ".",
        "children": walk(root, 0),
        "truncated": truncated,
        "max_entries": max_entries,
        "max_depth": max_depth,
    }


def safe_project_path(root: Path, relative_path: str) -> Path:
    if not relative_path or "\0" in relative_path:
        raise ValueError("missing or invalid path")
    candidate = (root / relative_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("path is outside the project root")
    return candidate


def open_project_file(root: Path, relative_path: str) -> dict:
    try:
        path = safe_project_path(root, relative_path)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    if not path.exists():
        return {"ok": False, "message": f"path does not exist: {relative_path}"}
    if path.is_dir():
        return {"ok": False, "message": "select a file, not a directory"}
    opener = shutil.which("xdg-open")
    if not opener:
        return {"ok": False, "message": "xdg-open is not available on this system"}
    try:
        subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return {"ok": False, "message": f"failed to open file: {exc}"}
    return {"ok": True, "message": f"opened {relative_path}", "path": relative_path}


def argv_has_script(argv: list[str], script_name: str) -> bool:
    return any(Path(arg).name == script_name or script_name in arg for arg in argv)


def is_cursor_agent_process(argv: list[str]) -> bool:
    if not argv:
        return False
    executable = Path(argv[0]).name
    if executable == "cursor-agent":
        return True
    if executable in {"node", "index.js"} and any("cursor-agent" in arg for arg in argv[:3]):
        return True
    return False


def process_blocks(root: Path) -> dict:
    blocks = {"worker": [], "supervisor": [], "cursor": [], "codex": []}
    proc_root = Path("/proc")
    for proc in proc_root.iterdir():
        if not proc.name.isdigit():
            continue
        try:
            raw_cmdline = (proc / "cmdline").read_bytes()
            argv = [
                part.decode("utf-8", errors="replace")
                for part in raw_cmdline.split(b"\0")
                if part
            ]
            cmdline = " ".join(argv).strip()
            if not cmdline:
                continue
            cwd = Path(os.readlink(proc / "cwd"))
        except OSError:
            continue
        in_project = cwd == root or root in cwd.parents
        if not in_project and str(root) not in cmdline:
            continue
        try:
            stat = (proc / "stat").read_text(encoding="utf-8").split()
            state = stat[2]
        except OSError:
            state = "?"
        item = {"pid": int(proc.name), "state": state, "cmd": cmdline[:900]}
        if argv_has_script(argv, "worker_loop.sh"):
            blocks["worker"].append(item)
        elif argv_has_script(argv, "supervisor_loop.sh"):
            blocks["supervisor"].append(item)
        elif is_cursor_agent_process(argv):
            blocks["cursor"].append(item)
        elif "codex" in cmdline and " exec " in f" {cmdline} ":
            blocks["codex"].append(item)
    return blocks


def state(root: Path) -> dict:
    job_rows = jobs(root)
    counts: dict[str, int] = {}
    for job in job_rows:
        counts[job.get("state", "unknown")] = counts.get(job.get("state", "unknown"), 0) + 1
    accepted = counts.get("accepted", 0)
    total = len(job_rows)
    progress = int((accepted / total) * 100) if total else 0
    processes = process_blocks(root)
    controls = {
        "worker": control_info(root, "worker_loop"),
        "supervisor": control_info(root, "supervisor_loop"),
    }
    controls["worker"].update(worker_display_log(root, job_rows, controls["worker"]))
    supervisor = supervisor_state(root, job_rows)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "project": {"root": str(root), "name": root.name},
        "git": git_info(root),
        "jobs": job_rows,
        "job_counts": counts,
        "job_progress": progress,
        "supervisor": supervisor,
        "worktrees": worktrees(root),
        "processes": processes,
        "controls": controls,
        "activity": activity_state(job_rows, processes, controls, supervisor),
        "reviewers": reviewer_state(root, job_rows),
        "tree": project_tree(root),
    }


def json_response(handler: SimpleHTTPRequestHandler, status: HTTPStatus, payload: dict) -> None:
    body = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_request_json(handler: SimpleHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON body: {exc}") from exc


def start_loop(root: Path, name: str, env_updates: dict[str, str]) -> dict:
    existing = read_pid(pid_file(root, name))
    if existing:
        return {"ok": True, "message": f"{name} already running", "pid": existing}

    script_name = "worker_loop.sh" if name == "worker_loop" else "supervisor_loop.sh"
    script_path = root / "scripts" / script_name
    if not script_path.exists():
        return {"ok": False, "message": f"missing script: {script_path}"}

    env = os.environ.copy()
    env.update({key: value for key, value in env_updates.items() if value != ""})
    log = log_file(root, name)
    max_restarts = str(env.get("AI_WORKFLOW_LOOP_MAX_RESTARTS", "3"))
    restart_delay = str(env.get("AI_WORKFLOW_LOOP_RESTART_DELAY", "5"))
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
    with log.open("ab") as handle:
        handle.write(f"\n--- launched {datetime.now(timezone.utc).isoformat()} ---\n".encode("utf-8"))
        proc = subprocess.Popen(
            ["bash", "-lc", wrapper],
            cwd=str(root),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_file(root, name).write_text(str(proc.pid) + "\n", encoding="utf-8")
    return {"ok": True, "message": f"started {name}", "pid": proc.pid}


def worker_loop_env(payload: dict | None = None) -> dict[str, str]:
    payload = payload or {}
    extra_args = str(payload.get("extra_args", ""))
    if payload.get("force") and "--force" not in extra_args:
        extra_args = (extra_args + " --force").strip()
    return {
        "CURSOR_MODEL": str(payload.get("model", "gpt-5.5-high")),
        "CURSOR_TIMEOUT": str(payload.get("timeout", "3600")),
        "CURSOR_AGENT_EXTRA_ARGS": extra_args,
        "CURSOR_REVIEWERS_ENABLED": "1" if payload.get("reviewers_enabled", True) else "0",
        "CURSOR_REVIEW_TIMEOUT": str(payload.get("review_timeout", "2400")),
        "CURSOR_REVIEWER_A_MODEL": str(payload.get("reviewer_a_model", "claude-opus-4-7-thinking-high")),
        "CURSOR_REVIEWER_B_MODEL": str(payload.get("reviewer_b_model", "gpt-5.3-codex-high")),
        "CURSOR_REVIEWER_MAX_RELAUNCHES": str(payload.get("reviewer_max_relaunches", "1")),
        "WORKER_AUTO_RELAUNCH_FAILURE": "1",
        "WORKER_MAX_FAILURE_RESUMES": str(payload.get("max_failure_resumes", "2")),
        "WORKER_AUTO_RESUME_TIMEOUT": "1" if payload.get("auto_resume_timeout", False) else "0",
        "WORKER_MAX_TIMEOUT_RESUMES": str(payload.get("max_timeout_resumes", "2")),
    }


def supervisor_loop_env(payload: dict | None = None) -> dict[str, str]:
    payload = payload or {}
    return {
        "CODEX_MODEL": str(payload.get("model", "gpt-5.5")),
        "CODEX_REASONING_EFFORT": str(payload.get("reasoning", "high")),
        "SUPERVISOR_POLL_SECONDS": str(payload.get("poll_seconds", "10")),
        "SUPERVISOR_VERBOSE": "1" if payload.get("verbose", True) else "0",
        "CODEX_EXTRA_ARGS": str(payload.get("extra_args", "")),
        "SUPERVISOR_AUTO_RELAUNCH_FAILURE": "1",
        "SUPERVISOR_MAX_FAILURE_RELAUNCHES": str(payload.get("max_failure_relaunches", "1")),
    }


def auto_start_loops_after_human_review(root: Path) -> dict:
    supervisor = start_loop(root, "supervisor_loop", supervisor_loop_env())
    worker = start_loop(root, "worker_loop", worker_loop_env())
    return {
        "ok": bool(supervisor.get("ok")) and bool(worker.get("ok")),
        "supervisor": supervisor,
        "worker": worker,
    }


def stop_loop(root: Path, name: str) -> dict:
    process_key = "worker" if name == "worker_loop" else "supervisor"
    targets: set[int] = set()
    pid = read_pid(pid_file(root, name))
    if pid:
        targets.add(pid)
    for item in process_blocks(root).get(process_key, []):
        targets.add(int(item.get("pid", 0)))

    targets = {target for target in targets if target and pid_running(target)}
    if not targets:
        try:
            pid_file(root, name).unlink()
        except OSError:
            pass
        return {"ok": True, "message": f"{name} is not running"}

    groups: set[int] = set()
    for target in targets:
        try:
            groups.add(os.getpgid(target))
        except OSError:
            pass

    errors = []
    for group in groups:
        try:
            os.killpg(group, signal.SIGTERM)
        except OSError as exc:
            errors.append(str(exc))
    for target in targets:
        try:
            os.kill(target, signal.SIGTERM)
        except OSError:
            pass

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not any(pid_running(target) for target in targets):
            break
        time.sleep(0.1)

    stubborn = {target for target in targets if pid_running(target)}
    if stubborn:
        for group in groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except OSError:
                pass
        for target in stubborn:
            try:
                os.kill(target, signal.SIGKILL)
            except OSError:
                pass

    try:
        pid_file(root, name).unlink()
    except OSError:
        pass

    stopped = sorted(targets)
    killed = sorted(target for target in targets if not pid_running(target))
    if errors and not killed:
        return {"ok": False, "message": f"failed to stop {name}: {'; '.join(errors)}", "pids": stopped}
    return {"ok": True, "message": f"stopped {name}", "pids": stopped, "stopped_pids": killed}


def active_jobs(root: Path) -> list[str]:
    active = []
    for status_path in sorted((root / ".ai" / "jobs").glob("J*/status.json")):
        data = read_json(status_path)
        state_value = data.get("state", "")
        if state_value in ACTIVE_JOB_STATES:
            active.append(f"{data.get('id', status_path.parent.name)}: {state_value}")
    return active


def prune_accepted_job_refs(root: Path, review_record: Path) -> tuple[bool, str]:
    script = PACKAGE_ROOT / "scripts" / "prune_accepted_job_refs.py"
    if not script.exists():
        return False, f"Prune skipped: helper not found at {script}"
    result = subprocess.run(
        ["python3", str(script), "--review-record", str(review_record)],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode == 0, output or "No accepted job refs needed pruning."


def commit_workflow_records(root: Path, message: str) -> tuple[bool, str]:
    script = PACKAGE_ROOT / "scripts" / "commit_workflow_records.py"
    if not script.exists():
        return False, f"Workflow record commit skipped: helper not found at {script}"
    result = subprocess.run(
        ["python3", str(script), "--message", message],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode == 0, output or "No workflow record changes to commit."


def compact_history(history: object, limit: int = 12) -> str:
    if not isinstance(history, list):
        return "No prior chat in this dashboard session."
    lines = []
    for item in history[-limit:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "unknown"))[:40]
        content = str(item.get("content", "")).strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n\n".join(lines) if lines else "No prior chat in this dashboard session."


def draft_review_text(draft_review: object) -> str:
    if not isinstance(draft_review, dict):
        return "No draft review choices are visible yet."
    lines = []
    structural = draft_review.get("structural_change")
    if isinstance(structural, dict):
        lines.extend(
            [
                "Structural change requested: "
                + ("yes" if structural.get("requested") else "no"),
                "Structural change comment:",
                str(structural.get("comment", "")).strip() or "(empty)",
                "",
            ]
        )
    decisions = draft_review.get("decisions")
    if isinstance(decisions, list) and decisions:
        lines.append("Draft checklist answers:")
        for item in decisions:
            if not isinstance(item, dict):
                continue
            label = str(item.get("item", "Unnamed item"))
            passed = "yes" if item.get("passed") else "no"
            comment = str(item.get("comment", "")).strip()
            lines.append(f"- {label}: {passed}")
            if comment:
                lines.append(f"  Comment: {comment}")
    return "\n".join(lines).strip() or "No draft review choices are visible yet."


def supervisor_chat(root: Path, message: str, history: object, draft_review: object) -> dict:
    gate_path = root / ".ai" / "supervisor" / "HUMAN_REVIEW_REQUIRED.md"
    if not gate_path.exists():
        return {"ok": False, "message": "No human milestone review gate exists."}
    message = message.strip()
    if not message:
        return {"ok": False, "message": "Enter a question for the supervisor."}
    if not shutil.which("codex"):
        return {"ok": False, "message": "codex executable was not found in PATH."}

    code, jobs_summary, jobs_err = run(["python3", "scripts/summarize_jobs.py"], root)
    if code != 0:
        jobs_summary = jobs_err or jobs_summary or "Unable to summarize jobs."

    context_files = [
        ("AGENTS.md", read_text(root / "AGENTS.md", 40_000)),
        (".ai/supervisor/supervisor_protocol.md", read_text(root / ".ai" / "supervisor" / "supervisor_protocol.md", 40_000)),
        (".ai/supervisor/project_brief.md", read_text(root / ".ai" / "supervisor" / "project_brief.md", 50_000)),
        (".ai/supervisor/roadmap.md", read_text(root / ".ai" / "supervisor" / "roadmap.md", 50_000)),
        (".ai/supervisor/ledger.md", read_text(root / ".ai" / "supervisor" / "ledger.md", 60_000)),
        (".ai/supervisor/HUMAN_REVIEW_REQUIRED.md", read_text(gate_path, 60_000)),
    ]
    context = "\n\n".join(f"## {name}\n\n{text or '(missing or empty)'}" for name, text in context_files)
    prompt = f"""You are the Codex supervisor for this scientific coding project.

The human is in the dashboard human milestone review panel and wants read-only guidance before submitting the review.

Hard constraints:
- Answer the human's question only.
- Do not edit files.
- Do not dispatch jobs.
- Do not accept or reject work.
- Do not update the ledger, roadmap, project brief, or any workflow state.
- Do not ask the worker or reviewers to do anything.
- Keep the answer concise and actionable.
- If the human asks what yes/no means for a checklist item, explain the consequence and what evidence to inspect.
- If the human asks for a recommendation, state the recommendation and the reason from the provided records.

# Current human question

{message}

# Current draft review answers/comments

{draft_review_text(draft_review)}

# Recent dashboard chat history

{compact_history(history)}

# Compact job table

{jobs_summary}

# Workflow and milestone context

{context}
"""

    model = os.environ.get("AI_WORKFLOW_CHAT_MODEL") or os.environ.get("CODEX_MODEL") or "gpt-5.5"
    effort = os.environ.get("AI_WORKFLOW_CHAT_REASONING_EFFORT") or os.environ.get("CODEX_REASONING_EFFORT") or "high"
    timeout_seconds = max(30, env_int("AI_WORKFLOW_CHAT_TIMEOUT", 300))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = runs_dir(root) / f"human_review_chat_{stamp}.log"
    args = [
        "codex",
        "--ask-for-approval",
        "never",
        "--sandbox",
        "read-only",
        "exec",
        "-C",
        str(root),
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-",
    ]
    try:
        result = subprocess.run(
            args,
            input=prompt,
            cwd=str(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(
            f"# Human Review Supervisor Chat\n\nTimed out after {timeout_seconds}s.\n\n## Prompt\n\n{prompt}\n\n## Partial stdout\n\n{exc.stdout or ''}\n\n## Partial stderr\n\n{exc.stderr or ''}\n",
            encoding="utf-8",
        )
        return {
            "ok": False,
            "message": f"Supervisor chat timed out after {timeout_seconds}s.",
            "log_file": str(log_path.relative_to(root)),
            "model": model,
        }

    answer = result.stdout.strip()
    log_path.write_text(
        "\n".join(
            [
                "# Human Review Supervisor Chat",
                "",
                f"- Model: `{model}`",
                f"- Reasoning effort: `{effort}`",
                f"- Exit code: `{result.returncode}`",
                "",
                "## Prompt",
                "",
                prompt,
                "",
                "## Stdout",
                "",
                answer,
                "",
                "## Stderr",
                "",
                result.stderr.strip(),
            ]
        ).rstrip() + "\n",
        encoding="utf-8",
    )
    if result.returncode != 0:
        return {
            "ok": False,
            "message": (result.stderr.strip() or answer or f"Supervisor chat failed with exit code {result.returncode}")[-2000:],
            "answer": answer,
            "exit_code": result.returncode,
            "log_file": str(log_path.relative_to(root)),
            "model": model,
        }
    return {
        "ok": True,
        "answer": answer or "(The supervisor returned no text.)",
        "model": model,
        "reasoning_effort": effort,
        "log_file": str(log_path.relative_to(root)),
    }


def workflow_chat(root: Path, message: str, history: object, allow_edits: bool, model_override: str = "") -> dict:
    message = message.strip()
    if not message:
        return {"ok": False, "message": "Enter a question for the workflow chat."}
    if not shutil.which("codex"):
        return {"ok": False, "message": "codex executable was not found in PATH."}

    code, jobs_summary, jobs_err = run(["python3", "scripts/summarize_jobs.py"], root)
    if code != 0:
        jobs_summary = jobs_err or jobs_summary or "Unable to summarize jobs."
    _, project_status, _ = run(["git", "status", "--short"], root)
    _, project_head, _ = run(["git", "log", "--oneline", "-1"], root)
    _, workflow_status, _ = run(["git", "status", "--short"], PACKAGE_ROOT)
    _, workflow_head, _ = run(["git", "log", "--oneline", "-1"], PACKAGE_ROOT)

    job_rows = jobs(root)
    processes = process_blocks(root)
    controls = {
        "worker": control_info(root, "worker_loop"),
        "supervisor": control_info(root, "supervisor_loop"),
    }
    supervisor = supervisor_state(root, job_rows)
    activity = activity_state(job_rows, processes, controls, supervisor)
    active = activity.get("active_job") or {}

    context_files = [
        ("Project AGENTS.md", read_text(root / "AGENTS.md", 35_000)),
        ("Workflow package README.md", read_text(PACKAGE_ROOT / "README.md", 35_000)),
        (".ai/supervisor/supervisor_protocol.md", read_text(root / ".ai" / "supervisor" / "supervisor_protocol.md", 35_000)),
        (".ai/supervisor/roadmap.md", read_text(root / ".ai" / "supervisor" / "roadmap.md", 45_000)),
        (".ai/supervisor/ledger.md", read_text(root / ".ai" / "supervisor" / "ledger.md", 45_000)),
    ]
    if active.get("id"):
        job_dir = root / ".ai" / "jobs" / str(active.get("id"))
        attempt = active.get("attempt", 0)
        context_files.extend(
            [
                (f"{active.get('id')} status.json", json.dumps(read_json(job_dir / "status.json"), indent=2)),
                (f"{active.get('id')} task.md", read_text(job_dir / "task.md", 30_000)),
                (f"{active.get('id')} report.md", read_text(job_dir / "report.md", 25_000)),
                (f"{active.get('id')} worker output", tail(job_dir / f"cursor_final.attempt-{attempt}.md", 160)),
            ]
        )
    context = "\n\n".join(f"## {name}\n\n{text or '(missing or empty)'}" for name, text in context_files)

    if allow_edits:
        mode_rules = f"""The user explicitly enabled edit mode for this chat.

You may edit files if and only if the user's current message asks for a concrete workflow change.

Editing rules:
- Prefer reusable workflow changes in `{PACKAGE_ROOT}` when the request is generally applicable to the AI supervisor/worker package.
- Use the project repo `{root}` only for project-specific workflow state, wrappers, or submodule pointer updates.
- Do not edit active job artifacts under `.ai/jobs/` unless the user explicitly asks for job-state repair.
- Do not run `cursor-agent`, `scripts/worker_loop.sh`, or `scripts/supervisor_loop.sh`.
- Do not stop running worker or supervisor loops unless the user explicitly asks.
- Do not push to a remote unless the user explicitly asks.
- If you make reusable workflow-package changes, run focused validation and commit them in the workflow package when complete.
- If you advance the project submodule pointer, commit only that pointer/wrapper change in the project repo and do not stage active job artifacts.
- Keep the final answer concise: what changed, validation, commits, and any manual step.
"""
    else:
        mode_rules = """This chat is in read-only guidance mode.

Hard constraints:
- Answer the user's question only.
- Do not edit files.
- Do not dispatch jobs.
- Do not start, stop, or relaunch loops.
- Do not update Git state.
- If the user asks for a change, explain that they must enable "Allow this chat agent to edit workflow files" and resend the request.
"""

    prompt = f"""You are a workflow-aware Codex agent launched from the AI Workflow Console.

The user wants to chat about the supervisor/worker workflow, the current run, or the reusable workflow package.

{mode_rules}

# User message

{message}

# Recent chat history

{compact_history(history)}

# Current activity

- Summary: {activity.get('summary', '')}
- Worker: {activity.get('worker', '')}
- Supervisor: {activity.get('supervisor', '')}
- Active job: {json.dumps(active, indent=2)}

# Project Git

- Root: `{root}`
- HEAD: `{project_head}`
- Dirty status:
```text
{project_status or '(clean)'}
```

# Workflow Package Git

- Root: `{PACKAGE_ROOT}`
- HEAD: `{workflow_head}`
- Dirty status:
```text
{workflow_status or '(clean)'}
```

# Compact job table

```text
{jobs_summary}
```

# Context

{context}
"""

    model = model_override.strip() or os.environ.get("AI_WORKFLOW_CHAT_MODEL") or os.environ.get("CODEX_MODEL") or "gpt-5.5"
    effort = os.environ.get("AI_WORKFLOW_CHAT_REASONING_EFFORT") or os.environ.get("CODEX_REASONING_EFFORT") or "high"
    timeout_seconds = max(30, env_int("AI_WORKFLOW_CHAT_TIMEOUT", 600 if allow_edits else 300))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = runs_dir(root) / f"workflow_chat_{stamp}.log"
    sandbox = "workspace-write" if allow_edits else "read-only"
    args = [
        "codex",
        "--ask-for-approval",
        "never",
        "--sandbox",
        sandbox,
        "exec",
        "-C",
        str(root),
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-",
    ]
    try:
        result = subprocess.run(
            args,
            input=prompt,
            cwd=str(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(
            f"# Workflow Chat\n\nTimed out after {timeout_seconds}s.\n\n## Mode\n\n{sandbox}\n\n## Prompt\n\n{prompt}\n\n## Partial stdout\n\n{exc.stdout or ''}\n\n## Partial stderr\n\n{exc.stderr or ''}\n",
            encoding="utf-8",
        )
        return {
            "ok": False,
            "message": f"Workflow chat timed out after {timeout_seconds}s.",
            "log_file": str(log_path.relative_to(root)),
            "model": model,
        }

    answer = result.stdout.strip()
    log_path.write_text(
        "\n".join(
            [
                "# Workflow Chat",
                "",
                f"- Mode: `{sandbox}`",
                f"- Model: `{model}`",
                f"- Reasoning effort: `{effort}`",
                f"- Exit code: `{result.returncode}`",
                "",
                "## Prompt",
                "",
                prompt,
                "",
                "## Stdout",
                "",
                answer,
                "",
                "## Stderr",
                "",
                result.stderr.strip(),
            ]
        ).rstrip() + "\n",
        encoding="utf-8",
    )
    if result.returncode != 0:
        return {
            "ok": False,
            "message": (result.stderr.strip() or answer or f"Workflow chat failed with exit code {result.returncode}")[-2000:],
            "answer": answer,
            "exit_code": result.returncode,
            "log_file": str(log_path.relative_to(root)),
            "model": model,
        }
    return {
        "ok": True,
        "answer": answer or "(The workflow agent returned no text.)",
        "model": model,
        "reasoning_effort": effort,
        "log_file": str(log_path.relative_to(root)),
        "mode": sandbox,
    }


def create_structural_change_request(
    root: Path,
    reviews_dir: Path,
    stamp: str,
    archived_gate: Path,
    review_record: Path,
    comment: str,
) -> Path:
    request_path = root / ".ai" / "supervisor" / "STRUCTURAL_CHANGE_REQUESTED.md"
    task_lines = [
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
        "- Keep accepted reference implementations as reference/test-oracle paths unless the human request explicitly says otherwise.",
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
        f"- Milestone gate: `{archived_gate}`",
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
    text = "\n".join(task_lines).rstrip() + "\n"
    request_path.write_text(text, encoding="utf-8")
    archive_copy = reviews_dir / f"structural_change_request_{stamp}.md"
    archive_copy.write_text(text, encoding="utf-8")
    return request_path


def create_human_review_action_request(
    root: Path,
    reviews_dir: Path,
    stamp: str,
    archived_gate: Path,
    review_record: Path,
    failed: list[dict],
) -> Path:
    request_path = root / ".ai" / "supervisor" / "HUMAN_REVIEW_ACTION_REQUESTED.md"
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
        f"- Archived milestone gate: `{archived_gate}`",
        f"- Human review record: `{review_record}`",
        "",
        "## Failed Human Review Items",
        "",
    ]
    for index, item in enumerate(failed, 1):
        lines.append(f"### {index}. {item.get('item', 'Unnamed item')}")
        lines.append("")
        comment = str(item.get("comment", "")).strip() or "No comment provided."
        lines.append(comment)
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


def write_human_review(root: Path, decisions: list[dict], structural_change: dict | None = None) -> dict:
    gate_path = root / ".ai" / "supervisor" / "HUMAN_REVIEW_REQUIRED.md"
    if not gate_path.exists():
        return {"ok": False, "message": "No human review gate exists."}

    gate_text = read_text(gate_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    reviews_dir = root / ".ai" / "supervisor" / "human_reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    review_record = reviews_dir / f"human_review_{stamp}.md"
    archived_gate = reviews_dir / f"HUMAN_REVIEW_REQUIRED_{stamp}.md"
    structural_requested = bool((structural_change or {}).get("requested"))
    structural_comment = str((structural_change or {}).get("comment", "")).strip()
    failed = [item for item in decisions if not item.get("passed")]
    result_label = "structural_change_requested" if structural_requested else (
        "changes_requested" if failed else "approved"
    )

    lines = [
        "# Human Milestone Review Record",
        "",
        f"- Reviewed at: `{stamp}`",
        f"- Result: `{result_label}`",
        "",
    ]
    if structural_requested:
        lines.extend(["## Major Structural Change", ""])
        lines.append(structural_comment or "No structural change details provided.")
        lines.append("")
        lines.append("Checklist review was superseded by the structural change request.")
        lines.append("")
    else:
        lines.extend(["## Checklist Results", ""])
        for item in decisions:
            mark = "x" if item.get("passed") else " "
            label = str(item.get("item", "Unnamed item"))
            lines.append(f"- [{mark}] {label}")
            if not item.get("passed"):
                comment = str(item.get("comment", "")).strip() or "No comment provided."
                lines.append("")
                lines.append("  Comment:")
                for comment_line in comment.splitlines():
                    lines.append(f"  {comment_line}")
                lines.append("")
    lines.extend(["", "## Original Milestone Gate", "", gate_text])
    review_record.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    shutil.move(str(gate_path), archived_gate)

    ledger = root / ".ai" / "supervisor" / "ledger.md"
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write("\n## Human milestone review update\n\n")
        handle.write(f"- Review record: `{review_record.relative_to(root)}`.\n")

    if structural_requested:
        request_path = create_structural_change_request(
            root, reviews_dir, stamp, archived_gate, review_record, structural_comment
        )
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(f"- Major structural change requested. Supervisor structural request: `{request_path.relative_to(root)}`.\n")
        commit_ok, commit_output = commit_workflow_records(root, "workflow: record major structural change request")
        return {
            "ok": True,
            "message": "Major structural change requested. The supervisor must update the milestones itself and open a follow-up human review gate before implementation resumes.",
            "request_path": str(request_path.relative_to(root)),
            "review_record": str(review_record.relative_to(root)),
            "archived_gate": str(archived_gate.relative_to(root)),
            "commit_ok": commit_ok,
            "commit_output": commit_output,
        }

    if not failed:
        prune_ok, prune_output = prune_accepted_job_refs(root, review_record)
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write("- Accepted job branch/worktree pruning:\n")
            for line in prune_output.splitlines():
                handle.write(f"  - {line}\n")
        commit_ok, commit_output = commit_workflow_records(root, "workflow: record human milestone approval")
        return {
            "ok": True,
            "message": "Human review approved. Gate archived.",
            "review_record": str(review_record.relative_to(root)),
            "archived_gate": str(archived_gate.relative_to(root)),
            "prune_ok": prune_ok,
            "prune_output": prune_output,
            "commit_ok": commit_ok,
            "commit_output": commit_output,
        }

    request_path = create_human_review_action_request(
        root, reviews_dir, stamp, archived_gate, review_record, failed
    )
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(f"- Human milestone review requested changes. Supervisor action request: `{request_path.relative_to(root)}`.\n")
    commit_ok, commit_output = commit_workflow_records(root, "workflow: record human milestone review action request")
    return {
        "ok": True,
        "message": "Changes requested. Supervisor action request created; the supervisor will decide the next worker job or gate.",
        "request_path": str(request_path.relative_to(root)),
        "review_record": str(review_record.relative_to(root)),
        "archived_gate": str(archived_gate.relative_to(root)),
        "commit_ok": commit_ok,
        "commit_output": commit_output,
    }


class Handler(SimpleHTTPRequestHandler):
    project_root: Path

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), format % args))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            payload = json.dumps(state(self.project_root), indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = read_request_json(self)
        except ValueError as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "message": str(exc)})
            return

        if parsed.path == "/api/worker/start":
            result = start_loop(self.project_root, "worker_loop", worker_loop_env(payload))
            json_response(self, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        if parsed.path == "/api/supervisor/start":
            result = start_loop(self.project_root, "supervisor_loop", supervisor_loop_env(payload))
            json_response(self, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        if parsed.path == "/api/worker/stop":
            json_response(self, HTTPStatus.OK, stop_loop(self.project_root, "worker_loop"))
            return

        if parsed.path == "/api/supervisor/stop":
            json_response(self, HTTPStatus.OK, stop_loop(self.project_root, "supervisor_loop"))
            return

        if parsed.path == "/api/human-review":
            result = write_human_review(
                self.project_root,
                list(payload.get("decisions", [])),
                payload.get("structural_change") if isinstance(payload.get("structural_change"), dict) else None,
            )
            if result.get("ok"):
                result["auto_start"] = auto_start_loops_after_human_review(self.project_root)
                if result["auto_start"].get("ok"):
                    result["message"] = f"{result.get('message', 'Human review submitted.')} Supervisor and worker loops are running."
                else:
                    result["message"] = f"{result.get('message', 'Human review submitted.')} Auto-start attempted; inspect auto_start details."
            json_response(self, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        if parsed.path == "/api/supervisor-chat":
            result = supervisor_chat(
                self.project_root,
                str(payload.get("message", "")),
                payload.get("history", []),
                payload.get("draft_review", {}),
            )
            json_response(self, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        if parsed.path == "/api/workflow-chat":
            result = workflow_chat(
                self.project_root,
                str(payload.get("message", "")),
                payload.get("history", []),
                bool(payload.get("allow_edits", False)),
                str(payload.get("model", "")),
            )
            json_response(self, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        if parsed.path == "/api/open-file":
            result = open_project_file(self.project_root, str(payload.get("path", "")))
            json_response(self, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "message": f"unknown endpoint: {parsed.path}"})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if not (project_root / ".git").exists():
        raise SystemExit(f"project root is not a Git repository root: {project_root}")

    os.chdir(GUI_ROOT)
    Handler.project_root = project_root
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"AI workflow dashboard: {url}")
    print(f"Project: {project_root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
