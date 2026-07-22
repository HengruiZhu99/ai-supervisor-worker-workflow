from __future__ import annotations

import subprocess
from typing import Any

from aiflow.api.sse import EventBuffer
from aiflow.identity.context import ProjectContext
from aiflow.controller.lifecycle import RunLifecycle
from aiflow.state.store import RevisionConflict, StateError
from aiflow.security.permissions import validate_orchestrated_parent


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
    def __init__(self, context: ProjectContext, *, event_limit: int = 512) -> None:
        self.context = context
        self.lifecycle = RunLifecycle(context)
        self.events = EventBuffer(limit=event_limit)

    def project(self) -> dict[str, str]:
        return {
            "name": self.context.root.name,
            "root": str(self.context.root),
            "branch": _branch(self.context),
            **self.context.identity_fields(),
        }

    def snapshot(self) -> dict[str, Any]:
        runs = self.lifecycle.list()
        return {
            "schema_version": 1,
            "project": self.project(),
            "default_mode": "solo",
            "runs": runs,
            "event_cursor": self.events.replay("").events[-1].event_id
            if self.events.replay("").events
            else 0,
        }

    def _identity(self, payload: dict[str, Any], *, required: bool = True) -> None:
        checkout_id = str(payload.get("checkout_id", ""))
        if required and not checkout_id:
            raise RevisionConflict("checkout_id is required for an existing-run mutation")
        if checkout_id and checkout_id != self.context.checkout_id:
            raise RevisionConflict("mutation checkout identity does not match this server")

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._identity(payload, required=True)
        mode = str(payload.get("mode", "solo"))
        validate_orchestrated_parent(mode, str(payload.get("parent_sandbox", "")))
        result = self.lifecycle.start(
            mode=mode,
            objective=str(payload.get("objective", "")),
            acceptance_ids=tuple(str(value) for value in payload.get("acceptance_ids", [])),
        )
        self.events.publish("run", {"action": "start", "run": result})
        return result

    def mutate(self, run_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
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
        self.events.publish("run", {"action": action, "run": result})
        return result
