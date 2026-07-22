from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.api.server import create_server  # noqa: E402
from aiflow.identity.context import resolve_project  # noqa: E402
from aiflow.skills.installer import ProjectInstaller  # noqa: E402


def make_project(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "gui-e2e@example.invalid"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "GUI E2E"], cwd=path, check=True)
    ProjectInstaller(path, distribution_root=ROOT).init("solo")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=path, check=True)


def main() -> int:
    stopped = threading.Event()
    with tempfile.TemporaryDirectory(prefix="aiflow-gui-e2e-") as temporary:
        base = Path(temporary)
        os.environ.update(
            {
                "XDG_STATE_HOME": str(base / "state"),
                "XDG_RUNTIME_DIR": str(base / "runtime"),
                "XDG_CACHE_HOME": str(base / "cache"),
                "CODEX_PERMISSION_PROFILE": "workspace-write",
            }
        )
        roots = [base / "project-one", base / "project-two"]
        for root in roots:
            make_project(root)
        ports = (8877, 8878)
        servers = [
            create_server(resolve_project(explicit_root=root), port=port)
            for root, port in zip(roots, ports, strict=True)
        ]
        threads = [
            threading.Thread(target=server.serve_forever, daemon=True)
            for server in servers
        ]
        for thread in threads:
            thread.start()

        def stop(_signum: int, _frame: object) -> None:
            stopped.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        print("AIFLOW disposable GUI projects ready", flush=True)
        stopped.wait()
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
