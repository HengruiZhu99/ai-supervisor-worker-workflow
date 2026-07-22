from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from aiflow.agents.results import validate_role_result
from aiflow.agents.review import reviewers_for_risk
from aiflow.controller.attestation import (
    AttestationError,
    attest_result,
    changed_paths,
    workspace_snapshot,
)
from aiflow.controller.worktrees import TaskWorktree
from aiflow.integration.transaction import GateCommands, IntegrationTransaction
from aiflow.state.store import RunStore


InvokeAgent = Callable[[dict[str, Any]], Mapping[str, Any]]


class OrchestratedTaskRunner:
    """Run one task through bounded read-only analysis, one writer, review, and integration."""

    def __init__(
        self,
        store: RunStore,
        *,
        invoke: InvokeAgent,
        timeout: float,
    ) -> None:
        self.store = store
        self.invoke = invoke
        self.timeout = timeout

    @staticmethod
    def _capsule(
        base: Mapping[str, Any],
        context_fields: Mapping[str, str],
        *,
        action: str,
        role: str,
        workspace: Path,
    ) -> dict[str, Any]:
        return {
            **dict(base),
            **dict(context_fields),
            "action": action,
            "agent_role": role,
            "working_directory": str(workspace),
        }

    def _analyze(
        self,
        base: Mapping[str, Any],
        fields: Mapping[str, str],
        workspace: Path,
    ) -> list[dict[str, Any]]:
        before = workspace_snapshot(workspace)
        reports = []
        for role in ("codebase-mapper", "test-architect"):
            capsule = self._capsule(
                base, fields, action="analyze_task", role=role, workspace=workspace
            )
            result = dict(self.invoke(capsule))
            validate_role_result(
                result,
                identities=fields,
                task_id=str(base["task_id"]),
                role=role,
                action="analyze_task",
            )
            reports.append(result)
        if changed_paths(before, workspace_snapshot(workspace)):
            raise AttestationError("read-only analysis mutated the task worktree")
        return reports

    def _review(
        self,
        base: Mapping[str, Any],
        fields: Mapping[str, str],
        workspace: Path,
        risk: str,
    ) -> list[dict[str, Any]]:
        before = workspace_snapshot(workspace)
        reports = []
        for role in reviewers_for_risk(risk):
            if role == "cold-self-review":
                role = "engineering-reviewer"
            capsule = self._capsule(
                base, fields, action="review_task", role=role, workspace=workspace
            )
            result = dict(self.invoke(capsule))
            validate_role_result(
                result,
                identities=fields,
                task_id=str(base["task_id"]),
                role=role,
                action="review_task",
            )
            if (
                result.get("blocks_acceptance")
                or result.get("recommendation") != "accept"
            ):
                raise AttestationError(
                    f"independent reviewer {role} blocked acceptance"
                )
            reports.append(result)
        if changed_paths(before, workspace_snapshot(workspace)):
            raise AttestationError("read-only review mutated the task worktree")
        return reports

    def execute(
        self, record: Mapping[str, Any], base_capsule: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not record.get("allowed_scope"):
            raise AttestationError(
                "orchestrated writer requires an explicit allowed scope"
            )
        worktree = TaskWorktree(
            self.store.context,
            self.store.run_id,
            str(record["id"]),
            self.store.runtime,
        ).create()
        assert worktree.context is not None and worktree.path is not None
        fields = worktree.context.identity_fields(self.store.run_id)
        analyses = self._analyze(base_capsule, fields, worktree.path)
        before = workspace_snapshot(worktree.path)
        writer = self._capsule(
            base_capsule,
            fields,
            action="execute_task",
            role="implementation-worker",
            workspace=worktree.path,
        )
        result = dict(self.invoke(writer))
        validate_role_result(
            result,
            identities=fields,
            task_id=str(record["id"]),
            role="implementation-worker",
            action="execute_task",
        )
        result = attest_result(
            worktree.path,
            before=before,
            result=result,
            task=record,
            timeout=self.timeout,
            injected={f"AIFLOW_{key.upper()}": value for key, value in fields.items()},
        )
        candidate = worktree.commit(
            message=f"aiflow: {record['id']} {record['objective']}"
        )
        reviews = self._review(
            base_capsule,
            fields,
            worktree.path,
            str(record.get("risk", "normal")),
        )
        commands = tuple(tuple(command) for command in record.get("commands", []))
        integrated = IntegrationTransaction(
            self.store.context.root,
            gates=GateCommands(focused=commands),
        ).apply(candidate, method="merge", base_sha=worktree.base_sha)
        if not integrated.ok:
            raise AttestationError(f"two-phase integration failed: {integrated.reason}")
        worktree.remove()
        result["writer_worktree_id"] = fields["worktree_id"]
        result["worktree_id"] = self.store.context.worktree_id
        result["orchestration"] = {
            "analyses": analyses,
            "reviews": reviews,
            "candidate": candidate,
            "target_before": integrated.target_before,
            "target_after": integrated.target_after,
            "tested_tree": integrated.tested_tree,
            "target_tree": integrated.target_tree,
        }
        return result
