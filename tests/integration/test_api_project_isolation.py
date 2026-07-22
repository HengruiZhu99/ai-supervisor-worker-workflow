from __future__ import annotations

import json
import http.client
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from threading import Thread


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.api.hub import ProjectHub, ReadOnlyHubError  # noqa: E402
from aiflow.api.server import create_server  # noqa: E402
from aiflow.api.service import ApiService  # noqa: E402
from aiflow.controller.lifecycle import RunLifecycle  # noqa: E402
from aiflow.identity.context import resolve_project  # noqa: E402
from aiflow.skills.installer import ProjectInstaller  # noqa: E402


def project(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "AIFLOW Test"], cwd=path, check=True)
    ProjectInstaller(path, distribution_root=ROOT).init("solo")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=path, check=True)


@contextmanager
def running_server(path: Path, token: str):
    context = resolve_project(explicit_root=path)
    server = create_server(context, host="127.0.0.1", port=0, token=token)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(url: str, *, method: str = "GET", token: str = "", payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {}
    if data is not None:
        origin = url.split("/api/", 1)[0]
        headers.update(
            {
                "Content-Type": "application/json",
                "Origin": origin,
                "X-AIFLOW-Token": token,
            }
        )
    return urllib.request.urlopen(
        urllib.request.Request(url, data=data, method=method, headers=headers),
        timeout=3,
    )


class ApiProjectIsolationTests(unittest.TestCase):
    def test_sse_response_stays_streaming_without_content_length(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project"
            project(path)
            with running_server(path, "token") as (server, _url):
                server.service.events.publish("run", {"status": "PAUSED"})
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=2
                )
                try:
                    connection.request("GET", "/api/v1/events")
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertIsNone(response.getheader("Content-Length"))
                    self.assertTrue(response.readline().startswith(b"id: "))
                    self.assertEqual(response.readline().strip(), b"event: run")
                finally:
                    connection.close()

    def test_service_publishes_cli_side_state_changes_to_sse_buffer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project"
            project(path)
            context = resolve_project(
                explicit_root=path,
                env={"XDG_STATE_HOME": str(Path(tmp) / "registry")},
            )
            service = ApiService(context)
            RunLifecycle(context).start(mode="solo", objective="external CLI change")
            service.sync_events()
            replay = service.events.replay("")
            self.assertTrue(any(event.event_type == "run" for event in replay.events))

    def test_two_servers_keep_identity_state_and_tokens_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "first", Path(tmp) / "second"
            project(first)
            project(second)
            runtime = Path(tmp) / "runtime"
            previous = os.environ.get("XDG_RUNTIME_DIR")
            os.environ["XDG_RUNTIME_DIR"] = str(runtime)
            try:
                with (
                    running_server(first, "first-token") as (_, first_url),
                    running_server(second, "second-token") as (_, second_url),
                ):
                    first_snapshot = json.load(request(first_url + "/api/v1/snapshot"))
                    second_snapshot = json.load(
                        request(second_url + "/api/v1/snapshot")
                    )
                    self.assertNotEqual(
                        first_snapshot["project"]["checkout_id"],
                        second_snapshot["project"]["checkout_id"],
                    )
                    created = json.load(
                        request(
                            first_url + "/api/v1/runs",
                            method="POST",
                            token="first-token",
                            payload={
                                "mode": "solo",
                                "objective": "fix norm",
                                "checkout_id": first_snapshot["project"]["checkout_id"],
                            },
                        )
                    )
                    self.assertEqual(created["mode"], "solo")
                    self.assertEqual(
                        len(json.load(request(first_url + "/api/v1/snapshot"))["runs"]),
                        1,
                    )
                    self.assertEqual(
                        len(
                            json.load(request(second_url + "/api/v1/snapshot"))["runs"]
                        ),
                        0,
                    )
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        request(
                            second_url + "/api/v1/runs",
                            method="POST",
                            token="first-token",
                            payload={
                                "mode": "solo",
                                "objective": "wrong project",
                                "checkout_id": second_snapshot["project"][
                                    "checkout_id"
                                ],
                            },
                        )
                    self.assertEqual(denied.exception.code, 403)
            finally:
                if previous is None:
                    os.environ.pop("XDG_RUNTIME_DIR", None)
                else:
                    os.environ["XDG_RUNTIME_DIR"] = previous

    def test_stale_or_wrong_checkout_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project"
            project(path)
            with running_server(path, "token") as (_, url):
                snapshot = json.load(request(url + "/api/v1/snapshot"))
                created = json.load(
                    request(
                        url + "/api/v1/runs",
                        method="POST",
                        token="token",
                        payload={
                            "mode": "solo",
                            "objective": "bounded task",
                            "checkout_id": snapshot["project"]["checkout_id"],
                        },
                    )
                )
                mutation = {
                    "expected_revision": created["state_revision"],
                    "checkout_id": created["checkout_id"],
                }
                stopped = json.load(
                    request(
                        f"{url}/api/v1/runs/{created['run_id']}/stop",
                        method="POST",
                        token="token",
                        payload=mutation,
                    )
                )
                self.assertEqual(stopped["status"], "STOPPED")
                with self.assertRaises(urllib.error.HTTPError) as stale:
                    request(
                        f"{url}/api/v1/runs/{created['run_id']}/stop",
                        method="POST",
                        token="token",
                        payload=mutation,
                    )
                self.assertEqual(stale.exception.code, 409)
                wrong = dict(
                    mutation,
                    expected_revision=stopped["state_revision"],
                    checkout_id="wrong",
                )
                with self.assertRaises(urllib.error.HTTPError) as mismatch:
                    request(
                        f"{url}/api/v1/runs/{created['run_id']}/stop",
                        method="POST",
                        token="token",
                        payload=wrong,
                    )
                self.assertEqual(mismatch.exception.code, 409)
                handoff = json.load(
                    request(
                        f"{url}/api/v1/runs/{created['run_id']}/handoff",
                        method="POST",
                        token="token",
                        payload={
                            "expected_revision": stopped["state_revision"],
                            "checkout_id": stopped["checkout_id"],
                        },
                    )
                )
                self.assertTrue(Path(handoff["handoff_path"]).is_file())
                with self.assertRaises(urllib.error.HTTPError) as stale_handoff:
                    request(
                        f"{url}/api/v1/runs/{created['run_id']}/handoff",
                        method="POST",
                        token="token",
                        payload={
                            "expected_revision": stopped["state_revision"],
                            "checkout_id": stopped["checkout_id"],
                        },
                    )
                self.assertEqual(stale_handoff.exception.code, 409)

    def test_static_assets_run_without_node_and_hub_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project"
            project(path)
            context = resolve_project(explicit_root=path)
            hub = ProjectHub([context])
            self.assertEqual(
                hub.snapshot()["projects"][0]["checkout_id"], context.checkout_id
            )
            with self.assertRaises(ReadOnlyHubError):
                hub.mutate("stop", {})
            with running_server(path, "token") as (_, url):
                html = request(url + "/").read().decode()
                script = request(url + "/assets/app.js").read().decode()
                self.assertIn("project-identity", html)
                self.assertIn("Solo TDD", html)
                self.assertNotIn("from 'react'", script)
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    request(url + "/api/v1/files?path=/etc/passwd")
                self.assertEqual(missing.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
