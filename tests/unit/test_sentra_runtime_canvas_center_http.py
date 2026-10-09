"""Real Canvas HTTP -> host -> central SQLite/Grant/Operation integration tests.

The server is the production CanvasServer bound to 127.0.0.1 on an ephemeral
port, not an HTTP stub. Only read-only scoped operations can be dispatched.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from threading import Thread
import urllib.error
import urllib.request

import pytest

from sentra_canvas.service import Canvas
from sentra_canvas.__main__ import CanvasServer
from sentra_mcp.services.authorization import AuthorizationService


@contextmanager
def running_canvas(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    state = tmp_path / "state" / "canvas"
    app = Canvas(project, principal="local-owner", state_dir=state)
    server = CanvasServer(app, 0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield app, server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        app.shutdown()


def request(server, path, *, json_body=None, authorized=True):
    url = f"http://127.0.0.1:{server.server_port}{path}"
    headers = {}
    if authorized:
        headers["Authorization"] = "Bearer " + server.secret
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(json_body).encode("utf-8")
    else:
        data = None
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def install_grant(app, ws, *, principal="agent-1"):
    runtime = app._runtime()
    run = runtime.run(ws)
    if run["state"] != "RUNNING":
        runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING")
    runtime.governance.create_work_item(
        run["run_id"], runtime.owner,
        work_item_id="WI-INTEGRATED",
        objective="User-approved read-only Canvas center inspect",
        assignee_agent_id=principal,
        required_capabilities=["canvas.workspace.inspect"],
        metadata={"workspace_id": ws},
    )
    runtime.governance.transition_work_item("WI-INTEGRATED", runtime.owner, "RUNNING")
    auth = AuthorizationService(app.state_dir.parent)
    grant = auth.grant(
        runtime.owner, principal_type="agent", principal_id=principal,
        scope_type="work_item", scope_id="WI-INTEGRATED",
        capability="canvas.workspace.inspect",
    )
    return runtime, auth, grant


def body(ws):
    return {
        "ws": ws, "work_item_id": "WI-INTEGRATED",
        "operation_id": "op-canvas-http-1", "request_key": "idem-canvas-http-1",
        "confirm": True,
    }


def test_live_canvas_http_core_operation_success_replay_and_revoke(tmp_path):
    with running_canvas(tmp_path) as (app, server):
        workspace = app.create_workspace("Lab")
        ws = workspace["id"]
        runtime, auth, grant = install_grant(app, ws)

        code, caps = request(server, "/api/center/capabilities?ws=" + ws)
        assert code == 200
        assert caps["durable_intent_api"] is True
        assert caps["remote_executors_enabled"] is False
        assert caps["capabilities"] == ["canvas.workspace.inspect"]

        code, obj = request(server, "/api/center/inspect", json_body=body(ws))
        assert code == 200, obj
        assert obj["state"] == "SUCCEEDED"
        assert obj["source"] == "real-sentra-control-plane"
        assert obj["evidence"]["agents"] == 0
        assert runtime.durable.operation_status(
            "op-canvas-http-1", runtime.owner,
        )["state"] == "SUCCEEDED"

        code, replay = request(server, "/api/center/inspect", json_body=body(ws))
        assert code == 200
        assert replay["state"] == "UNCERTAIN"  # NO new effect on replay

        auth.revoke(grant["grant_id"], runtime.owner)
        code, denied = request(server, "/api/center/inspect", json_body=body(ws))
        assert code == 403
        assert denied["error"]


def test_center_route_requires_local_bearer_and_explicit_user_action(tmp_path):
    with running_canvas(tmp_path) as (app, server):
        ws = app.create_workspace("Lab")["id"]
        code, denied = request(server, "/api/center/capabilities?ws=" + ws,
                               authorized=False)
        assert code == 401
        code, denied = request(server, "/api/center/inspect",
                               json_body=body(ws), authorized=False)
        assert code == 401
        payload = body(ws)
        payload.pop("confirm")
        code, denied = request(server, "/api/center/inspect", json_body=payload)
        assert code == 400
        code, denied = request(server, "/api/center/inspect", json_body=body(ws))
        assert code in {403, 500}  # nonexistent central WorkItem cannot execute


def test_center_rejects_wrong_workspace_binding_even_with_live_grant(tmp_path):
    with running_canvas(tmp_path) as (app, server):
        ws = app.create_workspace("First")["id"]
        other = app.create_workspace("Second")["id"]
        install_grant(app, ws)
        code, denied = request(server, "/api/center/inspect",
                               json_body=body(other))
        assert code == 403
        assert denied["error"]
