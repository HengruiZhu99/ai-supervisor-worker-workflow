#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Compile the Architect spec into the supervisor bootstrap artifacts.

On a passing spec, this renders the files the existing supervisor consumes
(`design_prompt.md`, `project_brief.md`, `roadmap.md` with machine-readable
Definition-of-Done, `ledger.md`, `autonomy_delegation.json`), writes a
stack-agnostic `project.yaml`, creates the change-control directory, and
optionally creates the first worker job and starts the loops.

By default it refuses to overwrite existing supervisor planning files (so it
cannot clobber an active project); pass --overwrite to replace them.
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
SUPERVISOR_DIR = Path(".ai/supervisor")


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


def _write(path: Path, content: str, overwrite: bool, results: dict) -> None:
    rel = str(path)
    if path.exists() and not overwrite:
        results["skipped"].append(rel)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    results["written"].append(rel)


def render_first_job_task(spec: dict) -> str:
    """A minimal, progress-gate-valid first-job task for the first milestone."""
    milestones = spec.get("milestones", [])
    milestone = milestones[0] if milestones else {"id": "M1", "title": "first milestone"}
    dod = milestone.get("definition_of_done", []) or []
    first_check = dod[0].get("check", "") if dod else ""
    first_acc = dod[0].get("acceptance", "") if dod else ""
    test_cmd = spec.get("runtime", {}).get("test", "") or "echo no-test-configured"
    unlocks = milestones[1]["id"] if len(milestones) > 1 else f"remaining {milestone.get('id')} Definition-of-Done acceptance checks"
    capability = (
        f"first executable slice of {milestone.get('id')} ({milestone.get('title', '')}) "
        f"verified by acceptance {first_acc or 'criterion'} via `{first_check or test_cmd}`"
    )
    lines = [
        f"# Job: bootstrap {milestone.get('id')} - {milestone.get('title', '')}",
        "",
        "## Objective",
        "",
        f"Begin milestone {milestone.get('id')} ({milestone.get('title', '')}). Implement the "
        "smallest meaningful slice toward its Definition-of-Done and add a test that "
        "exercises new behavior.",
        "",
        "## Background from design prompt",
        "",
        "See .ai/supervisor/design_prompt.md (compiled from the Architect spec) and "
        ".ai/supervisor/roadmap.md for this milestone's Definition-of-Done.",
        "",
        "## Progress Classification",
        "",
        "```yaml",
        "progress:",
        "  job_type: implementation",
        "  subsystem: other",
        f"  capability_target: \"{capability}\"",
        "  new_executable_behavior: true",
        "  validation_class: construction",
        f"  unlocks_next: \"{unlocks}\"",
        "  metadata_only: false",
        "  progress_exception_type: none",
        "  progress_exception_record: \"\"",
        "```",
        "",
        "## Scope",
        "",
        "Allowed:",
        f"- implement the first slice of {milestone.get('id')} and its test",
        "",
        "Not allowed:",
        "- work on later milestones",
        "",
        "## Required validation",
        "",
        "Run:",
        "",
        "```bash",
        test_cmd,
        "```",
        "",
    ]
    if first_check and first_check != test_cmd:
        lines += ["Definition-of-Done check for this milestone:", "", "```bash", first_check, "```", ""]
    return "\n".join(lines)


def create_first_job(root: Path, spec: dict, base_ref: str) -> dict:
    task_path = architect.architect_dir(root) / "first_job_task.md"
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(render_first_job_task(spec), encoding="utf-8")
    test_cmd = spec.get("runtime", {}).get("test", "") or "echo no-test-configured"
    milestone = (spec.get("milestones") or [{"id": "M1", "title": "first"}])[0]
    cmd = [
        sys.executable, str(SCRIPT_DIR / "create_job.py"),
        "--title", f"Bootstrap {milestone.get('id')}: {milestone.get('title', '')}",
        "--base-ref", base_ref,
        "--test-command", test_cmd,
        "--task-file", str(task_path),
    ]
    completed = subprocess.run(cmd, cwd=str(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return {"exit": completed.returncode, "output": completed.stdout.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="overwrite existing supervisor planning files")
    parser.add_argument("--delegate-milestones", type=int, default=1,
                        help="number of leading milestones to delegate before the first human gate")
    parser.add_argument("--create-first-job", action="store_true", help="also create the first queued worker job")
    parser.add_argument("--base-ref", default="HEAD", help="base ref for the first job")
    parser.add_argument("--start", action="store_true", help="start the supervisor and worker loops after compiling")
    parser.add_argument("--allow-incomplete", action="store_true", help="compile even if deterministic checks fail (not recommended)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = git_root()
    session = architect.load_session(root)
    spec = session["spec"]

    completeness = ac.spec_completeness(spec)
    if not completeness["complete"] and not args.allow_incomplete:
        msg = {"ok": False, "reason": "spec is not complete; run the gate first", "missing": completeness["missing"]}
        print(json.dumps(msg, indent=2) if args.json else f"Refusing to compile: spec incomplete.\n- " + "\n- ".join(completeness["missing"]))
        return 1

    results: dict = {"written": [], "skipped": []}
    sup = root / SUPERVISOR_DIR
    _write(sup / "design_prompt.md", ac.render_design_prompt(spec), args.overwrite, results)
    _write(sup / "project_brief.md", ac.render_project_brief(spec), args.overwrite, results)
    _write(sup / "roadmap.md", ac.render_roadmap(spec), args.overwrite, results)
    _write(sup / "ledger.md", ac.render_ledger_seed(spec), args.overwrite, results)
    _write(
        sup / "autonomy_delegation.json",
        json.dumps(ac.build_autonomy_delegation(spec, args.delegate_milestones), indent=2, sort_keys=True) + "\n",
        args.overwrite,
        results,
    )
    _write(
        root / "project.yaml",
        ac.dump_simple_yaml(ac.default_project_yaml(spec)),
        args.overwrite,
        results,
    )
    # Change-control directory for post-handoff scope requests.
    (architect.architect_dir(root) / "change_requests").mkdir(parents=True, exist_ok=True)

    session["status"] = "compiled"
    architect.save_session(root, session)

    first_job = None
    if args.create_first_job:
        first_job = create_first_job(root, spec, args.base_ref)

    started: list[str] = []
    if args.start:
        try:
            import human_milestone_review as hmr
            for loop in ("supervisor_loop", "worker_loop"):
                started.append(f"{loop}: {hmr.start_loop(loop)}")
        except Exception as exc:  # best-effort
            started.append(f"failed to start loops: {exc}")

    out = {
        "ok": True,
        "written": results["written"],
        "skipped": results["skipped"],
        "first_job": first_job,
        "started": started,
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print("Compiled spec into bootstrap artifacts.")
        for p in results["written"]:
            print(f"  written: {p}")
        for p in results["skipped"]:
            print(f"  skipped (exists, use --overwrite): {p}")
        if first_job:
            print(f"  first job: exit={first_job['exit']} {first_job['output']}")
        for line in started:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
