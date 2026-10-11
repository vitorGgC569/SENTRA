"""Physical HTTP GET Last-Event-ID/DELETE, WorkItem grants and central durable SQLite."""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.mcpb_http import MCPHttpRegistry

OWNER, RUN, WORK, AGENT = "owner", "run-stream-ctl", "WI-stream-ctl", "worker"


class SessionServer(BaseHTTPRequestHandler):
    seen = []
    def log_message(self, *_):
        pass

    def _reply(self, status, body=b"", content_type="application/json", session=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if session:
            self.send_header("Mcp-Session-Id", "session_1")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        request = json.loads(raw)
        method = request["method"]
        self.seen.append(("POST", method, self.headers.get("Mcp-Session-Id")))
        if method == "notifications/initialized":
            self._reply(202)
            return
        if method == "initialize":
            data = {"protocolVersion": "2025-06-18"}
        elif method == "tools/list":
            data = {"tools": [{"name": "echo"}]}
        elif method == "tools/call":
            data = {"content": [{"type": "text", "text": "OK"}]}
        else:
            self._reply(400)
            return
        body = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": data}).encode()
        self._reply(200, body, session=True)

    def do_GET(self):
        cursor = self.headers.get("Last-Event-ID")
        session = self.headers.get("Mcp-Session-Id")
        self.seen.append(("GET", cursor, session))
        if session != "session_1" or cursor not in (None, "cursor_1"):
            self._reply(403)
            return
        eid = "cursor_1" if cursor is None else "cursor_2"
        payload = json.dumps({"jsonrpc": "2.0", "method": "notifications/progress",
                              "params": {"progress": 1}}).encode()
        body = b"event: message\nid: " + eid.encode() + b"\ndata: " + payload + b"\n\n"
        self._reply(200, body, content_type="text/event-stream")

    def do_DELETE(self):
        self.seen.append(("DELETE", self.headers.get("Mcp-Session-Id"), None))
        self._reply(204)


@pytest.fixture
def fixture(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    control = ControlPlaneService(DurableRunService(tmp_path / "state"),
                                  ContextBusService(tmp_path / "state"))
    control.durable.create_run(OWNER, run_id=RUN, workspace=str(ws))
    control.ensure_agent(RUN, OWNER, agent_id=AGENT, role="worker")
    control.create_work_item(RUN, OWNER, work_item_id=WORK,
                             objective="MCP managed session", assignee_agent_id=AGENT,
                             required_capabilities=["mcp:http-connect", "mcp:list",
                                                    "mcp:echo", "mcp:events",
                                                    "mcp:session-delete"])
    control.transition_work_item(WORK, OWNER, "RUNNING")
    SessionServer.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), SessionServer)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    registry = MCPHttpRegistry(control)
    registry.register(OWNER, ws, "local-session",
                      f"http://127.0.0.1:{server.server_address[1]}/mcp",
                      approved=True, streamable=True)
    try:
        yield control, registry, ws
    finally:
        server.shutdown()
        server.server_close()
        th.join(timeout=3)
        control.durable.close()


def _grant(cp, capability):
    return cp.authorization_grant(OWNER, principal_type="agent",
                                  principal_id=AGENT, capability=capability,
                                  scope_type="work_item", scope_id=WORK)


def _args(ws, action, name):
    return dict(owner=OWNER, workspace=str(ws), server_id="local-session",
                run_id=RUN, work_item_id=WORK, agent_id=AGENT,
                source_operation_id="op-session-init",
                operation_id="op-session-" + name, idempotency_key="idem-session-" + name,
                action=action)


