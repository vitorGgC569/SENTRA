"""P0 availability regressions: watchdog ownership and safe, correlated 503 receipts."""
from __future__ import annotations

import http.client
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

from sentra_model_gateway import gateway as module


def test_cli_gateway_always_starts_watchdog_without_launch_flag(monkeypatch, tmp_path):
    events = []

    class FakeGateway:
        def __init__(self, config):
            self.server_port = config.port
            self.launcher = SimpleNamespace(
                start=lambda: events.append("launch"),
                stop=lambda: events.append("launcher_stop"),
            )

        def start_upstream_watchdog(self):
            events.append("watchdog_start")

        def serve_forever(self):
            events.append("serve")

        def stop_upstream_watchdog(self):
            events.append("watchdog_stop")

        def server_close(self):
            events.append("server_close")

    monkeypatch.setattr(module, "GatewayServer", FakeGateway)
    monkeypatch.setattr(module, "resolve_gateway_state_root", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["gateway"])
    module.main()
    assert events == ["watchdog_start", "serve", "watchdog_stop", "launcher_stop", "server_close"]


class FailingProducer(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(size)
        body = b'{"error":"upstream temporarily unavailable"}'
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("cf-ray", "a4aa22e83eb87a84-GRU")
        self.end_headers()
        self.wfile.write(body)


def test_upstream_503_traces_provider_cf_ray_without_request_secrets(tmp_path, monkeypatch):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), FailingProducer)
    gateway = module.GatewayServer(module.GatewayConfig(
        upstream=f"http://127.0.0.1:{upstream.server_port}",
        port=0,
        state_root=tmp_path / "state",
        browser_descriptor=tmp_path / "browser.json",
    ))
    events = []
    monkeypatch.setattr(gateway.audit, "emit",
                        lambda action, outcome, details: events.append((action, outcome, details)))
    workers = [threading.Thread(target=s.serve_forever, daemon=True) for s in (upstream, gateway)]
    for worker in workers:
        worker.start()
    try:
        client = http.client.HTTPConnection("127.0.0.1", gateway.server_port, timeout=5)
        try:
            client.request("POST", "/v1/responses",
                           json.dumps({"model": "gpt-6.1-sol", "input": "DO_NOT_LOG"}).encode(),
                           {"Authorization": "Bearer DO_NOT_LOG_TOKEN",
                            "Content-Type": "application/json", "Connection": "close"})
            response = client.getresponse()
            assert response.status == 503
            observed_request_id = response.getheader('X-SENTRA-Request-ID')
            response.read()
        finally:
            client.close()
    finally:
        for server in (gateway, upstream):
            server.shutdown()
            server.server_close()
        for worker in workers:
            worker.join(timeout=3)

    by_action = {action: details for action, _, details in events
                 if action.startswith("model.gateway.")}
    assert by_action["model.gateway.upstream_5xx"]["cf_ray"] == "a4aa22e83eb87a84-GRU"
    assert by_action["model.gateway.upstream_5xx"]["upstream_http_status"] == 503
    assert observed_request_id == by_action["model.gateway.forwarded"]["correlation_id"]
    assert by_action["model.gateway.received"]["correlation_id"] == by_action["model.gateway.forwarded"]["correlation_id"]
    assert by_action["model.gateway.received"]["correlation_id"] == by_action["model.gateway.upstream_5xx"]["correlation_id"]
    assert by_action["model.gateway.forwarded"]["automatic_retry"] is False
    assert "DO_NOT_LOG" not in json.dumps(events)


def test_upstream_connect_failure_is_correlated_and_never_retried(tmp_path, monkeypatch):
    gateway = module.GatewayServer(module.GatewayConfig(
        upstream="http://127.0.0.1:9", port=0,
        state_root=tmp_path / "state",
        browser_descriptor=tmp_path / "browser.json",
    ))
    events = []
    monkeypatch.setattr(gateway.audit, "emit",
                        lambda action, outcome, details: events.append((action, outcome, details)))
    def fail_connect(_handler, *args, **kwargs):
        raise module.UpstreamTransportError("connect", ConnectionRefusedError("injected"))
    monkeypatch.setattr(module.GatewayHandler, "_upstream", fail_connect)
    worker = threading.Thread(target=gateway.serve_forever, daemon=True)
    worker.start()
    try:
        client = http.client.HTTPConnection("127.0.0.1", gateway.server_port, timeout=5)
        try:
            client.request("POST", "/v1/responses",
                           b'{"model":"gpt-6.1-sol","input":"private"}',
                           {"Content-Type": "application/json", "Connection": "close"})
            response = client.getresponse()
            assert response.status == 503
            payload = json.loads(response.read())
            assert payload["error"]["delivery_state"] == "NOT_SENT"
            assert payload["error"]["automatic_retry"] is False
        finally:
            client.close()
    finally:
        gateway.shutdown()
        gateway.server_close()
        worker.join(timeout=3)
    matching = {action: details for action, _, details in events
                if action.startswith("model.gateway.")}
    assert matching["model.gateway.transport_error"]["failure_phase"] == "connect"
    assert matching["model.gateway.transport_error"]["upstream_headers_received"] is False
    assert matching["model.gateway.received"]["correlation_id"] == matching["model.gateway.transport_error"]["correlation_id"]
    assert matching["model.gateway.forwarded"]["automatic_retry"] is False

def test_inference_health_separates_http_liveness_from_503_and_recovers(tmp_path, monkeypatch):
    gateway = module.GatewayServer(module.GatewayConfig(
        upstream="http://127.0.0.1:9", port=0,
        state_root=tmp_path / "state",
        browser_descriptor=tmp_path / "browser.json",
    ))
    try:
        assert gateway.inference_health()["state"] == "OBSERVING"
        for status in [503, 503, 503, 502, 200, 503]:
            gateway.record_inference_outcome(status)
        result = gateway.inference_health()
        assert result["state"] == "DEGRADED"
        assert result["sample_count"] == 6
        assert result["upstream_5xx_count"] == 5
        assert result["failure_rate_percent"] == 83.3
        assert result["automatic_retry"] is False
        module.time.sleep(0.01)
        assert gateway.inference_health(window_s=0)["state"] == "OBSERVING"
        for status in [200] * 8:
            gateway.record_inference_outcome(status)
        assert gateway.inference_health()["state"] == "HEALTHY"
    finally:
        gateway.server_close()
