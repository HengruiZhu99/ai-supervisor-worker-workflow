from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.cli.main import parser  # noqa: E402
from aiflow.identity.context import resolve_project  # noqa: E402
from aiflow.state.atomic import atomic_write_json, signed  # noqa: E402
from aiflow.state.store import RunStore  # noqa: E402


def init_project(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    config = path / ".aiflow" / "project.toml"
    config.parent.mkdir()
    config.write_text(
        'schema_version=1\nproject_id="state-gui-audit"\nname="fixture"\nprofile="solo"\n',
        encoding="utf-8",
    )


class StateGuiAuditRegressionTests(unittest.TestCase):
    def test_stale_owned_transaction_lock_is_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            context = resolve_project(explicit_root=root, env={"XDG_STATE_HOME": str(Path(tmp) / "registry")})
            store = RunStore.create(
                context,
                mode="solo",
                run_id="stale-lock",
                runtime_env={"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime")},
            )
            store.lock_dir.mkdir()
            atomic_write_json(
                store.lock_owner_file,
                signed(
                    {
                        "schema_version": 1,
                        "host_id": store.local_host_id(),
                        "boot_id": store.local_boot_id(),
                        "pid": 999_999_999,
                        "process_start_time": "missing",
                        "created_at": "2000-01-01T00:00:00Z",
                    }
                ),
            )
            self.assertEqual(store.recover(), "clean")
            self.assertFalse(store.lock_dir.exists())

    def test_lease_heartbeat_renews_only_for_live_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            store = RunStore.create(
                resolve_project(explicit_root=root, env={"XDG_STATE_HOME": str(Path(tmp) / "registry")}),
                mode="solo",
                run_id="heartbeat",
                runtime_env={"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime")},
            )
            identity = store.local_process_identity()
            lease = store.claim_controller("controller", ttl_seconds=1, **identity)
            renewed = store.heartbeat_controller("controller", ttl_seconds=60)
            self.assertGreater(renewed["expires_at"], lease["expires_at"])

    def test_runtime_and_event_state_are_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            init_project(root)
            store = RunStore.create(
                resolve_project(explicit_root=root, env={"XDG_STATE_HOME": str(Path(tmp) / "registry")}),
                mode="solo",
                run_id="permissions",
                runtime_env={"XDG_RUNTIME_DIR": str(Path(tmp) / "runtime")},
            )
            identity = store.local_process_identity()
            store.claim_controller("controller", ttl_seconds=60, **identity)
            self.assertEqual(stat.S_IMODE(store.runtime.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(store.events_file.stat().st_mode), 0o600)

    def test_gui_uses_os_selected_port_by_default(self) -> None:
        args = parser().parse_args(["--project-root", str(ROOT), "gui", "--check"])
        self.assertEqual(args.port, 0)

    def test_frontend_has_recurring_fallback_and_focusable_skip_target(self) -> None:
        source = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
        self.assertIn("scheduleFallbackPoll", source)
        self.assertIn('tabIndex={-1}', source)
        self.assertIn("worktree", source)


if __name__ == "__main__":
    unittest.main()
