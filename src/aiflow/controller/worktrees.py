from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from aiflow.identity.context import ProjectContext, resolve_project
from aiflow.security.process import run_owned_process


class WorktreeError(RuntimeError):
    """An orchestrated writer worktree cannot be created or verified."""


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return run_owned_process(
        ["git", *arguments],
        cwd=root,
        timeout=60,
    )


@dataclass
class TaskWorktree:
    target: ProjectContext
    run_id: str
    task_id: str
    runtime: Path
    base_sha: str = ""
    path: Path | None = None
    context: ProjectContext | None = None
    branch: str = ""

    def _verify_existing(self) -> None:
        assert self.path is not None
        status = _git(self.path, "status", "--porcelain")
        head = _git(self.path, "rev-parse", "HEAD")
        branch = _git(self.path, "branch", "--show-current")
        if status.returncode or status.stdout.strip():
            raise WorktreeError(
                "pre-existing task worktree is dirty; explicit reconciliation is required"
            )
        if head.returncode or head.stdout.strip() != self.base_sha:
            raise WorktreeError(
                "pre-existing task worktree is not at the captured base"
            )
        if branch.returncode or branch.stdout.strip() != self.branch:
            raise WorktreeError("pre-existing task worktree has the wrong branch")

    def create(self) -> "TaskWorktree":
        base = _git(self.target.root, "rev-parse", "HEAD")
        if base.returncode:
            raise WorktreeError(
                "orchestrated execution requires a committed target HEAD"
            )
        self.base_sha = base.stdout.strip()
        self.branch = f"aiflow/{self.run_id[:12]}/{self.task_id}"
        parent = self.runtime / "agent-worktrees"
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(parent, 0o700)
        self.path = parent / self.task_id
        if not self.path.exists():
            added = _git(
                self.target.root,
                "worktree",
                "add",
                "-b",
                self.branch,
                str(self.path),
                self.base_sha,
            )
            if added.returncode and "already exists" in added.stderr:
                added = _git(
                    self.target.root,
                    "worktree",
                    "add",
                    str(self.path),
                    self.branch,
                )
            if added.returncode:
                raise WorktreeError(
                    f"cannot create task worktree: {added.stderr.strip()}"
                )
        self._verify_existing()
        self.context = resolve_project(explicit_root=self.path)
        if self.context.git_common_dir != self.target.git_common_dir:
            raise WorktreeError("task worktree escaped the active checkout")
        return self

    def commit(self, *, message: str) -> str:
        if self.path is None:
            raise WorktreeError("task worktree is not initialized")
        if not _git(self.path, "status", "--porcelain").stdout.strip():
            raise WorktreeError("writer produced no workspace delta")
        if _git(self.path, "add", "--all").returncode:
            raise WorktreeError("cannot stage verified task changes")
        committed = _git(
            self.path,
            "-c",
            "user.name=AIFLOW Controller",
            "-c",
            "user.email=aiflow@example.invalid",
            "commit",
            "-m",
            message,
        )
        if committed.returncode:
            raise WorktreeError(
                f"cannot commit verified task: {committed.stderr.strip()}"
            )
        return _git(self.path, "rev-parse", "HEAD").stdout.strip()

    def remove(self) -> None:
        if self.path is None or not self.path.exists():
            return
        removed = _git(self.target.root, "worktree", "remove", str(self.path))
        if removed.returncode:
            raise WorktreeError(
                f"cannot retire integrated task worktree: {removed.stderr.strip()}"
            )
