"""No-secret request boundary receipts for the local Codex HTTP gateway."""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from sentra_model_gateway.gateway import GatewayHandler


def configure_web_authority(server):
    retired = []
    completed = threading.Event()
    def retire(capability, **kwargs):
        retired.append(capability)
        completed.set()
    server.web_transport_mode = lambda: "legacy"
    server.turn_authority = SimpleNamespace(
        issue=lambda **kwargs: "isolated-capability",
        telemetry_metadata=lambda capability: {"completion_verified": False},
        retire=retire,
    )
    return retired, completed


@pytest.mark.parametrize("status", [200, 503])
def test_web_requests_audited_without_prompts_or_tokens(status):
    events = []

    class Audit:
        def emit(self, action, outcome, details):
            events.append((action, outcome, details))

    class Handler(GatewayHandler):
        def _body(self):
            return {"model": "chatgpt-web/gpt-6", "input": "PRIVATE_DO_NOT_AUDIT"}

        def _proxy(self, *args, **kwargs):
            self._json(status, {"status": status})
            return status

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.audit = Audit()
    retired, completed = configure_web_authority(server)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=6)
        try:
            conn.request("POST", "/v1/responses", b"", {
                "Authorization": "Bearer SECRET_DO_NOT_AUDIT",
                "Content-Type": "application/json",
                "Content-Length": "0",
                "Connection": "close",
            })
            reply = conn.getresponse()
            assert reply.status == status
            reply.read()
        finally:
            conn.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)

    gateway_events = [event for event in events if event[0].startswith("model.gateway.")]
    assert [event[0] for event in gateway_events] == [
        "model.gateway.received",
        "model.gateway.forwarded",
    ]
    started, finished = gateway_events[0][2], gateway_events[1][2]
    assert started["correlation_id"] == finished["correlation_id"]
    assert started["path"] == finished["path"] == "/v1/responses"
    assert finished["upstream_http_status"] == status
    assert finished["automatic_retry"] is False
    assert finished["elapsed_ms"] >= 0
    assert gateway_events[1][1] == ("ok" if status == 200 else "error")
    assert completed.wait(2) and retired == ["isolated-capability"]
    safe = json.dumps(events)
    assert "PRIVATE_DO_NOT_AUDIT" not in safe
    assert "SECRET_DO_NOT_AUDIT" not in safe


def test_audit_failure_does_not_break_request():
    class Audit:
        def emit(self, *args):
            raise RuntimeError("audit disk full")

    class Handler(GatewayHandler):
        def _body(self):
            return {"model": "chatgpt-web/gpt-6", "input": "NO_LEAK"}

        def _proxy(self, *args, **kwargs):
            self._json(200, {"ok": True})
            return 200

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.audit = Audit()
    retired, completed = configure_web_authority(server)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        c = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            c.request("POST", "/v1/responses", b"", {"Connection": "close"})
            reply = c.getresponse()
            assert reply.status == 200
            assert json.loads(reply.read())["ok"] is True
        finally:
            c.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert completed.wait(2) and retired == ["isolated-capability"]
