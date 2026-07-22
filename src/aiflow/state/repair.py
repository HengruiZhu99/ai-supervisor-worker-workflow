from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiflow.state.atomic import atomic_write_json, signed

if TYPE_CHECKING:
    from aiflow.state.store import RunStore


CURRENT_SCHEMA = 1


def _base(store: "RunStore", event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    identities = store.context.identity_fields(store.run_id)
    occurred = str(event["occurred_at"])
    mode = str(event.get("data", {}).get("mode", "solo"))
    run = {
        "schema_version": CURRENT_SCHEMA,
        "state_revision": 0,
        **identities,
        "controller_id": "",
        "mode": mode,
        "status": "CREATED",
        "created_at": occurred,
        "updated_at": occurred,
    }
    tasks = {
        "schema_version": CURRENT_SCHEMA,
        "state_revision": 0,
        **identities,
        "tasks": [],
        "updated_at": occurred,
    }
    return run, tasks


def _replay(store: "RunStore") -> tuple[dict[str, Any], dict[str, Any]]:
    events = store.read_events()
    if not events or events[0].get("event_type") != "run_created":
        raise RuntimeError("event history has no run_created root")
    run, tasks = _base(store, events[0])
    protected = {"schema_version", "state_revision", "project_id", "checkout_id", "worktree_id", "run_id"}
    for event in events[1:]:
        data = event.get("data", {})
        updates = data.get("updates", {})
        task_updates = data.get("task_updates", {})
        if not isinstance(updates, dict) or not isinstance(task_updates, dict):
            raise RuntimeError(f"event {event['sequence']} lacks replayable updates")
        if protected.intersection(updates) or protected.intersection(task_updates):
            raise RuntimeError(f"event {event['sequence']} attempts protected replay mutation")
        run.update(updates)
        tasks.update(task_updates)
        revision = int(event["state_revision"])
        occurred = str(event["occurred_at"])
        run.update({
            "state_revision": revision,
            "controller_id": str(data.get("controller_id", "")),
            "updated_at": occurred,
        })
        tasks.update({"state_revision": revision, "updated_at": occurred})
    return signed(run), signed(tasks)


def _backup(store: "RunStore") -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = store.path / "evidence" / f"repair-{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    for path in (store.run_file, store.tasks_file, store.intent_file, store.committed_file):
        if path.is_file():
            shutil.copy2(path, backup / path.name)
    return backup


def repair_store(store: "RunStore") -> dict[str, Any]:
    with store._lock():
        if store.intent_file.exists():
            raise RuntimeError("resolve the prepared transaction before snapshot repair")
        run, tasks = _replay(store)
        backup = _backup(store)
        atomic_write_json(store.run_file, run)
        atomic_write_json(store.tasks_file, tasks)
        store.verify()
        report = {
            "schema_version": CURRENT_SCHEMA,
            "status": "repaired",
            "run_id": store.run_id,
            "state_revision": run["state_revision"],
            "backup": str(backup),
        }
        atomic_write_json(backup / "REPAIR.json", report)
        return report


def migrate_store(store: "RunStore") -> dict[str, Any]:
    with store._lock():
        run, tasks = store.read_run(), store.read_tasks()
        source = int(run.get("schema_version", 0))
        if source != int(tasks.get("schema_version", -1)):
            raise RuntimeError("snapshot schema versions disagree")
        if source == CURRENT_SCHEMA:
            store.verify()
            return {
                "status": "current", "run_id": store.run_id,
                "from_version": source, "to_version": CURRENT_SCHEMA,
            }
        if source != 0:
            raise RuntimeError(f"unsupported state migration {source}->{CURRENT_SCHEMA}")
        backup = _backup(store)
        for payload, path in ((run, store.run_file), (tasks, store.tasks_file)):
            migrated = dict(payload)
            migrated.pop("checksum", None)
            migrated["schema_version"] = CURRENT_SCHEMA
            atomic_write_json(path, signed(migrated))
        store.verify()
        result = {
            "status": "migrated", "run_id": store.run_id,
            "from_version": source, "to_version": CURRENT_SCHEMA,
            "backup": str(backup),
        }
        atomic_write_json(backup / "MIGRATION.json", result)
        return result
