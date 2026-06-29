#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Spec completeness gate for the Architect intake stage.

Two layers, both must pass before the spec is handed off to the supervisor:

1. Deterministic checks (`architect_core.spec_completeness`): every requirement
   has an acceptance criterion, every milestone has a Definition-of-Done, every
   requirement is covered by a milestone, the runtime test command is set, and no
   open questions remain.
2. Multi-model consensus review (reuses `orchestrator.py` with the `spec`
   decision schema and the `spec` panel): a panel must broadly agree the spec is
   complete, feasible, and internally consistent (verdict `ready`).

Exit codes: 0 = gate passed; 1 = deterministic checks failed; 2 = consensus
review did not reach a `ready` consensus; 3 = could not run the consensus panel.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import architect
import architect_core as ac

SCRIPT_DIR = Path(__file__).resolve().parent


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


def build_spec_review_prompt(spec: dict) -> str:
    parts = [
        "# Specification review",
        "",
        "You are reviewing a compiled project specification BEFORE an autonomous "
        "multi-agent build begins. Decide whether the spec is READY to build or "
        "NEEDS_REVISION. Judge completeness, feasibility for the chosen stack, and "
        "internal consistency. List concrete, actionable gaps; do not invent new "
        "scope.",
        "",
        "Set `consensus_vote.verdict` to `ready` or `needs_revision`.",
        "",
        "## Project",
        "",
        f"Name: {spec.get('project', {}).get('name', '')}",
        f"Language/stack: {spec.get('project', {}).get('language', '')}",
        f"Summary: {spec.get('project', {}).get('summary', '')}",
        f"Runtime test command: {spec.get('runtime', {}).get('test', '') or '(unset)'}",
        "",
        ac.render_requirements_md(spec),
        "",
        ac.render_acceptance_md(spec),
        "",
        ac.render_milestones_md(spec),
        "",
        ac.render_risks_md(spec),
    ]
    return "\n".join(parts)


def run_consensus_gate(root: Path, spec: dict, args: argparse.Namespace) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = architect.architect_dir(root) / f"gate.{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = out_dir / "spec_review.prompt.md"
    prompt_file.write_text(build_spec_review_prompt(spec), encoding="utf-8")

    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "orchestrator.py"),
        "run",
        "--role",
        "architect",
        "--decision-schema",
        "spec",
        "--panel-id",
        args.panel,
        "--base-prompt-file",
        str(prompt_file),
        "--workspace",
        str(root),
        "--output-dir",
        str(out_dir),
        "--max-rounds",
        str(args.max_rounds),
        "--quorum",
        args.quorum,
        "--output-format",
        "stream-json",
    ]
    if args.models:
        cmd.extend(["--models", args.models])
    if args.extra_args:
        cmd.append(f"--extra-args={args.extra_args}")
    if args.timeout:
        cmd.extend(["--timeout", str(args.timeout)])

    log = out_dir / "gate.log"
    exit_code = 0
    try:
        with log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(cmd, cwd=str(root), stdout=handle, stderr=subprocess.STDOUT, check=False)
            exit_code = completed.returncode
    except OSError as exc:
        return {"ran": False, "error": str(exc), "out_dir": str(out_dir)}

    consensus_path = out_dir / "consensus.json"
    if not consensus_path.exists():
        return {"ran": False, "error": f"no consensus.json (orchestrator exit {exit_code})", "out_dir": str(out_dir)}
    try:
        consensus = json.loads(consensus_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ran": False, "error": f"unreadable consensus.json: {exc}", "out_dir": str(out_dir)}
    consensus["ran"] = True
    consensus["out_dir"] = str(out_dir)
    return consensus


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consensus", dest="consensus", action="store_true", default=True,
                        help="run the multi-model consensus review (default)")
    parser.add_argument("--no-consensus", dest="consensus", action="store_false",
                        help="run deterministic checks only (offline)")
    parser.add_argument("--panel", default="spec")
    parser.add_argument("--models", default="")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--quorum", default="unanimous")
    parser.add_argument("--extra-args", default="--force")
    parser.add_argument("--timeout", type=int, default=0)
    parser.add_argument("--json", action="store_true", help="emit a machine-readable result")
    args = parser.parse_args()

    root = git_root()
    session = architect.load_session(root)
    spec = session["spec"]

    completeness = ac.spec_completeness(spec)
    result: dict = {
        "deterministic_complete": completeness["complete"],
        "missing": completeness["missing"],
        "warnings": completeness["warnings"],
        "consensus_enabled": args.consensus,
    }

    if not completeness["complete"]:
        result["passed"] = False
        result["reason"] = "deterministic completeness checks failed"
        _emit(result, args)
        return 1

    if not args.consensus:
        result["passed"] = True
        result["reason"] = "deterministic checks passed (consensus skipped)"
        _emit(result, args)
        return 0

    consensus = run_consensus_gate(root, spec, args)
    result["consensus"] = {
        "ran": consensus.get("ran"),
        "converged": consensus.get("converged"),
        "method": consensus.get("method"),
        "verdict": consensus.get("verdict"),
        "blocking_reasons": consensus.get("blocking_reasons"),
        "out_dir": consensus.get("out_dir"),
        "error": consensus.get("error"),
    }
    if not consensus.get("ran"):
        result["passed"] = False
        result["reason"] = f"could not run consensus panel: {consensus.get('error')}"
        _emit(result, args)
        return 3
    ready = bool(consensus.get("converged")) and consensus.get("verdict") == "ready"
    result["passed"] = ready
    result["reason"] = "spec is ready" if ready else "consensus panel did not agree the spec is ready"
    _emit(result, args)
    return 0 if ready else 2


def _emit(result: dict, args: argparse.Namespace) -> None:
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    print(f"Spec gate: {'PASS' if result.get('passed') else 'FAIL'} - {result.get('reason')}")
    if result.get("missing"):
        print("Missing:")
        for item in result["missing"]:
            print(f"- {item}")
    if result.get("warnings"):
        print("Warnings:")
        for item in result["warnings"]:
            print(f"- {item}")
    consensus = result.get("consensus")
    if consensus and consensus.get("ran"):
        print(f"Consensus: verdict={consensus.get('verdict')} converged={consensus.get('converged')} ({consensus.get('out_dir')})")


if __name__ == "__main__":
    raise SystemExit(main())
