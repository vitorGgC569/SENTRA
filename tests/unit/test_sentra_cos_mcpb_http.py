"""Hermetic real HTTP JSON-RPC, SENTRA WorkItem grants and central SQLite."""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.mcpb_http import MCPHttpRegistry
from sentra_interop.mcp_http import LoopbackMCPHttpClient, MCPHttpError

OWNER, AGENT, WORK, RUN = "owner", "agent", "WI-http", "run-http"


class EchoHandler(BaseHTTPRequestHandler):
    observations = []
    lock = threading.Lock()

    def log_message(self, *_):
        pass  # Never write authorization headers in test output.

    def do_POST(self):
        assert self.path == "/mcp"
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        with self.lock:
            self.observations.append((self.headers.get("Authorization"), json.loads(body)))
        req = json.loads(body)
        method = req["method"]
        if method == "initialize":
            payload = {"protocolVersion": "2025-06-18"}
        elif method == "tools/list":
            payload = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
        elif method == "tools/call":
            payload = {"content": [{"type": "text",
                                    "text": req["params"]["arguments"]["message"]}]}
        else:
            self.send_error(400)
            return
        raw = json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": payload}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def loopback():
    EchoHandler.observations = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/mcp"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.fixture
def control(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    cp = ControlPlaneService(DurableRunService(tmp_path / "state"),
                             ContextBusService(tmp_path / "state"))
    cp.durable.create_run(OWNER, run_id=RUN, workspace=str(ws))
    cp.ensure_agent(RUN, OWNER, agent_id=AGENT, role="worker")
    cp.create_work_item(RUN, OWNER, work_item_id=WORK, objective="HTTP fixture",
                        assignee_agent_id=AGENT,
                        required_capabilities=["mcp:http-connect", "mcp:list", "mcp:echo"])
    cp.transition_work_item(WORK, OWNER, "RUNNING")
    try:
        yield cp, ws
    finally:
        cp.durable.close()


def grant(cp, cap):
    return cp.authorization_grant(OWNER, principal_type="agent", principal_id=AGENT,
                                  capability=cap, scope_type="work_item", scope_id=WORK)


def args(ws, identity="one"):
    return dict(owner=OWNER, workspace=str(ws), server_id="local-echo", run_id=RUN,
                work_item_id=WORK, agent_id=AGENT, tool_name="echo",
                arguments={"message": "HTTP_OK"}, operation_id=f"op-http-{identity}",
                idempotency_key=f"idem-http-{identity}")


def test_http_loopback_real_grants_sqlite_no_replay_and_revocation(control, loopback):
    cp, ws = control
    catalog = MCPHttpRegistry(cp)
    with pytest.raises(PermissionError):
        catalog.register(OWNER, ws, "local-echo", loopback)
    catalog.register(OWNER, ws, "local-echo", loopback, approved=True)
    params = args(ws)
    with pytest.raises(PermissionError, match="grant"):
        asyncio.run(catalog.execute(**params))
    assert not EchoHandler.observations
    grants = [grant(cp, cap) for cap in ("mcp:http-connect", "mcp:list", "mcp:echo")]
    outcome = asyncio.run(catalog.execute(**{**params, "access_token": lambda: "test-token"}))
    assert outcome.operation.state == "SUCCEEDED", outcome
    assert outcome.payload["content"][0]["text"] == "HTTP_OK"
    assert len(EchoHandler.observations) == 3
    assert all(h == "Bearer test-token" for h, _ in EchoHandler.observations)
    record = cp.durable.operation_status(params["operation_id"], OWNER)
    assert record["state"] == "SUCCEEDED" and record["run_id"] == RUN
    again = asyncio.run(catalog.execute(**{**params, "access_token": lambda: "test-token"}))
    assert again.duplicate and len(EchoHandler.observations) == 3
    cp.authorization_revoke(grants[-1]["grant_id"], OWNER)
    with pytest.raises(PermissionError, match="grant"):
        asyncio.run(catalog.execute(**args(ws, "revoked")))
    assert len(EchoHandler.observations) == 3
    catalog.disable(OWNER, ws, "local-echo", approved=True)
    assert MCPHttpRegistry(cp).get(OWNER, ws, "local-echo")["enabled"] == 0
    with pytest.raises(PermissionError, match="revoked"):
        asyncio.run(catalog.execute(**args(ws, "disabled")))
    assert len(EchoHandler.observations) == 3
    with pytest.raises(PermissionError):
        catalog.register(OWNER, ws, "local-echo", loopback, approved=True)


def test_http_url_ssrf_rejects_and_does_not_accept_secrets_in_registry(control):
    cp, ws = control
    catalog = MCPHttpRegistry(cp)
    for url in ("https://example.org/mcp", "http://localhost:8080/mcp",
                "http://169.254.169.254/mcp", "http://127.0.0.1:8080/mcp?a=1",
                "http://user:pass@127.0.0.1:1234/mcp",
                "http://127.0.0.1:8080/mcp#token"):
        with pytest.raises((MCPHttpError, ValueError)):
            catalog.register(OWNER, ws, "rejected", url, approved=True)
    with cp.store.connect("plugin_bundle") as db:
        assert db.execute("SELECT count(*) FROM mcp_http_endpoints").fetchone()[0] == 0


def test_http_missing_launch_and_list_grants_fail_before_network(control, loopback):
    cp, ws = control
    catalog = MCPHttpRegistry(cp)
    catalog.register(OWNER, ws, "local-echo", loopback, approved=True)
    grant(cp, "mcp:echo")
    with pytest.raises(PermissionError):
        asyncio.run(catalog.execute(**args(ws)))
    grant(cp, "mcp:http-connect")
    with pytest.raises(PermissionError):
        asyncio.run(catalog.execute(**args(ws, "without-list")))
    assert not EchoHandler.observations
