"""Fault injection against isolated HTTP servers; never terminate a live user model turn."""
import http.client
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sentra_model_gateway.gateway import GatewayServer, GatewayConfig


class DisappearingModel(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls = 0
    sent = threading.Event()

    def log_message(self, *args):
        pass

    def do_POST(self):
        type(self).calls += 1
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b'event: response.output_text.delta\ndata: {"delta":"partial"}\n\n')
        self.wfile.flush()
        self.sent.set()
        # Simulates a producer/browser connection dying without a completed event.
        self.connection.shutdown(socket.SHUT_RDWR)
        self.connection.close()


def test_producer_disconnect_during_stream_preserves_uncertainty_no_post_replay(tmp_path, monkeypatch):
    DisappearingModel.calls = 0
    DisappearingModel.sent = threading.Event()
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), DisappearingModel)
    gateway = GatewayServer(GatewayConfig(
        upstream=f"http://127.0.0.1:{upstream.server_port}",
        port=0, state_root=tmp_path / "state",
        browser_descriptor=tmp_path / "browser.json"))
    events = []
    monkeypatch.setattr(gateway.audit, "emit",
                        lambda action, outcome, details: events.append((action, outcome, details)))
    threads = [threading.Thread(target=server.serve_forever, daemon=True)
               for server in (upstream, gateway)]
    for t in threads:
        t.start()
    try:
        client = http.client.HTTPConnection("127.0.0.1", gateway.server_port, timeout=6)
        try:
            client.request("POST", "/v1/responses",
                           json.dumps({"model": "gpt-6.1-sol", "input": "fault-test"}).encode(),
                           {"Content-Type": "application/json", "Connection": "close"})
            response = client.getresponse()
            assert response.status == 200  # Initial headers are NOT final completion.
            try:
                body = response.read()
                # Chunk framing intentionally lacks a successful terminating chunk.
                assert b"response.completed" not in body
            except (http.client.IncompleteRead, http.client.HTTPException, ConnectionResetError):
                pass
        finally:
            client.close()
        assert DisappearingModel.sent.wait(timeout=3)
    finally:
        for server in (gateway, upstream):
            server.shutdown()
            server.server_close()
        for t in threads:
            t.join(timeout=3)
    assert DisappearingModel.calls == 1
    errors = [v for name, _, v in events if name == "model.gateway.transport_error"]
    assert errors, events
    assert errors[-1]["upstream_headers_received"] is True
    assert errors[-1]["failure_phase"] == "stream_or_downstream_delivery"
    assert errors[-1]["automatic_retry"] is False
