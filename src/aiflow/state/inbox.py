from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from aiflow.state.atomic import atomic_write_json, read_json, verify_signed
from aiflow.state.errors import StateError


def write_once(target: Path, payload: Mapping[str, Any]) -> Path:
    if target.exists():
        try:
            existing = read_json(target)
            verify_signed(existing, "existing inbox result")
        except (OSError, ValueError) as exc:
            raise StateError(f"existing inbox result is invalid: {target}") from exc
        if existing == payload:
            return target
        raise StateError(f"inbox result conflicts with existing result: {target}")
    atomic_write_json(target, payload)
    return target
