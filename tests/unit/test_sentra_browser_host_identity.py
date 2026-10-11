"""Host snapshots authenticate observations without promoting account proof."""
import json
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sentra_model_gateway.browser_host_identity import read_host_identity, read_host_message


@pytest.mark.parametrize("endpoint", [
    "http://example.com:80", "https://127.0.0.1:17841", "http://user@127.0.0.1:80",
    "http://127.0.0.1:80/other", "http://127.0.0.1:80?token=bad", "http://127.0.0.1:80#bad",
])
def test_host_identity_rejects_untrusted_endpoints_before_credentials(monkeypatch, endpoint):
    def forbidden(*_args, **_kwargs):
        pytest.fail("untrusted endpoint attempted a connection")
    monkeypatch.setattr("http.client.HTTPConnection", forbidden)
    with pytest.raises(PermissionError):
        read_host_identity({"control": {"endpoint": endpoint, "token": "a" * 48}}, {}, trace_id="trace")


@pytest.mark.parametrize("mutation", [None, "document_id", "identity_epoch", "surface_id", "collector_id", "collector_sha256", "oversized"])
def test_actual_host_http_snapshot_preserves_unknown_account_and_rejects_identity_change(mutation):
    observed = {}
    snapshot = {"ok": True, "surface_id": "surface", "document_id": "document", "identity_epoch": "epoch",
                "collector_id": "collector", "collector_sha256": "b" * 64, "account_verified": False}
    if mutation == "oversized":
        snapshot["padding"] = "x" * 128001
    elif mutation:
        snapshot[mutation] = "changed"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def do_POST(self):
            observed["path"] = self.path
            observed["auth"] = self.headers.get("Authorization")
            observed["request"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps(snapshot).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    descriptor = {"control": {"endpoint": f"http://127.0.0.1:{server.server_port}", "token": "a" * 48},
                  "sentraIdentityCollector": {"id": "collector", "sha256": "b" * 64}}
    tab = {"surfaceId": "surface", "documentId": "document", "identityEpoch": "epoch"}
    try:
        if mutation:
            with pytest.raises(PermissionError):
                read_host_identity(descriptor, tab, trace_id="trace")
        else:
            assert read_host_identity(descriptor, tab, trace_id="trace")["account_verified"] is False
        assert observed["path"] == "/v1/sentra/identity-snapshot"
        assert observed["auth"] == "Bearer " + "a" * 48
        assert observed["request"] == {"traceId": "trace", "surface_id": "surface", "document_id": "document", "identity_epoch": "epoch"}
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


@pytest.mark.parametrize("mutation", [None, "challenge_sha256", "matched", "role", "document_id", "identity_epoch",
                                    "message_id", "observed_request_id", "parent_user_message_id", "body_sha256",
                                    "host_revision", "complete", "collector_sha256"])
def test_host_message_challenge_cannot_substitute_role_parent_body_or_revision(mutation):
    expected = {"role": "assistant", "conversation_id": "conversation-one", "message_id": "assistant-one",
                "request_id": "request-one", "parent_user_message_id": "user-one",
                "body_sha256": "c" * 64, "revision": 17, "complete": True}
    observed_requests = []
    nonce = "d" * 32

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            observed_requests.append((self.path, value))
            if self.path == "/v1/sentra/message-challenge":
                self.server.digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                result = {"ok": True, "state": "CHALLENGED", "challenge_id": nonce,
                          "challenge_sha256": self.server.digest}
            else:
                assert value == {"challenge_id": nonce}
                result = {"ok": True, "state": "OBSERVED", "matched": True, "challenge_id": nonce,
                    "challenge_sha256": self.server.digest, "role": "assistant", "surface_id": "surface-one",
                    "document_id": "doc-one", "identity_epoch": "epoch-one", "conversation_id": "conversation-one",
                    "message_id": "assistant-one", "observed_request_id": "request-one", "parent_user_message_id": "user-one",
                    "body_sha256": "c" * 64, "host_revision": 2, "revision_source": "host-observation", "complete": True,
                    "collector_id": "message-collector", "collector_sha256": "b" * 64, "account_verified": False}
                if mutation:
                    result[mutation] = {"matched": False, "host_revision": 0, "complete": False}.get(mutation, "changed")
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    descriptor = {"control": {"endpoint": f"http://127.0.0.1:{server.server_port}", "token": "a" * 48},
                  "sentraMessageCollector": {"id": "message-collector", "sha256": "b" * 64}}
    tab = {"surfaceId": "surface-one", "documentId": "doc-one", "identityEpoch": "epoch-one"}
    try:
        if mutation:
            with pytest.raises(PermissionError):
                read_host_message(descriptor, tab, trace_id="trace-one", expected=expected)
        else:
            assert read_host_message(descriptor, tab, trace_id="trace-one", expected=expected)["account_verified"] is False
        assert len(observed_requests) == 2
        assert "body" not in observed_requests[0][1]  # Only fingerprint, never raw message.
        assert "revision" not in observed_requests[0][1]  # Host observes its own revision.
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
