from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Callable


GitCommand = Callable[..., subprocess.CompletedProcess[str]]


def _value(git: GitCommand, target: Path, *args: str) -> str:
    result = git(target, *args)
    return result.stdout.strip() if result.returncode == 0 else ""


def _symbolic_ref(git: GitCommand, target: Path) -> str:
    return _value(git, target, "symbolic-ref", "-q", "HEAD") or "HEAD"


def safe_worktree_transition(
    git: GitCommand, target: Path, before: str, after: str
) -> bool:
    return git(target, "read-tree", "-u", "-m", before, after).returncode == 0


def refresh_bound_target(
    git: GitCommand,
    target: Path,
    *,
    captured: str,
    integrated: str,
    target_ref: str,
) -> str:
    if not safe_worktree_transition(git, target, captured, integrated):
        rolled_back = git(target, "update-ref", target_ref, captured, integrated)
        return (
            "target worktree refresh failed"
            if rolled_back.returncode == 0
            else "target worktree refresh and ref rollback failed"
        )
    current_ref = _symbolic_ref(git, target)
    current_head = _value(git, target, "rev-parse", "HEAD")
    if current_ref == target_ref and current_head == integrated:
        return ""
    rolled_back = git(target, "update-ref", target_ref, captured, integrated)
    restored = bool(
        current_head and safe_worktree_transition(git, target, integrated, current_head)
    )
    if rolled_back.returncode or not restored:
        return "target drift reconciliation failed"
    return (
        "target symbolic ref changed"
        if current_ref != target_ref
        else "target HEAD changed"
    )


def _preserve_untracked(git: GitCommand, target: Path) -> str:
    result = git(target, "ls-files", "--others", "--exclude-standard", "-z")
    paths = [value for value in result.stdout.split("\0") if value]
    if not paths:
        return ""
    common = _value(git, target, "rev-parse", "--git-common-dir")
    common_path = Path(common) if Path(common).is_absolute() else target / common
    recovery = common_path.resolve() / "aiflow" / "recovery" / str(uuid.uuid4())
    for relative in paths:
        source = (target / relative).resolve()
        if target not in source.parents or not source.exists():
            continue
        destination = recovery / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), destination)
    return str(recovery)


def rollback_bound_target(
    git: GitCommand,
    target: Path,
    *,
    captured: str,
    integrated: str,
    target_ref: str,
) -> str:
    recovery = _preserve_untracked(git, target)
    current_ref = _symbolic_ref(git, target)
    current_head = _value(git, target, "rev-parse", "HEAD")
    updated = git(target, "update-ref", target_ref, captured, integrated)
    restore_to = captured if current_ref == target_ref else current_head
    restored = bool(
        restore_to and safe_worktree_transition(git, target, integrated, restore_to)
    )
    target_value = _value(git, target, "rev-parse", target_ref)
    if updated.returncode or not restored or target_value != captured:
        raise RuntimeError("failed integration could not restore the captured target")
    return recovery
