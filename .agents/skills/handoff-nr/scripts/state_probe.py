#!/usr/bin/env python3
"""Capture and verify portable Git/contract state for a Codex handoff.

The script records addresses and fingerprints, not file contents. It uses only the
Python standard library and Git. Remote URLs are sanitized before writing.
State-artifact paths can be excluded from the code-worktree fingerprint.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
from typing import Any, Iterable


SCHEMA_VERSION = 1


def run_git(repo: pathlib.Path, *args: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.rstrip("\n"),
        "stderr": proc.stderr.rstrip("\n"),
        "command": ["git", "-C", ".", *args],
    }


def git_root(repo: pathlib.Path) -> pathlib.Path:
    repo = repo.resolve()
    result = run_git(repo, "rev-parse", "--show-toplevel")
    if not result["ok"]:
        raise RuntimeError(f"not a Git repository: {result['stderr']}")
    return pathlib.Path(result["stdout"]).resolve()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_remote(url: str) -> str:
    value = url.strip()
    # Remove scheme userinfo: https://user:token@example/repo -> https://example/repo
    value = re.sub(r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/@]+@", r"\g<scheme>", value)
    # Remove common query/fragment credential carriers.
    value = value.split("?", 1)[0].split("#", 1)[0]
    return value


def relative_or_input(repo: pathlib.Path, raw: str | pathlib.Path) -> tuple[str, pathlib.Path]:
    candidate = pathlib.Path(raw)
    path = candidate if candidate.is_absolute() else repo / candidate
    try:
        label = path.resolve(strict=False).relative_to(repo.resolve()).as_posix()
    except ValueError:
        label = str(candidate)
    return label, path


def normalize_ignored(git_root_path: pathlib.Path, values: Iterable[str | pathlib.Path]) -> list[str]:
    normalized: list[str] = []
    for raw in values:
        label, path = relative_or_input(git_root_path, raw)
        try:
            path.resolve(strict=False).relative_to(git_root_path)
        except ValueError:
            # An external path cannot affect this Git worktree.
            continue
        label = label.rstrip("/")
        if label in ("", "."):
            raise ValueError("refusing to ignore the entire repository")
        if label not in normalized:
            normalized.append(label)
    return sorted(normalized)


def pathspec_args(ignored: list[str]) -> list[str]:
    args = ["--", "."]
    for path in ignored:
        args.extend([f":(exclude){path}", f":(exclude){path}/**"])
    return args


def capture(repo: pathlib.Path, contracts: list[str], ignore_paths: Iterable[str | pathlib.Path] = ()) -> dict[str, Any]:
    root = git_root(repo)
    ignored = normalize_ignored(root, ignore_paths)
    specs = pathspec_args(ignored)

    head = run_git(root, "rev-parse", "HEAD")
    branch = run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    upstream = run_git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    status = run_git(root, "status", "--porcelain=v2", "--branch", "--untracked-files=all", *specs)
    diff_stat = run_git(root, "diff", "--stat", *specs)
    staged_stat = run_git(root, "diff", "--cached", "--stat", *specs)
    origin = run_git(root, "remote", "get-url", "origin")

    contract_rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for raw in contracts:
        label, path = relative_or_input(root, raw)
        exists = path.is_file()
        row: dict[str, Any] = {"path": label, "exists": exists}
        if exists:
            row.update({"sha256": sha256_file(path), "size": path.stat().st_size})
        else:
            missing.append(label)
        contract_rows.append(row)

    status_text = status["stdout"] if status["ok"] else ""
    status_digest = hashlib.sha256(status_text.encode("utf-8")).hexdigest()
    disk = shutil.disk_usage(root)

    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repository": {
            "root_name": root.name,
            "origin": sanitize_remote(origin["stdout"]) if origin["ok"] else None,
            "branch": branch["stdout"] if branch["ok"] else "DETACHED",
            "head": head["stdout"] if head["ok"] else None,
            "upstream": upstream["stdout"] if upstream["ok"] else None,
            "ignored_state_paths": ignored,
            "status_porcelain_v2": status_text,
            "status_sha256": status_digest,
            "worktree_clean": status_text.strip() == "" or all(
                line.startswith("# ") for line in status_text.splitlines() if line
            ),
            "diff_stat": diff_stat["stdout"] if diff_stat["ok"] else None,
            "staged_diff_stat": staged_stat["stdout"] if staged_stat["ok"] else None,
        },
        "contracts": contract_rows,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "disk_free_bytes": disk.free,
            "disk_total_bytes": disk.total,
        },
        "missing_contracts": missing,
    }


def load_json(path: pathlib.Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("snapshot root must be a JSON object")
    return value


def contract_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = snapshot.get("contracts", [])
    return {str(row.get("path")): row for row in rows if isinstance(row, dict)}


def verify(
    snapshot_path: pathlib.Path,
    repo: pathlib.Path,
    additional_ignores: Iterable[str | pathlib.Path] = (),
) -> tuple[dict[str, Any], int]:
    expected = load_json(snapshot_path)
    root = git_root(repo)
    expected_contracts = [row["path"] for row in expected.get("contracts", []) if row.get("path")]
    saved_ignores = expected.get("repository", {}).get("ignored_state_paths", [])
    ignores: list[str | pathlib.Path] = list(saved_ignores) + list(additional_ignores)
    # The snapshot itself is state, not production worktree content.
    ignores.append(snapshot_path)
    current = capture(root, expected_contracts, ignores)
    mismatches: list[dict[str, Any]] = []

    exp_repo = expected.get("repository", {})
    cur_repo = current.get("repository", {})
    for key in ("origin", "branch", "head", "status_sha256"):
        if exp_repo.get(key) != cur_repo.get(key):
            mismatches.append(
                {"field": f"repository.{key}", "expected": exp_repo.get(key), "current": cur_repo.get(key)}
            )

    exp_contracts = contract_map(expected)
    cur_contracts = contract_map(current)
    for path, exp in exp_contracts.items():
        cur = cur_contracts.get(path, {"exists": False})
        for key in ("exists", "sha256"):
            if exp.get(key) != cur.get(key):
                mismatches.append(
                    {
                        "field": f"contracts[{path}].{key}",
                        "expected": exp.get(key),
                        "current": cur.get(key),
                    }
                )

    result = {
        "schema_version": SCHEMA_VERSION,
        "verified_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "snapshot": str(snapshot_path),
        "match": not mismatches,
        "mismatches": mismatches,
        "current": current,
    }
    return result, 0 if not mismatches else 2


def write_json(value: dict[str, Any], output: pathlib.Path | None) -> None:
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, output)
    print(output)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="capture current Git and contract state")
    cap.add_argument("--repo", default=".", help="repository path")
    cap.add_argument(
        "--contract",
        nargs="+",
        default=["DESIGN.md", "TDD_PLAN.md", "GOAL.md"],
        help="contract files relative to the repository",
    )
    cap.add_argument(
        "--ignore",
        action="append",
        default=[],
        help="repository-relative state path to exclude from worktree status (repeatable)",
    )
    cap.add_argument("--output", help="write JSON atomically to this path")

    ver = sub.add_parser("verify", help="compare current state with a prior snapshot")
    ver.add_argument("--repo", default=".", help="repository path")
    ver.add_argument("--snapshot", required=True, help="snapshot JSON created by capture")
    ver.add_argument(
        "--ignore",
        action="append",
        default=[],
        help="additional repository-relative state path to exclude (repeatable)",
    )
    ver.add_argument("--output", help="write comparison JSON atomically to this path")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "capture":
            ignores: list[str | pathlib.Path] = list(args.ignore)
            if args.output:
                ignores.append(pathlib.Path(args.output))
            result = capture(pathlib.Path(args.repo), list(args.contract), ignores)
            write_json(result, pathlib.Path(args.output) if args.output else None)
            return 0 if not result["missing_contracts"] else 2
        ignores = list(args.ignore)
        if args.output:
            ignores.append(pathlib.Path(args.output))
        result, code = verify(pathlib.Path(args.snapshot), pathlib.Path(args.repo), ignores)
        write_json(result, pathlib.Path(args.output) if args.output else None)
        return code
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"state_probe: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
