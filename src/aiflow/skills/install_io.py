from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from pathlib import Path


class InstallError(RuntimeError):
    """A project installation cannot proceed without risking user files."""


def write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_bytes(path: Path, content: bytes) -> None:
    """Patchable write seam; transaction rollback deliberately uses write_atomic."""
    write_atomic(path, content)


def json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def project_config(
    root: Path, config_dir: Path, profile: str, project_id: str
) -> bytes:
    path = config_dir / "project.toml"
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8")
            payload = tomllib.loads(text)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise InstallError(f"invalid existing project config: {exc}") from exc
        if str(payload.get("project_id", "")) != project_id:
            raise InstallError("existing project config changed project identity")
        pattern = re.compile(r'^profile\s*=\s*"[^"]*"\s*$', re.MULTILINE)
        updated, count = pattern.subn(f'profile = "{profile}"', text, count=1)
        return (updated if count else updated + f'\nprofile = "{profile}"\n').encode()
    return (
        "schema_version = 1\n"
        f'project_id = "{project_id}"\n'
        f'name = "{root.name}"\n'
        f'profile = "{profile}"\n\n'
        "[commands]\n"
        "build = []\n"
        "test_focused = []\n"
        "test_regression = []\n\n"
        "[execution]\n"
        "allow_parallel_mutating_runs = false\n"
        'default_mode = "solo"\n'
        "max_wall_time_seconds = 14400\n"
        "max_idle_seconds = 900\n"
        "max_attempts_per_task = 3\n\n"
        "[gui]\n"
        'bind = "127.0.0.1"\n'
    ).encode()
