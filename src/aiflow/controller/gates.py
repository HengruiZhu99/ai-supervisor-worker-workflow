from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

from aiflow.controller.attestation import AttestationError
from aiflow.controller.tasks import project_command_group
from aiflow.integration.transaction import GateCommands


def integration_gates(
    root: Path, record: Mapping[str, Any], base_sha: str
) -> GateCommands:
    focused = tuple(tuple(command) for command in record.get("commands", []))
    regression = tuple(
        tuple(command) for command in project_command_group(root, "test_regression")
    )
    if not focused:
        raise AttestationError("integration requires a focused task gate")
    if not regression:
        raise AttestationError("integration requires a project regression gate")
    quality = (
        (
            sys.executable,
            "-m",
            "aiflow",
            "--project-root",
            ".",
            "quality",
            "check",
            "--diff-base",
            base_sha,
        ),
    )
    return GateCommands(focused=focused, regression=regression, quality=quality)
