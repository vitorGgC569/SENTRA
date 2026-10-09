"""Phase 2 slice 2: actual authenticated loopback TCP client/server fixture E2E."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import socket
import threading
import time

import pytest

from sentra_runtime.contracts import OperationRequest, PolicyDecision
from sentra_runtime.executor import AuthorizationRequired, ExecutorRegistry
from sentra_executors import RemoteReadBinding, declare_remote_readonly_machine
from sentra_executors.remote_readonly import _mac, _recv, _send


def run(c):
    return asyncio.run(c)


class Grant:
    allowed = True
    calls = 0
    def __call__(self, req):
        self.calls += 1
        return PolicyDecision(self.allowed, "test-only grant")


class AuthenticatedFixtureServer:
    """One authorized peer, stdlib TCP, strict read-only protocol only."""

    def __init__(self, secret, *, wrong_server_key=False, wrong_reply=False, stall=0):
        self.secret = secret
        self.wrong_server_key = wrong_server_key
        self.wrong_reply = wrong_reply
        self.stall = stall
        self.actions = []
        self.errors = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.sock.settimeout(3)
        self.port = self.sock.getsockname()[1]
        self.finished = threading.Event()
        self.worker = threading.Thread(target=self.handle, daemon=True)
        self.worker.start()

    def handle(self):
        try:
            with self.sock:
                conn, addr = self.sock.accept()
                assert addr[0] == "127.0.0.1"
                with conn:
                    conn.settimeout(2)
                    hello = _recv(conn)
                    assert set(hello) == {"v", "machine", "nonce"}
                    assert hello["v"] == 1 and hello["machine"] == "peer-lab"
                    nonce = hello["nonce"]
                    server_nonce = secrets.token_hex(16)
                    key = b"invalid-key" if self.wrong_server_key else self.secret
                    proof = _mac(key, f"server|peer-lab|{nonce}|{server_nonce}")
                    _send(conn, {"v": 1, "nonce": server_nonce, "proof": proof})
                    try:
                        request = _recv(conn)
                    except (ConnectionError, TimeoutError):
                        return
                    if set(request) != {"v", "method", "nonce", "server_nonce", "proof"}:
                        return
                    if request["nonce"] != nonce or request["server_nonce"] != server_nonce:
                        return
                    if request["method"] not in {"read.status", "read.frame_digest"}:
                        return
                    expected = _mac(self.secret, f"client|peer-lab|{nonce}|{server_nonce}|{request['method']}")
                    if not hmac.compare_digest(expected, request["proof"]):
                        return
                    self.actions.append(request["method"])
                    if self.stall:
                        time.sleep(self.stall)
                    if request["method"] == "read.status":
                        result = {"state": "ready"}
                    else:
                        result = {"frame_sha256": hashlib.sha256(b"test-owned-frame").hexdigest()}
                    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"))
                    reply_key = b"wrong-server-key" if self.wrong_reply else self.secret
                    signature = _mac(reply_key, f"reply|peer-lab|{nonce}|{server_nonce}|{canonical}")
                    _send(conn, {"v": 1, "result": result, "proof": signature})
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        except Exception as exc:
            self.errors.append(type(exc).__name__)
        finally:
            self.finished.set()

    def close(self):
        self.finished.wait(3)
        self.worker.join(3)
        self.sock.close()


def client(port, secret, *, timeout=1.0, grant=None):
    grant = grant or Grant()
    binding = RemoteReadBinding(
        capability_id="remote-read", machine_peer="peer-lab",
        port=port, shared_secret=secret, timeout_seconds=timeout)
    declaration = declare_remote_readonly_machine(
        machine_id="remote-lab", owner_principal_id="lab",
        bindings=(binding,), policy=grant)
    registry = ExecutorRegistry(authorize=grant)
    declaration.register(registry)
    return registry, grant, declaration


def request(action="read_status", op="remote-1"):
    return OperationRequest(
        operation_id=op, principal_id="lab", machine_id="remote-lab",
        capability_id="remote-read", work_item_id="work", idempotency_key=op,
        arguments={"action": action})


@pytest.mark.parametrize("action,method,key", [
    ("read_status", "read.status", "state"),
    ("read_frame_digest", "read.frame_digest", "frame_sha256"),
])
def test_authenticated_real_socket_readonly_registry_e2e(action, method, key):
    secret = secrets.token_bytes(32)
    server = AuthenticatedFixtureServer(secret)
    try:
        registry, grant, decl = client(server.port, secret)
        assert [x.capability_id for x in run(decl.discover())] == ["remote-read"]
        result = run(registry.submit(request(action)))
        assert result.state == "SUCCEEDED"
        assert key in result.evidence
        assert server.actions == [method]
        assert run(registry.submit(request(action))).state == "SUCCEEDED"
        assert server.actions == [method]  # no second socket invocation
        grant.allowed = False
        with pytest.raises(AuthorizationRequired):
            run(registry.submit(request(action)))
        assert server.actions == [method]
    finally:
        server.close()
    assert server.errors == []


@pytest.mark.parametrize("action", [
    "mouse.click", "keyboard.type", "send_clipboard", "exec", "take_screenshot",
])
def test_remote_rejects_input_operations_before_socket(action):
    secret = secrets.token_bytes(32)
    registry, grant, _ = client(9999, secret)
    outcome = run(registry.submit(request(action)))
    assert outcome.state == "FAILED"
    assert outcome.error == "invalid_scope_or_capability"


@pytest.mark.parametrize("host,secret,port", [
    ("192.168.1.1", b"z"*32, 20001),
    ("example.com", b"z"*32, 20001),
    ("127.0.0.1", b"weak", 20001),
    ("127.0.0.1", b"z"*32, True),
])
def test_remote_rejects_non_loopback_and_weak_secrets(host, secret, port):
    with pytest.raises(ValueError, match="invalid_remote_session_binding"):
        RemoteReadBinding("remote-read", "peer-lab", port, secret, host=host)


def test_remote_binding_repr_never_contains_key():
    secret = b"ULTRA_PRIVATE_TEST_KEY_ABC-123456"
    binding = RemoteReadBinding("remote-read", "peer-lab", 12345, secret)
    assert secret.decode() not in repr(binding)


def test_wrong_server_key_cannot_authenticate():
    secret = secrets.token_bytes(32)
    server = AuthenticatedFixtureServer(secret, wrong_server_key=True)
    try:
        registry, grant, _ = client(server.port, secret)
        result = run(registry.submit(request()))
        assert result.state == "FAILED" and result.error == "backend_error"
        assert server.actions == []
    finally:
        server.close()
    assert server.errors == []


def test_tampered_reply_is_rejected():
    secret = secrets.token_bytes(32)
    server = AuthenticatedFixtureServer(secret, wrong_reply=True)
    try:
        registry, _, _ = client(server.port, secret)
        result = run(registry.submit(request()))
        assert result.state == "FAILED" and result.error == "backend_error"
        assert server.actions == ["read.status"]
        assert result.evidence == {}
    finally:
        server.close()


def test_timeout_is_uncertain_without_double_remote_request():
    secret = secrets.token_bytes(32)
    server = AuthenticatedFixtureServer(secret, stall=0.3)
    try:
        registry, _, _ = client(server.port, secret, timeout=.06)
        first = run(registry.submit(request()))
        assert first.state == "UNCERTAIN"
        retry = run(registry.submit(request()))
        assert retry.state == "UNCERTAIN"
    finally:
        server.close()
    assert server.actions == ["read.status"]
