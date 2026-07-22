from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from aiflow.identity.context import ProjectContext, new_run_id, runtime_path
from aiflow.state.atomic import atomic_write_json, read_json, signed, verify_signed
from aiflow.state.events import append_event, make_event, read_events
from aiflow.state import ownership


class StateError(RuntimeError):
    """Base state protocol error."""


class RevisionConflict(StateError):
    """A mutation used a stale state revision."""


class LeaseConflict(StateError):
    """Another controller owns the run."""


class AmbiguousLease(LeaseConflict):
    """A cross-host lease cannot be safely taken over."""


class StateCorruption(StateError):
    """Snapshots, intents, or events disagree."""


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class RunStore:
    def __init__(self, context: ProjectContext, run_id: str, *, runtime_env=None):
        if not SAFE_ID.fullmatch(run_id):
            raise StateError(f"invalid run ID: {run_id!r}")
        self.context = context
        self.run_id = run_id
        self.path = context.state_root / "runs" / run_id
        self.runtime = runtime_path(context, run_id, env=runtime_env)
        self.run_file = self.path / "RUN.json"
        self.tasks_file = self.path / "TASKS.json"
        self.events_file = self.path / "EVENTS.jsonl"
        self.intent_file = self.path / "TRANSACTION.json"
        self.committed_file = self.path / "TRANSACTION.committed.json"
        self.lock_dir = self.path / ".transaction.lock"
        self.lock_owner_file = self.lock_dir / "OWNER.json"
        self.lease_file = self.runtime / "CONTROLLER_LEASE.json"
        self.lease_lock = self.runtime / ".lease.lock"

    @classmethod
    def create(
        cls, context: ProjectContext, *, mode: str, run_id: str | None = None,
        runtime_env=None,
    ) -> "RunStore":
        store = cls(context, run_id or new_run_id(), runtime_env=runtime_env)
        try:
            store.path.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise StateError(f"run already exists: {store.run_id}") from exc
        for directory in ("context", "inbox", "evidence"):
            (store.path / directory).mkdir()
        now = utc_now()
        identities = context.identity_fields(store.run_id)
        run = signed({
            "schema_version": 1,
            "state_revision": 0,
            **identities,
            "controller_id": "",
            "mode": mode,
            "status": "CREATED",
            "created_at": now,
            "updated_at": now,
        })
        tasks = signed({
            "schema_version": 1,
            "state_revision": 0,
            **identities,
            "tasks": [],
            "updated_at": now,
        })
        atomic_write_json(store.run_file, run)
        atomic_write_json(store.tasks_file, tasks)
        event = make_event(
            sequence=1, state_revision=0, event_type="run_created",
            identities=identities, data={"mode": mode}, occurred_at=now,
            previous_checksum="",
        )
        append_event(store.events_file, event)
        store.verify()
        return store

    @contextmanager
    def _lock(self, *, timeout: float = 5.0) -> Iterator[None]:
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.lock_dir.mkdir()
                atomic_write_json(
                    self.lock_owner_file,
                    signed({"schema_version": 1, **self.local_process_identity(), "created_at": utc_now()}),
                )
                break
            except FileExistsError:
                if self._recover_stale_transaction_lock():
                    continue
                if time.monotonic() >= deadline:
                    raise StateError(f"run transaction lock is busy: {self.lock_dir}")
                time.sleep(0.01)
        try:
            yield
        finally:
            try:
                self.lock_owner_file.unlink(missing_ok=True)
                self.lock_dir.rmdir()
            except OSError as exc:
                raise StateError(f"cannot release transaction lock {self.lock_dir}: {exc}") from exc

    @staticmethod
    def local_host_id() -> str:
        return ownership.local_host_id()

    @staticmethod
    def local_boot_id() -> str:
        return ownership.local_boot_id()

    @staticmethod
    def _process_start(pid: int) -> str:
        return ownership.process_start(pid)

    @classmethod
    def local_process_identity(cls) -> dict[str, Any]:
        return ownership.local_process_identity()

    @classmethod
    def _owner_is_live(cls, owner: Mapping[str, Any]) -> bool:
        return ownership.owner_is_live(owner)

    def _recover_stale_transaction_lock(self) -> bool:
        try:
            owner = read_json(self.lock_owner_file)
            verify_signed(owner, "transaction lock owner")
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return False
        if owner.get("host_id") != self.local_host_id() or owner.get("boot_id") != self.local_boot_id():
            return False
        if self._owner_is_live(owner):
            return False
        try:
            self.lock_owner_file.unlink()
            self.lock_dir.rmdir()
        except OSError:
            return False
        return True

    def read_run(self) -> dict[str, Any]:
        payload = read_json(self.run_file)
        try:
            verify_signed(payload, "RUN.json")
        except ValueError as exc:
            raise StateCorruption(str(exc)) from exc
        return payload

    def read_tasks(self) -> dict[str, Any]:
        payload = read_json(self.tasks_file)
        try:
            verify_signed(payload, "TASKS.json")
        except ValueError as exc:
            raise StateCorruption(str(exc)) from exc
        return payload

    def read_events(self) -> list[dict[str, Any]]:
        try:
            return read_events(self.events_file)
        except ValueError as exc:
            raise StateCorruption(str(exc)) from exc

    def _build_intent(
        self, expected_revision: int, updates: Mapping[str, Any], event_type: str,
        *, task_updates: Mapping[str, Any] | None = None,
        evidence: list[str] | None = None, controller_id: str,
    ) -> dict[str, Any]:
        run, tasks = self.read_run(), self.read_tasks()
        current = int(run["state_revision"])
        if int(tasks["state_revision"]) != current:
            raise StateCorruption("RUN.json and TASKS.json revisions disagree")
        if current != expected_revision:
            raise RevisionConflict(f"stale revision {expected_revision}; current revision is {current}")
        next_revision = current + 1
        now = utc_now()
        next_run = dict(run)
        next_run.pop("checksum", None)
        protected = {"schema_version", "state_revision", "project_id", "checkout_id", "worktree_id", "run_id"}
        if protected.intersection(updates):
            raise StateError("identity/schema/revision fields cannot be mutated")
        next_run.update(dict(updates))
        next_run.update({
            "state_revision": next_revision,
            "controller_id": controller_id,
            "updated_at": now,
        })
        next_run = signed(next_run)
        next_tasks = dict(tasks)
        next_tasks.pop("checksum", None)
        if task_updates:
            if protected.intersection(task_updates):
                raise StateError("task snapshot identity/schema/revision fields cannot be mutated")
            next_tasks.update(dict(task_updates))
        next_tasks.update({"state_revision": next_revision, "updated_at": now})
        next_tasks = signed(next_tasks)
        events = self.read_events()
        event = make_event(
            sequence=len(events) + 1, state_revision=next_revision,
            event_type=event_type, identities=self.context.identity_fields(self.run_id),
            data={
                "updates": dict(updates),
                "task_updates": dict(task_updates or {}),
                "evidence": list(evidence or []),
                "controller_id": controller_id,
            },
            occurred_at=now, previous_checksum=events[-1]["checksum"] if events else "",
        )
        return signed({
            "schema_version": 1,
            "phase": "prepared",
            "base_revision": current,
            "next_revision": next_revision,
            "run": next_run,
            "tasks": next_tasks,
            "event": event,
            "prepared_at": now,
        })

    def prepare_transition(
        self, expected_revision: int, updates: Mapping[str, Any], *, event_type: str,
        task_updates: Mapping[str, Any] | None = None,
        evidence: list[str] | None = None, controller_id: str = "",
    ) -> dict[str, Any]:
        with self._lock():
            self._recover_locked()
            self._validate_controller(controller_id)
            intent = self._build_intent(
                expected_revision, updates, event_type,
                task_updates=task_updates, evidence=evidence, controller_id=controller_id,
            )
            atomic_write_json(self.intent_file, intent)
            return intent

    def apply_prepared_snapshot(
        self, intent: Mapping[str, Any], *, append_event: bool = True
    ) -> None:
        verify_signed(intent, "transaction intent")
        atomic_write_json(self.run_file, intent["run"])
        atomic_write_json(self.tasks_file, intent["tasks"])
        if append_event:
            self._append_intent_event(intent)

    def _append_intent_event(self, intent: Mapping[str, Any]) -> None:
        event = intent["event"]
        events = self.read_events()
        sequence = int(event["sequence"])
        if sequence <= len(events):
            if events[sequence - 1].get("checksum") != event.get("checksum"):
                raise StateCorruption("prepared event conflicts with existing event")
            return
        try:
            append_event(self.events_file, event)
        except ValueError as exc:
            raise StateCorruption(str(exc)) from exc

    def _finalize_intent(self, intent: Mapping[str, Any]) -> None:
        atomic_write_json(self.committed_file, signed({
            "schema_version": 1,
            "intent_checksum": intent["checksum"],
            "next_revision": intent["next_revision"],
            "committed_at": utc_now(),
        }))
        self.intent_file.unlink(missing_ok=True)

    def transition(
        self, expected_revision: int, updates: Mapping[str, Any], *, event_type: str,
        task_updates: Mapping[str, Any] | None = None,
        evidence: list[str] | None = None, controller_id: str = "",
    ) -> dict[str, Any]:
        with self._lock():
            self._recover_locked()
            self._validate_controller(controller_id)
            intent = self._build_intent(
                expected_revision, updates, event_type,
                task_updates=task_updates, evidence=evidence, controller_id=controller_id,
            )
            atomic_write_json(self.intent_file, intent)
            self.apply_prepared_snapshot(intent)
            self._finalize_intent(intent)
            self.verify()
            return self.read_run()

    def _recover_locked(self) -> str:
        if not self.intent_file.exists():
            return "clean"
        intent = read_json(self.intent_file)
        try:
            verify_signed(intent, "transaction intent")
        except ValueError as exc:
            raise StateCorruption(str(exc)) from exc
        if intent.get("kind") == "schema_migration":
            self._apply_migration_intent(intent)
            return "rolled_forward_migration"
        current = int(self.read_run()["state_revision"])
        expected = {int(intent["base_revision"]), int(intent["next_revision"])}
        if current not in expected:
            raise StateCorruption("snapshot revision is unrelated to prepared transaction")
        self.apply_prepared_snapshot(intent)
        self._finalize_intent(intent)
        self.verify()
        return "rolled_forward"

    def _apply_migration_intent(self, intent: Mapping[str, Any]) -> None:
        atomic_write_json(self.run_file, intent["run"])
        atomic_write_json(self.tasks_file, intent["tasks"])
        atomic_write_json(
            self.committed_file,
            signed(
                {
                    "schema_version": 1,
                    "kind": "schema_migration",
                    "intent_checksum": intent["checksum"],
                    "committed_at": utc_now(),
                }
            ),
        )
        self.intent_file.unlink(missing_ok=True)
        self.verify()

    def recover(self) -> str:
        with self._lock():
            return self._recover_locked()

    def verify(self) -> None:
        run, tasks, events = self.read_run(), self.read_tasks(), self.read_events()
        if run["state_revision"] != tasks["state_revision"]:
            raise StateCorruption("snapshot revisions disagree")
        identities = self.context.identity_fields(self.run_id)
        for payload in (run, tasks):
            for key, expected in identities.items():
                if payload.get(key) != expected:
                    raise StateCorruption(f"{key} mismatch in snapshot")
        if not events or events[-1]["state_revision"] != run["state_revision"]:
            raise StateCorruption("event history does not reach snapshot revision")

    def _validate_controller(self, controller_id: str) -> None:
        if not controller_id or not self.lease_file.exists():
            raise LeaseConflict("canonical mutation requires an active controller lease")
        lease = read_json(self.lease_file)
        try:
            verify_signed(lease, "controller lease")
        except ValueError as exc:
            raise StateCorruption(str(exc)) from exc
        if lease.get("controller_id") != controller_id:
            raise LeaseConflict("controller ID does not own the active lease")
        if parse_time(str(lease["expires_at"])) <= datetime.now(timezone.utc):
            raise LeaseConflict("controller lease has expired")
        identities = self.context.identity_fields(self.run_id)
        if any(lease.get(key) != expected for key, expected in identities.items()):
            raise LeaseConflict("controller lease identity does not match this run")

    @contextmanager
    def _lease_guard(self) -> Iterator[None]:
        if self.runtime.is_symlink():
            raise LeaseConflict("runtime directory cannot be a symlink")
        self.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.runtime, 0o700)
        try:
            self.lease_lock.mkdir()
        except FileExistsError as exc:
            raise LeaseConflict("controller lease claim is already in progress") from exc
        try:
            yield
        finally:
            self.lease_lock.rmdir()

    def claim_controller(
        self, controller_id: str, *, host_id: str, boot_id: str, pid: int,
        process_start_time: str, ttl_seconds: int,
    ) -> dict[str, Any]:
        if not all(SAFE_ID.fullmatch(value) for value in (controller_id, host_id, boot_id)):
            raise StateError("invalid controller, host, or boot identity")
        with self._lease_guard():
            if self.lease_file.exists():
                current = read_json(self.lease_file)
                expired = parse_time(str(current["expires_at"])) <= datetime.now(timezone.utc)
                if not expired:
                    raise LeaseConflict(f"run is owned by controller {current.get('controller_id')}")
                if current.get("host_id") != host_id or current.get("boot_id") != boot_id:
                    raise AmbiguousLease("expired lease belongs to another host/boot; reconcile explicitly")
                if self._owner_is_live(current):
                    raise LeaseConflict("expired lease still belongs to the live controller process")
                self.lease_file.unlink()
            now = datetime.now(timezone.utc)
            lease = signed({
                "schema_version": 1,
                **self.context.identity_fields(self.run_id),
                "controller_id": controller_id,
                "host_id": host_id,
                "boot_id": boot_id,
                "pid": pid,
                "process_start_time": process_start_time,
                "mode": self.read_run()["mode"],
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "heartbeat_at": now.isoformat().replace("+00:00", "Z"),
                "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z"),
            })
            descriptor = os.open(self.lease_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(lease, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            return lease

    def heartbeat_controller(self, controller_id: str, *, ttl_seconds: int) -> dict[str, Any]:
        if ttl_seconds <= 0:
            raise StateError("controller heartbeat TTL must be positive")
        with self._lease_guard():
            lease = read_json(self.lease_file)
            verify_signed(lease, "controller lease")
            if lease.get("controller_id") != controller_id:
                raise LeaseConflict("only the live owning controller may heartbeat")
            if not self._owner_is_live(lease):
                raise LeaseConflict("controller process identity is no longer live")
            now = datetime.now(timezone.utc)
            updated = dict(lease)
            updated.pop("checksum", None)
            updated["heartbeat_at"] = now.isoformat().replace("+00:00", "Z")
            updated["expires_at"] = (now + timedelta(seconds=ttl_seconds)).isoformat().replace(
                "+00:00", "Z"
            )
            atomic_write_json(self.lease_file, signed(updated))
            return read_json(self.lease_file)

    def release_controller(self, controller_id: str) -> None:
        with self._lease_guard():
            current = read_json(self.lease_file)
            if current.get("controller_id") != controller_id:
                raise LeaseConflict("only the owning controller may release the lease")
            self.lease_file.unlink()

    def write_inbox_result(
        self, *, task_id: str, agent_id: str, result: Mapping[str, Any]
    ) -> Path:
        if not SAFE_ID.fullmatch(task_id) or not SAFE_ID.fullmatch(agent_id):
            raise StateError("invalid task or agent ID")
        identities = self.context.identity_fields(self.run_id)
        for key, expected in identities.items():
            if result.get(key) != expected:
                raise StateError(f"inbox result {key} does not match active run")
        directory = self.path / "inbox" / task_id / agent_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "result.json"
        if target.exists():
            raise StateError(f"inbox result already exists: {target}")
        atomic_write_json(target, signed(dict(result)))
        return target

    def repair(self) -> dict[str, Any]:
        from aiflow.state.repair import repair_store

        return repair_store(self)

    def migrate(self) -> dict[str, Any]:
        from aiflow.state.repair import migrate_store

        return migrate_store(self)
