from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.identity.context import resolve_project  # noqa: E402
from aiflow.state.store import (  # noqa: E402
    AmbiguousLease,
    LeaseConflict,
    RevisionConflict,
    RunStore,
)


def init_project(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    config = path / ".aiflow" / "project.toml"
    config.parent.mkdir()
    config.write_text(
        'schema_version = 1\nproject_id = "state-project"\nname = "state"\nprofile = "solo"\n',
        encoding="utf-8",
    )


class StateStoreTests(unittest.TestCase):
    def make_store(self, root: Path, *, claim: bool = True) -> RunStore:
        context = resolve_project(explicit_root=root)
        store = RunStore.create(context, mode="solo", run_id="run-test")
        if claim:
            store.claim_controller(
                "controller-test", host_id="host-test", boot_id="boot-test", pid=100,
                process_start_time="one", ttl_seconds=60,
            )
        return store

    def test_stale_revision_is_rejected_and_state_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            init_project(project)
            store = self.make_store(project)
            first = store.transition(
                0, {"status": "RUNNING"}, event_type="run_started",
                controller_id="controller-test",
            )
            self.assertEqual(first["state_revision"], 1)
            with self.assertRaises(RevisionConflict):
                store.transition(
                    0, {"status": "FAILED"}, event_type="stale",
                    controller_id="controller-test",
                )
            self.assertEqual(store.read_run()["status"], "RUNNING")
            self.assertEqual(store.read_run()["state_revision"], 1)

    def test_two_controllers_cannot_claim_one_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            init_project(project)
            store = self.make_store(project, claim=False)
            store.claim_controller(
                "controller-a", host_id="host-a", boot_id="boot-a", pid=100,
                process_start_time="one", ttl_seconds=60,
            )
            with self.assertRaises(LeaseConflict):
                store.claim_controller(
                    "controller-b", host_id="host-a", boot_id="boot-a", pid=101,
                    process_start_time="two", ttl_seconds=60,
                )

    def test_expired_cross_host_lease_is_ambiguous_not_stolen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            init_project(project)
            store = self.make_store(project, claim=False)
            store.claim_controller(
                "controller-a", host_id="host-a", boot_id="boot-a", pid=100,
                process_start_time="one", ttl_seconds=-1,
            )
            with self.assertRaises(AmbiguousLease):
                store.claim_controller(
                    "controller-b", host_id="host-b", boot_id="boot-b", pid=101,
                    process_start_time="two", ttl_seconds=60,
                )

    def test_snapshot_event_recovery_is_deterministic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            init_project(project)
            store = self.make_store(project)
            intent = store.prepare_transition(
                0, {"status": "RUNNING"}, event_type="run_started",
                controller_id="controller-test",
            )
            store.apply_prepared_snapshot(intent, append_event=False)
            first = store.recover()
            second = store.recover()
            self.assertEqual(first, "rolled_forward")
            self.assertEqual(second, "clean")
            events = store.read_events()
            self.assertEqual(len(events), 2)  # run_created + run_started
            self.assertEqual(events[-1]["state_revision"], 1)
            store.verify()

    def test_events_are_sequenced_and_checksum_chained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            init_project(project)
            store = self.make_store(project)
            store.transition(
                0, {"status": "RUNNING"}, event_type="run_started",
                controller_id="controller-test",
            )
            events = store.read_events()
            self.assertEqual([event["sequence"] for event in events], [1, 2])
            self.assertEqual(events[1]["previous_checksum"], events[0]["checksum"])
            store.verify()

    def test_child_result_writes_inbox_without_mutating_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            init_project(project)
            store = self.make_store(project)
            before = store.read_run()
            result_path = store.write_inbox_result(
                task_id="T0001", agent_id="worker-1",
                result={
                    "project_id": before["project_id"],
                    "checkout_id": before["checkout_id"],
                    "worktree_id": before["worktree_id"],
                    "run_id": before["run_id"],
                    "status": "completed",
                },
            )
            self.assertTrue(result_path.is_file())
            self.assertEqual(store.read_run(), before)

    def test_canonical_mutation_requires_active_controller_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            init_project(project)
            store = self.make_store(project, claim=False)
            with self.assertRaises(LeaseConflict):
                store.transition(0, {"status": "RUNNING"}, event_type="run_started")

    def test_two_projects_run_and_stop_without_crossing_state_or_process_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first_root, second_root = base / "first", base / "second"
            init_project(first_root)
            init_project(second_root)
            first = RunStore.create(
                resolve_project(explicit_root=first_root), mode="solo", run_id="same-run-name"
            )
            second = RunStore.create(
                resolve_project(explicit_root=second_root), mode="solo", run_id="same-run-name"
            )
            first.claim_controller(
                "controller-first", host_id="host", boot_id="boot", pid=100,
                process_start_time="first", ttl_seconds=60,
            )
            second.claim_controller(
                "controller-second", host_id="host", boot_id="boot", pid=101,
                process_start_time="second", ttl_seconds=60,
            )
            self.assertNotEqual(first.path, second.path)
            self.assertNotEqual(first.runtime, second.runtime)
            first.release_controller("controller-first")
            self.assertFalse(first.lease_file.exists())
            self.assertTrue(second.lease_file.exists())
            self.assertEqual(second.read_run()["run_id"], "same-run-name")


if __name__ == "__main__":
    unittest.main()