def test_get_event_resume_delete_durable_grants_and_no_replay(fixture):
    cp, registry, ws = fixture
    for cap in ("mcp:http-connect", "mcp:list", "mcp:echo"):
        _grant(cp, cap)
    source = asyncio.run(registry.execute(owner=OWNER, workspace=str(ws),
        server_id="local-session", run_id=RUN, work_item_id=WORK,
        agent_id=AGENT, tool_name="echo", arguments={},
        operation_id="op-session-init", idempotency_key="idem-session-init"))
    assert source.operation.state == "SUCCEEDED", source
    assert len(SessionServer.seen) == 4
    with pytest.raises(PermissionError, match="grant"):
        asyncio.run(registry.session_action(**_args(ws, "events", "first")))
    assert len(SessionServer.seen) == 4
    _grant(cp, "mcp:events")
    event = asyncio.run(registry.session_action(**_args(ws, "events", "first")))
    assert event.operation.state == "SUCCEEDED", event
    assert event.payload["last_event_id"] == "cursor_1"
    assert ("GET", None, "session_1") in SessionServer.seen
    assert cp.durable.operation_status("op-session-first", OWNER)["state"] == "SUCCEEDED"
    again = asyncio.run(registry.session_action(**_args(ws, "events", "second")))
    assert again.payload["last_event_id"] == "cursor_2"
    assert ("GET", "cursor_1", "session_1") in SessionServer.seen
    with pytest.raises(PermissionError, match="grant"):
        asyncio.run(registry.session_action(**_args(ws, "delete", "remove")))
    _grant(cp, "mcp:session-delete")
    removed = asyncio.run(registry.session_action(**_args(ws, "delete", "remove")))
    assert removed.operation.state == "SUCCEEDED" and removed.payload["deleted"]
    assert sum(item[0] == "DELETE" for item in SessionServer.seen) == 1
    with pytest.raises(PermissionError):
        asyncio.run(registry.session_action(**_args(ws, "delete", "remove-again")))
    assert sum(item[0] == "DELETE" for item in SessionServer.seen) == 1


def test_mcp_session_wrong_owner_denied_without_get_or_delete(fixture):
    cp, registry, ws = fixture
    for cap in ("mcp:http-connect", "mcp:list", "mcp:echo",
                "mcp:events", "mcp:session-delete"):
        _grant(cp, cap)
    asyncio.run(registry.execute(owner=OWNER, workspace=str(ws),
        server_id="local-session", run_id=RUN, work_item_id=WORK,
        agent_id=AGENT, tool_name="echo", arguments={},
        operation_id="op-session-init", idempotency_key="idem-session-init"))
    with pytest.raises((FileNotFoundError, PermissionError)):
        asyncio.run(registry.session_action(**{**_args(ws, "events", "other"),
                                               "owner": "other"}))
    assert not any(item[0] in {"GET", "DELETE"} for item in SessionServer.seen)


def test_get_delete_crash_recovery_marks_uncertain_without_http_replay(fixture):
    import time
    cp, registry, ws = fixture
    with cp.store.connect("plugin_bundle") as db:
        db.execute(
            "INSERT INTO mcp_http_session_attempts("
            "owner,workspace,server_id,operation_id,session_id,state,updated,"
            "observation_state,deletion_state) VALUES(?,?,?,?,?,?,?,?,?)",
            (OWNER, str(ws.resolve()), "local-session", "op-abandoned-events",
             "session_1", "COMPLETED", time.time()-1000, "READING", "ACTIVE"))
        db.execute(
            "INSERT INTO mcp_http_session_attempts("
            "owner,workspace,server_id,operation_id,session_id,state,updated,"
            "observation_state,deletion_state) VALUES(?,?,?,?,?,?,?,?,?)",
            (OWNER, str(ws.resolve()), "local-session", "op-abandoned-delete",
             "session_1", "COMPLETED", time.time()-1000, "IDLE", "DELETING"))
    recovered = MCPHttpRegistry(cp)
    result = recovered.reconcile_abandoned(OWNER, ws, min_age_seconds=60)
    assert result["event_reads_uncertain"] == 1
    assert result["deletions_uncertain"] == 1
    assert result["effects_replayed"] == 0
    assert not SessionServer.seen
