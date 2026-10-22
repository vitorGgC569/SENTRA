"""Real temporary HTTP proxy + actual durable receipts; observations are fixtures.

Only the route admission token/host observations are fixture inputs. Production
_proxy, _upstream, require_receipts, JobStore and protected history are exercised.
No production gateway, upstream, browser or account is accessed.
"""
import http.client
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from sentra_model_gateway.gateway import GatewayHandler
from sentra_model_gateway.web_transport import DurableWebTransport
from test_sentra_cos_backend_web_send import (
    backend, start, observe, receipt_args, OWNER, WORKER, REQUEST, CHAT, EPOCH, DOC,
)


@pytest.fixture
def durable_receipts(backend):
    _, _, control, _, web, params, _ = backend
    job_id, claim, _ = start(backend)
    cap = SimpleNamespace(shared_run=True, token_hash="fixture-host-token", owner=OWNER,
                          run_id=params["run_id"], operation_id=params["operation_id"])
    transport = DurableWebTransport.__new__(DurableWebTransport)
    transport.control, transport.web = control, web
    transport.authority = SimpleNamespace(_capability=lambda token: cap if token == "host-only-fixture" else None)
    transport._initialize()
    with control.store.connect("session_checkpoint") as db:
        db.execute("INSERT INTO gateway_web_submissions VALUES(?,?,?,?,?,?,?,?)",
                   (cap.token_hash, cap.operation_id, 0, job_id, WORKER, DOC, EPOCH,
                    web.status(OWNER, job_id)["prompt_sha256"]))

    def set_state(state):
        if state == "UNCONFIRMED":
            web.failure(OWNER, job_id, reason="fixture page lost")
        else:
            observe(control)
            web.receipt(OWNER, job_id, **receipt_args(claim))
            if state in {"ANSWERING", "ANSWERED"}:
                web.assistant_attestor = lambda **expected: {**expected, "authenticated": True}
                web.answer(OWNER, job_id, request_id=REQUEST, worker=WORKER,
                    browser_principal="local-operator", conversation_id=CHAT,
                    message_id="assistant-terminal-fixture", revision=1, body="OBSERVED_FINAL_FIXTURE",
                    identity_epoch=EPOCH, complete=state == "ANSWERED")
        assert web.status(OWNER, job_id)["state"] == state

    class CountedTransport:
        calls = 0

        def delivery_view(self, token):
            return transport.delivery_view(token)

        def require_receipts(self, token):
            self.calls += 1
            return transport.require_receipts(token)

    yield CountedTransport(), set_state


