"""Activepieces-like action connector: authenticated localhost HTTP ONLY.

This is a local, explicit integration contract, not Activepieces' native API.
No external SaaS, secrets vault, webhooks reachable from another host or
unreviewed automation flows. The SENTRA gate authorizes *both* ends.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import re
from typing import Any, Awaitable, Callable, Mapping

from sentra_runtime.contracts import OperationRequest, OperationResult
from .gate import InteropGate, DispatchOutcome, _fingerprint, EffectRejected
from .requests import _bounded, InteropMappingDenied

ACTION = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
MAX_HTTP = 32768


def _encode(obj: Mapping[str, Any]) -> bytes:
    value = json.dumps(obj, allow_nan=False, ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8")
    if len(value) > MAX_HTTP:
        raise ValueError("action HTTP payload too large")
    return value


def _decode(payload: bytes) -> Mapping[str, Any]:
    def unique(pairs):
        fields = {}
        for k, v in pairs:
            if k in fields:
                raise ValueError("duplicate action JSON field")
            fields[k] = v
        return fields
    value = json.loads(payload, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if not isinstance(value, dict):
        raise ValueError("action JSON object required")
    return value


class ActivepiecesLoopbackServer:
    def __init__(self, gate: InteropGate, *, principal_id: str, workspace_id: str,
                 token: str, handlers: Mapping[str, Callable[[Mapping[str, Any]],
                                                              Awaitable[Mapping[str, Any]]]],
                 allowlist: Mapping[str, frozenset[str]]) -> None:
        if (not isinstance(token, str) or len(token) < 32
            or not principal_id or not workspace_id or not handlers
            or set(handlers) != set(allowlist)
            or any(not ACTION.fullmatch(x) or not isinstance(allowlist[x], frozenset)
                   for x in handlers)):
            raise ValueError("invalid trusted Activepieces fixture configuration")
        self.gate, self.principal_id, self.workspace_id = gate, principal_id, workspace_id
        self._token, self._handlers, self._allowlist = token, dict(handlers), dict(allowlist)
        self._server = None
        self.port: int | None = None
        self._counts: dict[str, int] = {}

    async def start(self) -> "ActivepiecesLoopbackServer":
        if self._server is not None:
            raise ValueError("already started")
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @property
    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        code, result = 400, {"error": "invalid_request"}
        try:
            if writer.get_extra_info("peername")[0] != "127.0.0.1":
                raise PermissionError()
            line = (await asyncio.wait_for(reader.readline(), 3)).decode("ascii")
            method, path, version = line.rstrip("\r\n").split(" ")
            if method != "POST" or version != "HTTP/1.1" or not path.startswith("/v1/actions/"):
                raise ValueError("unapproved endpoint")
            action = path[len("/v1/actions/"):]
            if action not in self._handlers:
                raise ValueError("unapproved action")
            headers = {}
            for _ in range(24):
                line = await asyncio.wait_for(reader.readline(), 3)
                if line == b"\r\n":
                    break
                if not line or len(line) > 2048:
                    raise ValueError("invalid header")
                key, sep, value = line.decode("ascii").partition(":")
                if not sep or key.lower() in headers:
                    raise ValueError("duplicate or malformed header")
                headers[key.lower()] = value.strip()
            else:
                raise ValueError("excess HTTP headers")
            authorization = headers.get("authorization", "")
            if not hmac.compare_digest(authorization.encode("utf-8"),
                                       ("Bearer " + self._token).encode("utf-8")):
                raise PermissionError()
            if headers.get("content-type") != "application/json" or headers.get("transfer-encoding"):
                raise ValueError("unsupported transfer encoding")
            n = headers.get("content-length", "")
            if not n.isdecimal() or not 0 < int(n) <= MAX_HTTP:
                raise ValueError("invalid request size")
            payload = _decode(await asyncio.wait_for(reader.readexactly(int(n)), 3))
            if set(payload) != {"operation_id", "idempotency_key", "arguments"}:
                raise ValueError("invalid action envelope")
            args = payload["arguments"]
            if not isinstance(args, Mapping) or set(args) - self._allowlist[action]:
                raise ValueError("action arguments not allowlisted")
            args = _bounded(args)
            request = OperationRequest(payload["operation_id"], self.principal_id,
                                       self.gate.machine.machine_id, "activepieces:" + action,
                                       self.workspace_id, payload["idempotency_key"],
                                       {"action": action, "arguments": args})
            async def run() -> Mapping[str, Any]:
                # The server gate and journal are independent of the client.
                self._counts[action] = self._counts.get(action, 0) + 1
                return await self._handlers[action](args)
            outcome = await self.gate.execute(request, run, timeout=3)
            if outcome.operation.state == "SUCCEEDED" and not outcome.duplicate:
                if not isinstance(outcome.payload, Mapping):
                    raise ValueError("malformed connector action response")
                # A malformed response after the side effect is UNCERTAIN.
                try:
                    data = _bounded(outcome.payload)
                except (InteropMappingDenied, TypeError, ValueError):
                    data = None
                if data is None or set(data) != {"value"} or not isinstance(data["value"], str):
                    outcome = DispatchOutcome(OperationResult(request.operation_id, "UNCERTAIN",
                                                                error="invalid remote result"))
                    await self.gate.journal.finish(request, outcome.operation)
            elif outcome.duplicate:
                # A duplicate succeeded earlier but the result is intentionally
                # NOT cached: report receipt, not a fabricated response.
                data = None
            else:
                data = None
            result = {"state": outcome.operation.state, "duplicate": outcome.duplicate,
                      "value": data["value"] if data is not None else None}
            code = 200 if outcome.operation.state == "SUCCEEDED" else 403
        except PermissionError:
            code, result = 401, {"error": "unauthorized"}
        except (ValueError, KeyError, TypeError, InteropMappingDenied,
                asyncio.TimeoutError, asyncio.IncompleteReadError):
            code, result = 400, {"error": "invalid_request"}
        except Exception:
            code, result = 500, {"error": "internal_error"}
        try:
            data = _encode(result)
            writer.write(f"HTTP/1.1 {code} OK\r\nContent-Type: application/json\r\n"
                         f"Content-Length: {len(data)}\r\nConnection: close\r\n"
                         "Cache-Control: no-store\r\n\r\n".encode("ascii") + data)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


class ActivepiecesActionClient:
    """Explicit local action invoker. Never retries after timeout/unknown state."""

    def __init__(self, gate: InteropGate, *, server_port: int, token: str,
                 allowed_actions: Mapping[str, frozenset[str]]) -> None:
        if (type(server_port) is not int or not 0 < server_port < 65536
            or not isinstance(token, str) or len(token) < 32):
            raise ValueError("invalid local Activepieces endpoint")
        self.gate, self.port, self._token = gate, server_port, token
        self._allowlist = dict(allowed_actions)

    async def call(self, request: OperationRequest, *, action: str,
                   arguments: Mapping[str, Any], timeout: float = 1) -> DispatchOutcome:
        if (action not in self._allowlist or timeout <= 0
            or not isinstance(arguments, Mapping)
            or set(arguments) - self._allowlist[action]
            or request.capability_id != "activepieces:" + action
            or request.arguments != {"action": action, "arguments": dict(arguments)}):
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED",
                                                   error="action not allowlisted"))
        try:
            clean = _bounded(arguments)
        except (InteropMappingDenied, TypeError, ValueError):
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED",
                                                   error="invalid action payload"))

        async def dispatch() -> Mapping[str, Any]:
            reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
            try:
                payload = _encode({"operation_id": request.operation_id,
                                   "idempotency_key": request.idempotency_key,
                                   "arguments": clean})
                writer.write(f"POST /v1/actions/{action} HTTP/1.1\r\n"
                             f"Host: 127.0.0.1\r\nAuthorization: Bearer {self._token}\r\n"
                             f"Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n"
                             "Connection: close\r\n\r\n".encode("ascii") + payload)
                await writer.drain()
                headline = await reader.readline()
                parts = headline.decode("ascii").split(" ", 2)
                if len(parts) != 3 or parts[0] != "HTTP/1.1" or parts[1] != "200":
                    raise ValueError("remote action refused or uncertain")
                headers = {}
                for _ in range(24):
                    line = await reader.readline()
                    if line == b"\r\n":
                        break
                    if not line or len(line) > 2048:
                        raise ValueError("invalid response header")
                    k, sep, v = line.decode("ascii").partition(":")
                    if not sep or k.lower() in headers:
                        raise ValueError("malformed response header")
                    headers[k.lower()] = v.strip()
                count = headers.get("content-length", "")
                if not count.isdecimal() or not 0 < int(count) <= MAX_HTTP:
                    raise ValueError("malformed response size")
                result = _decode(await reader.readexactly(int(count)))
                if (set(result) != {"state", "duplicate", "value"}
                    or result["state"] != "SUCCEEDED"
                    or not isinstance(result["duplicate"], bool)
                    or result["duplicate"]
                    or not isinstance(result["value"], str)):
                    raise ValueError("malformed or duplicate action reply")
                return {"value": result["value"]}
            finally:
                writer.close()
                await writer.wait_closed()

        # Re-check the grant at dispatch start AND again after remote response.
        # Side effects with corrupt/missing result are UNCERTAIN, never retried.
        return await self.gate.execute(request, dispatch, timeout=timeout)
