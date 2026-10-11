"""Real Streamable HTTP framing/session bound to central WorkItem and grants."""
import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sentra_mcp.services.mcpb_http import MCPHttpRegistry
from test_sentra_cos_mcpb_http import control, args, grant


class SessionHandler(BaseHTTPRequestHandler):
    observed = []
    def log_message(self, *args):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        req = json.loads(raw)
        method = req["method"]
        token = self.headers.get("Mcp-Session-Id")
        self.observed.append((method, token))
        if method == "notifications/initialized":
            assert token == "unit-session_1"
            self.send_response(202)
            self.end_headers()
            return
        result = ({"protocolVersion": "2025-06-18"} if method == "initialize"
                  else {"tools": [{"name": "echo"}]} if method == "tools/list"
                  else {"content": [{"type": "text",
                                    "text": req["params"]["arguments"]["message"]}]})
        if method != "initialize":
            assert token == "unit-session_1"
        payload = json.dumps({"jsonrpc": "2.0", "id": req["id"],
                              "result": result}).encode()
        if method == "tools/call":
            payload = b"event: message\ndata: " + payload + b"\n\n"
        self.send_response(200)
        self.send_header("Mcp-Session-Id", "unit-session_1")
        self.send_header("Content-Type", "text/event-stream" if method == "tools/call"
                         else "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def streamable():
    SessionHandler.observed = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), SessionHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%s/mcp" % server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_session_sse_jsonrpc_real_sqlite_grants_and_replay(control, streamable):
    cp, ws = control
    reg = MCPHttpRegistry(cp)
    reg.register("owner", ws, "local-echo", streamable, approved=True, streamable=True)
    for capability in ("mcp:http-connect", "mcp:list", "mcp:echo"):
        grant(cp, capability)
    details = args(ws, "session")
    result = asyncio.run(reg.execute(**details))
    assert result.operation.state == "SUCCEEDED", result
    assert result.payload["content"] == [{"type": "text", "text": "HTTP_OK"}]
    assert SessionHandler.observed == [
        ("initialize", None), ("notifications/initialized", "unit-session_1"),
        ("tools/list", "unit-session_1"), ("tools/call", "unit-session_1")]
    assert reg.session_status("owner", ws, details["operation_id"])["state"] == "COMPLETED"
    assert cp.durable.operation_status(details["operation_id"], "owner")["state"] == "SUCCEEDED"
    replay = asyncio.run(reg.execute(**details))
    assert replay.duplicate
    assert len(SessionHandler.observed) == 4
    with pytest.raises(PermissionError):
        reg.register("owner", ws, "local-echo", streamable, approved=True,
                     streamable=False)


def test_stale_session_restart_reconciles_without_resend(control, streamable):
    cp, ws = control
    reg = MCPHttpRegistry(cp)
    reg.register("owner", ws, "local-echo", streamable, approved=True, streamable=True)
    with cp.store.connect("plugin_bundle") as db:
        db.execute("INSERT INTO mcp_http_session_attempts("
                   "owner,workspace,server_id,operation_id,session_id,state,updated)"
                   " VALUES(?,?,?,?,?,?,?)",
                   ("owner", str(ws.resolve()), "local-echo", "op-crashed",
                    "unit-session_1", "ACTIVE", time.time() - 1000))
    recovered = MCPHttpRegistry(cp)
    report = recovered.reconcile_abandoned("owner", ws, min_age_seconds=60)
    assert report["sessions_marked_uncertain"] == 1
    assert report["effects_replayed"] == 0
    assert recovered.session_status("owner", ws, "op-crashed")["state"] == "UNCERTAIN"
    assert not SessionHandler.observed
    assert recovered.reconcile_abandoned("owner", ws)["sessions_marked_uncertain"] == 0
