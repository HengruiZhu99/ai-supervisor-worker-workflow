from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Iterator

from aiflow.state.atomic import atomic_write_json, read_json, signed, verify_signed
from aiflow.state.errors import (
    AmbiguousLease,
    LeaseConflict,
    StateCorruption,
    StateError,
)
from aiflow.state.identifiers import SAFE_ID

if TYPE_CHECKING:
    from aiflow.state.store import RunStore


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_controller(store: "RunStore", controller_id: str) -> None:
    if not controller_id or not store.lease_file.exists():
        raise LeaseConflict("canonical mutation requires an active controller lease")
    lease = read_json(store.lease_file)
    try:
        verify_signed(lease, "controller lease")
    except ValueError as exc:
        raise StateCorruption(str(exc)) from exc
    if lease.get("controller_id") != controller_id:
        raise LeaseConflict("controller ID does not own the active lease")
    if _parse_time(str(lease["expires_at"])) <= datetime.now(timezone.utc):
        raise LeaseConflict("controller lease has expired")
    identities = store.context.identity_fields(store.run_id)
    if any(lease.get(key) != expected for key, expected in identities.items()):
        raise LeaseConflict("controller lease identity does not match this run")


@contextmanager
def guard(store: "RunStore") -> Iterator[None]:
    if store.runtime.is_symlink():
        raise LeaseConflict("runtime directory cannot be a symlink")
    store.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(store.runtime, 0o700)
    try:
        store.lease_lock.mkdir()
    except FileExistsError as exc:
        raise LeaseConflict("controller lease claim is already in progress") from exc
    try:
        yield
    finally:
        store.lease_lock.rmdir()


def claim_controller(
    store: "RunStore",
    controller_id: str,
    *,
    host_id: str,
    boot_id: str,
    pid: int,
    process_start_time: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    if not all(SAFE_ID.fullmatch(value) for value in (controller_id, host_id, boot_id)):
        raise StateError("invalid controller, host, or boot identity")
    with guard(store):
        _clear_expired(store, host_id=host_id, boot_id=boot_id)
        now = datetime.now(timezone.utc)
        lease = signed(
            {
                "schema_version": 1,
                **store.context.identity_fields(store.run_id),
                "controller_id": controller_id,
                "host_id": host_id,
                "boot_id": boot_id,
                "pid": pid,
                "process_start_time": process_start_time,
                "mode": store.read_run()["mode"],
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "heartbeat_at": now.isoformat().replace("+00:00", "Z"),
                "expires_at": (now + timedelta(seconds=ttl_seconds))
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
        descriptor = os.open(
            store.lease_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(lease, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return lease


def _clear_expired(store: "RunStore", *, host_id: str, boot_id: str) -> None:
    if not store.lease_file.exists():
        return
    current = read_json(store.lease_file)
    if _parse_time(str(current["expires_at"])) > datetime.now(timezone.utc):
        raise LeaseConflict(
            f"run is owned by controller {current.get('controller_id')}"
        )
    if current.get("host_id") != host_id or current.get("boot_id") != boot_id:
        raise AmbiguousLease(
            "expired lease belongs to another host/boot; reconcile explicitly"
        )
    if store._owner_is_live(current):
        raise LeaseConflict(
            "expired lease still belongs to the live controller process"
        )
    store.lease_file.unlink()


def heartbeat_controller(
    store: "RunStore", controller_id: str, *, ttl_seconds: int
) -> dict[str, Any]:
    if ttl_seconds <= 0:
        raise StateError("controller heartbeat TTL must be positive")
    with guard(store):
        lease = read_json(store.lease_file)
        verify_signed(lease, "controller lease")
        if lease.get("controller_id") != controller_id:
            raise LeaseConflict("only the live owning controller may heartbeat")
        if not store._owner_is_live(lease):
            raise LeaseConflict("controller process identity is no longer live")
        now = datetime.now(timezone.utc)
        updated = dict(lease)
        updated.pop("checksum", None)
        updated["heartbeat_at"] = now.isoformat().replace("+00:00", "Z")
        updated["expires_at"] = (
            (now + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z")
        )
        atomic_write_json(store.lease_file, signed(updated))
        return read_json(store.lease_file)


def release_controller(store: "RunStore", controller_id: str) -> None:
    with guard(store):
        current = read_json(store.lease_file)
        if current.get("controller_id") != controller_id:
            raise LeaseConflict("only the owning controller may release the lease")
        store.lease_file.unlink()
