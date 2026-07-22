from __future__ import annotations

import os
from typing import Mapping


class PermissionBoundaryError(ValueError):
    """The effective parent permission cannot safely host child agents."""


def _normalized(value: str) -> str:
    return value.strip().lower().removeprefix(":")


def validate_orchestrated_parent(
    mode: str,
    claimed_sandbox: str,
    *,
    env: Mapping[str, str] | None = None,
) -> None:
    if mode != "orchestrated":
        return
    values = os.environ if env is None else env
    claimed = _normalized(claimed_sandbox)
    effective = _normalized(values.get("CODEX_PERMISSION_PROFILE", ""))
    if not claimed:
        raise PermissionBoundaryError(
            "orchestrated mode requires an explicit parent permission preflight"
        )
    if effective and effective != claimed:
        raise PermissionBoundaryError(
            f"claimed parent sandbox {claimed!r} does not match effective profile {effective!r}"
        )
    selected = effective or claimed
    if selected in {"danger-full-access", "full-access", "unrestricted"}:
        raise PermissionBoundaryError(
            "orchestrated mode refuses an unrestricted parent permission profile"
        )
    if selected not in {"read-only", "workspace-write"}:
        raise PermissionBoundaryError(f"unknown effective parent permission profile: {selected}")
