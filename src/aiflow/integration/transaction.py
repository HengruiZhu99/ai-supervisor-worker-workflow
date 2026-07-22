from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


Command = tuple[str, ...]
Runner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class GateCommands:
    focused: tuple[Command, ...] = ()
    regression: tuple[Command, ...] = ()
    quality: tuple[Command, ...] = ()


@dataclass(frozen=True)
class IntegrationResult:
    ok: bool
    reason: str
    target_before: str
    target_after: str
    evidence: tuple[str, ...] = ()


def run_command(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False, timeout=1800,
    )


class IntegrationTransaction:
    def __init__(
        self,
        target: Path,
        *,
        gates: GateCommands | None = None,
        runner: Runner = run_command,
        before_apply: Callable[[], None] | None = None,
    ) -> None:
        self.target = target.resolve()
        self.gates = gates or GateCommands()
        self.runner = runner
        self.before_apply = before_apply

    def _git(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return self.runner(["git", *args], cwd)

    def _head(self, cwd: Path) -> str:
        return self._git(cwd, "rev-parse", "HEAD").stdout.strip()

    def _result(self, ok: bool, reason: str, before: str, evidence=()) -> IntegrationResult:
        after = self._head(self.target) or before
        return IntegrationResult(ok, reason, before, after, tuple(evidence))

    def _candidate_checks(self, candidate: str, base_sha: str, captured: str) -> str:
        if self._git(self.target, "status", "--porcelain").stdout.strip():
            return "dirty target"
        if self._git(self.target, "cat-file", "-e", f"{candidate}^{{commit}}").returncode:
            return "candidate does not exist"
        if self._git(self.target, "merge-base", "--is-ancestor", candidate, captured).returncode == 0:
            return "duplicate integration"
        if base_sha and self._git(
            self.target, "merge-base", "--is-ancestor", base_sha, candidate
        ).returncode:
            return "candidate base mismatch"
        return ""

    def _prepare(self, worktree: Path, candidate: str, method: str, base_sha: str) -> str:
        if method == "merge":
            command = ("merge", "--no-commit", "--no-ff", candidate)
        elif method == "cherry-pick":
            if not base_sha:
                return "cherry-pick requires base SHA"
            command = ("cherry-pick", "--no-commit", f"{base_sha}..{candidate}")
        else:
            return f"unsupported integration method: {method}"
        result = self._git(worktree, *command)
        return "" if result.returncode == 0 else "integration conflict"

    def _run_gates(self, worktree: Path) -> tuple[str, list[str]]:
        evidence: list[str] = []
        for label in ("focused", "regression", "quality"):
            for command in getattr(self.gates, label):
                result = self.runner(list(command), worktree)
                evidence.append(f"{label}:{' '.join(command)}:{result.returncode}")
                if result.returncode:
                    return f"{label} gate failed", evidence
        return "", evidence

    def _apply_target(self, candidate: str, method: str, base_sha: str) -> bool:
        if method == "merge":
            result = self._git(
                self.target, "merge", "--no-ff", candidate,
                "-m", f"integrate {candidate[:12]}",
            )
        else:
            result = self._git(self.target, "cherry-pick", f"{base_sha}..{candidate}")
        return result.returncode == 0

    def _rollback_failed_apply(self, method: str, captured: str) -> None:
        operation = "merge" if method == "merge" else "cherry-pick"
        self._git(self.target, operation, "--abort")
        if self._head(self.target) != captured:
            raise RuntimeError("target changed during failed final apply")

    def apply(self, candidate: str, *, method: str, base_sha: str = "") -> IntegrationResult:
        with tempfile.TemporaryDirectory(prefix="aiflow-integrate-") as container:
            worktree = Path(container) / "integration-worktree"
            # Capture HEAD by materializing an integration worktree first. This is the
            # first Git mutation and never changes the target branch or target files.
            added = self._git(self.target, "worktree", "add", "--detach", str(worktree), "HEAD")
            if added.returncode:
                return IntegrationResult(False, "integration worktree creation failed", "", "")
            try:
                captured = self._head(worktree)
                failure = self._candidate_checks(candidate, base_sha, captured)
                if failure:
                    return self._result(False, failure, captured)
                failure = self._prepare(worktree, candidate, method, base_sha)
                if failure:
                    return self._result(False, failure, captured)
                failure, evidence = self._run_gates(worktree)
                if failure:
                    return self._result(False, failure, captured, evidence)
                try:
                    if self.before_apply:
                        self.before_apply()
                except KeyboardInterrupt:
                    return self._result(False, "user interruption", captured, evidence)
                if self._head(self.target) != captured:
                    return self._result(False, "target HEAD changed", captured, evidence)
                if not self._apply_target(candidate, method, base_sha):
                    self._rollback_failed_apply(method, captured)
                    return self._result(False, "final apply failed", captured, evidence)
                if self._git(self.target, "status", "--porcelain").stdout.strip():
                    raise RuntimeError("successful integration left a dirty target")
                return self._result(True, "integrated", captured, evidence)
            finally:
                self._git(self.target, "worktree", "remove", "--force", str(worktree))
