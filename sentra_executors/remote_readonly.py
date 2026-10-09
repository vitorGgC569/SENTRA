"""Read-only loopback remote-session gateway; Guacamole/RustDesk-inspired boundary.

NOT a Guacamole or RustDesk protocol implementation. TCP stdlib handshake
authenticates both peers via HMAC; transport never accepts mouse, keyboard,
clipboard, command execution, host names or user account credentials.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import socket
import time
from dataclasses import dataclass, field

from sentra_runtime.contracts import Capability, Machine
from ._base import GuardedExecutor
from .rpa import effect_checkpoint


def _mac(secret: bytes, payload: str) -> str:
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _send(sock, message: dict):
    effect_checkpoint()
    data = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode()
    if len(data) > 2048:
        raise RuntimeError("remote_message_too_large")
    sock.sendall(data + b"\n")


def _recv(sock) -> dict:
    effect_checkpoint()
    duration=sock.gettimeout() or 3.0
    deadline=time.monotonic()+duration
    data = bytearray()
    while len(data) <= 2048:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('bounded_remote_read_timeout')
        sock.settimeout(remaining)
        c = sock.recv(1)
        if c == b"\n":
            break
        if not c:
            raise ConnectionError("remote_socket_closed")
        data.extend(c)
    else:
        raise RuntimeError("remote_message_too_large")
    obj = json.loads(data.decode("ascii"))
    if type(obj) is not dict:
        raise ValueError("remote_invalid_message")
    return obj


@dataclass(frozen=True)
class RemoteReadBinding:
    capability_id: str
    machine_peer: str
    port: int
    shared_secret: bytes = field(repr=False, compare=False)
    timeout_seconds: float = 3.0
    host: str = "127.0.0.1"

    def __post_init__(self):
        if (not self.capability_id or not self.machine_peer or
                self.host != "127.0.0.1" or
                type(self.port) is not int or not 1 <= self.port <= 65535 or
                type(self.shared_secret) is not bytes or len(self.shared_secret) < 32 or
                not 0 < self.timeout_seconds <= 10):
            raise ValueError("invalid_remote_session_binding")


class AuthenticatedLoopbackTransport:
    """Only trusted 127.0.0.1 endpoint, fresh nonces, exact frame/status API."""

    def run(self, binding: RemoteReadBinding, arguments: dict) -> dict:
        action = arguments["action"]
        method = {"read_status": "read.status",
                  "read_frame_digest": "read.frame_digest"}[action]
        client_nonce = secrets.token_hex(16)
        effect_checkpoint()
        with socket.create_connection(("127.0.0.1", binding.port),
                                      timeout=binding.timeout_seconds) as sock:
            sock.settimeout(binding.timeout_seconds)
            _send(sock, {"v": 1, "machine": binding.machine_peer,
                         "nonce": client_nonce})
            reply = _recv(sock)
            if (set(reply) != {"v", "nonce", "proof"} or reply["v"] != 1 or
                    not isinstance(reply["nonce"], str) or
                    not re.fullmatch(r"[0-9a-f]{32}", reply["nonce"])):
                raise PermissionError("remote_server_untrusted")
            server_nonce = reply["nonce"]
            expected = _mac(binding.shared_secret,
                            f"server|{binding.machine_peer}|{client_nonce}|{server_nonce}")
            if (type(reply["proof"]) is not str or
                    not hmac.compare_digest(reply["proof"], expected)):
                raise PermissionError("remote_server_untrusted")
            signature = _mac(binding.shared_secret,
                             f"client|{binding.machine_peer}|{client_nonce}|{server_nonce}|{method}")
            _send(sock, {"v": 1, "method": method, "nonce": client_nonce,
                         "server_nonce": server_nonce, "proof": signature})
            result = _recv(sock)
            if (set(result) != {"v", "result", "proof"} or
                    result["v"] != 1 or type(result["result"]) is not dict):
                raise PermissionError("remote_reply_invalid")
            data = result["result"]
            if method == "read.status":
                if set(data) != {"state"} or data["state"] not in {
                        "ready", "busy", "offline"}:
                    raise PermissionError("remote_status_not_allowlisted")
            else:
                if (set(data) != {"frame_sha256"} or
                        type(data["frame_sha256"]) is not str or
                        not re.fullmatch(r"[0-9a-f]{64}", data["frame_sha256"])):
                    raise PermissionError("remote_frame_digest_invalid")
            canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
            proof = _mac(binding.shared_secret,
                         f"reply|{binding.machine_peer}|{client_nonce}|{server_nonce}|{canonical}")
            if (type(result["proof"]) is not str or
                    not hmac.compare_digest(result["proof"], proof)):
                raise PermissionError("remote_reply_untrusted")
            return data


class RemoteReadOnlyExecutor(GuardedExecutor):
    kind = "remote_readonly"

    def __init__(self, *, machine_id: str, owner_principal_id: str,
                 bindings: tuple[RemoteReadBinding, ...], policy=None,
                 transport=None):
        if len({b.capability_id for b in bindings}) != len(bindings):
            raise ValueError("duplicate_remote_capability")
        super().__init__(machine_id=machine_id, owner_principal_id=owner_principal_id,
                         bindings={b.capability_id: b for b in bindings},
                         policy=policy)
        self.transport = transport if transport is not None else AuthenticatedLoopbackTransport()

    def _validate(self, request, binding: RemoteReadBinding):
        args = dict(request.arguments)
        if (set(args) != {"action"} or args["action"] not in
                {"read_status", "read_frame_digest"}):
            raise ValueError("remote_read_only_actions")
        return args

    def _execute(self, binding, arguments):
        return self.transport.run(binding, arguments)


def declare_remote_readonly_machine(*, machine_id: str, owner_principal_id: str,
                                    bindings: tuple[RemoteReadBinding, ...],
                                    policy, transport=None):
    from .discovery import MachineDeclaration
    machine = Machine(
        machine_id, "remote_readonly", owner_principal_id,
        tuple(Capability(b.capability_id, "Authenticated read-only remote session",
                         "high") for b in bindings))
    executor = RemoteReadOnlyExecutor(
        machine_id=machine_id, owner_principal_id=owner_principal_id,
        bindings=bindings, policy=policy, transport=transport)
    return MachineDeclaration(machine, executor)
