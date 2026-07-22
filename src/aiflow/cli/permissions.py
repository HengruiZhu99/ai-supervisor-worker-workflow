from __future__ import annotations

from aiflow.security.permissions import validate_orchestrated_parent
from aiflow.state.store import StateError


def permission_preflight(mode: str, parent_sandbox: str) -> None:
    try:
        validate_orchestrated_parent(mode, parent_sandbox)
    except ValueError as exc:
        raise StateError(str(exc)) from exc
