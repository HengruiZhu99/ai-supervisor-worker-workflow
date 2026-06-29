#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Serve a local dashboard for the AI supervisor/worker workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4
from urllib.parse import parse_qs, urlparse


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = PACKAGE_ROOT / "gui"
WORKFLOW_CHAT_JOBS: dict[str, dict] = {}
WORKFLOW_CHAT_JOBS_LOCK = threading.Lock()
STATE_CACHE_LOCK = threading.Lock()
STATE_CACHE_ROOT = ""
STATE_CACHE_PAYLOAD = b""
STATE_CACHE_AT = 0.0
DEFAULT_LOG_DISPLAY_LINES = 2_000
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
WORKER_PIPELINE_STATES = {"queued", "running", "rejected", "implemented", "reviewing"}
SUPERVISOR_ACTIONABLE_JOB_STATES = {"ready_for_review", "blocked", "review_failed", "review_timeout", "invalid"}
DEFAULT_HUMAN_REVIEW_ITEMS = [
    "Milestone summary is accurate.",
    "Accepted jobs and commits are reviewable.",
    "Progress accounting shows executable, numerical, or backend validation progress, or this is explicitly approved as a planning/source-only milestone.",
    "Tests and validation are acceptable.",
    "Scientific assumptions, risks, and limitations are acceptable.",
    "Workflow evolution decisions are acceptable.",
    "Recommended next milestone is acceptable.",
]


def env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(100, value)


def env_nonnegative_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(0, value)


LOG_DISPLAY_LINES = env_int("AI_WORKFLOW_GUI_LOG_LINES", DEFAULT_LOG_DISPLAY_LINES)
DEFAULT_GUI_PORT = 8765
GUI_PORT_SEARCH_LIMIT = 100


def run(args: list[str], cwd: Path, timeout: float = 10.0) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return 124, stdout.strip(), (stderr.strip() + f"\ncommand timed out after {timeout}s").strip()


def read_text(path: Path, limit: int | None = 80_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if limit is not None and len(text) > limit:
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


def loop_lock_pid_file(root: Path, name: str) -> Path:
    return runs_dir(root) / f"{name}.lock" / "pid"


def loop_lock_workflow_commit_file(root: Path, name: str) -> Path:
    return runs_dir(root) / f"{name}.lock" / "workflow_commit"


def log_file(root: Path, name: str) -> Path:
    return runs_dir(root) / f"{name}.log"


def runtime_dir(root: Path) -> Path:
    runtime = root / ".ai" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime


def gui_port_config_path(root: Path) -> Path:
    return runtime_dir(root) / "workflow_gui_port.json"


def loop_autostart_disabled_path(root: Path, name: str) -> Path:
    return runtime_dir(root) / f"{name}.autostart_disabled"


def loop_launch_env_path(root: Path, name: str) -> Path:
    return runtime_dir(root) / f"{name}.launch_env.json"


def loop_autorelaunch_state_path(root: Path, name: str) -> Path:
    return runtime_dir(root) / f"{name}.autorelaunch.json"


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_available_port(host: str, start_port: int) -> int:
    for port in range(start_port, start_port + GUI_PORT_SEARCH_LIMIT):
        if port_available(host, port):
            return port
    raise SystemExit(f"no available dashboard port found in {start_port}-{start_port + GUI_PORT_SEARCH_LIMIT - 1}")


def load_stored_gui_port(root: Path) -> int | None:
    data = read_json(gui_port_config_path(root))
    try:
        port = int(data.get("port", 0))
    except (TypeError, ValueError):
        return None
    if 0 < port < 65536:
        return port
    return None


def store_gui_port(root: Path, host: str, port: int) -> None:
    payload = {
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}/",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    gui_port_config_path(root).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resolve_gui_port(root: Path, host: str, requested_port: int | None) -> tuple[int, str]:
    if requested_port is not None:
        store_gui_port(root, host, requested_port)
        return requested_port, "explicit"

    stored_port = load_stored_gui_port(root)
    if stored_port is not None and port_available(host, stored_port):
        return stored_port, "stored"

    start_port = stored_port or DEFAULT_GUI_PORT
    selected = find_available_port(host, start_port)
    store_gui_port(root, host, selected)
    if stored_port is not None and selected != stored_port:
        return selected, f"stored port {stored_port} was busy; reassigned"
    return selected, "auto"


def workflow_package_commit() -> str:
    code, out, _ = run(["git", "rev-parse", "--short", "HEAD"], PACKAGE_ROOT)
    return out if code == 0 and out else "unknown"


def logged_workflow_commit(log_tail: str) -> str:
    matches = re.findall(r"workflow_commit=([0-9a-fA-F]+|unknown)", log_tail)
    return matches[-1] if matches else ""


def latest_loop_launch_env(root: Path, name: str) -> dict[str, str]:
    """Parse the most recent launch header from a loop log.

    The GUI needs the active wrapper/model, not the static form defaults. Loop
    logs can be long enough that the launch header falls outside the displayed
    tail, so scan the full local log and keep only simple key=value header
    entries from the latest launch block.
    """
    path = log_file(root, name)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}

    latest: dict[str, str] = {}
    in_header = False
    for line in lines:
        if line.startswith("--- launched "):
            latest = {}
            in_header = True
            continue
        if not in_header:
            continue
        if "=" not in line:
            in_header = False
            continue
        key, value = line.split("=", 1)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            latest[key] = value.strip()
        else:
            in_header = False
    return latest


def lock_workflow_commit(root: Path, name: str) -> str:
    if read_pid(loop_lock_pid_file(root, name)) is None:
        return ""
    try:
        value = loop_lock_workflow_commit_file(root, name).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if re.fullmatch(r"[0-9a-fA-F]+|unknown", value):
        return value
    return ""


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


def loop_pid(root: Path, name: str) -> tuple[int | None, str]:
    pid = read_pid(pid_file(root, name))
    if pid is not None:
        return pid, "pid_file"
    pid = read_pid(loop_lock_pid_file(root, name))
    if pid is not None:
        return pid, "lock_pid_file"
    return None, ""


def remove_stale_loop_lock(root: Path, name: str) -> None:
    lock_pid_path = loop_lock_pid_file(root, name)
    lock_dir = lock_pid_path.parent
    if read_pid(lock_pid_path) is not None:
        return
    for child in (lock_pid_path, lock_dir / "started_at", loop_lock_workflow_commit_file(root, name)):
        try:
            child.unlink()
        except OSError:
            pass
    try:
        lock_dir.rmdir()
    except OSError:
        pass


