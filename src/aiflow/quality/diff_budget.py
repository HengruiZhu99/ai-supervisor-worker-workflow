from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path
from typing import Any


SOURCE_SUFFIXES = {".py", ".sh", ".bash", ".js", ".jsx", ".ts", ".tsx"}


def source_lines(path: Path) -> int:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    return sum(
        1
        for line in lines
        if line.strip() and not line.lstrip().startswith(("#", "//"))
    )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )


def _tracked_rows(output: str) -> list[tuple[int, int, str]]:
    rows: list[tuple[int, int, str]] = []
    for line in output.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        added, removed, path = parts
        if (
            Path(path).suffix.lower() in SOURCE_SUFFIXES
            and added.isdigit()
            and removed.isdigit()
        ):
            rows.append((int(added), int(removed), path))
    return rows


def _untracked_rows(root: Path) -> list[tuple[int, int, str]]:
    result = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    if result.returncode:
        return []
    rows: list[tuple[int, int, str]] = []
    for relative in result.stdout.split("\0"):
        path = root / relative
        if relative and path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
            rows.append((source_lines(path), 0, relative))
    return rows


def _active_exception(entries: object, scope: str) -> dict[str, Any] | None:
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("scope") != scope:
            continue
        try:
            expiry = date.fromisoformat(str(entry.get("expires", "")))
        except ValueError:
            continue
        if expiry >= date.today():
            return entry
    return None


def _budget_errors(
    root: Path,
    raw_policy: dict[str, Any],
    rows: list[tuple[int, int, str]],
    *,
    resolved_base: str,
) -> tuple[list[str], list[str]]:
    config = raw_policy.get("diff", {})
    soft_files = int(config.get("soft_source_files", 8))
    soft_lines = int(config.get("soft_logical_lines", 500))
    multiplier = float(config.get("hard_multiplier", 2.0))
    files = len(rows)
    lines = sum(added + removed for added, removed, _ in rows)
    errors: list[str] = []
    applied: list[str] = []
    hard = files > soft_files * multiplier or lines > soft_lines * multiplier
    scope = f"diff-from:{resolved_base}"
    exception = _active_exception(raw_policy.get("exception", []), scope)
    if hard and exception is None:
        errors.append(
            f"diff hard budget exceeded: {files} files, {lines} changed lines"
        )
    elif hard:
        applied.append(scope)
    note = root / "docs" / "architecture-impact.md"
    if (files > soft_files or lines > soft_lines) and not note.is_file():
        errors.append("soft diff budget requires docs/architecture-impact.md")
    return errors, applied


def diff_errors(
    root: Path, raw_policy: dict[str, Any], *, base: str
) -> tuple[list[str], list[str]]:
    if not (root / ".git").exists():
        return [], []
    verified = _git(root, "rev-parse", "--verify", base)
    if verified.returncode and base == "HEAD":
        return [], []
    if verified.returncode:
        return [f"cannot measure source diff from {base}"], []
    resolved_base = verified.stdout.strip()
    result = _git(root, "diff", "--numstat", base)
    if result.returncode:
        return [f"cannot measure source diff from {base}"], []
    rows = _tracked_rows(result.stdout)
    rows.extend(_untracked_rows(root))
    return _budget_errors(root, raw_policy, rows, resolved_base=resolved_base)
