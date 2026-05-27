#!/usr/bin/env python3
"""Serve a local dashboard for the AI supervisor/worker workflow."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = PACKAGE_ROOT / "gui"


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
    text = read_text(path)
    if not text:
        return ""
    return "\n".join(text.splitlines()[-lines:])


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
        "latest_supervisor_log": str(latest_log.relative_to(root)) if latest_log else "",
        "latest_supervisor_tail": tail(latest_log, 80) if latest_log else "",
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


def file_tree(root: Path, max_depth: int = 3, max_entries: int = 260) -> list[dict]:
    ignored = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        rel = current.relative_to(root)
        depth = 0 if rel == Path(".") else len(rel.parts)
        dirnames[:] = [name for name in sorted(dirnames) if name not in ignored]
        filenames = sorted(filenames)
        if depth >= max_depth:
            dirnames[:] = []
        if rel != Path("."):
            rows.append({"type": "dir", "path": str(rel), "depth": depth})
        for name in filenames:
            path = current / name
            rel_file = path.relative_to(root)
            if any(part in ignored for part in rel_file.parts):
                continue
            rows.append({"type": "file", "path": str(rel_file), "depth": depth + 1, "size": path.stat().st_size})
            if len(rows) >= max_entries:
                rows.append({"type": "more", "path": f"Showing first {max_entries} entries", "depth": 0})
                return rows
    return rows


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
        "tree": file_tree(root),
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

