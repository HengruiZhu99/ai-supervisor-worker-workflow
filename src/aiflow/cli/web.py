from __future__ import annotations

import json
import secrets
import webbrowser
from pathlib import Path

from aiflow.api.hub import ProjectHub
from aiflow.api.hub_server import create_hub_server
from aiflow.api.server import STATIC_ROOT, create_server
from aiflow.identity.context import resolve_project


def _serve(server, *, url: str, open_browser: bool) -> int:
    print(json.dumps({"url": url, "status": "SERVING"}, sort_keys=True), flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def gui_command(args) -> int:
    context = resolve_project(explicit_root=Path(args.project_root or ".").resolve())
    if args.check:
        assets = sorted(path.name for path in STATIC_ROOT.iterdir() if path.is_file())
        print(json.dumps({"ok": {"index.html", "app.js", "app.css"} <= set(assets), "assets": assets, "project": context.identity_fields()}, sort_keys=True))
        return 0
    token = secrets.token_urlsafe(32)
    server = create_server(
        context,
        host=args.host,
        port=args.port,
        token=token,
        allow_remote=args.allow_remote,
    )
    url = f"http://{args.host}:{server.server_port}/"
    print(json.dumps({"checkout_id": context.checkout_id, "mutation_token": token}, sort_keys=True), flush=True)
    return _serve(server, url=url, open_browser=not args.no_open)


def hub_command(args) -> int:
    roots = args.project or [args.project_root or "."]
    contexts = [resolve_project(explicit_root=Path(root).resolve()) for root in roots]
    if args.check:
        print(json.dumps(ProjectHub(contexts).snapshot(), sort_keys=True))
        return 0
    server = create_hub_server(
        contexts, host=args.host, port=args.port, allow_remote=args.allow_remote
    )
    url = f"http://{args.host}:{server.server_port}/"
    return _serve(server, url=url, open_browser=not args.no_open)
