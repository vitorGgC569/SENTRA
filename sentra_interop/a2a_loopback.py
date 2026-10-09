"""Explicitly started, *loopback-only* authenticated A2A task fixture transport.

Not a public A2A implementation: HTTP/1.1 JSON subset, no TLS (127.0.0.1
only), no external agent discovery, no background daemon. Every request
requires a pre-shared test token; agent identity is fixed by the host rather
than trusted from network input. All state writes use A2ATaskBoundary.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from sentra_runtime.contracts import OperationRequest, OperationResult

from .a2a import A2AEnvelope, A2ATaskBoundary, A2AValidationError, AgentIdentity
from .gate import InteropGate
from .requests import InteropRequestMapper, InteropMappingDenied

MAX_HTTP = 65536
TASK = re.compile(r"^[a-zA-Z0-9._-]{1,128}$")


def _json(value: Any) -> bytes:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > MAX_HTTP:
        raise ValueError("response exceeds limit")
    return data


def _decode(raw: bytes) -> Mapping[str, Any]:
    def duplicate(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError("duplicate JSON key")
            out[k] = v
        return out
    parsed = json.loads(raw, object_pairs_hook=duplicate,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NaN")))
    if not isinstance(parsed, dict):
        raise ValueError("JSON object required")
    return parsed


class _LocalCancelAck:
    def __init__(self, context_id: str):
        self.context_id = context_id

    async def cancel_task(self, task_id: str) -> Mapping[str, Any]:
        # Test-owned cooperative peer: only this fixture asserts an ACK.
        return {"id": task_id, "contextId": self.context_id,
                "status": {"state": "TASK_STATE_CANCELED"}}


class A2ALoopbackServer:
    """Host-attested agent card + pinned principal/workspace, strict HTTP subset."""

    def __init__(self, gate: InteropGate, mapper: InteropRequestMapper,
                 identity: AgentIdentity, *, token: str) -> None:
        if (not isinstance(token, str) or len(token) < 32 or
            identity.principal_id != mapper.principal_id or
            mapper.machine_id != gate.machine.machine_id or
            not {"a2a:ingest", "a2a:read", "a2a:cancel"}.issubset(mapper.capabilities)):
            raise ValueError("trusted loopback identity, capabilities and token required")
        self.gate, self.mapper, self.identity = gate, mapper, identity
        self._token = token
        self.boundary = A2ATaskBoundary(gate, trusted_agents=frozenset({identity}),
                                        require_mapped_arguments=True)
        self._server: asyncio.AbstractServer | None = None
        self._event_lock = asyncio.Lock()
        self._artifacts: dict[tuple[str, str], dict[str, Any]] = {}
        self._cancel_receipts: dict[str, tuple[str, str]] = {}
        self.port: int | None = None

    async def start(self) -> "A2ALoopbackServer":
        if self._server is not None:
            raise ValueError("loopback server already started")
        self._server = await asyncio.start_server(self._handle, host="127.0.0.1", port=0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        code = 400
        response: Mapping[str, Any] = {"error": "invalid_request"}
        try:
            peer = writer.get_extra_info("peername")
            if not peer or peer[0] != "127.0.0.1":
                raise PermissionError("non-loopback client")
            headline = await asyncio.wait_for(reader.readline(), 3)
            if len(headline) > 512:
                raise ValueError("invalid request line")
            words = headline.decode("ascii").rstrip("\r\n").split(" ")
            if len(words) != 3 or words[2] != "HTTP/1.1":
                raise ValueError("invalid HTTP request")
            method, path, _ = words
            headers: dict[str, str] = {}
            for _ in range(32):
                line = await asyncio.wait_for(reader.readline(), 3)
                if not line or len(line) > 4096:
                    raise ValueError("invalid HTTP headers")
                if line == b"\r\n":
                    break
                k, sep, v = line.decode("ascii").partition(":")
                if not sep or k.lower() in headers:
                    raise ValueError("invalid or duplicate header")
                headers[k.lower()] = v.strip()
            else:
                raise ValueError("too many HTTP headers")
            bearer = headers.get("authorization", "")
            if not hmac.compare_digest(bearer.encode("utf-8"),
                                       ("Bearer " + self._token).encode("utf-8")):
                raise PermissionError("invalid credentials")
            if headers.get("transfer-encoding"):
                raise ValueError("streaming HTTP unsupported")
            if method == "POST":
                if headers.get("content-type") != "application/json":
                    raise ValueError("expected JSON")
                length = headers.get("content-length")
                if not length or not length.isdecimal() or not 0 < int(length) <= MAX_HTTP:
                    raise ValueError("invalid content length")
                body = _decode(await asyncio.wait_for(reader.readexactly(int(length)), 3))
            elif method == "GET":
                if headers.get("content-length") not in (None, "0"):
                    raise ValueError("GET body not allowed")
                body = {}
            else:
                raise ValueError("method unsupported")
            code, response = await self._route(method, path, body)
        except PermissionError:
            code, response = 401, {"error": "unauthorized"}
        except (ValueError, KeyError, TypeError, OSError, asyncio.TimeoutError,
                asyncio.IncompleteReadError, A2AValidationError, InteropMappingDenied):
            code, response = 400, {"error": "invalid_request"}
        except Exception:
            code, response = 500, {"error": "internal_error"}
        try:
            payload = _json(response)
            reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized",
                      403: "Forbidden", 404: "Not Found", 500: "Internal Server Error"}[code]
            writer.write(f"HTTP/1.1 {code} {reason}\r\nContent-Type: application/json\r\n"
                         f"Content-Length: {len(payload)}\r\nConnection: close\r\n"
                         f"Cache-Control: no-store\r\n\r\n".encode("ascii") + payload)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _route(self, method: str, path: str,
                     body: Mapping[str, Any]) -> tuple[int, Mapping[str, Any]]:
        if method == "GET" and path == "/.well-known/agent-card.json":
            return 200, {"name": self.identity.agent_id, "id": self.identity.agent_id,
                         "trustDomain": self.identity.trust_domain,
                         "url": f"http://127.0.0.1:{self.port}",
                         "capabilities": {"tasks": True, "streaming": False}}
        if method == "POST" and path == "/v1/events":
            if set(body) != {"operation_id", "idempotency_key", "event_id", "sequence", "payload"}:
                raise ValueError("unexpected event fields")
            payload = body["payload"]
            if not isinstance(payload, Mapping):
                raise ValueError("invalid event")
            task = payload.get("task", payload.get("statusUpdate", payload.get("artifactUpdate")))
            if not isinstance(task, Mapping):
                raise ValueError("invalid task")
            task_id = task.get("id") or task.get("taskId")
            current_state = await self.boundary.state(task_id)
            event = A2AEnvelope.from_stream_response(
                payload, identity=self.identity,
                authenticated_principal_id=self.mapper.principal_id,
                event_id=body["event_id"], sequence=body["sequence"],
                current_state=current_state,
            )
            request = self.mapper.a2a_event(operation_id=body["operation_id"],
                                            idempotency_key=body["idempotency_key"],
                                            event=event)
            async with self._event_lock:
                outcome = await self.boundary.accept(request, event)
                if (outcome.operation.state == "SUCCEEDED" and not outcome.duplicate
                    and event.artifact_id is not None):
                    key = (event.task_id, event.artifact_id)
                    if not event.artifact_append:
                        self._artifacts[key] = {"artifactId": event.artifact_id, "parts": [],
                                                "final": False}
                    receipt = self._artifacts[key]
                    receipt["parts"].extend([
                        {"text": part["text"]} if part["type"] == "text"
                        else {"data": dict(part["data"])}
                        for part in event.parts
                    ])
                    receipt["final"] = event.artifact_final
            return (200 if outcome.operation.state == "SUCCEEDED" else 403), {
                "state": outcome.operation.state, "duplicate": outcome.duplicate,
                "taskId": event.task_id, "taskState": await self.boundary.state(event.task_id),
            }
        if path.startswith("/v1/tasks/"):
            leaf = path[len("/v1/tasks/"):]
            cancel = leaf.endswith(":cancel")
            artifacts = leaf.endswith("/artifacts")
            task_id = (leaf[:-len(":cancel")] if cancel else
                       leaf[:-len("/artifacts")] if artifacts else leaf)
            if not TASK.fullmatch(task_id):
                raise ValueError("invalid task ID")
            if method == "GET" and not cancel:
                query = OperationRequest("read-" + task_id, self.mapper.principal_id,
                                         self.mapper.machine_id, "a2a:read",
                                         self.mapper.work_item_id, "read-" + task_id,
                                         {"task_id": task_id})
                if not (await self.gate.decision(query)).allowed:
                    return 403, {"error": "forbidden"}
                state = await self.boundary.state(task_id)
                if not state:
                    return 404, {"error": "not_found"}
                if artifacts:
                    async with self._event_lock:
                        items = [dict(receipt) for (tid, _), receipt in self._artifacts.items()
                                 if tid == task_id]
                    return 200, {"taskId": task_id, "artifacts": items}
                return 200, {"taskId": task_id, "state": state}
            if method == "POST" and cancel:
                if set(body) != {"operation_id", "idempotency_key", "task_id"} or body["task_id"] != task_id:
                    raise ValueError("cancel scope mismatch")
                request = self.mapper.make(
                    operation_id=body["operation_id"], idempotency_key=body["idempotency_key"],
                    capability_id="a2a:cancel",
                    arguments={"task_id": task_id, "context_id": self.mapper.work_item_id},
                )
                async with self._event_lock:
                    receipt = self._cancel_receipts.get(request.operation_id)
                    if receipt is not None:
                        if (receipt != (request.idempotency_key, task_id)
                            or not (await self.gate.decision(request)).allowed):
                            return 403, {"error": "forbidden"}
                        return 200, {"state": "CANCELLED", "taskId": task_id,
                                     "taskState": await self.boundary.state(task_id),
                                     "duplicate": True}
                    outcome = await self.boundary.cancel(
                        request, task_id=task_id,
                        transport=_LocalCancelAck(self.mapper.work_item_id),
                    )
                    if outcome.operation.state == "CANCELLED":
                        self._cancel_receipts[request.operation_id] = (
                            request.idempotency_key, task_id)
                return (200 if outcome.operation.state == "CANCELLED" else 403), {
                    "state": outcome.operation.state, "taskId": task_id,
                    "taskState": await self.boundary.state(task_id), "duplicate": False,
                }
        return 404, {"error": "not_found"}


class A2ALoopbackClient:
    """Real network HTTP client for tests; never follows redirects or uses proxies."""

    def __init__(self, *, port: int, token: str) -> None:
        if type(port) is not int or not 1 <= port <= 65535 or not token:
            raise ValueError("explicit loopback endpoint and credentials required")
        self.port, self._token = port, token

    async def request(self, method: str, path: str, body: Mapping[str, Any] | None = None,
                      *, token_override: str | None = None) -> tuple[int, Mapping[str, Any]]:
        if method not in {"GET", "POST"} or not path.startswith("/") or "?" in path:
            raise ValueError("unsupported local HTTP operation")
        payload = _json(body or {}) if method == "POST" else b""
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", self.port), 3)
        try:
            auth = token_override if token_override is not None else self._token
            writer.write(f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                         f"Authorization: Bearer {auth}\r\n"
                         f"Content-Length: {len(payload)}\r\n"
                         "Content-Type: application/json\r\nConnection: close\r\n\r\n"
                         .encode("utf-8") + payload)
            await writer.drain()
            headline = await asyncio.wait_for(reader.readline(), 3)
            bits = headline.decode("ascii").split(" ", 2)
            if len(bits) < 2 or bits[0] != "HTTP/1.1":
                raise ValueError("invalid local HTTP response")
            headers = {}
            for _ in range(32):
                line = await asyncio.wait_for(reader.readline(), 3)
                if line == b"\r\n":
                    break
                k, _, v = line.decode("ascii").partition(":")
                headers[k.lower()] = v.strip()
            n = int(headers["content-length"])
            if n > MAX_HTTP:
                raise ValueError("HTTP result oversized")
            return int(bits[1]), _decode(await asyncio.wait_for(reader.readexactly(n), 3))
        finally:
            writer.close()
            await writer.wait_closed()
