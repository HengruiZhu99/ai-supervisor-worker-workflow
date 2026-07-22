from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.api.server import create_server  # noqa: E402
from aiflow.identity.context import resolve_project  # noqa: E402
from aiflow.skills.installer import ProjectInstaller  # noqa: E402


class RestartableProjectServer:
    def __init__(self, context, port: int) -> None:
        self.context = context
        self.port = port
        self.token = f"gui-e2e-token-{port}"
        self.lock = threading.Lock()
        self.server = None
        self.thread = None

    def _start(self) -> None:
        self.server = create_server(self.context, port=self.port, token=self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def start(self) -> "RestartableProjectServer":
        with self.lock:
            self._start()
        return self

    def restart(self) -> None:
        with self.lock:
            self._stop()
            self._start()

    def _stop(self) -> None:
        if self.server is None or self.thread is None:
            return
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.server = None
        self.thread = None

    def stop(self) -> None:
        with self.lock:
            self._stop()


def restart_handler(target: RestartableProjectServer):
    class RestartHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/restart":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            target.restart()
            body = b'{"ok":true}\n'
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    return RestartHandler


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
            RestartableProjectServer(resolve_project(explicit_root=root), port).start()
            for root, port in zip(roots, ports, strict=True)
        ]
        control = ThreadingHTTPServer(("127.0.0.1", 8879), restart_handler(servers[0]))
        control_thread = threading.Thread(target=control.serve_forever, daemon=True)
        control_thread.start()

        def stop(_signum: int, _frame: object) -> None:
            stopped.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        print("AIFLOW disposable GUI projects ready", flush=True)
        stopped.wait()
        control.shutdown()
        control.server_close()
        control_thread.join(timeout=2)
        for server in servers:
            server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
