from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from aiflow.state.atomic import atomic_write_json, read_json, signed, verify_signed
from aiflow.state.errors import StateError
from aiflow.state.ownership import local_process_identity, owner_is_live
from aiflow.state.time import utc_now


def _recover(lock: Path, owner_file: Path, *, orphan_grace: float) -> bool:
    try:
        owner = read_json(owner_file)
        verify_signed(owner, "owned directory lock")
    except FileNotFoundError:
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            return False
        if age < orphan_grace:
            return False
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    else:
        if owner_is_live(owner):
            return False
    try:
        owner_file.unlink(missing_ok=True)
        lock.rmdir()
    except OSError:
        return False
    return True


@contextmanager
def owned_directory_lock(
    path: Path, *, timeout: float = 1.0, orphan_grace: float = 1.0
) -> Iterator[None]:
    owner_file = path / "OWNER.json"
    deadline = time.monotonic() + timeout
    owner = signed(
        {
            "schema_version": 1,
            **local_process_identity(),
            "created_at": utc_now(),
        }
    )
    while True:
        try:
            path.mkdir()
            atomic_write_json(owner_file, owner)
            break
        except FileExistsError:
            if _recover(path, owner_file, orphan_grace=orphan_grace):
                continue
            if time.monotonic() >= deadline:
                raise StateError(f"owned directory lock is busy: {path}")
            time.sleep(0.01)
    try:
        yield
    finally:
        try:
            current = read_json(owner_file)
            if current.get("checksum") != owner.get("checksum"):
                raise StateError(f"owned directory lock changed owner: {path}")
            owner_file.unlink()
            path.rmdir()
        except OSError as exc:
            raise StateError(
                f"cannot release owned directory lock {path}: {exc}"
            ) from exc
