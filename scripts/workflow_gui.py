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
from collections import deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = PACKAGE_ROOT / "gui"
DEFAULT_LOG_DISPLAY_LINES = 10_000


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


def pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_pid(path: Path) -> int | None:
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid_running(pid) else None


def control_info(root: Path, name: str) -> dict:
    pid = read_pid(pid_file(root, name))
    log = log_file(root, name)
    return {
        "pid": pid,
        "running": pid is not None,
        "pid_file": str(pid_file(root, name).relative_to(root)),
        "log_file": str(log.relative_to(root)),
        "log_tail": tail(log, LOG_DISPLAY_LINES),
        "log_display_lines": LOG_DISPLAY_LINES,
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
        out.append(data)
    return out


def parse_roadmap(text: str) -> list[dict]:
    milestones = []
    current: dict | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                milestones.append(current)
            current = {"title": line[3:].strip(), "items": [], "done": 0, "total": 0}
            continue
        if current and re.match(r"^-\s+\[[ xX]\]", line.strip()):
            done = "[x]" in line.lower()
            current["items"].append({"text": line.strip()[6:].strip(), "done": done})
            current["total"] += 1
            if done:
                current["done"] += 1
    if current:
        milestones.append(current)
    return milestones


def supervisor_state(root: Path) -> dict:
    supervisor = root / ".ai" / "supervisor"
    roadmap = read_text(supervisor / "roadmap.md")
    ledger = read_text(supervisor / "ledger.md")
    project_brief = read_text(supervisor / "project_brief.md")
    gate_path = supervisor / "HUMAN_REVIEW_REQUIRED.md"
    runs_dir = root / ".ai" / "supervisor_runs"
    run_logs = sorted(runs_dir.glob("supervisor.*.log"))
    latest_log = run_logs[-1] if run_logs else None
    return {
        "roadmap": roadmap,
        "milestones": parse_roadmap(roadmap),
        "ledger": ledger,
        "project_brief": project_brief,
        "human_gate_exists": gate_path.exists(),
        "human_gate": read_text(gate_path),
        "human_gate_checklist": parse_gate_checklist(read_text(gate_path)) if gate_path.exists() else [],
        "latest_supervisor_log": str(latest_log.relative_to(root)) if latest_log else "",
        "latest_supervisor_tail": tail(latest_log, LOG_DISPLAY_LINES) if latest_log else "",
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


def process_blocks(root: Path) -> dict:
    blocks = {"worker": [], "supervisor": [], "cursor": [], "codex": []}
    proc_root = Path("/proc")
    for proc in proc_root.iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
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
        if "worker_loop.sh" in cmdline:
            blocks["worker"].append(item)
        elif "supervisor_loop.sh" in cmdline:
            blocks["supervisor"].append(item)
        elif "cursor-agent" in cmdline:
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
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "project": {"root": str(root), "name": root.name},
        "git": git_info(root),
        "jobs": job_rows,
        "job_counts": counts,
        "job_progress": progress,
        "supervisor": supervisor_state(root),
        "worktrees": worktrees(root),
        "processes": process_blocks(root),
        "controls": {
            "worker": control_info(root, "worker_loop"),
            "supervisor": control_info(root, "supervisor_loop"),
        },
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
    with log.open("ab") as handle:
        handle.write(f"\n--- launched {datetime.now(timezone.utc).isoformat()} ---\n".encode("utf-8"))
        proc = subprocess.Popen(
            [str(script_path)],
            cwd=str(root),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_file(root, name).write_text(str(proc.pid) + "\n", encoding="utf-8")
    return {"ok": True, "message": f"started {name}", "pid": proc.pid}


def stop_loop(root: Path, name: str) -> dict:
    pid = read_pid(pid_file(root, name))
    if not pid:
        return {"ok": True, "message": f"{name} is not running"}
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        return {"ok": False, "message": f"failed to stop {name}: {exc}"}
    return {"ok": True, "message": f"sent SIGTERM to {name}", "pid": pid}


def active_jobs(root: Path) -> list[str]:
    active = []
    for status_path in sorted((root / ".ai" / "jobs").glob("J*/status.json")):
        data = read_json(status_path)
        state_value = data.get("state", "")
        if state_value in {"queued", "running", "rejected", "ready_for_review", "blocked"}:
            active.append(f"{data.get('id', status_path.parent.name)}: {state_value}")
    return active


def write_human_review(root: Path, decisions: list[dict]) -> dict:
    gate_path = root / ".ai" / "supervisor" / "HUMAN_REVIEW_REQUIRED.md"
    if not gate_path.exists():
        return {"ok": False, "message": "No human review gate exists."}

    gate_text = read_text(gate_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    reviews_dir = root / ".ai" / "supervisor" / "human_reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    review_record = reviews_dir / f"human_review_{stamp}.md"
    archived_gate = reviews_dir / f"HUMAN_REVIEW_REQUIRED_{stamp}.md"
    failed = [item for item in decisions if not item.get("passed")]

    lines = [
        "# Human Milestone Review Record",
        "",
        f"- Reviewed at: `{stamp}`",
        f"- Result: `{'changes_requested' if failed else 'approved'}`",
        "",
        "## Checklist Results",
        "",
    ]
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

    if not failed:
        return {
            "ok": True,
            "message": "Human review approved. Gate archived.",
            "review_record": str(review_record.relative_to(root)),
            "archived_gate": str(archived_gate.relative_to(root)),
        }

    active = active_jobs(root)
    if active:
        return {
            "ok": False,
            "message": "Changes requested, but active jobs remain; no revision job created.",
            "active_jobs": active,
            "review_record": str(review_record.relative_to(root)),
            "archived_gate": str(archived_gate.relative_to(root)),
        }

    task_path = reviews_dir / f"revision_task_{stamp}.md"
    task_lines = [
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
        "",
        "## Failed Human Review Items",
        "",
    ]
    for index, item in enumerate(failed, 1):
        task_lines.append(f"### {index}. {item.get('item', 'Unnamed item')}")
        task_lines.append("")
        task_lines.append(str(item.get("comment", "")).strip() or "No comment provided.")
        task_lines.append("")
    task_lines.extend(
        [
            "## Required Validation",
            "",
            "Run the validation command from the affected milestone or explain why it cannot run.",
        ]
    )
    task_path.write_text("\n".join(task_lines).rstrip() + "\n", encoding="utf-8")
    _, base_ref, _ = run(["git", "rev-parse", "HEAD"], root)
    result = subprocess.run(
        [
            "python3",
            "scripts/create_job.py",
            "--title",
            "Address human milestone review concerns",
            "--base-ref",
            base_ref or "HEAD",
            "--test-command",
            "python3 scripts/summarize_jobs.py",
            "--task-file",
            str(task_path),
        ],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return {"ok": False, "message": result.stderr or result.stdout or "failed to create revision job"}
    return {
        "ok": True,
        "message": "Changes requested. Revision job created.",
        "job_path": result.stdout.strip(),
        "review_record": str(review_record.relative_to(root)),
        "archived_gate": str(archived_gate.relative_to(root)),
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
            extra_args = payload.get("extra_args", "")
            if payload.get("force") and "--force" not in extra_args:
                extra_args = (extra_args + " --force").strip()
            result = start_loop(
                self.project_root,
                "worker_loop",
                {
                    "CURSOR_MODEL": str(payload.get("model", "gpt-5.5-high")),
                    "CURSOR_TIMEOUT": str(payload.get("timeout", "3600")),
                    "CURSOR_AGENT_EXTRA_ARGS": extra_args,
                },
            )
            json_response(self, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        if parsed.path == "/api/supervisor/start":
            result = start_loop(
                self.project_root,
                "supervisor_loop",
                {
                    "CODEX_MODEL": str(payload.get("model", "gpt-5.5")),
                    "CODEX_REASONING_EFFORT": str(payload.get("reasoning", "high")),
                    "SUPERVISOR_POLL_SECONDS": str(payload.get("poll_seconds", "10")),
                    "SUPERVISOR_VERBOSE": "1" if payload.get("verbose", True) else "0",
                    "CODEX_EXTRA_ARGS": str(payload.get("extra_args", "")),
                },
            )
            json_response(self, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        if parsed.path == "/api/worker/stop":
            json_response(self, HTTPStatus.OK, stop_loop(self.project_root, "worker_loop"))
            return

        if parsed.path == "/api/supervisor/stop":
            json_response(self, HTTPStatus.OK, stop_loop(self.project_root, "supervisor_loop"))
            return

        if parsed.path == "/api/human-review":
            result = write_human_review(self.project_root, list(payload.get("decisions", [])))
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
