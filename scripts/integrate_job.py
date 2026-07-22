#!/usr/bin/env python3
"""Finite compatibility shim for the two-phase AIFLOW integration transaction.

The package creates an integration worktree, runs focused, regression, and quality
gates, then enforces the ``target HEAD changed`` compare-and-swap guard before applying.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.integration.transaction import GateCommands, IntegrationTransaction  # noqa: E402


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )


def git_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    if result.returncode:
        raise SystemExit("integrate_job.py must run inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def load_status(root: Path, job_id: str) -> tuple[Path, dict]:
    job = root / ".ai" / "jobs" / job_id
    try:
        status = json.loads((job / "status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid job status for {job_id}: {exc}") from exc
    return job, status


def verify(status: dict) -> list[str]:
    errors: list[str] = []
    if status.get("state") not in {"ready_for_review", "accepted"}:
        errors.append("job is not ready for integration")
    for key in ("base_sha", "commit", "branch"):
        if not status.get(key):
            errors.append(f"missing {key}")
    if status.get("tests_passed") is not True:
        errors.append("tests_passed is not true")
    if status.get("reviewer_a_blocks") or status.get("reviewer_b_blocks"):
        errors.append("a reviewer blocks acceptance")
    return errors


def _commands(root: Path) -> GateCommands:
    try:
        config = tomllib.loads((root / ".aiflow" / "project.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        config = {}
    commands = config.get("commands", {}) if isinstance(config, dict) else {}

    def command(name: str) -> tuple[tuple[str, ...], ...]:
        value = commands.get(name, []) if isinstance(commands, dict) else []
        return (tuple(str(part) for part in value),) if value else ()

    quality = ((str(ROOT / "bin" / "aiflow"), "--project-root", ".", "quality", "check"),)
    return GateCommands(
        focused=command("test_focused"),
        regression=command("test_regression"),
        quality=quality,
    )


def integrate(root: Path, status: dict, method: str) -> int:
    if method == "ff-only":
        print("ff-only is not supported by the two-phase transaction", file=sys.stderr)
        return 2
    transaction = IntegrationTransaction(root, gates=_commands(root), runner=run)
    result = transaction.apply(
        str(status.get("commit") or status["branch"]),
        method=method,
        base_sha=str(status.get("base_sha", "")),
    )
    print(json.dumps(result.__dict__, indent=2, sort_keys=True))
    return 0 if result.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--method", choices=("merge", "cherry-pick", "ff-only"), default="merge")
    args = parser.parse_args()
    root = git_root()
    _, status = load_status(root, args.job_id)
    errors = verify(status)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, indent=2))
        return 1
    if not args.apply:
        print(json.dumps({"ok": True, "next": "re-run with --apply"}, indent=2))
        return 0
    return integrate(root, status, args.method)


if __name__ == "__main__":
    raise SystemExit(main())
