#!/usr/bin/env python3
"""Restore undeclared worker submodules to clean superproject state."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def status_for(root: Path, path: str) -> list[str]:
    result = run(["git", "status", "--porcelain", "--", path], root)
    if result.returncode != 0:
        return [f"?? {path} # status failed: {result.stderr.strip()}"]
    return result.stdout.splitlines()


def submodule_paths(root: Path) -> list[str]:
    gitmodules = root / ".gitmodules"
    if not gitmodules.exists():
        return []
    result = run(["git", "config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"], root)
    if result.returncode != 0:
        return []
    paths: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            paths.append(parts[1])
    return sorted(set(paths))


def load_paths(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    values: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            values.add(line.rstrip("/"))
    return values


def append_result(log: list[str], title: str, result: subprocess.CompletedProcess[str]) -> None:
    log.append(f"$ {' '.join(result.args if isinstance(result.args, list) else [str(result.args)])}")
    log.append(f"exit={result.returncode}")
    if result.stdout.strip():
        log.append("stdout:")
        log.append(result.stdout.rstrip())
    if result.stderr.strip():
        log.append("stderr:")
        log.append(result.stderr.rstrip())
    log.append("")


def clean_submodule(root: Path, path: str, phase: str, required: bool, log: list[str]) -> None:
    before = status_for(root, path)
    if not before:
        return

    log.append(f"## {path}")
    log.append("before:")
    log.extend(before)
    log.append("")

    for cmd in (
        ["git", "restore", "--staged", "--", path],
        ["git", "restore", "--worktree", "--", path],
        ["git", "submodule", "update", "--init", "--recursive", "--", path],
    ):
        append_result(log, "", run(cmd, root))

    sub_root = root / path
    if sub_root.exists():
        for cmd in (
            ["git", "reset", "--hard"],
            ["git", "clean", "-fd"],
        ):
            append_result(log, "", run(cmd, sub_root))
        append_result(log, "", run(["git", "submodule", "update", "--init", "--recursive", "--", path], root))

    after = status_for(root, path)
    if after and (phase == "posttest" or not required):
        append_result(log, "", run(["git", "submodule", "deinit", "-f", "--", path], root))
        append_result(log, "", run(["git", "restore", "--staged", "--worktree", "--", path], root))
        after = status_for(root, path)

    log.append("after:")
    if after:
        log.extend(after)
    else:
        log.append("clean")
    log.append("")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--phase", required=True, choices=("precommit", "posttest"))
    parser.add_argument("--allowed-paths-file", default="")
    parser.add_argument("--required-paths", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(args.worktree).resolve()
    allowed = load_paths(Path(args.allowed_paths_file) if args.allowed_paths_file else None)
    required_paths = {path.rstrip("/") for path in args.required_paths.split() if path.strip()}

    log: list[str] = [
        f"# Worker submodule cleanliness repair ({args.phase})",
        f"worktree={root}",
        f"allowed_paths={sorted(allowed)}",
        f"required_paths={sorted(required_paths)}",
        "",
    ]

    for path in submodule_paths(root):
        if path.rstrip("/") in allowed:
            log.append(f"## {path}")
            log.append("skipped: path is declared in allowed_submodule_paths.txt")
            log.append("")
            continue
        clean_submodule(root, path, args.phase, path.rstrip("/") in required_paths, log)

    remaining: list[str] = []
    for path in submodule_paths(root):
        if path.rstrip("/") not in allowed:
            remaining.extend(status_for(root, path))

    if remaining:
        log.append("## Remaining undeclared submodule status")
        log.extend(remaining)
        exit_code = 1
    else:
        log.append("## Remaining undeclared submodule status")
        log.append("clean")
        exit_code = 0

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(log) + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
