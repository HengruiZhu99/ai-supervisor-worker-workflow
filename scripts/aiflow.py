#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""aiflow: the front-door CLI for the AI build workflow.

Subcommands:
  init     run the Architect interview, then gate, then compile the spec into the
           supervisor bootstrap artifacts (the full intake-to-handoff flow).
  spec     resume the interactive Architect interview only.
  gate     run the spec completeness gate (deterministic + consensus).
  compile  compile the (passing) spec into the supervisor bootstrap artifacts.
  start    start the supervisor and worker loops.
  status   print the current intake state.

The interactive interview uses architect.interview_turn directly; gate/compile
shell out to their dedicated scripts so their behavior is identical to running
them standalone.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import architect
import architect_core as ac

SCRIPT_DIR = Path(__file__).resolve().parent


def git_root() -> Path:
    # Standalone tool: AIFLOW_PROJECT_ROOT selects the target repo so the tool can
    # run from its own install location against any project. Falls back to the
    # current git repo, then cwd.
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


def _print_state(root: Path) -> dict:
    session = architect.load_session(root)
    completeness = ac.spec_completeness(session["spec"])
    print(ac.render_spec_summary(session["spec"]))
    return completeness


def run_interview(root: Path, wrapper: str, model: str, timeout: int) -> bool:
    """Drive the interactive interview loop. Returns True if the spec is ready."""
    runner = architect.make_default_runner(workspace=str(root), wrapper=wrapper, model=model, timeout=timeout)
    print("Architect intake. Describe the software you want to build.")
    print("Commands: /done to try finalizing, /state to see progress, /quit to stop.\n")
    # Greet / first questions (empty user message).
    result = architect.interview_turn(root, "", runner=runner)
    if result["ask_user"]:
        print(f"\nArchitect: {result['ask_user']}\n")
    while True:
        try:
            message = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n(stopping; progress saved)")
            return False
        if message in {"/quit", "/exit"}:
            print("(stopping; progress saved)")
            return False
        if message == "/state":
            _print_state(root)
            continue
        finalize = message == "/done"
        result = architect.interview_turn(root, "" if finalize else message, runner=runner)
        if result["ask_user"]:
            print(f"\nArchitect: {result['ask_user']}\n")
        completeness = result["completeness"]
        if result["status"] == "ready":
            print("Spec looks complete. Run the gate next (aiflow gate) or continue refining.")
            return True
        if finalize and not completeness["complete"]:
            print("Not ready to finalize yet. Still missing:")
            for item in completeness["missing"]:
                print(f"- {item}")
    return False


def _run(script: str, extra: list[str], root: Path) -> int:
    cmd = [sys.executable, str(SCRIPT_DIR / script), *extra]
    return subprocess.run(cmd, cwd=str(root), check=False).returncode


def cmd_init(args: argparse.Namespace) -> int:
    root = git_root()
    ready = run_interview(root, args.wrapper, args.model, args.timeout)
    if not ready and not args.force:
        print("\nInterview not finalized; run `aiflow spec` to continue or `aiflow gate` to check.")
        return 0
    gate_args = ["--json"]
    if args.no_consensus:
        gate_args.append("--no-consensus")
    print("\nRunning spec completeness gate...")
    gate_rc = _run("check_spec_completeness.py", gate_args, root)
    if gate_rc != 0:
        print(f"Gate did not pass (exit {gate_rc}); refine the spec and re-run `aiflow gate`.")
        return gate_rc
    print("\nCompiling bootstrap artifacts...")
    compile_args: list[str] = []
    if args.create_first_job:
        compile_args.append("--create-first-job")
    if args.start:
        compile_args.append("--start")
    return _run("architect_compile.py", compile_args, root)


def cmd_spec(args: argparse.Namespace) -> int:
    root = git_root()
    run_interview(root, args.wrapper, args.model, args.timeout)
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    root = git_root()
    extra = []
    if args.no_consensus:
        extra.append("--no-consensus")
    if args.json:
        extra.append("--json")
    return _run("check_spec_completeness.py", extra, root)


def cmd_compile(args: argparse.Namespace) -> int:
    root = git_root()
    extra = []
    if args.overwrite:
        extra.append("--overwrite")
    if args.create_first_job:
        extra.append("--create-first-job")
    if args.start:
        extra.append("--start")
    return _run("architect_compile.py", extra, root)


def cmd_start(args: argparse.Namespace) -> int:
    root = git_root()
    try:
        import human_milestone_review as hmr
    except Exception as exc:
        print(f"could not import loop starter: {exc}")
        return 1
    for loop in ("supervisor_loop", "worker_loop"):
        print(hmr.start_loop(loop))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = git_root()
    _print_state(root)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_interview_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--wrapper", default="cursor-agent")
        p.add_argument("--model", default="gpt-5.5-high")
        p.add_argument("--timeout", type=int, default=0)

    init = sub.add_parser("init", help="interview -> gate -> compile")
    add_interview_args(init)
    init.add_argument("--no-consensus", action="store_true")
    init.add_argument("--create-first-job", action="store_true")
    init.add_argument("--start", action="store_true")
    init.add_argument("--force", action="store_true", help="proceed to gate even if not marked ready")
    init.set_defaults(func=cmd_init)

    spec = sub.add_parser("spec", help="resume the interactive interview")
    add_interview_args(spec)
    spec.set_defaults(func=cmd_spec)

    gate = sub.add_parser("gate", help="run the spec completeness gate")
    gate.add_argument("--no-consensus", action="store_true")
    gate.add_argument("--json", action="store_true")
    gate.set_defaults(func=cmd_gate)

    comp = sub.add_parser("compile", help="compile the spec into bootstrap artifacts")
    comp.add_argument("--overwrite", action="store_true")
    comp.add_argument("--create-first-job", action="store_true")
    comp.add_argument("--start", action="store_true")
    comp.set_defaults(func=cmd_compile)

    start = sub.add_parser("start", help="start the supervisor and worker loops")
    start.set_defaults(func=cmd_start)

    status = sub.add_parser("status", help="print the current intake state")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
