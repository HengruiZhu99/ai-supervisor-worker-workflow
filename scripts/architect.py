#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Architect intake runner: drives a multi-turn interview to build a project spec.

The interview is stateless-per-call but stateful-via-transcript (the same pattern
as the dashboard supervisor chat): each turn rebuilds the prompt from the current
structured spec plus the recent conversation, runs an agent read-only, parses the
agent's machine block, merges it into the spec, and persists the session.

Pure spec logic lives in `architect_core.py`; this module owns session I/O and
the agent process. ``interview_turn`` takes an injectable ``runner`` so the loop
is unit-testable without launching a real agent.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import architect_core as ac

SCRIPT_DIR = Path(__file__).resolve().parent
ARCHITECT_DIR = Path(".ai/architect")
SESSION_NAME = "spec_session.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def architect_dir(root: Path) -> Path:
    return root / ARCHITECT_DIR


def session_path(root: Path) -> Path:
    return architect_dir(root) / SESSION_NAME


def new_session() -> dict:
    now = utc_now()
    return {
        "schema_version": 1,
        "status": "interviewing",
        "created_at": now,
        "updated_at": now,
        "spec": ac.new_spec(),
        "history": [],
        "last_ask": "",
    }


def load_session(root: Path) -> dict:
    path = session_path(root)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "spec" in data:
                data.setdefault("history", [])
                data.setdefault("status", "interviewing")
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return new_session()


def save_session(root: Path, session: dict) -> None:
    architect_dir(root).mkdir(parents=True, exist_ok=True)
    session["updated_at"] = utc_now()
    session_path(root).write_text(
        json.dumps(session, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_spec_artifacts(root: Path, spec: dict) -> None:
    """Persist the human-readable spec artifacts under .ai/architect/."""
    out = architect_dir(root)
    out.mkdir(parents=True, exist_ok=True)
    (out / "requirements.md").write_text(ac.render_requirements_md(spec), encoding="utf-8")
    (out / "acceptance.md").write_text(ac.render_acceptance_md(spec), encoding="utf-8")
    (out / "milestones.md").write_text(ac.render_milestones_md(spec), encoding="utf-8")
    (out / "risks.md").write_text(ac.render_risks_md(spec), encoding="utf-8")
    (out / "glossary.md").write_text(ac.render_glossary_md(spec), encoding="utf-8")


def _stream_to_text(raw_stdout: str) -> str:
    converter = SCRIPT_DIR / "cursor_stream_to_text.py"
    if not converter.exists():
        return raw_stdout
    try:
        completed = subprocess.run(
            [sys.executable, str(converter)],
            input=raw_stdout,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return completed.stdout or raw_stdout
    except OSError:
        return raw_stdout


def make_default_runner(
    *,
    workspace: str,
    wrapper: str = "codex",
    model: str = "gpt-5.6-sol",
    output_format: str = "",
    extra_args: str = "",
    timeout: int = 1800,
):
    """Build a runner that invokes an agent read-only and returns its text output."""

    def run(prompt_text: str) -> str:
        prompt_dir = architect_dir(Path(workspace))
        prompt_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = prompt_dir / "interview.prompt.md"
        prompt_file.write_text(prompt_text, encoding="utf-8")
        cmd = [
            sys.executable,
            str(SCRIPT_DIR / "agent_wrapper.py"),
            "run",
            "--role",
            "chat",
            "--wrapper",
            wrapper,
            "--model",
            model,
            "--workspace",
            workspace,
            "--prompt-file",
            str(prompt_file),
            "--read-only",
        ]
        if output_format:
            cmd.extend(["--output-format", output_format])
        if extra_args:
            cmd.append(f"--extra-args={extra_args}")
        try:
            completed = subprocess.run(
                cmd,
                cwd=workspace,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout if timeout and timeout > 0 else None,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ""
        raw = completed.stdout or ""
        return _stream_to_text(raw) if output_format == "stream-json" else raw

    return run


def interview_turn(root: Path, user_message: str, runner=None) -> dict:
    """Run one interview turn and persist the updated session.

    Returns ``{"ask_user", "ready_to_finalize", "completeness", "spec", "raw"}``.
    """
    session = load_session(root)
    spec = session["spec"]
    history = session.get("history", [])

    if user_message.strip():
        history.append({"role": "user", "content": user_message.strip()})

    if runner is None:
        runner = make_default_runner(workspace=str(root))

    prompt = ac.build_interview_prompt(spec, history, user_message)
    raw = runner(prompt)
    update = ac.extract_architect_update(raw) or {}
    ac.apply_update(spec, update)

    ask_user = str(update.get("ask_user", "")).strip()
    ready = bool(update.get("ready_to_finalize"))
    history.append({"role": "architect", "content": ask_user or raw.strip()[:4000]})

    completeness = ac.spec_completeness(spec)
    # Finalize only when the agent says it is ready AND the deterministic checks agree.
    session["status"] = "ready" if (ready and completeness["complete"]) else "interviewing"
    session["history"] = history
    session["spec"] = spec
    session["last_ask"] = ask_user
    save_session(root, session)
    write_spec_artifacts(root, spec)

    return {
        "ask_user": ask_user,
        "ready_to_finalize": ready,
        "completeness": completeness,
        "status": session["status"],
        "spec": spec,
        "raw": raw,
    }


def git_root() -> Path:
    env_root = os.environ.get("AIFLOW_PROJECT_ROOT")
    if env_root:
        return Path(env_root).resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return Path.cwd()


def cmd_message(args: argparse.Namespace) -> int:
    root = git_root()
    runner = make_default_runner(
        workspace=str(root), wrapper=args.wrapper, model=args.model, timeout=args.timeout
    )
    result = interview_turn(root, args.message, runner=runner)
    print(json.dumps({
        "ask_user": result["ask_user"],
        "status": result["status"],
        "complete": result["completeness"]["complete"],
        "missing": result["completeness"]["missing"],
    }, indent=2))
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    root = git_root()
    session = load_session(root)
    completeness = ac.spec_completeness(session["spec"])
    print(json.dumps({
        "status": session.get("status"),
        "complete": completeness["complete"],
        "missing": completeness["missing"],
        "warnings": completeness["warnings"],
        "summary": ac.render_spec_summary(session["spec"]),
    }, indent=2))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    root = git_root()
    session = load_session(root)
    print(json.dumps(session["spec"], indent=2, sort_keys=True))
    return 0


def split_extra_args(value: str) -> list[str]:
    return shlex.split(value) if value and value.strip() else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    msg = sub.add_parser("message", help="send one interview message")
    msg.add_argument("message")
    msg.add_argument("--wrapper", default="codex")
    msg.add_argument("--model", default="gpt-5.6-sol")
    msg.add_argument("--timeout", type=int, default=1800)
    msg.set_defaults(func=cmd_message)

    state = sub.add_parser("state", help="print interview completeness state")
    state.set_defaults(func=cmd_state)

    show = sub.add_parser("show", help="print the current spec as json")
    show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
