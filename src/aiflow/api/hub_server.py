from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterable
from urllib.parse import urlsplit

from aiflow.api.hub import ProjectHub
from aiflow.api.security import SecurityError, validate_bind
from aiflow.identity.context import ProjectContext


class HubHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        projects: Iterable[ProjectContext],
        *,
        allow_remote: bool,
    ) -> None:
        validate_bind(address[0], allow_remote=allow_remote)
        self.hub = ProjectHub(projects)
        super().__init__(address, HubRequestHandler)
        self.authority = f"{address[0]}:{self.server_port}"


class HubRequestHandler(BaseHTTPRequestHandler):
    server: HubHTTPServer
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.headers.get("Host", "") != self.server.authority:
            self._send(HTTPStatus.FORBIDDEN, "application/json", b'{"error":"wrong hub host"}\n')
            return
        path = urlsplit(self.path).path
        payload = self.server.hub.snapshot()
        if path == "/api/v1/projects":
            self._send(
                HTTPStatus.OK,
                "application/json; charset=utf-8",
                (json.dumps(payload, sort_keys=True) + "\n").encode(),
            )
        elif path == "/":
            items = "".join(
                f"<li><strong>{project['name']}</strong><br><code>{project['root']}</code>"
                f"<br>checkout {project['checkout_id'][-8:]}</li>"
                for project in payload["projects"]
            )
            body = (
                "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                "<title>AIFLOW project hub</title><style>body{font:16px system-ui;max-width:52rem;"
                "margin:4rem auto;padding:0 1rem}li{margin:1rem 0;padding:1rem;border:1px solid #bbb;"
                "border-radius:.75rem}code{overflow-wrap:anywhere}</style><h1>AIFLOW projects</h1>"
                "<p>Read-only registry. Open a project server to make changes.</p><ul>" + items + "</ul>"
            ).encode()
            self._send(HTTPStatus.OK, "text/html; charset=utf-8", body)
        else:
            self._send(HTTPStatus.NOT_FOUND, "application/json", b'{"error":"route not found"}\n')

    def do_POST(self) -> None:
        self._send(HTTPStatus.METHOD_NOT_ALLOWED, "application/json", b'{"error":"hub is read-only"}\n')

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def create_hub_server(
    projects: Iterable[ProjectContext],
    *,
    host: str = "127.0.0.1",
    port: int = 8766,
    allow_remote: bool = False,
) -> HubHTTPServer:
    return HubHTTPServer((host, port), projects, allow_remote=allow_remote)
