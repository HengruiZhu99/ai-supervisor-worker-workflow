from __future__ import annotations

import json
import os
import secrets
import webbrowser
from pathlib import Path

from aiflow.api.hub import ProjectHub
from aiflow.api.hub_server import create_hub_server
from aiflow.api.security import format_authority
from aiflow.api.server import STATIC_ROOT, create_server
from aiflow.identity.context import ProjectContext, resolve_project, runtime_path
from aiflow.state.atomic import atomic_write_json


def endpoint_metadata_path(context: ProjectContext) -> Path:
    return runtime_path(context, "gui") / "ENDPOINT.json"


def _write_endpoint_metadata(context: ProjectContext, *, url: str, token: str) -> Path:
    path = endpoint_metadata_path(context)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            **context.identity_fields(),
            "url": url,
            "mutation_token": token,
            "pid": os.getpid(),
        },
    )
    os.chmod(path, 0o600)
    return path


def _url(host: str, port: int) -> str:
    return f"http://{format_authority(host, port)}/"


def _serve(
    server, *, url: str, open_browser: bool, endpoint: Path | None = None
) -> int:
    print(json.dumps({"url": url, "status": "SERVING"}, sort_keys=True), flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if endpoint is not None:
            endpoint.unlink(missing_ok=True)
    return 0


def gui_command(args) -> int:
    context = resolve_project(explicit_root=Path(args.project_root or ".").resolve())
    if args.check:
        assets = sorted(path.name for path in STATIC_ROOT.iterdir() if path.is_file())
        print(
            json.dumps(
                {
                    "ok": {"index.html", "app.js", "app.css"} <= set(assets),
                    "assets": assets,
                    "project": context.identity_fields(),
                },
                sort_keys=True,
            )
        )
        return 0
    token = secrets.token_urlsafe(32)
    server = create_server(
        context,
        host=args.host,
        port=args.port,
        token=token,
        allow_remote=args.allow_remote,
    )
    url = _url(args.host, server.server_port)
    endpoint = _write_endpoint_metadata(context, url=url, token=token)
    print(
        json.dumps(
            {"checkout_id": context.checkout_id, "endpoint_metadata": str(endpoint)},
            sort_keys=True,
        ),
        flush=True,
    )
    return _serve(server, url=url, open_browser=not args.no_open, endpoint=endpoint)


def hub_command(args) -> int:
    roots = args.project or [args.project_root or "."]
    contexts = [resolve_project(explicit_root=Path(root).resolve()) for root in roots]
    if args.check:
        print(json.dumps(ProjectHub(contexts).snapshot(), sort_keys=True))
        return 0
    server = create_hub_server(
        contexts, host=args.host, port=args.port, allow_remote=args.allow_remote
    )
    url = _url(args.host, server.server_port)
    return _serve(server, url=url, open_browser=not args.no_open)
