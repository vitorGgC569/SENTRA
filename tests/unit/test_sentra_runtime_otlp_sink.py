"""Real loopback HTTP OTLP endpoint fixture; no collector or Internet needed."""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import pytest

from sentra_runtime.otlp_sink import (
    LocalOtlpExporter, SafeTelemetryEvent, TelemetryUnavailable, to_otlp,
)


@contextmanager
def collector(status=200):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received.append((self.path, self.headers.get("Content-Type"), body))
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args, **kwargs):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1/traces", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_otlp_http_e2e_json_valid_and_sanitized():
    with collector() as (url, rows):
        LocalOtlpExporter(url).emit(SafeTelemetryEvent(
            "sentra.operation", "UNCERTAIN", "secret-sensitive-operation-1", 12,
        ))
        assert len(rows) == 1
        path, kind, raw = rows[0]
        assert path == "/v1/traces"
        assert kind.startswith("application/json")
        envelope = json.loads(raw)
        span = envelope["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert span["name"] == "sentra.operation"
        assert len(span["traceId"]) == 32
        assert len(span["spanId"]) == 16
        assert "secret-sensitive-operation-1" not in raw.decode("utf-8")
        attrs = span["attributes"]
        assert [x["key"] for x in attrs] == ["sentra.operation_sha256",
                                             "sentra.operation_state"]


@pytest.mark.parametrize("status", [400, 401, 403, 500])
def test_telemetry_unavailable_on_collector_error_without_retry(status):
    with collector(status) as (url, rows):
        with pytest.raises(TelemetryUnavailable):
            LocalOtlpExporter(url).emit(SafeTelemetryEvent(
                "sentra.policy", "FAILED", "op-1",
            ))
        assert len(rows) == 1


@pytest.mark.parametrize("url", [
    "https://collector.example/v1/traces",
    "http://example.com:4318/v1/traces",
    "http://127.0.0.1:4318/metrics",
    "http://user:password@127.0.0.1:4318/v1/traces",
    "http://127.0.0.1:4318/v1/traces?token=x",
    "file:///tmp/anything",
    "http://127.0.0.1/v1/traces",
])
def test_refuses_non_loopback_or_implicit_collector(url):
    with pytest.raises(ValueError):
        LocalOtlpExporter(url)


def test_refuses_raw_untyped_secrets_and_unsupported_events():
    with pytest.raises(ValueError):
        to_otlp({"token": "sensitive"})  # not a SafeTelemetryEvent
    with pytest.raises(ValueError):
        SafeTelemetryEvent("terminal.content", "SUCCEEDED", "op-1")
    with pytest.raises(ValueError):
        SafeTelemetryEvent("sentra.operation", "DENIED", "op-1")


def test_digests_stable_for_same_operation_id():
    one = to_otlp(SafeTelemetryEvent("sentra.operation", "SUCCEEDED", "op-1"))
    two = to_otlp(SafeTelemetryEvent("sentra.operation", "SUCCEEDED", "op-1"))
    a = one["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"][0]
    b = two["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"][0]
    assert a == b


def test_failure_refuses_unavailable_collector(tmp_path):
    with collector() as (url, _):
        pass
    with pytest.raises(TelemetryUnavailable):
        LocalOtlpExporter(url, timeout_s=.1).emit(
            SafeTelemetryEvent("sentra.machine", "FAILED", "op"),
        )