def control_info(root: Path, name: str) -> dict:
    pid, pid_source = loop_pid(root, name)
    log = log_file(root, name)
    log_tail = tail(log, LOG_DISPLAY_LINES)
    expected_commit = workflow_package_commit()
    running_commit = lock_workflow_commit(root, name) or logged_workflow_commit(log_tail)
    version_warning = ""
    if pid is not None and expected_commit != "unknown" and running_commit and running_commit != expected_commit:
        version_warning = "running loop uses older workflow version; restart recommended"
    return {
        "pid": pid,
        "running": pid is not None,
        "pid_file": str(pid_file(root, name).relative_to(root)),
        "lock_pid_file": str(loop_lock_pid_file(root, name).relative_to(root)),
        "pid_source": pid_source,
        "log_file": str(log.relative_to(root)),
        "log_tail": log_tail,
        "log_display_lines": LOG_DISPLAY_LINES,
        "workflow_commit": running_commit,
        "expected_workflow_commit": expected_commit,
        "version_warning": version_warning,
        "launch_env": latest_loop_launch_env(root, name),
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
    return items or DEFAULT_HUMAN_REVIEW_ITEMS


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
        load_detail = data.get("state") in ACTIVE_JOB_STATES
        data["_path"] = str(job_dir.relative_to(root))
        data["_files"] = sorted(path.name for path in job_dir.iterdir() if path.is_file())
        data["_report_tail"] = tail(job_dir / "report.md", 60) if load_detail else ""
        data["_test_tail"] = tail(job_dir / f"test.attempt-{attempt}.log", 60) if load_detail else ""
        data["_cursor_tail"] = tail(job_dir / f"cursor_final.attempt-{attempt}.md", 60) if load_detail else ""
        data["_task_text"] = read_text(job_dir / "task.md", 40_000) if load_detail else ""
        reviews_dir = job_dir / "reviews"
        data["_reviewer_a_tail"] = tail(reviews_dir / f"reviewer-a.attempt-{attempt}.md", 80) if load_detail else ""
        data["_reviewer_b_tail"] = tail(reviews_dir / f"reviewer-b.attempt-{attempt}.md", 80) if load_detail else ""
        data["_consensus_tail"] = ""
        if load_detail:
            consensus_dir = reviews_dir / f"consensus.attempt-{attempt}"
            if consensus_dir.is_dir():
                data["_consensus_tail"] = tail(consensus_dir / "consensus.md", 120)
                finals = sorted(consensus_dir.glob("*.final.md"))
                # Surface panelist final reports in the two reviewer slots when
                # the legacy reviewer-a/b files are absent (consensus mode).
                if not data["_reviewer_a_tail"] and finals:
                    data["_reviewer_a_tail"] = tail(finals[0], 80)
                if not data["_reviewer_b_tail"] and len(finals) > 1:
                    data["_reviewer_b_tail"] = tail(finals[1], 80)
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
    consensus_mode = str(job.get("reviewers_mode", "")) == "consensus"
    title = f"{job_id} reviewer reports"
    reviewer_a_path = f".ai/jobs/{job_id}/reviews/reviewer-a.attempt-{attempt}.md" if job_id else ""
    reviewer_b_path = f".ai/jobs/{job_id}/reviews/reviewer-b.attempt-{attempt}.md" if job_id else ""
    if consensus_mode:
        verdict = job.get("consensus_verdict", "?")
        method = job.get("consensus_method", "?")
        title = f"{job_id} consensus review (verdict {verdict}, {method})"
        consensus_dir = root / ".ai" / "jobs" / job_id / "reviews" / f"consensus.attempt-{attempt}"
        finals = sorted(consensus_dir.glob("*.final.md")) if consensus_dir.is_dir() else []
        if finals:
            reviewer_a_path = str(finals[0].relative_to(root))
        if len(finals) > 1:
            reviewer_b_path = str(finals[1].relative_to(root))
    return {
        "title": title,
        "job_id": job_id,
        "state": job.get("state", ""),
        "consensus_mode": consensus_mode,
        "consensus_verdict": job.get("consensus_verdict", ""),
        "consensus_method": job.get("consensus_method", ""),
        "consensus": job.get("_consensus_tail", ""),
        "reviewer_a_model": job.get("reviewer_a_model", ""),
        "reviewer_b_model": job.get("reviewer_b_model", ""),
        "reviewer_a_exit": job.get("reviewer_a_exit", ""),
        "reviewer_b_exit": job.get("reviewer_b_exit", ""),
        "reviewer_a": job.get("_reviewer_a_tail") or "Reviewer A has not emitted a report yet.",
        "reviewer_b": job.get("_reviewer_b_tail") or "Reviewer B has not emitted a report yet.",
        "reviewer_a_path": reviewer_a_path,
        "reviewer_b_path": reviewer_b_path,
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


def milestone_key(text: str) -> str:
    match = re.match(r"^\s*(?:#+\s*)?(M\d+(?:\.\d+)?)\b", text, re.IGNORECASE)
    return match.group(1).upper() if match else ""


def milestone_label_hint(line: str) -> tuple[str, str] | None:
    match = re.match(r"^(M\d+(?:\.\d+)?)\s+([^:]{1,120}):\s*$", line.strip(), re.IGNORECASE)
    if not match:
        return None
    return match.group(1).upper(), match.group(2).strip()


def add_milestone_hint(
    hints: dict[str, dict],
    key: str,
    subtitle: str,
    source_line: int,
) -> None:
    if not subtitle:
        return
    subtitle = subtitle.strip().rstrip(".")
    record = hints.setdefault(key, {"source_line": source_line, "subtitles": []})
    record["source_line"] = min(record["source_line"], source_line)
    subtitles_lower = {str(value).lower() for value in record["subtitles"]}
    if subtitle.lower() not in subtitles_lower:
        record["subtitles"].append(subtitle)


def milestone_title_from_hint(key: str, hint: dict) -> str:
    subtitles = [str(value).strip() for value in hint.get("subtitles", []) if str(value).strip()]
    if not subtitles:
        return key
    normalized = [subtitles[0][:1].upper() + subtitles[0][1:]]
    normalized.extend(subtitle[:1].lower() + subtitle[1:] for subtitle in subtitles[1:])
    return f"{key}: {' and '.join(normalized)}"


def milestone_subtitle_from_item(key: str, item_text: str) -> str:
    subtitle = item_text[len(key) :].strip(" :-")
    subtitle = re.split(r"\s+(?:before|after)\s+", subtitle, maxsplit=1)[0]
    subtitle = re.sub(r"\s+are\s+approved\b.*$", "", subtitle, flags=re.IGNORECASE)
    subtitle = re.sub(r"\s+is\s+approved\b.*$", "", subtitle, flags=re.IGNORECASE)
    return subtitle.strip()


def human_gate_milestone(gate_text: str) -> str:
    lines = gate_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "## Milestone":
            for value in lines[index + 1 :]:
                value = value.strip()
                if value:
                    return value.rstrip(".")
        match = re.match(r"^##\s+(M\d+(?:\.\d+)?:.+)$", line.strip())
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
    left_id = milestone_key(left)
    right_id = milestone_key(right)
    return bool(left_id and right_id and left_id == right_id)


def parse_roadmap(
    text: str,
    active_contexts: list[str] | None = None,
    pending_human_milestone: str = "",
) -> list[dict]:
    active_contexts = active_contexts or []
    milestones = []
    current: dict | None = None
    synthetic_hints: dict[str, dict] = {}
    synthetic_items: dict[str, list[dict]] = {}
    for line_index, line in enumerate(text.splitlines()):
        if line.startswith("## "):
            if current:
                milestones.append(current)
            current = {
                "title": line[3:].strip(),
                "items": [],
                "done": 0,
                "total": 0,
                "_source_line": line_index,
            }
            continue
        label_hint = milestone_label_hint(line)
        if label_hint:
            key, subtitle = label_hint
            add_milestone_hint(synthetic_hints, key, subtitle, line_index)
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
            item_key = milestone_key(item_text)
            if item_key:
                synthetic_items.setdefault(item_key, []).append(current["items"][-1].copy())
                if item_key not in synthetic_hints:
                    add_milestone_hint(
                        synthetic_hints,
                        item_key,
                        milestone_subtitle_from_item(item_key, item_text),
                        line_index,
                    )
    if current:
        milestones.append(current)
    existing_keys = {milestone_key(str(milestone.get("title", ""))) for milestone in milestones}
    for key, hint in synthetic_hints.items():
        if key in existing_keys:
            continue
        items = synthetic_items.get(key, [])
        synthetic = {
            "title": milestone_title_from_hint(key, hint),
            "items": items,
            "done": sum(1 for item in items if item.get("done")),
            "total": len(items),
            "_source_line": hint.get("source_line", len(milestones) + 1),
        }
        active_count = sum(1 for item in items if item.get("active"))
        if active_count:
            synthetic["active"] = active_count
        milestones.append(synthetic)
    milestones.sort(key=lambda milestone: int(milestone.get("_source_line", 0)))
    for milestone in milestones:
        milestone.pop("_source_line", None)
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
    roadmap_for_milestones = read_text(supervisor / "roadmap.md", None)
    ledger = read_text(supervisor / "ledger.md")
    project_brief = read_text(supervisor / "project_brief.md")
    gate_path = supervisor / "HUMAN_REVIEW_REQUIRED.md"
    gate_text = read_text(gate_path)
    structural_request_path = supervisor / "STRUCTURAL_CHANGE_REQUESTED.md"
    structural_request_text = read_text(structural_request_path)
    human_review_action_path = supervisor / "HUMAN_REVIEW_ACTION_REQUESTED.md"
    human_review_action_text = read_text(human_review_action_path)
    supervisor_action_path = supervisor / "SUPERVISOR_ACTION_REQUIRED.md"
    supervisor_action_text = read_text(supervisor_action_path)
    runs_dir = root / ".ai" / "supervisor_runs"
    run_logs = sorted(runs_dir.glob("supervisor.*.log"))
    latest_log = run_logs[-1] if run_logs else None
    review_records = sorted(
        path for path in (supervisor / "human_reviews").glob("human_review_*.md")
        if re.fullmatch(r"human_review_\d{8}T\d{6}Z\.md", path.name)
    )
    latest_review = review_records[-1] if review_records else None
    latest_review_text = read_text(latest_review) if latest_review else ""
    latest_review_result = ""
    match = re.search(r"^- Result:\s+`([^`]+)`", latest_review_text, re.MULTILINE)
    if match:
        latest_review_result = match.group(1)
    return {
        "roadmap": roadmap,
        "milestones": parse_roadmap(
            roadmap_for_milestones,
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
        "supervisor_action_exists": supervisor_action_path.exists(),
        "supervisor_action": supervisor_action_text,
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
    latest_result = str(supervisor.get("latest_human_review_result", ""))
    if latest_result == "approved":
        return False
    if latest_result in {"changes_requested", "structural_change_requested"}:
        return False
    if any(job.get("state") in ACTIVE_JOB_STATES for job in job_rows):
        return False
    ledger = str(supervisor.get("ledger", "")).lower()
    review_phrases = [
        "pending human boundary review",
        "pending human milestone review",
        "pending renewed human boundary review",
        "pending renewed human milestone review",
        "human review gate is open",
        "reopened the m",
    ]
    return any(phrase in ledger for phrase in review_phrases)


def activity_state(job_rows: list[dict], processes: dict, controls: dict, supervisor: dict) -> dict:
    active = active_job_summary(job_rows)
    ready_job = next((job for job in job_rows if job.get("state") == "ready_for_review"), None)
    recovery_job = next((job for job in job_rows if job.get("state") in {"blocked", "review_failed", "review_timeout"}), None)
    supervisor_agent_active = bool(processes.get("supervisor_agent"))
    supervisor_running = bool(controls.get("supervisor", {}).get("running"))
    worker_running = bool(controls.get("worker", {}).get("running"))
    human_gate_exists = bool(supervisor.get("human_gate_exists"))
    structural_request_exists = bool(supervisor.get("structural_request_exists"))
    human_review_action_exists = bool(supervisor.get("human_review_action_exists"))
    preparing_human_review = supervisor_agent_active and supervisor_preparing_human_review(supervisor, job_rows)

    if human_gate_exists:
        summary = "Wait for Human Milestone Review."
        if processes.get("modulator_agent"):
            summary = "Modulator agent is triaging the open human review gate."
    elif structural_request_exists:
        summary = (
            "Supervisor is preparing a structural plan revision."
            if supervisor_agent_active
            else "Structural plan revision is waiting for the supervisor."
        )
    elif human_review_action_exists:
        summary = (
            "Supervisor is preparing a human-review revision plan."
            if supervisor_agent_active
            else "Human-review revision request is waiting for the supervisor."
        )
    elif ready_job:
        summary = (
            f"Supervisor is reviewing {ready_job.get('id', 'a job')}."
            if supervisor_agent_active
            else f"{ready_job.get('id', 'A job')} is ready for supervisor review."
        )
    elif recovery_job:
        if recovery_job.get("state") == "blocked":
            summary = f"Worker is blocked on {recovery_job.get('id', 'a job')}; supervisor action is needed."
        else:
            summary = f"Reviewer stage failed on {recovery_job.get('id', 'a job')}; supervisor action is needed."
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
    elif supervisor_agent_active:
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
    elif any(job.get("state") in {"blocked", "review_failed", "review_timeout"} for job in job_rows):
        supervisor_text = "Supervisor should inspect blocked/reviewer-failure artifacts and decide whether to repair, retry, reject, or open a gate."
    elif preparing_human_review:
        supervisor_text = "Supervisor is preparing the milestone review summary and checklist."
    elif supervisor_agent_active:
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
    blocks = {
        "worker": [],
        "supervisor": [],
        "modulator": [],
        "cursor": [],
        "supervisor_agent": [],
        "modulator_agent": [],
    }
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
        elif argv_has_script(argv, "modulator_loop.sh"):
            blocks["modulator"].append(item)
        elif is_cursor_agent_process(argv):
            # The supervisor/modulator prompts carry stable role markers, so
            # their cursor-agent runs can be distinguished from worker runs.
            if "boundary-gated supervisor agent" in cmdline:
                blocks["supervisor_agent"].append(item)
            elif "always-on workflow modulator agent" in cmdline:
                blocks["modulator_agent"].append(item)
            else:
                blocks["cursor"].append(item)
        elif "codex" in cmdline and " exec " in f" {cmdline} ":
            # Legacy codex supervisor runs count as supervisor-agent activity.
            blocks["supervisor_agent"].append(item)
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
        "modulator": control_info(root, "modulator_loop"),
    }
    supervisor = supervisor_state(root, job_rows)
    auto_relaunch = auto_relaunch_worker_if_needed(root, job_rows, processes, controls, supervisor)
    auto_relaunch_supervisor = auto_relaunch_supervisor_if_needed(
        root, job_rows, processes, controls, supervisor
    )
    if (
        auto_relaunch.get("attempted") and auto_relaunch.get("start_result", {}).get("ok")
    ) or (
        auto_relaunch_supervisor.get("attempted")
        and auto_relaunch_supervisor.get("start_result", {}).get("ok")
    ):
        processes = process_blocks(root)
        controls = {
            "worker": control_info(root, "worker_loop"),
            "supervisor": control_info(root, "supervisor_loop"),
            "modulator": control_info(root, "modulator_loop"),
        }
    controls["worker"].update(worker_display_log(root, job_rows, controls["worker"]))
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
        "auto_relaunch": auto_relaunch,
        "auto_relaunch_supervisor": auto_relaunch_supervisor,
        "activity": activity_state(job_rows, processes, controls, supervisor),
        "reviewers": reviewer_state(root, job_rows),
        "agent_wrappers": agent_wrapper_catalog(root),
        "tree": project_tree(root),
    }


def state_payload(root: Path) -> bytes:
    global STATE_CACHE_AT, STATE_CACHE_PAYLOAD, STATE_CACHE_ROOT

    cache_ttl = env_nonnegative_int("AI_WORKFLOW_GUI_STATE_CACHE_SECONDS", 5)
    cache_root = str(root)
    now = time.monotonic()
    if (
        cache_ttl > 0
        and STATE_CACHE_ROOT == cache_root
        and STATE_CACHE_PAYLOAD
        and now - STATE_CACHE_AT <= cache_ttl
    ):
        return STATE_CACHE_PAYLOAD

    with STATE_CACHE_LOCK:
        now = time.monotonic()
        if (
            cache_ttl > 0
            and STATE_CACHE_ROOT == cache_root
            and STATE_CACHE_PAYLOAD
            and now - STATE_CACHE_AT <= cache_ttl
        ):
            return STATE_CACHE_PAYLOAD

        payload = json.dumps(state(root), indent=2).encode("utf-8")
        STATE_CACHE_ROOT = cache_root
        STATE_CACHE_PAYLOAD = payload
        STATE_CACHE_AT = time.monotonic()
        return payload


def agent_wrapper_catalog(root: Path) -> dict:
    script = PACKAGE_ROOT / "scripts" / "agent_wrapper.py"
    if not script.exists():
        return {"wrappers": [], "error": f"missing {script}"}
    result = subprocess.run(
        ["python3", str(script), "list", "--json"],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return {"wrappers": [], "error": result.stderr.strip() or result.stdout.strip() or "failed to list wrappers"}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"wrappers": [], "error": f"invalid wrapper catalog JSON: {exc}"}


def json_response(handler: SimpleHTTPRequestHandler, status: HTTPStatus, payload: dict) -> None:
    body = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        return


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
    existing, existing_source = loop_pid(root, name)
    if existing:
        if existing_source == "lock_pid_file":
            pid_file(root, name).write_text(str(existing) + "\n", encoding="utf-8")
        try:
            loop_autostart_disabled_path(root, name).unlink()
        except OSError:
            pass
        return {"ok": True, "message": f"{name} already running", "pid": existing, "pid_source": existing_source}

    script_names = {
        "worker_loop": "worker_loop.sh",
        "supervisor_loop": "supervisor_loop.sh",
        "modulator_loop": "modulator_loop.sh",
    }
    script_name = script_names.get(name, "supervisor_loop.sh")
    script_path = root / "scripts" / script_name
    if not script_path.exists():
        return {"ok": False, "message": f"missing script: {script_path}"}

    remove_stale_loop_lock(root, name)
    env = os.environ.copy()
    clean_env_updates = {key: value for key, value in env_updates.items() if value != ""}
    env.update(clean_env_updates)
    try:
        loop_autostart_disabled_path(root, name).unlink()
    except OSError:
        pass
    stamped_env = dict(clean_env_updates)
    stamped_env["_defaults_fingerprint"] = defaults_fingerprint(loop_default_env(name))
    loop_launch_env_path(root, name).write_text(
        json.dumps(stamped_env, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
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


def defaults_fingerprint(default_env: dict[str, str]) -> str:
    payload = json.dumps(default_env, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def saved_loop_env(root: Path, name: str, default_env: dict[str, str]) -> dict[str, str]:
    """Return the saved launch env only if the loop defaults are unchanged.

    Saved launch envs capture user customizations from the GUI form. When the
    workflow defaults themselves change (e.g. a wrapper/model migration), a
    stale snapshot must not silently resurrect the old stack on auto-relaunch
    (observed 2026-06-11: a pre-migration codex/gpt-5.5 env was replayed).
    The env is stamped with a fingerprint of the defaults at save time; on
    mismatch the current defaults win.
    """
    data = read_json(loop_launch_env_path(root, name))
    if not data:
        return default_env
    saved_fingerprint = data.pop("_defaults_fingerprint", None)
    if saved_fingerprint != defaults_fingerprint(default_env):
        return default_env
    return {str(key): str(value) for key, value in data.items() if str(value) != ""}


def mark_autorelaunch_attempt(root: Path, name: str, result: dict | None = None) -> None:
    payload = {
        "attempted_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    if result is not None:
        payload["result"] = result
    loop_autorelaunch_state_path(root, name).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def autorelaunch_recently_attempted(root: Path, name: str, cooldown_seconds: int) -> bool:
    if cooldown_seconds <= 0:
        return False
    path = loop_autorelaunch_state_path(root, name)
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age < cooldown_seconds


def loop_default_env(name: str) -> dict[str, str]:
    if name == "worker_loop":
        return worker_loop_env()
    if name == "modulator_loop":
        return modulator_loop_env()
    return supervisor_loop_env()


def worker_loop_env(payload: dict | None = None) -> dict[str, str]:
    payload = payload or {}
    extra_args = str(payload.get("extra_args", ""))
    if payload.get("force") and "--force" not in extra_args:
        extra_args = (extra_args + " --force").strip()
    worker_model = str(payload.get("model", "claude-fable-5-thinking-high"))
    return {
        "WORKER_AGENT_WRAPPER": str(payload.get("wrapper", "cursor-agent")),
        "WORKER_MODEL": worker_model,
        "CURSOR_MODEL": worker_model,
        "WORKER_TIMEOUT": str(payload.get("timeout", "0")),
        "WORKER_AGENT_EXTRA_ARGS": extra_args,
        "CURSOR_AGENT_EXTRA_ARGS": extra_args,
        "CURSOR_REVIEWERS_ENABLED": "1" if payload.get("reviewers_enabled", True) else "0",
        "CURSOR_REVIEW_TIMEOUT": str(payload.get("review_timeout", "2400")),
        "REVIEWER_A_AGENT_WRAPPER": str(payload.get("reviewer_a_wrapper", "cursor-agent")),
        "REVIEWER_B_AGENT_WRAPPER": str(payload.get("reviewer_b_wrapper", "cursor-agent")),
        "REVIEWER_A_MODEL": str(payload.get("reviewer_a_model", "claude-opus-4-7-thinking-high")),
        "REVIEWER_B_MODEL": str(payload.get("reviewer_b_model", "gpt-5.3-codex-high")),
        "CURSOR_REVIEWER_A_MODEL": str(payload.get("reviewer_a_model", "claude-opus-4-7-thinking-high")),
        "CURSOR_REVIEWER_B_MODEL": str(payload.get("reviewer_b_model", "gpt-5.3-codex-high")),
        "CURSOR_REVIEWER_MAX_RELAUNCHES": str(payload.get("reviewer_max_relaunches", "1")),
        "REVIEWER_CONSENSUS_ENABLED": "1" if payload.get("reviewer_consensus_enabled", True) else "0",
        "REVIEWER_CONSENSUS_PANEL": str(payload.get("reviewer_consensus_panel", "reviewer")),
        "REVIEWER_CONSENSUS_MODELS": str(payload.get("reviewer_consensus_models", "")),
        "REVIEWER_CONSENSUS_MAX_ROUNDS": str(payload.get("reviewer_consensus_max_rounds", "3")),
        "REVIEWER_CONSENSUS_QUORUM": str(payload.get("reviewer_consensus_quorum", "unanimous")),
        "WORKER_AUTO_RELAUNCH_FAILURE": "1",
        "WORKER_MAX_FAILURE_RESUMES": str(payload.get("max_failure_resumes", "2")),
        "WORKER_AUTO_RESUME_TIMEOUT": "1" if payload.get("auto_resume_timeout", False) else "0",
        "WORKER_MAX_TIMEOUT_RESUMES": str(payload.get("max_timeout_resumes", "2")),
    }


def supervisor_loop_env(payload: dict | None = None) -> dict[str, str]:
    payload = payload or {}
    supervisor_model = str(payload.get("model", "gpt-5.5-high"))
    return {
        "SUPERVISOR_AGENT_WRAPPER": str(payload.get("wrapper", "cursor-agent")),
        "SUPERVISOR_MODEL": supervisor_model,
        "CODEX_MODEL": supervisor_model,
        "SUPERVISOR_REASONING_EFFORT": str(payload.get("reasoning", "")),
        "SUPERVISOR_POLL_SECONDS": str(payload.get("poll_seconds", "10")),
        "SUPERVISOR_VERBOSE": "1" if payload.get("verbose", True) else "0",
        "SUPERVISOR_EXTRA_ARGS": str(payload.get("extra_args", "--force")),
        "SUPERVISOR_AUTO_RELAUNCH_FAILURE": "1",
        "SUPERVISOR_MAX_FAILURE_RELAUNCHES": str(payload.get("max_failure_relaunches", "1")),
        "SUPERVISOR_CONSENSUS_ENABLED": "1" if payload.get("supervisor_consensus_enabled", True) else "0",
        "SUPERVISOR_CONSENSUS_PANEL": str(payload.get("supervisor_consensus_panel", "supervisor")),
        "SUPERVISOR_CONSENSUS_MODELS": str(payload.get("supervisor_consensus_models", "")),
        "SUPERVISOR_CONSENSUS_MAX_ROUNDS": str(payload.get("supervisor_consensus_max_rounds", "3")),
        "SUPERVISOR_CONSENSUS_QUORUM": str(payload.get("supervisor_consensus_quorum", "unanimous")),
    }


def modulator_loop_env(payload: dict | None = None) -> dict[str, str]:
    payload = payload or {}
    wrapper = str(payload.get("wrapper", os.environ.get("MODULATOR_AGENT_WRAPPER", "codex")))
    default_model = "gpt-5.5" if wrapper == "codex" else "gpt-5.5-high"
    modulator_model = str(payload.get("model", os.environ.get("MODULATOR_MODEL", default_model)))
    default_extra_args = "" if wrapper == "codex" else "--force"
    return {
        "MODULATOR_AGENT_WRAPPER": wrapper,
        "MODULATOR_MODEL": modulator_model,
        "MODULATOR_POLL_SECONDS": str(payload.get("poll_seconds", "30")),
        "MODULATOR_EXTRA_ARGS": str(payload.get("extra_args", default_extra_args)),
        "MODULATOR_CLEARS_PRESET_BOUNDARIES": str(payload.get("clears_preset_boundaries", "0")),
        "MODULATOR_CONSENSUS_ENABLED": "1" if payload.get("consensus_enabled", False) else "0",
        "MODULATOR_CONSENSUS_PANEL": str(payload.get("consensus_panel", "supervisor")),
        "MODULATOR_CONSENSUS_MODELS": str(payload.get("consensus_models", "")),
    }


def running_modulator_agent(root: Path) -> tuple[str, str]:
    wrapper = os.environ.get("MODULATOR_AGENT_WRAPPER", "codex")
    model = os.environ.get(
        "MODULATOR_MODEL",
        "gpt-5.5" if wrapper == "codex" else "gpt-5.5-high",
    )
    launch_env = latest_loop_launch_env(root, "modulator_loop")
    wrapper = launch_env.get("modulator_agent_wrapper", wrapper) or wrapper
    model = launch_env.get("modulator_model", model) or model
    if model == "claude-fable-5-thinking-xhigh" and wrapper == "codex" and "MODULATOR_MODEL" not in os.environ:
        model = "gpt-5.5"
    return wrapper, model


def auto_relaunch_worker_if_needed(
    root: Path,
    job_rows: list[dict],
    processes: dict,
    controls: dict,
    supervisor: dict,
) -> dict:
    if os.environ.get("AI_WORKFLOW_AUTO_RELAUNCH_WORKER", "1") == "0":
        return {"attempted": False, "reason": "disabled by AI_WORKFLOW_AUTO_RELAUNCH_WORKER=0"}
    if controls.get("worker", {}).get("running"):
        return {"attempted": False, "reason": "worker loop already running"}
    if processes.get("worker"):
        return {"attempted": False, "reason": "worker loop process already visible"}
    if loop_autostart_disabled_path(root, "worker_loop").exists():
        return {"attempted": False, "reason": "worker loop autostart disabled by manual stop"}
    if (
        supervisor.get("human_gate_exists")
        or supervisor.get("structural_request_exists")
        or supervisor.get("human_review_action_exists")
        or supervisor.get("supervisor_action_exists")
    ):
        return {"attempted": False, "reason": "workflow gate pauses worker loop"}

    active_worker_jobs = [
        str(job.get("id") or job.get("_path") or "")
        for job in job_rows
        if job.get("state") in WORKER_PIPELINE_STATES
    ]
    active_worker_jobs = [job_id for job_id in active_worker_jobs if job_id]
    if not active_worker_jobs:
        return {"attempted": False, "reason": "no worker-pipeline job state"}

    cooldown = env_nonnegative_int("AI_WORKFLOW_AUTO_RELAUNCH_COOLDOWN_SECONDS", 30)
    if autorelaunch_recently_attempted(root, "worker_loop", cooldown):
        return {
            "attempted": False,
            "reason": f"worker loop autorelaunch cooldown active ({cooldown}s)",
            "active_worker_jobs": active_worker_jobs,
        }

    mark_autorelaunch_attempt(root, "worker_loop")
    result = start_loop(
        root,
        "worker_loop",
        saved_loop_env(root, "worker_loop", worker_loop_env()),
    )
    payload = {
        "attempted": True,
        "reason": "worker loop was offline while worker-pipeline jobs were active",
        "active_worker_jobs": active_worker_jobs,
        "start_result": result,
    }
    mark_autorelaunch_attempt(root, "worker_loop", payload)
    return payload


def auto_relaunch_supervisor_if_needed(
    root: Path,
    job_rows: list[dict],
    processes: dict,
    controls: dict,
    supervisor: dict,
) -> dict:
    if os.environ.get("AI_WORKFLOW_AUTO_RELAUNCH_SUPERVISOR", "1") == "0":
        return {"attempted": False, "reason": "disabled by AI_WORKFLOW_AUTO_RELAUNCH_SUPERVISOR=0"}
    if controls.get("supervisor", {}).get("running"):
        return {"attempted": False, "reason": "supervisor loop already running"}
    if processes.get("supervisor"):
        return {"attempted": False, "reason": "supervisor loop process already visible"}
    if loop_autostart_disabled_path(root, "supervisor_loop").exists():
        return {"attempted": False, "reason": "supervisor loop autostart disabled by manual stop"}
    if supervisor.get("human_gate_exists"):
        return {"attempted": False, "reason": "human review gate pauses supervisor loop"}

    active_reasons = []
    if supervisor.get("structural_request_exists"):
        active_reasons.append("structural change request")
    if supervisor.get("human_review_action_exists"):
        active_reasons.append("human review action request")
    if supervisor.get("supervisor_action_exists"):
        active_reasons.append("supervisor action request")

    actionable_jobs = [
        str(job.get("id") or job.get("_path") or "")
        for job in job_rows
        if job.get("state") in SUPERVISOR_ACTIONABLE_JOB_STATES
    ]
    actionable_jobs = [job_id for job_id in actionable_jobs if job_id]
    if actionable_jobs:
        active_reasons.append("supervisor-actionable job state")

    if not active_reasons:
        return {"attempted": False, "reason": "no supervisor-actionable state"}

    cooldown = env_nonnegative_int("AI_WORKFLOW_AUTO_RELAUNCH_COOLDOWN_SECONDS", 30)
    if autorelaunch_recently_attempted(root, "supervisor_loop", cooldown):
        return {
            "attempted": False,
            "reason": f"supervisor loop autorelaunch cooldown active ({cooldown}s)",
            "active_reasons": active_reasons,
            "actionable_jobs": actionable_jobs,
        }

    mark_autorelaunch_attempt(root, "supervisor_loop")
    result = start_loop(
        root,
        "supervisor_loop",
        saved_loop_env(root, "supervisor_loop", supervisor_loop_env()),
    )
    payload = {
        "attempted": True,
        "reason": "supervisor loop was offline while supervisor-actionable state existed",
        "active_reasons": active_reasons,
        "actionable_jobs": actionable_jobs,
        "start_result": result,
    }
    mark_autorelaunch_attempt(root, "supervisor_loop", payload)
    return payload


def auto_start_loops_after_human_review(root: Path) -> dict:
    supervisor = start_loop(root, "supervisor_loop", supervisor_loop_env())
    worker = start_loop(root, "worker_loop", worker_loop_env())
    modulator = start_loop(root, "modulator_loop", modulator_loop_env())
    return {
        "ok": bool(supervisor.get("ok")) and bool(worker.get("ok")),
        "supervisor": supervisor,
        "worker": worker,
        "modulator": modulator,
    }


def stop_loop(root: Path, name: str) -> dict:
    process_keys = {
        "worker_loop": "worker",
        "supervisor_loop": "supervisor",
        "modulator_loop": "modulator",
    }
    process_key = process_keys.get(name, "supervisor")
    targets: set[int] = set()
    pid, _pid_source = loop_pid(root, name)
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
        remove_stale_loop_lock(root, name)
        loop_autostart_disabled_path(root, name).write_text(
            datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") + "\n",
            encoding="utf-8",
        )
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
    remove_stale_loop_lock(root, name)
    loop_autostart_disabled_path(root, name).write_text(
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") + "\n",
        encoding="utf-8",
    )

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


def push_after_human_review(root: Path) -> tuple[bool, str]:
    if os.environ.get("AI_WORKFLOW_PUSH_AFTER_HUMAN_REVIEW", "1") == "0":
        return True, "Push skipped: AI_WORKFLOW_PUSH_AFTER_HUMAN_REVIEW=0"
    remote = os.environ.get("AI_WORKFLOW_PUSH_REMOTE", "origin")
    branch = os.environ.get("AI_WORKFLOW_PUSH_BRANCH", "")
    if not branch:
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if branch_result.returncode != 0:
            output = "\n".join(part for part in [branch_result.stdout.strip(), branch_result.stderr.strip()] if part)
            return False, output or "Push skipped: failed to determine current branch."
        branch = branch_result.stdout.strip()
    if not branch:
        return False, "Push skipped: current Git checkout is detached or branch is unknown."
    remote_result = subprocess.run(
        ["git", "remote", "get-url", remote],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if remote_result.returncode != 0:
        return False, f"Push skipped: remote '{remote}' is not configured."
    result = subprocess.run(
        ["git", "push", "-u", remote, branch],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode == 0, output or f"Pushed {branch} to {remote}."


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
    approval_comment = str(draft_review.get("approval_comment", "")).strip()
    if approval_comment:
        lines.extend(["", "Optional approval comment:", approval_comment])
    return "\n".join(lines).strip() or "No draft review choices are visible yet."


def supervisor_chat(root: Path, message: str, history: object, draft_review: object) -> dict:
    gate_path = root / ".ai" / "supervisor" / "HUMAN_REVIEW_REQUIRED.md"
    if not gate_path.exists():
        return {"ok": False, "message": "No human review gate exists."}
    message = message.strip()
    if not message:
        return {"ok": False, "message": "Enter a question for the supervisor."}
    if not shutil.which("cursor-agent"):
        return {"ok": False, "message": "cursor-agent executable was not found in PATH."}

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
    prompt = f"""You are the supervisor agent for this scientific coding project.

The human is in the dashboard human review panel and wants read-only guidance before submitting the review.

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

    model = (
        os.environ.get("AI_WORKFLOW_CHAT_MODEL")
        or os.environ.get("SUPERVISOR_MODEL")
        or os.environ.get("CODEX_MODEL")
        or "gpt-5.5-high"
    )
    effort = os.environ.get("AI_WORKFLOW_CHAT_REASONING_EFFORT") or "model-default"
    timeout_seconds = max(30, env_int("AI_WORKFLOW_CHAT_TIMEOUT", 300))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = runs_dir(root) / f"human_review_chat_{stamp}.log"
    args = [
        "cursor-agent",
        "-p",
        "--trust",
        "--mode",
        "ask",
        "--workspace",
        str(root),
        "--model",
        model,
        prompt,
    ]
    try:
        result = subprocess.run(
            args,
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


def modulator_terminal_history_path(root: Path) -> Path:
    return root / ".ai" / "modulator" / "terminal_history.jsonl"


def append_terminal_entry(root: Path, role: str, content: str, meta: dict | None = None) -> None:
    path = modulator_terminal_history_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "role": role,
        "content": content,
    }
    if meta:
        entry["meta"] = meta
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def load_terminal_history(root: Path, limit: int = 40) -> list[dict]:
    path = modulator_terminal_history_path(root)
    entries: list[dict] = []
    if not path.exists():
        return entries
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return entries
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def modulator_terminal_chat(root: Path, message: str, model_override: str = "") -> dict:
    message = message.strip()
    if not message:
        return {"ok": False, "message": "Enter a message for the modulator terminal."}
    wrapper, running_model = running_modulator_agent(root)
    executable = "codex" if wrapper == "codex" else "cursor-agent"
    if not shutil.which(executable):
        return {"ok": False, "message": f"{executable} executable was not found in PATH."}

    code, jobs_summary, jobs_err = run(["python3", "scripts/summarize_jobs.py"], root)
    if code != 0:
        jobs_summary = jobs_err or jobs_summary or "Unable to summarize jobs."
    _, project_status, _ = run(["git", "status", "--short"], root)
    _, project_head, _ = run(["git", "log", "--oneline", "-1"], root)

    job_rows = jobs(root)
    processes = process_blocks(root)
    controls = {
        "worker": control_info(root, "worker_loop"),
        "supervisor": control_info(root, "supervisor_loop"),
        "modulator": control_info(root, "modulator_loop"),
    }
    supervisor = supervisor_state(root, job_rows)
    activity = activity_state(job_rows, processes, controls, supervisor)
    active = activity.get("active_job") or {}

    modulator_dir = root / ".ai" / "modulator"
    triage_files = sorted((modulator_dir / "triage").glob("triage.*.md")) if (modulator_dir / "triage").exists() else []
    recent_triage = "\n\n".join(read_text(p, 8_000) for p in triage_files[-2:])

    context_files = [
        (".ai/supervisor/modulator_protocol.md", read_text(root / ".ai" / "supervisor" / "modulator_protocol.md", 25_000)),
        (".ai/supervisor/autonomous_boundary_policy.md", read_text(root / ".ai" / "supervisor" / "autonomous_boundary_policy.md", 25_000)),
        (".ai/supervisor/HUMAN_REVIEW_REQUIRED.md", read_text(root / ".ai" / "supervisor" / "HUMAN_REVIEW_REQUIRED.md", 30_000)),
        (".ai/supervisor/MODULATOR_FINDINGS.md", read_text(root / ".ai" / "supervisor" / "MODULATOR_FINDINGS.md", 20_000)),
        ("Recent modulator triage records", recent_triage),
        (".ai/supervisor/roadmap.md (tail)", tail(root / ".ai" / "supervisor" / "roadmap.md", 260)),
        (".ai/supervisor/ledger.md (tail)", tail(root / ".ai" / "supervisor" / "ledger.md", 200)),
    ]
    if active.get("id"):
        job_dir = root / ".ai" / "jobs" / str(active.get("id"))
        context_files.extend(
            [
                (f"{active.get('id')} status.json", json.dumps(read_json(job_dir / "status.json"), indent=2)),
                (f"{active.get('id')} task.md", read_text(job_dir / "task.md", 25_000)),
            ]
        )
    context = "\n\n".join(f"## {name}\n\n{text or '(missing or empty)'}" for name, text in context_files)

    history = load_terminal_history(root, limit=14)
    history_text = compact_history(
        [{"role": e.get("role", ""), "content": e.get("content", "")} for e in history]
    )

    prompt = f"""You are the modulator agent answering on the modulator terminal of the AI Workflow Console.

The human operator steers the autonomous workflow through this terminal. You have the modulator's full authority and limits (see the protocol in the context below). Treat the operator's message as coming from the project owner.

Rules for this terminal session:
- Answer the operator's message directly and concisely. Investigate first when the question concerns workflow state, job evidence, or scientific artifacts: read files, run read-only probes, check processes.
- If the message contains an operator DIRECTIVE that should change workflow behavior (pause or redirect dispatch, reprioritize, impose a constraint, overrule or confirm a modulator/supervisor decision, adjust validation requirements), record it durably by writing `.ai/modulator/steering/steering.<UTC timestamp>.md` containing: the verbatim operator message, your interpretation, and the concrete behavioral change. The always-on modulator loop wakes on that file and honors it. Confirm in your answer that the directive was recorded.
- If the directive requires immediate supervisor action, also write `.ai/supervisor/MODULATOR_FINDINGS.md` (or a dated addendum) carrying the directive per the Findings Contract.
- You may repair mechanical workflow state and manage gates exactly as the modulator protocol allows. You must not edit `src/`, `tests/`, `CMakeLists.txt`, or supervisor-owned planning files, and you must not clear preset boundary gates unless the operator explicitly instructs it in this message (operator instruction here counts as explicit human configuration).
- Do not start or stop loops unless the operator asks.
- Keep the final answer terse and operational: findings, actions taken, files written, recommended next step.

# Operator message

{message}

# Recent terminal history

{history_text}

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

# Compact job table

```text
{jobs_summary}
```

# Context

{context}
"""

    requested_model = model_override.strip()
    if requested_model:
        catalog = agent_wrapper_catalog(root)
        wrapper_info = next(
            (
                item for item in catalog.get("wrappers", [])
                if isinstance(item, dict) and item.get("id") == wrapper
            ),
            {},
        )
        allowed_models = wrapper_info.get("models") if isinstance(wrapper_info, dict) else []
        if isinstance(allowed_models, list) and allowed_models and requested_model not in allowed_models:
            requested_model = ""
    model = requested_model or os.environ.get("AI_WORKFLOW_TERMINAL_MODEL") or running_model
    timeout_seconds = max(30, env_int("AI_WORKFLOW_TERMINAL_TIMEOUT", 900))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = runs_dir(root) / f"modulator_terminal_{stamp}.log"
    prompt_path = runs_dir(root) / f"modulator_terminal_{stamp}.prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    args = [
        "python3",
        "scripts/agent_wrapper.py",
        "run",
        "--role",
        "modulator",
        "--wrapper",
        wrapper,
        "--model",
        model,
        "--workspace",
        str(root),
        "--prompt-file",
        str(prompt_path.relative_to(root)),
    ]
    append_terminal_entry(root, "user", message)
    try:
        result = subprocess.run(
            args,
            cwd=str(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(
            f"# Modulator Terminal\n\nTimed out after {timeout_seconds}s.\n\n## Prompt\n\n{prompt}\n\n## Partial stdout\n\n{exc.stdout or ''}\n\n## Partial stderr\n\n{exc.stderr or ''}\n",
            encoding="utf-8",
        )
        failure = f"Modulator terminal timed out after {timeout_seconds}s."
        append_terminal_entry(root, "modulator", failure, {"ok": False, "model": model})
        return {
            "ok": False,
            "message": failure,
            "log_file": str(log_path.relative_to(root)),
            "model": model,
        }

    answer = result.stdout.strip()
    log_path.write_text(
        "\n".join(
            [
                "# Modulator Terminal",
                "",
                f"- Wrapper: `{wrapper}`",
                f"- Model: `{model}`",
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
        failure = (result.stderr.strip() or answer or f"Modulator terminal failed with exit code {result.returncode}")[-2000:]
        append_terminal_entry(root, "modulator", failure, {"ok": False, "model": model, "exit_code": result.returncode})
        return {
            "ok": False,
            "message": failure,
            "answer": answer,
            "exit_code": result.returncode,
            "log_file": str(log_path.relative_to(root)),
            "model": model,
        }
    final_answer = answer or "(The modulator returned no text.)"
    append_terminal_entry(root, "modulator", final_answer, {"ok": True, "model": model})
    return {
        "ok": True,
        "answer": final_answer,
        "model": model,
        "log_file": str(log_path.relative_to(root)),
    }


def prune_workflow_chat_jobs() -> None:
    cutoff = time.time() - env_int("AI_WORKFLOW_CHAT_JOB_TTL_SECONDS", 3600)
    with WORKFLOW_CHAT_JOBS_LOCK:
        for chat_id, job in list(WORKFLOW_CHAT_JOBS.items()):
            if float(job.get("created_monotonic", 0)) < cutoff:
                WORKFLOW_CHAT_JOBS.pop(chat_id, None)


def start_workflow_chat_job(
    root: Path,
    message: str,
    model_override: str = "",
) -> dict:
    message = message.strip()
    if not message:
        return {"ok": False, "message": "Enter a message for the modulator terminal."}
    prune_workflow_chat_jobs()
    chat_id = uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with WORKFLOW_CHAT_JOBS_LOCK:
        WORKFLOW_CHAT_JOBS[chat_id] = {
            "ok": True,
            "chat_id": chat_id,
            "state": "running",
            "created_at": created_at,
            "created_monotonic": time.time(),
        }

    def run_chat() -> None:
        try:
            result = modulator_terminal_chat(root, message, model_override)
        except Exception as exc:  # Keep API responses JSON even on unexpected agent failure.
            result = {"ok": False, "message": f"Modulator terminal failed before completion: {exc}"}
        with WORKFLOW_CHAT_JOBS_LOCK:
            current = WORKFLOW_CHAT_JOBS.get(chat_id, {})
            current.update(
                {
                    "state": "done",
                    "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "result": result,
                }
            )
            WORKFLOW_CHAT_JOBS[chat_id] = current

    threading.Thread(target=run_chat, name=f"modulator-terminal-{chat_id[:8]}", daemon=True).start()
    return {"ok": True, "state": "running", "chat_id": chat_id, "message": "Modulator terminal request started."}


def workflow_chat_result(chat_id: str) -> dict:
    prune_workflow_chat_jobs()
    with WORKFLOW_CHAT_JOBS_LOCK:
        job = dict(WORKFLOW_CHAT_JOBS.get(chat_id, {}))
    if not job:
        return {"ok": False, "message": f"Unknown workflow chat id: {chat_id}"}
    if job.get("state") != "done":
        return {"ok": True, "state": "running", "chat_id": chat_id, "created_at": job.get("created_at", "")}
    result = dict(job.get("result") or {})
    result.setdefault("ok", False)
    result["state"] = "done"
    result["chat_id"] = chat_id
    result["finished_at"] = job.get("finished_at", "")
    return result


def _scripts_dir() -> Path:
    return Path(__file__).resolve().parent


def architect_state(root: Path) -> dict:
    """Return the current Architect intake state (fast, no agent call)."""
    try:
        import architect
        import architect_core as ac
    except Exception as exc:  # pragma: no cover - import guard
        return {"ok": False, "message": f"architect modules unavailable: {exc}"}
    session = architect.load_session(root)
    completeness = ac.spec_completeness(session["spec"])
    return {
        "ok": True,
        "status": session.get("status", "interviewing"),
        "complete": completeness["complete"],
        "missing": completeness["missing"],
        "warnings": completeness["warnings"],
        "summary": ac.render_spec_summary(session["spec"]),
        "last_ask": session.get("last_ask", ""),
    }


def _register_async_job(label: str) -> tuple[str, str]:
    prune_workflow_chat_jobs()
    chat_id = uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with WORKFLOW_CHAT_JOBS_LOCK:
        WORKFLOW_CHAT_JOBS[chat_id] = {
            "ok": True,
            "chat_id": chat_id,
            "label": label,
            "state": "running",
            "created_at": created_at,
            "created_monotonic": time.time(),
        }
    return chat_id, created_at


def _finish_async_job(chat_id: str, result: dict) -> None:
    with WORKFLOW_CHAT_JOBS_LOCK:
        current = WORKFLOW_CHAT_JOBS.get(chat_id, {})
        current.update(
            {
                "state": "done",
                "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "result": result,
            }
        )
        WORKFLOW_CHAT_JOBS[chat_id] = current


def start_architect_job(root: Path, message: str, model: str = "", wrapper: str = "") -> dict:
    """Run one Architect interview turn asynchronously (mirrors the chat-job pattern)."""
    chat_id, _ = _register_async_job("architect")

    def run() -> None:
        try:
            import architect
            runner = architect.make_default_runner(
                workspace=str(root),
                wrapper=wrapper or "cursor-agent",
                model=model or "gpt-5.5-high",
            )
            turn = architect.interview_turn(root, message, runner=runner)
            result = {
                "ok": True,
                "ask_user": turn["ask_user"],
                "answer": turn["ask_user"] or "(spec updated)",
                "status": turn["status"],
                "complete": turn["completeness"]["complete"],
                "missing": turn["completeness"]["missing"],
            }
        except Exception as exc:
            result = {"ok": False, "message": f"Architect failed: {exc}"}
        _finish_async_job(chat_id, result)

    threading.Thread(target=run, name=f"architect-{chat_id[:8]}", daemon=True).start()
    return {"ok": True, "state": "running", "chat_id": chat_id, "message": "Architect request started."}


def start_architect_gate_job(root: Path, no_consensus: bool = False) -> dict:
    """Run the spec completeness gate asynchronously."""
    chat_id, _ = _register_async_job("architect-gate")

    def run() -> None:
        cmd = [sys.executable, str(_scripts_dir() / "check_spec_completeness.py"), "--json"]
        if no_consensus:
            cmd.append("--no-consensus")
        try:
            completed = subprocess.run(cmd, cwd=str(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
            try:
                data = json.loads(completed.stdout)
            except json.JSONDecodeError:
                data = {"passed": False, "reason": (completed.stdout or "no output")[-2000:]}
            result = {
                "ok": True,
                "passed": bool(data.get("passed")),
                "reason": data.get("reason", ""),
                "missing": data.get("missing", []),
                "warnings": data.get("warnings", []),
                "consensus": data.get("consensus"),
                "answer": f"Gate {'PASS' if data.get('passed') else 'FAIL'}: {data.get('reason', '')}",
            }
        except Exception as exc:
            result = {"ok": False, "message": f"Gate failed to run: {exc}"}
        _finish_async_job(chat_id, result)

    threading.Thread(target=run, name=f"architect-gate-{chat_id[:8]}", daemon=True).start()
    return {"ok": True, "state": "running", "chat_id": chat_id, "message": "Spec gate started."}


def architect_handoff(root: Path, overwrite: bool = False, create_first_job: bool = False, start: bool = False) -> dict:
    """Compile the spec into bootstrap artifacts (synchronous; no agent call)."""
    cmd = [sys.executable, str(_scripts_dir() / "architect_compile.py"), "--json"]
    if overwrite:
        cmd.append("--overwrite")
    if create_first_job:
        cmd.append("--create-first-job")
    if start:
        cmd.append("--start")
    try:
        completed = subprocess.run(cmd, cwd=str(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return {"ok": False, "message": (completed.stdout or "no output")[-2000:]}
        data.setdefault("ok", completed.returncode == 0)
        return data
    except Exception as exc:
        return {"ok": False, "message": f"Compile failed: {exc}"}


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
        f"- Archived human gate: `{archived_gate}`",
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
        "4. Proposed next small worker jobs after boundary approval",
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
        "Read the failed human review items, classify the concerns, and decide the next safe workflow action.",
        "",
        "## Required Supervisor Behavior",
        "",
        "- Do not pass the raw failed checklist directly to Cursor.",
        "- Decide whether each concern is implementation work, test/validation work, documentation work, supervisor-owned planning/scope work, or a human clarification need.",
        "- If implementation is needed, create exactly one small, self-contained worker job for the next actionable piece.",
        "- Any created worker job must include a valid `Progress Classification` block that passes `python3 scripts/check_job_progress_gate.py`.",
        "- If concerns should be split, create only the first small worker job and record the planned sequence in the ledger.",
        "- If supervisor-owned planning records must change, update them yourself and open a new human review gate before dispatching implementation.",
        "- If the concern is ambiguous, open a human review/clarification gate instead of guessing.",
        "- Archive or remove `.ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md` only after a new worker job or human gate exists.",
        "",
        "## Review Context",
        "",
        f"- Archived human gate: `{archived_gate}`",
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


def write_human_review(
    root: Path,
    decisions: list[dict],
    structural_change: dict | None = None,
    approval_comment: str = "",
) -> dict:
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
    approval_comment = approval_comment.strip()
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
        if result_label == "approved" and approval_comment:
            lines.extend(["", "## Approval Comment", "", approval_comment])
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
        push_ok, push_output = push_after_human_review(root)
        return {
            "ok": True,
            "message": "Major structural change requested. The supervisor must update the milestones itself and open a follow-up human review gate before implementation resumes.",
            "request_path": str(request_path.relative_to(root)),
            "review_record": str(review_record.relative_to(root)),
            "archived_gate": str(archived_gate.relative_to(root)),
            "commit_ok": commit_ok,
            "commit_output": commit_output,
            "push_ok": push_ok,
            "push_output": push_output,
        }

    if not failed:
        prune_ok, prune_output = prune_accepted_job_refs(root, review_record)
        with ledger.open("a", encoding="utf-8") as handle:
            if approval_comment:
                handle.write("- Approval comment:\n")
                for line in approval_comment.splitlines():
                    handle.write(f"  {line}\n")
            handle.write("- Accepted job branch/worktree pruning:\n")
            for line in prune_output.splitlines():
                handle.write(f"  - {line}\n")
        commit_ok, commit_output = commit_workflow_records(root, "workflow: record human review approval")
        push_ok, push_output = push_after_human_review(root)
        return {
            "ok": True,
            "message": "Human review approved. Gate archived.",
            "review_record": str(review_record.relative_to(root)),
            "archived_gate": str(archived_gate.relative_to(root)),
            "prune_ok": prune_ok,
            "prune_output": prune_output,
            "commit_ok": commit_ok,
            "commit_output": commit_output,
            "push_ok": push_ok,
            "push_output": push_output,
        }

    request_path = create_human_review_action_request(
        root, reviews_dir, stamp, archived_gate, review_record, failed
    )
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(f"- Human milestone review requested changes. Supervisor action request: `{request_path.relative_to(root)}`.\n")
    commit_ok, commit_output = commit_workflow_records(root, "workflow: record human review action request")
    push_ok, push_output = push_after_human_review(root)
    return {
        "ok": True,
        "message": "Changes requested. Supervisor action request created; the supervisor will decide the next worker job or gate.",
        "request_path": str(request_path.relative_to(root)),
        "review_record": str(review_record.relative_to(root)),
        "archived_gate": str(archived_gate.relative_to(root)),
        "commit_ok": commit_ok,
        "commit_output": commit_output,
        "push_ok": push_ok,
        "push_output": push_output,
    }


class Handler(SimpleHTTPRequestHandler):
    project_root: Path

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), format % args))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            payload = state_payload(self.project_root)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if parsed.path == "/api/modulator-terminal-result":
            query = parse_qs(parsed.query)
            chat_id = (query.get("id") or [""])[0]
            result = workflow_chat_result(chat_id)
            json_response(self, HTTPStatus.OK if result.get("ok") else HTTPStatus.NOT_FOUND, result)
            return
        if parsed.path == "/api/modulator-terminal-history":
            history = load_terminal_history(self.project_root, limit=60)
            json_response(self, HTTPStatus.OK, {"ok": True, "history": history})
            return
        if parsed.path == "/api/architect/state":
            json_response(self, HTTPStatus.OK, architect_state(self.project_root))
            return
        if parsed.path == "/api/architect/result":
            query = parse_qs(parsed.query)
            chat_id = (query.get("id") or [""])[0]
            result = workflow_chat_result(chat_id)
            json_response(self, HTTPStatus.OK if result.get("ok") else HTTPStatus.NOT_FOUND, result)
            return
        if parsed.path.startswith("/api/"):
            json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "message": f"unknown endpoint: {parsed.path}"})
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

        if parsed.path == "/api/modulator/start":
            result = start_loop(self.project_root, "modulator_loop", modulator_loop_env(payload))
            json_response(self, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        if parsed.path == "/api/worker/stop":
            json_response(self, HTTPStatus.OK, stop_loop(self.project_root, "worker_loop"))
            return

        if parsed.path == "/api/supervisor/stop":
            json_response(self, HTTPStatus.OK, stop_loop(self.project_root, "supervisor_loop"))
            return

        if parsed.path == "/api/modulator/stop":
            json_response(self, HTTPStatus.OK, stop_loop(self.project_root, "modulator_loop"))
            return

        if parsed.path == "/api/human-review":
            result = write_human_review(
                self.project_root,
                list(payload.get("decisions", [])),
                payload.get("structural_change") if isinstance(payload.get("structural_change"), dict) else None,
                str(payload.get("approval_comment", "")),
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

        if parsed.path == "/api/modulator-terminal":
            result = start_workflow_chat_job(
                self.project_root,
                str(payload.get("message", "")),
                str(payload.get("model", "")),
            )
            json_response(self, HTTPStatus.ACCEPTED if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        if parsed.path == "/api/open-file":
            result = open_project_file(self.project_root, str(payload.get("path", "")))
            json_response(self, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        if parsed.path == "/api/architect/message":
            result = start_architect_job(
                self.project_root,
                str(payload.get("message", "")),
                str(payload.get("model", "")),
                str(payload.get("wrapper", "")),
            )
            json_response(self, HTTPStatus.ACCEPTED if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        if parsed.path == "/api/architect/gate":
            result = start_architect_gate_job(self.project_root, bool(payload.get("no_consensus", False)))
            json_response(self, HTTPStatus.ACCEPTED if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        if parsed.path == "/api/architect/handoff":
            result = architect_handoff(
                self.project_root,
                bool(payload.get("overwrite", False)),
                bool(payload.get("create_first_job", False)),
                bool(payload.get("start", False)),
            )
            json_response(self, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "message": f"unknown endpoint: {parsed.path}"})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=None, type=int, help="dashboard port; when omitted, use or create the per-project stored port")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if not (project_root / ".git").exists():
        raise SystemExit(f"project root is not a Git repository root: {project_root}")

    port, port_source = resolve_gui_port(project_root, args.host, args.port)
    os.chdir(GUI_ROOT)
    Handler.project_root = project_root
    server = ThreadingHTTPServer((args.host, port), Handler)
    url = f"http://{args.host}:{port}/"
    print(f"AI workflow dashboard: {url}")
    print(f"Port source: {port_source}")
    print(f"Port config: {gui_port_config_path(project_root)}")
    print(f"Project: {project_root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