@contextmanager
def http_proxy(transport, payload, *, content_type, upstream_status=200, known_length=False, fragments=False):
    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.server.calls += 1
            self.send_response(upstream_status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length" if known_length else "Transfer-Encoding",
                             str(len(payload)) if known_length else "chunked")
            self.end_headers()
            pieces = (payload[i:i+3] for i in range(0, len(payload), 3)) if fragments else (payload,)
            try:
                for piece in pieces:
                    self.wfile.write(piece if known_length else f"{len(piece):X}\r\n".encode() + piece + b"\r\n")
                if not known_length:
                    self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except OSError:
                pass  # Gateway may close immediately after denying completion.

    class Proxy(GatewayHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            self._proxy("POST", "/v1/responses", body, delivery_capability="host-only-fixture")

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    upstream.calls = 0
    gateway = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    gateway.web_transport = transport
    gateway.audit = SimpleNamespace(emit=lambda *args: None)
    gateway.config = SimpleNamespace(upstream=f"http://127.0.0.1:{upstream.server_port}")
    threads = [threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
               for server in (upstream, gateway)]
    for thread in threads:
        thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", gateway.server_port, timeout=5)
    try:
        connection.request("POST", "/v1/responses", b"{}", {"Connection": "close"})
        response = connection.getresponse()
        try:
            body = response.read()
            clean = True
        except http.client.IncompleteRead as exc:
            body, clean = exc.partial, False
        yield response.status, body, clean, upstream.calls, dict(response.getheaders())
    finally:
        connection.close()
        for server in (gateway, upstream):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
            assert not thread.is_alive()


@pytest.mark.parametrize("state", ["UNCONFIRMED", "ANSWERING", "SENT"])
@pytest.mark.parametrize("terminal", [b'event: response.completed\ndata: {"response":{"status":"completed"}}\n\n', b'data: [DONE]\n\n', b'event: RESPONSE.COMPLETED\ndata: {}\n\n'])
def test_unattested_sse_success_never_reaches_http_client(durable_receipts, state, terminal):
    transport, set_state = durable_receipts
    set_state(state)
    prefix = b'event: response.output_text.delta\ndata: {"delta":"partial observed text"}\n\n'
    with http_proxy(transport, prefix + terminal, content_type="text/event-stream", fragments=True) as (status, body, clean, calls, _):
        assert status == 200  # Headers/partial deltas can precede final proof.
        assert b"partial observed text" in body
        assert b"event: sentra.web_delivery" in body
        assert b"response.completed" not in body.lower() and b"[DONE]" not in body
        assert clean is False  # No clean zero chunk claiming terminal success.
        assert calls == 1 and transport.calls == 1


@pytest.mark.parametrize("state", ["UNCONFIRMED", "ANSWERING", "SENT"])
def test_unattested_json_completion_returns_conflict_before_success_headers(durable_receipts, state):
    transport, set_state = durable_receipts
    set_state(state)
    payload = b'{"status":"completed","output":"OBSERVED_FINAL_FIXTURE"}'
    with http_proxy(transport, payload, content_type="application/json", known_length=True) as (status, body, clean, calls, headers):
        assert status == 409 and clean
        value = json.loads(body)
        assert value["error"]["type"] == "web_completion_unconfirmed"
        assert value["error"]["automatic_retry"] is False
        assert value["error"]["reconciliation_required"] is True
        assert b"OBSERVED_FINAL_FIXTURE" not in body and b'"completed"' not in body
        assert int(headers["Content-Length"]) == len(body)
        assert calls == 1 and transport.calls == 1


@pytest.mark.parametrize("kind", ["json", "sse", "done"])
def test_exact_answered_receipt_allows_terminal_success(durable_receipts, kind):
    transport, set_state = durable_receipts
    set_state("ANSWERED")
    payload = {"json": b'{"status":"completed","output":"OBSERVED_FINAL_FIXTURE"}',
               "sse": b'event: response.completed\ndata: {"response":{"status":"completed"}}\n\n',
               "done": b'data: [DONE]\n\n'}[kind]
    with http_proxy(transport, payload, content_type="application/json" if kind == "json" else "text/event-stream",
                    known_length=kind == "json", fragments=True) as (status, body, clean, calls, _):
        assert status == 200 and clean
        assert payload in body
        assert calls == 1 and transport.calls == 1


@pytest.mark.parametrize("terminal", ["failed", "incomplete"])
def test_upstream_failure_sse_is_preserved_without_success_receipt(durable_receipts, terminal):
    transport, set_state = durable_receipts
    set_state("UNCONFIRMED")
    payload = f'event: response.{terminal}\ndata: {{"response":{{"status":"{terminal}"}}}}\n\n'.encode()
    with http_proxy(transport, payload, content_type="text/event-stream") as (status, body, clean, calls, _):
        assert status == 200 and clean and payload in body
        assert b"response.completed" not in body
        assert transport.calls == 0 and calls == 1


def test_upstream_http_error_is_preserved_without_success_receipt(durable_receipts):
    transport, set_state = durable_receipts
    set_state("UNCONFIRMED")
    payload = b'{"error":{"type":"fixture_upstream_failure"}}'
    with http_proxy(transport, payload, content_type="application/json", upstream_status=503,
                    known_length=True) as (status, body, clean, calls, _):
        assert status == 503 and clean and body == payload
        assert transport.calls == 0 and calls == 1


@pytest.mark.parametrize("kind", ["sse", "json"])
def test_terminal_completion_requires_every_physical_submission(backend, durable_receipts, kind):
    transport, set_state = durable_receipts
    set_state("ANSWERED")
    _, _, control, _, web, params, _ = backend
    second = web.admit(OWNER, **{**params, "submission_index": 1})
    assert web.status(OWNER, second["job_id"])["state"] == "QUEUED"
    with control.store.connect("session_checkpoint") as db:
        db.execute("INSERT INTO gateway_web_submissions VALUES(?,?,?,?,?,?,?,?)",
            ("fixture-host-token", params["operation_id"], 1, second["job_id"], WORKER,
             "second-physical-document", EPOCH, second["prompt_sha256"]))
    payload = b'event: response.completed\ndata: {}\n\n' if kind == "sse" else b'{"status":"completed"}'
    with http_proxy(transport, payload, content_type="text/event-stream" if kind == "sse" else "application/json",
                    known_length=True) as (status, body, clean, calls, _):
        assert b"response.completed" not in body and b'"completed"' not in body
        assert (status == 200 and not clean) if kind == "sse" else (status == 409 and clean)
        assert calls == 1 and transport.calls == 1


def test_json_success_without_any_observed_submission_is_denied(backend, durable_receipts):
    transport, _ = durable_receipts
    _, _, control, _, _, _, _ = backend
    with control.store.connect("session_checkpoint") as db:
        db.execute("DELETE FROM gateway_web_submissions")
    with http_proxy(transport, b'{"status":"completed"}', content_type="application/json",
                    known_length=True) as (status, body, clean, calls, _):
        assert status == 409 and clean
        assert json.loads(body)["error"]["type"] == "web_completion_unconfirmed"
        assert calls == 1 and transport.calls == 1


@pytest.mark.parametrize("state", ["UNCONFIRMED", "ANSWERED"])
def test_large_completed_sse_frame_checks_receipts_before_any_terminal_bytes(durable_receipts, state):
    transport, set_state = durable_receipts
    set_state(state)
    data = {"response": {"status": "completed", "output": "observed upstream output " * 900}}
    payload = b"event: response.completed\ndata: " + json.dumps(data).encode() + b"\n\n"
    assert len(payload) > 8192  # Typical full Responses terminal exceeds tail buffer.
    with http_proxy(transport, payload, content_type="text/event-stream", fragments=True) as (status, body, clean, calls, _):
        assert status == 200 and calls == 1
        if state == "UNCONFIRMED":
            assert b"response.completed" not in body and clean is False
        else:
            assert payload in body and clean
        assert transport.calls == 1
