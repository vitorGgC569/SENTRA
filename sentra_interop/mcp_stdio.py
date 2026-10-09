"""Pinned local MCP JSON-RPC 2.0 stdio client; ToolHive is NOT started.

No shell, remote network, npx/uvx, ambient environment, or automatic retries.
Actual tools/call authorization belongs to ToolHiveMCPBoundary (injected client).
"""
from __future__ import annotations

import asyncio
import json
import os
import ctypes
from pathlib import Path
from typing import Any, Mapping

from sentra_runtime.contracts import OperationRequest, OperationResult
from .gate import InteropGate

MAX_FRAME = 65536


class MCPStdioError(ValueError):
    pass


def _minimal_windows_runtime_env() -> dict[str, str]:
    """OS-reported Windows dir only, never PATH, USERPROFILE or credentials."""
    if os.name != "nt":
        return {}
    directory = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetWindowsDirectoryW(directory, len(directory))
    if not 0 < size < len(directory):
        raise MCPStdioError("cannot identify trusted Windows directory")
    return {"SystemRoot": directory.value}



def _encode(body: Mapping[str, Any]) -> bytes:
    try:
        packet = json.dumps(body, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise MCPStdioError("invalid JSON-RPC request") from exc
    if len(packet) > MAX_FRAME:
        raise MCPStdioError("JSON-RPC request oversized")
    return packet + b"\n"


def _decode(raw: bytes) -> Mapping[str, Any]:
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise MCPStdioError("duplicate JSON-RPC property")
            out[k] = v
        return out
    try:
        msg = json.loads(raw, object_pairs_hook=unique,
                         parse_constant=lambda _: (_ for _ in ()).throw(MCPStdioError("invalid JSON value")))
    except (ValueError, UnicodeDecodeError) as exc:
        raise MCPStdioError("malformed MCP JSON-RPC frame") from exc
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        raise MCPStdioError("invalid JSON-RPC envelope")
    return msg


class MCPStdioClient:
    """Owns only the direct child PID; no process tree sandbox claim."""

    def __init__(self, process: asyncio.subprocess.Process, gate: InteropGate,
                 *, server_id: str) -> None:
        self.process, self.gate, self.server_id = process, gate, server_id
        self._lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future] = {}
        self._late: set[int] = set()
        self._seq = 0
        self._dead: Exception | None = None
        self._closed = False
        self._initialized = False
        self._reader = asyncio.create_task(self._reader_loop())

    @classmethod
    async def launch(cls, *, executable: str, argv: tuple[str, ...],
                     cwd: str, server_id: str, request: OperationRequest,
                     gate: InteropGate, timeout: float = 10) -> "MCPStdioClient":
        if (request.capability_id != "mcp:launch" or not isinstance(server_id, str)
            or not server_id or len(server_id) > 128
            or request.arguments != {"executable": executable, "args": list(argv),
                                     "cwd": cwd, "server_id": server_id}
            or not Path(executable).is_absolute() or not Path(executable).is_file()
            or not Path(cwd).is_absolute() or not Path(cwd).is_dir()
            or not isinstance(argv, tuple) or any(not isinstance(v, str) or "\0" in v for v in argv)):
            raise MCPStdioError("unapproved MCP launch specification")
        decision = await asyncio.wait_for(gate.decision(request), timeout)
        if not decision.allowed:
            raise MCPStdioError("MCP launch policy denied")
        previous = await gate.journal.reserve(request)
        if previous is not None:
            raise MCPStdioError("duplicate or uncertain MCP launch")
        client = None
        try:
            process = await asyncio.wait_for(asyncio.create_subprocess_exec(
                executable, *argv, cwd=cwd, env=_minimal_windows_runtime_env(),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=MAX_FRAME+1), timeout)
            client = cls(process, gate, server_id=server_id)
            decision = await asyncio.wait_for(gate.decision(request), timeout)
            if not decision.allowed:
                raise MCPStdioError("MCP launch policy revoked")
            await gate.journal.finish(request, OperationResult(request.operation_id, "SUCCEEDED"))
            return client
        except BaseException:
            if client is not None:
                await asyncio.shield(client.close())
            await gate.journal.finish(request, OperationResult(
                request.operation_id, "UNCERTAIN", error="MCP launch failed or revoked"))
            raise

    async def _send(self, msg: Mapping[str, Any]) -> None:
        if self._dead or self._closed or self.process.stdin is None:
            raise MCPStdioError("MCP stdio disconnected")
        async with self._lock:
            self.process.stdin.write(_encode(msg))
            await self.process.stdin.drain()

    async def _call(self, method: str, params: Mapping[str, Any], timeout: float) -> Mapping[str, Any]:
        if method not in {"initialize", "tools/list", "tools/call",
                           "resources/list", "resources/read",
                           "prompts/list", "prompts/get"} or timeout <= 0:
            raise MCPStdioError("MCP client method forbidden")
        if len(self._late) >= 4096:
            raise MCPStdioError("too many uncertain RPCs")
        self._seq += 1
        ident = self._seq
        fut = asyncio.get_running_loop().create_future()
        self._pending[ident] = fut
        try:
            await self._send({"jsonrpc":"2.0", "id":ident, "method":method, "params":dict(params)})
            return await asyncio.wait_for(fut, timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            # This is advisory only; remote effects remain UNCERTAIN.
            try:
                await self._send({"jsonrpc":"2.0", "method":"notifications/cancelled",
                                  "params":{"requestId":ident, "reason":"client timeout or cancellation"}})
            except MCPStdioError:
                pass
            raise
        finally:
            if ident in self._pending:
                if fut.cancelled():
                    self._late.add(ident)
                self._pending.pop(ident, None)

    async def _reader_loop(self) -> None:
        try:
            while True:
                if self.process.stdout is None:
                    raise MCPStdioError("missing MCP stdout")
                line = await self.process.stdout.readline()
                if not line:
                    raise MCPStdioError("MCP server disconnected")
                if len(line) > MAX_FRAME:
                    raise MCPStdioError("oversized MCP reply")
                msg = _decode(line)
                if "method" in msg:
                    if "id" in msg:
                        # MCP sampling/roots/elicitation are *not* available.
                        await self._send({"jsonrpc":"2.0","id":msg["id"],
                                          "error":{"code":-32601, "message":"not supported"}})
                    else:
                        if msg["method"] not in {"notifications/message",
                                                 "notifications/progress",
                                                 "notifications/tools/list_changed"}:
                            raise MCPStdioError("unexpected MCP notification")
                    continue
                ident = msg.get("id")
                if type(ident) is not int:
                    raise MCPStdioError("invalid response identity")
                if ident in self._late:
                    self._late.discard(ident)
                    continue
                fut = self._pending.get(ident)
                if fut is None or fut.done() or ("result" in msg) == ("error" in msg):
                    raise MCPStdioError("unexpected or ambiguous JSON-RPC reply")
                if "error" in msg:
                    fut.set_exception(MCPStdioError("MCP JSON-RPC peer error"))
                elif not isinstance(msg["result"], Mapping):
                    fut.set_exception(MCPStdioError("MCP result is not an object"))
                else:
                    fut.set_result(dict(msg["result"]))
        except BaseException as exc:
            self._dead = MCPStdioError("MCP reader closed")
            for f in list(self._pending.values()):
                if not f.done():
                    f.set_exception(self._dead)
            if self.process.returncode is None:
                try:
                    self.process.terminate()
                except ProcessLookupError:
                    pass

    async def initialize(self, *, timeout: float = 3) -> None:
        if self._initialized:
            raise MCPStdioError("MCP already initialized")
        response = await self._call("initialize", {
            "protocolVersion":"2025-06-18",
            "capabilities":{}, "clientInfo":{"name":"sentra-local","version":"1.0"}}, timeout)
        if response.get("protocolVersion") != "2025-06-18":
            raise MCPStdioError("unsupported MCP protocol version")
        await self._send({"jsonrpc":"2.0","method":"notifications/initialized"})
        self._initialized = True

    async def list_tools(self, request: OperationRequest, *, timeout: float = 3) -> tuple[str, ...]:
        if (not self._initialized or request.capability_id != "mcp:list"
            or request.arguments != {"server_id":self.server_id}
            or not (await self.gate.decision(request)).allowed):
            raise MCPStdioError("MCP tools/list unauthorized")
        result = await self._call("tools/list", {}, timeout)
        tools = result.get("tools")
        if not isinstance(tools, list) or len(tools) > 128:
            raise MCPStdioError("invalid MCP tools list")
        names: list[str] = []
        for item in tools:
            if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
                raise MCPStdioError("invalid MCP tool descriptor")
            if not item["name"] or len(item["name"]) > 128:
                raise MCPStdioError("invalid MCP tool name")
            names.append(item["name"])
        if len(names) != len(set(names)):
            raise MCPStdioError("duplicate MCP tools")
        if not (await self.gate.decision(request)).allowed:
            raise MCPStdioError("MCP discovery policy revoked")
        return tuple(names)

    requires_authorized_call = True

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Raw ToolHive call shape is deliberately forbidden for this client."""
        raise MCPStdioError("use ToolHiveMCPBoundary with a bound OperationRequest")

    async def call_tool_authorized(
        self, request: OperationRequest, name: str, arguments: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Second policy gate at the transport itself; no raw tools/call API."""
        if (not self._initialized or not isinstance(name, str) or not name
            or request.machine_id != self.gate.machine.machine_id
            or not request.capability_id.startswith("mcp:")
            or request.capability_id in {"mcp:launch", "mcp:list"}
            or request.arguments != {"server_id":self.server_id, "tool_name":name,
                                     "arguments":dict(arguments)}
            or not (await self.gate.decision(request)).allowed):
            raise MCPStdioError("MCP transport call not authorized")
        return await self._call("tools/call", {"name":name, "arguments":dict(arguments)}, 5)

    async def close(self) -> None:
        self._closed = True
        if self.process.stdin:
            self.process.stdin.close()
        if self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                if self.process.returncode is None:
                    self.process.kill()
                await self.process.wait()
        self._reader.cancel()
        await asyncio.gather(self._reader, return_exceptions=True)
        self._late.clear()
