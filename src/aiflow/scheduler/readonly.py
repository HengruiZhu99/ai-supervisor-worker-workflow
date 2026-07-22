from __future__ import annotations

import re
import subprocess
import time
from typing import Callable


class SchedulerError(RuntimeError):
    """A scheduler request is unsupported or unsafe."""


STATE_MAP = {
    "R": "RUNNING",
    "Q": "QUEUED",
    "H": "HELD",
    "C": "COMPLETED",
    "E": "EXITING",
}
SAFE_USER = re.compile(r"^[A-Za-z0-9._-]+$")


def _default_runner(command: tuple[str, ...]) -> str:
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise SchedulerError(result.stderr.strip() or "scheduler query failed")
    return result.stdout


class ReadOnlyScheduler:
    def __init__(
        self,
        kind: str,
        *,
        min_interval: float = 5,
        runner: Callable[[tuple[str, ...]], str] | None = None,
    ) -> None:
        if kind not in {"slurm", "pbs"}:
            raise SchedulerError(f"unsupported scheduler: {kind}")
        self.kind = kind
        self.min_interval = max(1.0, min_interval)
        self.runner = runner or _default_runner
        self._cached_at = float("-inf")
        self._cached_user = ""
        self._cached: list[dict[str, str]] = []

    def command(self, *, user: str) -> tuple[str, ...]:
        if not SAFE_USER.fullmatch(user):
            raise SchedulerError("scheduler user contains unsafe characters")
        if self.kind == "slurm":
            return (
                "squeue",
                "--noheader",
                "--user",
                user,
                "--format",
                "%i|%T|%P|%M|%R|%j",
            )
        return ("qstat", "-u", user, "-f", "-F", "dsv")

    def validate_command(self, command: tuple[str, ...]) -> None:
        allowed = "squeue" if self.kind == "slurm" else "qstat"
        if not command or command[0] != allowed:
            raise SchedulerError("scheduler monitoring is read-only")

    def parse(self, output: str) -> list[dict[str, str]]:
        return (
            self._parse_slurm(output)
            if self.kind == "slurm"
            else self._parse_pbs(output)
        )

    def _parse_slurm(self, output: str) -> list[dict[str, str]]:
        rows = []
        for line in output.splitlines():
            fields = line.split("|", 5)
            if len(fields) != 6:
                continue
            job_id, state, queue, elapsed, node, name = fields
            rows.append(
                {
                    "job_id": job_id,
                    "name": name,
                    "state": state,
                    "queue": queue,
                    "elapsed": elapsed,
                    "reason_or_node": node,
                }
            )
        return rows

    def _parse_pbs(self, output: str) -> list[dict[str, str]]:
        rows = []
        for line in output.splitlines():
            fields = line.split("|", 5)
            if len(fields) != 6:
                continue
            job_id, name, user, elapsed, state, queue = fields
            rows.append(
                {
                    "job_id": job_id,
                    "name": name,
                    "user": user,
                    "state": STATE_MAP.get(state, state),
                    "queue": queue,
                    "elapsed": elapsed,
                }
            )
        return rows

    def snapshot(self, *, user: str, now: float | None = None) -> list[dict[str, str]]:
        instant = time.monotonic() if now is None else now
        if user == self._cached_user and instant - self._cached_at < self.min_interval:
            return [dict(row) for row in self._cached]
        command = self.command(user=user)
        self.validate_command(command)
        self._cached = self.parse(self.runner(command))
        self._cached_at = instant
        self._cached_user = user
        return [dict(row) for row in self._cached]
