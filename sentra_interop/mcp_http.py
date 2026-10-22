"""Bound MCP Streamable HTTP on literal loopback, with stateless compatibility.

One POST per RPC. No retry after ambiguous effect. SSE events bounded;
sessions are bound to this authorized client's lifetime and never cached
between WorkItems. No cookies, redirects, DNS, proxies or ambient bearer.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import re
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

from sentra_interop.mcp_stdio import _decode, _encode
from sentra_runtime.contracts import OperationRequest

MAX_REPLY = 262_144
_SESSION = re.compile(r"[A-Za-z0-9._~-]{1,128}\Z")
_TOOL = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")


class MCPHttpError(ValueError):
    pass


def _sse(response):
    """Read a single complete bounded MCP message event; no event replay."""
    total = 0
    data, kind = [], "message"
    while True:
        # HTTPResponse decodes transfer chunks; reading fp directly would feed
        # hexadecimal chunk sizes into the SSE parser and skip its framing.
        line = response.readline(MAX_REPLY + 1)
        total += len(line)
        if not line or total > MAX_REPLY:
            raise MCPHttpError("MCP SSE event truncated or oversized")
        if line in (b"\n", b"\r\n"):
            if kind != "message" or not data:
                raise MCPHttpError("unsupported MCP SSE event")
            return b"\n".join(data)
        if line.startswith(b":"):
            continue
        if line.startswith(b"event:"):
            kind = line[6:].strip().decode("ascii", "strict")
        elif line.startswith(b"data:"):
            data.append(line[5:].lstrip(b" ").rstrip(b"\r\n"))
        elif line.startswith((b"id:", b"retry:")):
            # Event IDs are intentionally not used for tool-call resends.
            continue
        else:
            raise MCPHttpError("unexpected MCP SSE field")


class LoopbackMCPHttpClient:
    requires_authorized_call = True

    def __init__(self, endpoint: str, gate, *, server_id: str,
                 access_token: Callable[[], str | None] | None = None,
                 streamable: bool = False):
        if not isinstance(endpoint, str) or len(endpoint) > 2048:
            raise MCPHttpError("invalid MCP HTTP endpoint")
        parsed = urlsplit(endpoint)
        try:
            port = parsed.port
        except ValueError as exc:
            raise MCPHttpError("invalid MCP HTTP port") from exc
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not parsed.path.startswith("/") or "//" in parsed.path
                or port is None or not 1 <= port <= 65535):
            raise MCPHttpError("only literal-IP loopback MCP HTTP is admitted")
        if not isinstance(server_id, str) or not 1 <= len(server_id) <= 128:
            raise MCPHttpError("invalid MCP server identity")
        if access_token is not None and not callable(access_token):
            raise MCPHttpError("OAuth token accessor must be host-owned callable")
        if type(streamable) is not bool:
            raise MCPHttpError("MCP streamable mode must be operator-selected")
        self._host, self._port, self._path = parsed.hostname, port, parsed.path
        self._gate, self.server_id = gate, server_id
        self._access_token = access_token
        self._next_id = 0
        self._lock = asyncio.Lock()
        self._initialized = False
        self._closed = False
        self._uncertain = False
        self._streamable = streamable
        self._session_id: str | None = None

    @property
    def session_active(self):
        return self._initialized and not self._closed and not self._uncertain

    def _exchange(self, packet: bytes, timeout: float, *, notify=False):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream" if self._streamable else "application/json",
            "MCP-Protocol-Version": "2025-06-18",
        }
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        if self._access_token is not None:
            secret = self._access_token()
            if (not isinstance(secret, str) or not 1 <= len(secret) <= 4096
                    or not secret.isascii() or re.search(r"[\s\x00-\x1f\x7f]", secret)):
                raise MCPHttpError("ephemeral OAuth credential unavailable")
            headers["Authorization"] = "Bearer " + secret
        connection = http.client.HTTPConnection(self._host, self._port, timeout=timeout)
        try:
            connection.request("POST", self._path, body=packet.rstrip(b"\n"), headers=headers)
            response = connection.getresponse()
            if notify:
                if response.status != 202 or response.read(1):
                    raise MCPHttpError("MCP initialized notification not acknowledged")
                return b""
            if response.status != 200:
                raise MCPHttpError("MCP HTTP peer refused request")
            session = response.getheader("Mcp-Session-Id")
            if session is not None:
                if (not self._streamable or not _SESSION.fullmatch(session)
                        or self._session_id is not None and session != self._session_id):
                    raise MCPHttpError("MCP HTTP session identity changed")
                self._session_id = session
            content_type = response.getheader("Content-Type", "").split(";")[0].strip().lower()
            size = response.getheader("Content-Length")
            if size is not None and (not size.isdigit() or int(size) > MAX_REPLY):
                raise MCPHttpError("MCP HTTP response length invalid")
            if content_type == "text/event-stream" and self._streamable:
                return _sse(response)
            if content_type != "application/json":
                raise MCPHttpError("MCP HTTP unsupported response framing")
            body = response.read(MAX_REPLY + 1)
            if len(body) > MAX_REPLY:
                raise MCPHttpError("MCP HTTP reply exceeds size limit")
            if size is not None and len(body) != int(size):
                raise MCPHttpError("MCP HTTP response truncated")
            return body
        except (OSError, http.client.HTTPException, TimeoutError) as exc:
            raise MCPHttpError("MCP transport unavailable; response is uncertain") from None
        finally:
            connection.close()

    async def _call(self, method: str, params: Mapping, timeout: float = 5):
        if (self._closed or self._uncertain or method not in
                {"initialize", "tools/list", "tools/call"} or not 0 < timeout <= 30):
            raise MCPHttpError("MCP HTTP operation not admitted")
        async with self._lock:
            self._next_id += 1
            req_id = self._next_id
            packet = _encode({"jsonrpc": "2.0", "id": req_id,
                              "method": method, "params": dict(params)})
            try:
                body = await asyncio.to_thread(self._exchange, packet, timeout)
                msg = _decode(body)
                if type(msg.get("id")) is not int or msg["id"] != req_id:
                    raise MCPHttpError("MCP HTTP JSON-RPC response identity mismatch")
                if ("result" in msg) == ("error" in msg):
                    raise MCPHttpError("ambiguous MCP HTTP response")
                if "error" in msg:
                    raise MCPHttpError("MCP HTTP JSON-RPC peer error")
                if not isinstance(msg["result"], Mapping):
                    raise MCPHttpError("invalid MCP HTTP result object")
                return dict(msg["result"])
            except BaseException:
                # We cannot know if remote tool effect completed. This client
                # must not send a second message after any ambiguity.
                self._uncertain = True
                raise

    async def initialize(self, request: OperationRequest):
        if (self._initialized or request.capability_id != "mcp:http-connect"
                or request.arguments != {"server_id": self.server_id}
                or not (await self._gate.decision(request)).allowed):
            raise MCPHttpError("MCP HTTP connection grant denied or already initialized")
        response = await self._call("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "sentra-http", "version": "1.0"},
        })
        if response.get("protocolVersion") != "2025-06-18":
            self._uncertain = True
            raise MCPHttpError("MCP HTTP protocol version unsupported")
        if self._streamable:
            packet = _encode({"jsonrpc": "2.0", "method": "notifications/initialized"})
            try:
                await asyncio.to_thread(self._exchange, packet, 5, notify=True)
            except BaseException:
                self._uncertain = True
                raise
        self._initialized = True

    async def list_tools(self, request: OperationRequest):
        if (not self.session_active or request.capability_id != "mcp:list"
                or request.arguments != {"server_id": self.server_id}
                or not (await self._gate.decision(request)).allowed):
            raise MCPHttpError("MCP HTTP discovery grant denied")
        result = await self._call("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list) or len(tools) > 128:
            raise MCPHttpError("invalid MCP HTTP tools list")
        names = []
        for item in tools:
            if not isinstance(item, Mapping) or not _TOOL.fullmatch(item.get("name", "")):
                raise MCPHttpError("invalid MCP HTTP tool descriptor")
            names.append(item["name"])
        if len(set(names)) != len(names) or not (await self._gate.decision(request)).allowed:
            raise MCPHttpError("MCP discovery was revoked or ambiguous")
        return tuple(names)

    async def call_tool(self, name, arguments):
        raise MCPHttpError("unbound MCP HTTP execution prohibited")

    async def call_tool_authorized(self, request: OperationRequest, name: str, arguments: Mapping):
        if (not self.session_active or not isinstance(name, str) or not _TOOL.fullmatch(name)
                or request.machine_id != self._gate.machine.machine_id
                or request.capability_id != "mcp:" + name
                or request.arguments != {"server_id": self.server_id, "tool_name": name,
                                         "arguments": dict(arguments)}
                or not (await self._gate.decision(request)).allowed):
            raise MCPHttpError("MCP HTTP named tool grant denied")
        result = await self._call("tools/call", {"name": name, "arguments": dict(arguments)})
        if not (await self._gate.decision(request)).allowed:
            raise MCPHttpError("MCP HTTP tool grant revoked during call")
        return result

    async def close(self):
        self._closed = True
        # Intentionally no DELETE here: a shutdown message after an uncertain
        # tools/call could interfere with remote reconciliation. Host records
        # lifecycle in central SQLite; explicit session terminate needs its
        # own acknowledged operation and grant.


    @staticmethod
    def _event_id(value):
        if value is not None and (not isinstance(value, str) or
                not re.fullmatch(r"[A-Za-z0-9._~-]{1,128}", value)):
            raise MCPHttpError("invalid MCP stream cursor")
        return value

    def _session_http(self, method, *, session_id, last_event_id=None, timeout=4):
        """GET finite observation / DELETE session, never an MCP tool resend."""
        self._event_id(last_event_id)
        if not _SESSION.fullmatch(session_id or "") or self._closed or self._uncertain:
            raise MCPHttpError("MCP stream session unavailable")
        headers = {"MCP-Protocol-Version": "2025-06-18",
                   "Mcp-Session-Id": session_id,
                   "Accept": "text/event-stream" if method == "GET" else "application/json"}
        if last_event_id is not None:
            headers["Last-Event-ID"] = last_event_id
        if self._access_token is not None:
            token = self._access_token()
            if (not isinstance(token, str) or not 1 <= len(token) <= 4096
                    or not token.isascii() or re.search(r"[\s\x00-\x1f\x7f]", token)):
                raise MCPHttpError("OAuth session bearer unavailable")
            headers["Authorization"] = "Bearer " + token
        connection = http.client.HTTPConnection(self._host, self._port, timeout=timeout)
        try:
            connection.request(method, self._path, headers=headers)
            response = connection.getresponse()
            if method == "DELETE":
                if response.status not in (200, 202, 204) or response.read(1):
                    raise MCPHttpError("MCP session deletion unconfirmed")
                return {"deleted": True}
            if response.status != 200 or response.getheader("Content-Type", "").split(";")[0].strip().lower() != "text/event-stream":
                raise MCPHttpError("MCP GET event stream unavailable")
            length = response.getheader("Content-Length")
            if length is not None and (not length.isdigit() or int(length) > MAX_REPLY):
                raise MCPHttpError("MCP GET stream size invalid")
            data = response.read(MAX_REPLY + 1)
            if len(data) > MAX_REPLY:
                raise MCPHttpError("MCP GET stream oversized")
            if length is not None and len(data) != int(length):
                raise MCPHttpError("MCP GET stream truncated")
            events, current, previous = [], {}, last_event_id
            for raw in data.replace(b"\r\n", b"\n").split(b"\n\n"):
                if not raw.strip():
                    continue
                if len(events) >= 16:
                    raise MCPHttpError("MCP GET event count exceeded")
                name, event_id, lines = None, None, []
                for line in raw.split(b"\n"):
                    if line.startswith(b":"):
                        continue
                    if line.startswith(b"event:"):
                        name = line[6:].strip()
                    elif line.startswith(b"id:"):
                        event_id = self._event_id(line[3:].strip().decode("ascii", "strict"))
                    elif line.startswith(b"data:"):
                        lines.append(line[5:].lstrip(b" "))
                    elif line.startswith(b"retry:"):
                        raise MCPHttpError("MCP event retry directive not supported")
                    else:
                        raise MCPHttpError("MCP event contains unsupported field")
                if name != b"message" or not event_id or not lines or event_id == previous:
                    raise MCPHttpError("MCP event identity/order invalid")
                decoded = _decode(b"\n".join(lines))
                # Only notifications/observations, not an unapproved tool effect.
                if (decoded.get("jsonrpc") != "2.0"
                        or not isinstance(decoded.get("method"), str)
                        or not decoded["method"].startswith("notifications/")
                        or "id" in decoded):
                    raise MCPHttpError("MCP event is not a notification")
                events.append({"event_id": event_id, "message": decoded})
                previous = event_id
            return {"events": events, "last_event_id": previous,
                    "event_count": len(events)}
        except (OSError, TimeoutError, http.client.HTTPException):
            self._uncertain = True
            raise MCPHttpError("MCP session observation outcome uncertain") from None
        except BaseException:
            self._uncertain = True
            raise
        finally:
            connection.close()

    async def events_authorized(self, request: OperationRequest, *,
                                session_id: str, last_event_id=None):
        if (request.capability_id != "mcp:events" or
                request.arguments != {"server_id": self.server_id,
                                      "session_id": session_id,
                                      "last_event_id": last_event_id} or
                not (await self._gate.decision(request)).allowed):
            raise MCPHttpError("MCP GET event grant denied")
        outcome = await asyncio.to_thread(self._session_http, "GET",
                                          session_id=session_id,
                                          last_event_id=last_event_id)
        if not (await self._gate.decision(request)).allowed:
            raise MCPHttpError("MCP GET grant revoked during request")
        return outcome

    async def delete_authorized(self, request: OperationRequest, *,
                                session_id: str):
        if (request.capability_id != "mcp:session-delete" or
                request.arguments != {"server_id": self.server_id,
                                      "session_id": session_id} or
                not (await self._gate.decision(request)).allowed):
            raise MCPHttpError("MCP DELETE grant denied")
        outcome = await asyncio.to_thread(self._session_http, "DELETE",
                                          session_id=session_id)
        if not (await self._gate.decision(request)).allowed:
            raise MCPHttpError("MCP DELETE grant revoked during request")
        return outcome
