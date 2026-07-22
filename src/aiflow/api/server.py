from __future__ import annotations

import json
import secrets
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import socket
from typing import Any, Mapping, cast
from urllib.parse import parse_qs, urlsplit

from aiflow.api.security import RequestSecurity, SecurityError, validate_bind
from aiflow.api.service import ApiService
from aiflow.identity.context import ProjectContext
from aiflow.state.store import RevisionConflict, StateError


STATIC_ROOT = Path(__file__).with_name("static")
STATIC_FILES = {
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
}


class ProjectHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        context: ProjectContext,
        *,
        token: str,
        allow_remote: bool,
    ) -> None:
        validate_bind(address[0], allow_remote=allow_remote)
        self.service = ApiService(context)
        self.session_token = token
        self.stopping = threading.Event()
        super().__init__(address, ProjectRequestHandler)
        self.security = RequestSecurity(
            token=token,
            host=address[0],
            port=int(self.server_address[1]),
        )

    def server_close(self) -> None:
        self.stopping.set()
        super().server_close()

    def handle_error(
        self,
        request: socket | tuple[bytes, socket],
        client_address: Any,
    ) -> None:
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


class ProjectRequestHandler(BaseHTTPRequestHandler):
    server: ProjectHTTPServer
    protocol_version = "HTTP/1.1"

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()

    def _bytes(self, status: int, content_type: str, body: bytes) -> None:
        self._headers(status, content_type, len(body))
        self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        body = (json.dumps(payload, sort_keys=True) + "\n").encode()
        self._bytes(status, "application/json; charset=utf-8", body)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message, "status": status})

    def _authorize_read(self) -> bool:
        try:
            self.server.security.authorize_read(cast(Mapping[str, str], self.headers))
        except SecurityError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
            return False
        return True

    def _payload(self) -> dict[str, Any] | None:
        try:
            self.server.security.authorize_mutation(cast(Mapping[str, str], self.headers))
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("JSON payload must be an object")
            return payload
        except SecurityError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except (json.JSONDecodeError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        return None

    def do_GET(self) -> None:
        if not self._authorize_read():
            return
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            content = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
            body = content.replace("__AIFLOW_TOKEN__", self.server.session_token).encode()
            self._bytes(HTTPStatus.OK, "text/html; charset=utf-8", body)
        elif path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            self._bytes(HTTPStatus.OK, content_type, (STATIC_ROOT / filename).read_bytes())
        elif path == "/api/v1/snapshot":
            self._json(HTTPStatus.OK, self.server.service.snapshot())
        elif path == "/api/v1/events":
            self._events()
        else:
            self._error(HTTPStatus.NOT_FOUND, "route not found")

    def _events(self) -> None:
        query = parse_qs(urlsplit(self.path).query)
        last_id = self.headers.get("Last-Event-ID", "") or query.get("last_event_id", [""])[0]
        self.server.service.sync_events()
        replay = self.server.service.events.replay(last_id)
        if replay.reset:
            payload = json.dumps(self.server.service.snapshot(), separators=(",", ":"), sort_keys=True)
            body = f"event: reset\ndata: {payload}\n\n".encode()
            self.close_connection = True
            self._bytes(HTTPStatus.OK, "text/event-stream; charset=utf-8", body)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        cursor = last_id
        last_write = time.monotonic()
        try:
            while not self.server.stopping.is_set():
                self.server.service.sync_events()
                pending = self.server.service.events.wait_after(cursor, timeout=1.0)
                if pending.reset:
                    payload = json.dumps(
                        self.server.service.snapshot(), separators=(",", ":"), sort_keys=True
                    )
                    self.wfile.write(f"event: reset\ndata: {payload}\n\n".encode())
                    self.wfile.flush()
                    return
                for event in pending.events:
                    self.wfile.write(event.encode().encode())
                    cursor = str(event.event_id)
                    last_write = time.monotonic()
                if time.monotonic() - last_write >= 15:
                    self.wfile.write(b": keepalive\n\n")
                    last_write = time.monotonic()
                self.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            self.close_connection = True
            return

    def do_POST(self) -> None:
        payload = self._payload()
        if payload is None:
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/v1/runs":
                result = self.server.service.start(payload)
            else:
                pieces = path.strip("/").split("/")
                if len(pieces) != 5 or pieces[:3] != ["api", "v1", "runs"]:
                    self._error(HTTPStatus.NOT_FOUND, "route not found")
                    return
                result = self.server.service.mutate(pieces[3], pieces[4], payload)
            self._json(HTTPStatus.OK, result)
        except RevisionConflict as exc:
            self._error(HTTPStatus.CONFLICT, str(exc))
        except (StateError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def create_server(
    context: ProjectContext,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    token: str = "",
    allow_remote: bool = False,
) -> ProjectHTTPServer:
    return ProjectHTTPServer(
        (host, port),
        context,
        token=token or secrets.token_urlsafe(32),
        allow_remote=allow_remote,
    )
