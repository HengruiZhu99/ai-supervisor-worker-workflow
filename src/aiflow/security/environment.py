from __future__ import annotations

import os
from typing import Mapping


INJECTABLE_AIFLOW_KEYS = {
    "AIFLOW_PROJECT_ID",
    "AIFLOW_CHECKOUT_ID",
    "AIFLOW_WORKTREE_ID",
    "AIFLOW_RUN_ID",
    "AIFLOW_TASK_ID",
    "AIFLOW_MODE",
    "AIFLOW_PROJECT_ROOT",
    "AIFLOW_WORKTREE_ROOT",
    "AIFLOW_INBOX",
    "AIFLOW_EVIDENCE_DIR",
}


def scrub_environment(
    source: Mapping[str, str] | None = None, *, injected: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Remove inherited AIFLOW context and inject only controller-validated values."""
    original = os.environ if source is None else source
    cleaned = {str(key): str(value) for key, value in original.items() if not key.startswith("AIFLOW_")}
    for key, value in (injected or {}).items():
        if key not in INJECTABLE_AIFLOW_KEYS:
            raise ValueError(f"unsupported AIFLOW environment key: {key}")
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ValueError(f"invalid AIFLOW environment value for {key}")
        cleaned[key] = value
    return cleaned
