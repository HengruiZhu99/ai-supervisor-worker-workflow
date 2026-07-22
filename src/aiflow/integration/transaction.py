from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import uuid
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
    tested_tree: str = ""
    target_tree: str = ""
    recovery_path: str = ""
    evidence: tuple[str, ...] = ()


def run_command(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=1800,
    )


class IntegrationTransaction:
    def __init__(
        self,
        target: Path,
        *,
        gates: GateCommands | None = None,
        runner: Runner = run_command,
        before_apply: Callable[[], None] | None = None,
        after_apply: Callable[[], None] | None = None,
    ) -> None:
        self.target = target.resolve()
        self.gates = gates or GateCommands()
        self.runner = runner
        self.before_apply = before_apply
        self.after_apply = after_apply

    def _git(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return self.runner(["git", *args], cwd)

    def _head(self, cwd: Path) -> str:
        return self._git(cwd, "rev-parse", "HEAD").stdout.strip()

    def _tree(self, cwd: Path) -> str:
        return self._git(cwd, "rev-parse", "HEAD^{tree}").stdout.strip()

    def _result(
        self,
        ok: bool,
        reason: str,
        before: str,
        evidence=(),
        *,
        tested_tree: str = "",
        recovery_path: str = "",
    ) -> IntegrationResult:
        after = self._head(self.target) or before
        target_tree = self._tree(self.target) if after else ""
        return IntegrationResult(
            ok,
            reason,
            before,
            after,
            tested_tree,
            target_tree,
            recovery_path,
            tuple(evidence),
        )

    @staticmethod
    def _valid_ref(value: str, *, optional: bool = False) -> bool:
        if optional and not value:
            return True
        return bool(
            value
            and not value.startswith("-")
            and not value.endswith((".", "/", ".lock"))
            and not any(token in value for token in ("..", "@{", "\\", "//"))
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}", value)
        )

    def _candidate_checks(self, candidate: str, base_sha: str, captured: str) -> str:
        if self._git(self.target, "status", "--porcelain").stdout.strip():
            return "dirty target"
        if self._git(
            self.target, "cat-file", "-e", f"{candidate}^{{commit}}"
        ).returncode:
            return "candidate does not exist"
        if (
            self._git(
                self.target, "merge-base", "--is-ancestor", candidate, captured
            ).returncode
            == 0
        ):
            return "duplicate integration"
        if (
            base_sha
            and self._git(
                self.target, "merge-base", "--is-ancestor", base_sha, candidate
            ).returncode
        ):
            return "candidate base mismatch"
        return ""

    def _prepare(
        self, worktree: Path, candidate: str, method: str, base_sha: str
    ) -> str:
        command: tuple[str, ...]
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
                self.target,
                "merge",
                "--no-ff",
                candidate,
                "-m",
                f"integrate {candidate[:12]}",
            )
        else:
            result = self._git(self.target, "cherry-pick", f"{base_sha}..{candidate}")
        return result.returncode == 0

    def _rollback_failed_apply(self, method: str, captured: str) -> None:
        operation = "merge" if method == "merge" else "cherry-pick"
        self._git(self.target, operation, "--abort")
        if self._head(self.target) != captured:
            raise RuntimeError("target changed during failed final apply")

    def _preserve_untracked(self) -> str:
        result = self._git(
            self.target, "ls-files", "--others", "--exclude-standard", "-z"
        )
        paths = [value for value in result.stdout.split("\0") if value]
        if not paths:
            return ""
        common = self._git(self.target, "rev-parse", "--git-common-dir").stdout.strip()
        common_path = (
            Path(common) if Path(common).is_absolute() else self.target / common
        )
        recovery = common_path.resolve() / "aiflow" / "recovery" / str(uuid.uuid4())
        for relative in paths:
            source = (self.target / relative).resolve()
            if self.target not in source.parents or not source.exists():
                continue
            destination = recovery / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), destination)
        return str(recovery)

    def _rollback_applied(self, captured: str) -> str:
        recovery = self._preserve_untracked()
        current = self._head(self.target)
        updated = self._git(self.target, "update-ref", "HEAD", captured, current)
        restored = self._git(self.target, "read-tree", "--reset", "-u", captured)
        if (
            updated.returncode
            or restored.returncode
            or self._git(self.target, "status", "--porcelain").stdout.strip()
        ):
            raise RuntimeError(
                "failed integration could not restore the captured target"
            )
        return recovery

    def _test_candidate(
        self,
        worktree: Path,
        candidate: str,
        method: str,
        base_sha: str,
        captured: str,
    ) -> tuple[str, str, list[str]]:
        failure = self._candidate_checks(candidate, base_sha, captured)
        if failure:
            return failure, "", []
        failure = self._prepare(worktree, candidate, method, base_sha)
        if failure:
            return failure, "", []
        tested_tree = self._git(worktree, "write-tree").stdout.strip()
        if not tested_tree:
            return "cannot identify tested integration tree", "", []
        failure, evidence = self._run_gates(worktree)
        return failure, tested_tree, evidence

    def _finalize(
        self,
        candidate: str,
        method: str,
        base_sha: str,
        captured: str,
        tested_tree: str,
        evidence: list[str],
    ) -> IntegrationResult:
        try:
            if not self._apply_target(candidate, method, base_sha):
                self._rollback_failed_apply(method, captured)
                return self._result(
                    False,
                    "final apply failed",
                    captured,
                    evidence,
                    tested_tree=tested_tree,
                )
            if self.after_apply:
                self.after_apply()
        except KeyboardInterrupt:
            recovery = self._rollback_applied(captured)
            return self._result(
                False,
                "user interruption",
                captured,
                evidence,
                tested_tree=tested_tree,
                recovery_path=recovery,
            )
        dirty = self._git(self.target, "status", "--porcelain").stdout.strip()
        target_tree = self._tree(self.target)
        if dirty or target_tree != tested_tree:
            reason = (
                "post-apply target dirty"
                if dirty
                else "applied tree differs from tested tree"
            )
            recovery = self._rollback_applied(captured)
            return self._result(
                False,
                reason,
                captured,
                evidence,
                tested_tree=tested_tree,
                recovery_path=recovery,
            )
        return self._result(
            True, "integrated", captured, evidence, tested_tree=tested_tree
        )

    def apply(
        self, candidate: str, *, method: str, base_sha: str = ""
    ) -> IntegrationResult:
        if not self._valid_ref(candidate):
            return IntegrationResult(False, "invalid candidate ref", "", "")
        if not self._valid_ref(base_sha, optional=True):
            return IntegrationResult(False, "invalid base ref", "", "")
        with tempfile.TemporaryDirectory(prefix="aiflow-integrate-") as container:
            worktree = Path(container) / "integration-worktree"
            # Capture HEAD by materializing an integration worktree first. This is the
            # first Git mutation and never changes the target branch or target files.
            added = self._git(
                self.target, "worktree", "add", "--detach", str(worktree), "HEAD"
            )
            if added.returncode:
                return IntegrationResult(
                    False, "integration worktree creation failed", "", ""
                )
            try:
                captured = self._head(worktree)
                failure, tested_tree, evidence = self._test_candidate(
                    worktree, candidate, method, base_sha, captured
                )
                if failure:
                    return self._result(
                        False, failure, captured, evidence, tested_tree=tested_tree
                    )
                try:
                    if self.before_apply:
                        self.before_apply()
                except KeyboardInterrupt:
                    return self._result(False, "user interruption", captured, evidence)
                if self._head(self.target) != captured:
                    return self._result(
                        False, "target HEAD changed", captured, evidence
                    )
                return self._finalize(
                    candidate, method, base_sha, captured, tested_tree, evidence
                )
            finally:
                self._git(self.target, "worktree", "remove", "--force", str(worktree))
