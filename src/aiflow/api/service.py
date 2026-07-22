from __future__ import annotations

import os
import subprocess
import threading
from typing import Any

from aiflow.agents.codex import CodexAgentBackend
from aiflow.api.sse import EventBuffer
from aiflow.controller.execution import AgentBackend
from aiflow.controller.lifecycle import RunLifecycle
from aiflow.identity.context import ProjectContext
from aiflow.security.permissions import validate_orchestrated_parent
from aiflow.state.store import RevisionConflict, StateError


def _branch(context: ProjectContext) -> str:
    result = subprocess.run(
        ["git", "-C", str(context.root), "branch", "--show-current"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=3,
        check=False,
    )
    return result.stdout.strip() or "(detached)"


class ApiService:
    def __init__(
        self,
        context: ProjectContext,
        *,
        event_limit: int = 512,
        agent_backend: AgentBackend | None = None,
    ) -> None:
        self.context = context
        backend = agent_backend or CodexAgentBackend(context.root).run
        self.lifecycle = RunLifecycle(context, agent_backend=backend)
        self.events = EventBuffer(limit=event_limit)
        self._event_lock = threading.Lock()
        self._seen_runs = self._versions(self.lifecycle.list())

    @staticmethod
    def _versions(runs: list[dict[str, Any]]) -> dict[str, tuple[int, str]]:
        return {
            str(run["run_id"]): (int(run["state_revision"]), str(run["status"]))
            for run in runs
        }

    def _publish_run(self, action: str, run: dict[str, Any]) -> None:
        self.events.publish("run", {"action": action, "run": run})
        self._seen_runs[str(run["run_id"])] = (
            int(run["state_revision"]),
            str(run["status"]),
        )

    def sync_events(self) -> int:
        with self._event_lock:
            runs = self.lifecycle.list()
            current = self._versions(runs)
            changed = 0
            for run in runs:
                run_id = str(run["run_id"])
                if self._seen_runs.get(run_id) != current[run_id]:
                    self.events.publish("run", {"action": "sync", "run": run})
                    changed += 1
            for run_id in self._seen_runs.keys() - current.keys():
                self.events.publish("run", {"action": "removed", "run_id": run_id})
                changed += 1
            self._seen_runs = current
            return changed

    def project(self) -> dict[str, str]:
        return {
            "name": self.context.root.name,
            "root": str(self.context.root),
            "branch": _branch(self.context),
            **self.context.identity_fields(),
        }

    def snapshot(self) -> dict[str, Any]:
        runs = self.lifecycle.list()
        effective = (
            os.environ.get("CODEX_PERMISSION_PROFILE", "")
            .strip()
            .lower()
            .removeprefix(":")
        )
        return {
            "schema_version": 1,
            "project": self.project(),
            "default_mode": "solo",
            "parent_sandbox": effective
            if effective in {"read-only", "workspace-write"}
            else "",
            "runs": runs,
            "event_cursor": self.events.replay("").events[-1].event_id
            if self.events.replay("").events
            else 0,
        }

    def _identity(self, payload: dict[str, Any], *, required: bool = True) -> None:
        checkout_id = str(payload.get("checkout_id", ""))
        if required and not checkout_id:
            raise RevisionConflict(
                "checkout_id is required for an existing-run mutation"
            )
        if checkout_id and checkout_id != self.context.checkout_id:
            raise RevisionConflict(
                "mutation checkout identity does not match this server"
            )

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._identity(payload, required=True)
        mode = str(payload.get("mode", "solo"))
        validate_orchestrated_parent(mode, str(payload.get("parent_sandbox", "")))
        result = self.lifecycle.start(
            mode=mode,
            objective=str(payload.get("objective", "")),
            acceptance_ids=tuple(
                str(value) for value in payload.get("acceptance_ids", [])
            ),
            allowed_scope=tuple(
                str(value) for value in payload.get("allowed_scope", [])
            ),
        )
        self._publish_run("start", result)
        return result

    def mutate(
        self, run_id: str, action: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._identity(payload)
        try:
            expected = int(payload["expected_revision"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RevisionConflict("expected_revision is required") from exc
        if action == "stop":
            result = self.lifecycle.stop(run_id, expected_revision=expected)
        elif action == "resume":
            mode = str(self.lifecycle.status(run_id)["mode"])
            validate_orchestrated_parent(mode, str(payload.get("parent_sandbox", "")))
            result = self.lifecycle.resume(run_id, expected_revision=expected)
        elif action == "pause":
            result = self.lifecycle.pause(run_id, expected_revision=expected)
        elif action == "handoff":
            result = self.lifecycle.handoff(run_id, expected_revision=expected)
        else:
            raise StateError(f"unsupported named action: {action}")
        self._publish_run(action, result)
        return result
