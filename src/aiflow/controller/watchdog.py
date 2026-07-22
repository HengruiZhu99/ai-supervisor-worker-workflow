from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Mapping


ACTIONABLE = {
    "process_death",
    "lease_expiry",
    "stale_heartbeat",
    "transaction_recovery",
    "low_disk",
    "low_inodes",
    "no_progress",
    "timeout",
}


class DeterministicWatchdog:
    def __init__(
        self, *, diagnose: Callable[[dict[str, object]], Any] | None = None
    ) -> None:
        self.diagnose = diagnose
        self._seen: set[str] = set()

    @staticmethod
    def signature(event: Mapping[str, object]) -> str:
        stable = json.dumps(
            dict(event), sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(stable.encode()).hexdigest()

    def observe(self, event: Mapping[str, object]) -> str:
        if event.get("kind") not in ACTIONABLE:
            return "IGNORED"
        signature = self.signature(event)
        if signature in self._seen:
            return "DUPLICATE_EVENT"
        self._seen.add(signature)
        if self.diagnose is None:
            return "ACTION_REQUIRED"
        capsule: dict[str, object] = {"signature": signature, "event": dict(event)}
        self.diagnose(capsule)
        return "DIAGNOSED"

    @staticmethod
    def resource_preflight(
        path: Path, *, minimum_bytes: int = 50_000_000
    ) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        usage = shutil.disk_usage(path)
        if usage.free < minimum_bytes:
            events.append({"kind": "low_disk", "path": str(path), "free": usage.free})
        stat = os.statvfs(path)
        if stat.f_favail < 100:
            events.append(
                {"kind": "low_inodes", "path": str(path), "free": stat.f_favail}
            )
        return events
