"""Negotiated ACP v1/v2 JSON-RPC stdio client and session lifecycle.

Never executes registry commands automatically. Stdio launch must be explicitly
configured and admitted by SENTRA PolicyDecision beforehand.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Mapping, Protocol

from sentra_runtime.contracts import OperationRequest, OperationResult

from .gate import DispatchOutcome, InteropGate, EffectRejected
from .acp_session import ACPSessionState, ACPSessionStore, identity, V1_UPDATES
from .acp_process import ACPProcessOwner, spawn_owned

MAX_LINE = 65536
MAX_UNANSWERED_IDS = 4096
ALLOWED_REQUEST_METHODS = frozenset({"initialize", "session/new", "session/prompt",
    "session/load", "session/resume", "session/list", "session/close", "session/delete",
    "session/set_mode", "session/set_config_option"})
ALLOWED_NOTIFY_METHODS = frozenset({"session/cancel"})
VALID_UPDATES = V1_UPDATES  # Legacy import; actual validation follows negotiated revision.


class ACPProtocolError(ValueError):
    pass


class ACPLaunchError(ACPProtocolError):
    """A stable, non-sensitive failure code for subprocess launch diagnostics."""

    def __init__(self, code: str, state: str) -> None:
        self.code = code
        self.state = state
        super().__init__(f"ACP launch {code} ({state})")


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ACPProtocolError("duplicate JSON-RPC key")
        result[key] = value
    return result


def _reject_nonfinite(_):
    raise ACPProtocolError("non-finite JSON-RPC value")


class ACPTransport(Protocol):
    async def request(self, method: str, params: Mapping[str, Any], timeout: float) -> Mapping[str, Any]: ...
    async def notify(self, method: str, params: Mapping[str, Any]) -> None: ...
    async def next_update(self, timeout: float) -> Mapping[str, Any]: ...
    async def close(self) -> None: ...


def _frame(value: Mapping[str, Any]) -> bytes:
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if b"\n" in data or len(data) > MAX_LINE:
        raise ACPProtocolError("ACP frame exceeds limit")
    return data + b"\n"


class ACPStdioTransport:
    """Real, opt-in, local stdio transport; agent-initiated requests are rejected.

    It does not provide privileged file-system, terminal, MCP, or permission
    handlers. A disconnect is not proof the agent's work was rolled back.
    """

    def __init__(self, process: asyncio.subprocess.Process, *, owner: ACPProcessOwner | None = None) -> None:
        self.process = process
        self._owner = owner
        self._pending: dict[int, asyncio.Future[Mapping[str, Any]]] = {}
        self._expired_ids: set[int] = set()
        self._sequence = 0
        self._write_lock = asyncio.Lock()
        self._updates: asyncio.Queue[Mapping[str, Any]] = asyncio.Queue(maxsize=128)
        self._dead: BaseException | None = None
        self._closed = False
        self._read_task = asyncio.create_task(self._read_loop())

    @classmethod
    async def launch(
        cls, executable: str, args: tuple[str, ...] = (), *,
        cwd: str, gate: InteropGate, request: OperationRequest,
        env: Mapping[str, str] | None = None,
        spawn_timeout: float = 20,
        launch_hook: Callable[[Callable[[], Awaitable[Any]]], Awaitable[Any]] | None = None,
    ) -> "ACPStdioTransport":
        """Fail-closed spawn with typed diagnostics and explicit child ownership.

        Launch is the one effect that cannot use generic InteropGate.execute:
        the transport must be closed if authorization changes after creating
        the process. Journal admission and both policy checks are preserved.
        """
        if not isinstance(request, OperationRequest) or request.capability_id != "acp:launch":
            raise ACPLaunchError("INVALID_REQUEST", "FAILED")
        if (type(spawn_timeout) not in (float, int) or not 0 < spawn_timeout <= 120):
            raise ACPLaunchError("INVALID_CONFIG", "FAILED")
        if not isinstance(executable, str) or not isinstance(cwd, str):
            raise ACPLaunchError("INVALID_CONFIG", "FAILED")
        if not isinstance(args, (tuple, list)) or any(
            not isinstance(arg, str) or "\0" in arg for arg in args
        ):
            raise ACPLaunchError("INVALID_CONFIG", "FAILED")
        if request.arguments != {"executable": executable, "args": list(args), "cwd": cwd}:
            raise ACPLaunchError("INVALID_REQUEST", "FAILED")
        target = Path(executable)
        directory = Path(cwd)
        if not target.is_absolute() or not target.is_file() or not directory.is_dir():
            raise ACPLaunchError("INVALID_CONFIG", "FAILED")
        if env:
            raise ACPLaunchError("ENV_DENIED", "FAILED")
        if launch_hook is not None and not callable(launch_hook):
            raise ACPLaunchError("INVALID_CONFIG", "FAILED")

        try:
            decision = await asyncio.wait_for(gate.decision(request), spawn_timeout)
        except asyncio.TimeoutError:
            raise ACPLaunchError("POLICY_TIMEOUT", "FAILED") from None
        if not decision.allowed:
            raise ACPLaunchError("POLICY_DENIED", "FAILED")
        previous = await gate.journal.reserve(request)
        if previous is not None:
            raise ACPLaunchError("DUPLICATE_OR_CONFLICT", previous.state)

        transport: ACPStdioTransport | None = None
        spawned_owner: ACPProcessOwner | None = None
        stage = "SPAWN"
        try:
            # No shell, no inherited tokens, no implicit PATH resolution.
            # Trusted host injection, never selected through request arguments
            # or registry metadata. Central context owns physical I/O fencing.
            from sentra_runtime.effect_boundary import current_effect_context
            physical_context = getattr(gate, "physical_context", None)
            context = (physical_context(request) if callable(physical_context)
                       else current_effect_context.get())
            async def spawn():
                nonlocal spawned_owner
                if context is not None:
                    context.checkpoint()
                process, owner = await spawn_owned(
                    str(target), tuple(args), cwd=str(directory.resolve()),
                    env={}, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    limit=MAX_LINE + 1,
                    checkpoint=context.checkpoint if context is not None else None,
                )
                spawned_owner = owner
                return process, owner
            boundary = (context.run_async if callable(physical_context) else
                        launch_hook or (context.run_async if context is not None else None))
            process, owner = await asyncio.wait_for(boundary(spawn) if boundary else spawn(),
                                                   timeout=spawn_timeout)
            transport = cls(process, owner=owner)
            stage = "POST_POLICY"
            latest = await asyncio.wait_for(gate.decision(request), spawn_timeout)
            if not latest.allowed:
                raise ACPLaunchError("POST_POLICY_DENIED", "UNCERTAIN")
            result = OperationResult(request.operation_id, "SUCCEEDED")
            await gate.journal.finish(request, result)
            return transport
        except BaseException as exc:
            if isinstance(exc, ACPLaunchError):
                error = exc
            elif isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
                error = ACPLaunchError("POST_POLICY_TIMEOUT" if stage == "POST_POLICY"
                                       else "SPAWN_TIMEOUT", "UNCERTAIN")
            elif isinstance(exc, asyncio.CancelledError):
                error = ACPLaunchError("SPAWN_CANCELLED", "UNCERTAIN")
            elif isinstance(exc, OSError):
                error = ACPLaunchError("SPAWN_OS_ERROR", "UNCERTAIN")
            else:
                error = ACPLaunchError("SPAWN_FAILED", "UNCERTAIN")
            if transport is not None:
                # Never return an untrusted child to a caller, even after
                # post-launch policy revocation or a journal failure.
                try:
                    await asyncio.shield(transport.close())
                except Exception:
                    error = ACPLaunchError("CLEANUP_UNCERTAIN", "UNCERTAIN")
            elif spawned_owner is not None:
                try:
                    await asyncio.shield(spawned_owner.close())
                except Exception:
                    error = ACPLaunchError("CLEANUP_UNCERTAIN", "UNCERTAIN")
            await gate.journal.finish(request, OperationResult(
                request.operation_id, "UNCERTAIN", error=error.code))
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise error from None

    async def _write(self, message: Mapping[str, Any]) -> None:
        frame = _frame(message)
        if self._dead or self._closed or self.process.stdin is None:
            raise ACPProtocolError("ACP transport closed")
        async with self._write_lock:
            from sentra_runtime.effect_boundary import current_effect_context
            context = current_effect_context.get()
            if context is not None:
                context.checkpoint()
            self.process.stdin.write(frame)
            await self.process.stdin.drain()

    async def request(self, method: str, params: Mapping[str, Any], timeout: float = 30) -> Mapping[str, Any]:
        if method not in ALLOWED_REQUEST_METHODS or not isinstance(params, Mapping) or timeout <= 0:
            raise ACPProtocolError("outbound ACP method not supported")
        if len(self._expired_ids) >= MAX_UNANSWERED_IDS:
            raise ACPProtocolError("too many uncertain ACP requests; reconcile and reopen")
        loop = asyncio.get_running_loop()
        self._sequence += 1
        request_id = self._sequence
        future: asyncio.Future[Mapping[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
            return await asyncio.wait_for(future, timeout)
        finally:
            if request_id in self._pending:
                # Only a request cancelled while awaiting its result can
                # receive an orphaned response later. Completed requests
                # must not consume tombstone capacity.
                if future.cancelled():
                    self._expired_ids.add(request_id)
                self._pending.pop(request_id, None)

    async def notify(self, method: str, params: Mapping[str, Any]) -> None:
        if method not in ALLOWED_NOTIFY_METHODS or not isinstance(params, Mapping):
            raise ACPProtocolError("outbound ACP notification not supported")
        await self._write({"jsonrpc": "2.0", "method": method, "params": dict(params)})

    async def next_update(self, timeout: float = 30) -> Mapping[str, Any]:
        if timeout <= 0:
            raise ACPProtocolError("timeout must be positive")
        if self._dead and self._updates.empty():
            raise ACPProtocolError("ACP transport closed")
        update = await asyncio.wait_for(self._updates.get(), timeout)
        if update is None:
            raise ACPProtocolError("ACP transport closed")
        return update

    async def _read_loop(self) -> None:
        try:
            if self.process.stdout is None:
                raise ACPProtocolError("missing stdout")
            while True:
                raw = await self.process.stdout.readline()
                if not raw:
                    raise ACPProtocolError("ACP peer disconnected")
                if len(raw) > MAX_LINE:
                    raise ACPProtocolError("oversized ACP message")
                msg = json.loads(raw, object_pairs_hook=_reject_duplicate_keys,
                                 parse_constant=_reject_nonfinite)
                if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
                    raise ACPProtocolError("invalid JSON-RPC envelope")
                if "method" in msg and "id" in msg:
                    # An agent-initiated request has no authority: no dispatch,
                    # not even after recovering/attaching a different adapter.
                    if not isinstance(msg["method"], str) or not msg["method"]:
                        raise ACPProtocolError("invalid agent request method")
                    if type(msg["id"]) not in (str, int) or len(str(msg["id"])) > 128:
                        raise ACPProtocolError("invalid agent request id")
                    await self._write({"jsonrpc": "2.0", "id": msg["id"],
                                       "error": {"code": -32601, "message": "not supported"}})
                elif "method" in msg:
                    if msg["method"] != "session/update" or not isinstance(msg.get("params"), dict):
                        raise ACPProtocolError("unknown ACP notification")
                    try:
                        self._updates.put_nowait(msg["params"])
                    except asyncio.QueueFull as exc:
                        raise ACPProtocolError("ACP update queue exceeded") from exc
                else:
                    request_id = msg.get("id")
                    if type(request_id) is not int:
                        raise ACPProtocolError("invalid response id")
                    if request_id in self._expired_ids:
                        # Timed-out operations are never repeated; old responses
                        # cannot authorize effects or corrupt newer requests.
                        self._expired_ids.discard(request_id)
                        continue
                    future = self._pending.get(request_id)
                    if future is None or future.done():
                        raise ACPProtocolError("unexpected response id")
                    if ("error" in msg) == ("result" in msg):
                        raise ACPProtocolError("ambiguous JSON-RPC response")
                    if "error" in msg or not isinstance(msg["result"], dict):
                        future.set_exception(ACPProtocolError("ACP request failed"))
                    else:
                        future.set_result(msg["result"])
        except BaseException as exc:
            self._dead = exc
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(ACPProtocolError("ACP transport disconnected"))
            # Wake a listener blocked in next_update immediately on disconnect.
            try:
                self._updates.put_nowait(None)
            except asyncio.QueueFull:
                pass
            # Once the protocol has become untrustworthy, terminate only the
            # owned child process; never leave it running as an orphan.
            if self._owner is not None:
                await self._owner.close()
            elif self.process.returncode is None:
                try:
                    self.process.terminate()
                except ProcessLookupError:
                    pass

    async def close(self) -> None:
        self._closed = True
        if self.process.stdin is not None:
            self.process.stdin.close()
        if self._owner is not None:
            await self._owner.close()
        elif self.process.returncode is None:
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
        self._read_task.cancel()
        await asyncio.gather(self._read_task, return_exceptions=True)
        self._expired_ids.clear()


class ACPSessionAdapter:
    """Negotiated ACP v1/v2 with scoped identity and optional durable receipts.

    v2 is explicit opt-in because the pinned clone calls it a draft. Successful
    v2 prompt dispatch means message insertion, never foreground completion.
    """

    def __init__(self, gate: InteropGate, transport: ACPTransport, *, workspace: str,
                 supported_versions: tuple[int, ...] = (1,),
                 store: ACPSessionStore | None = None, provider: str = "local",
                 local_session_id: str | None = None) -> None:
        if (not supported_versions or any(type(v) is not int or v not in (1, 2)
                                           for v in supported_versions)):
            raise ValueError("unsupported ACP revision")
        if store is not None and local_session_id is None:
            raise ValueError("durable ACP requires an explicit local session ID")
        self.gate = gate
        self.transport = transport
        self.workspace = Path(workspace).resolve()
        if store is not None and store.workspace != self.workspace:
            raise ValueError("ACP store workspace mismatch")
        self.supported_versions = tuple(sorted(set(supported_versions)))
        self.store, self.provider = store, identity(provider)
        self.local_session_id = identity(local_session_id) if local_session_id is not None else None
        self.protocol_version: int | None = None
        self.capabilities: dict[str, Any] = {}
        self.state: ACPSessionState | None = None
        self._scope: tuple[str, str, str] | None = None
        self._negotiation_attempted = False
        self._initialization_lock = asyncio.Lock()
        self.session_id: str | None = None
        self._cancel_requested = False
        self._session_lock = asyncio.Lock()

    def _failure(self, request: OperationRequest, message: str) -> DispatchOutcome:
        return DispatchOutcome(OperationResult(request.operation_id, "FAILED", error=message))

    def _check(self, request: OperationRequest, capability: str, arguments: Mapping[str, Any],
               *, bound: bool = False) -> None:
        if request.capability_id != capability or request.arguments != dict(arguments):
            raise EffectRejected("ACP request payload mismatch")
        if bound and not self.session_id:
            raise EffectRejected("ACP session unavailable")
        scope = (request.principal_id, request.machine_id, request.work_item_id)
        if self._scope is not None and scope != self._scope:
            raise EffectRejected("ACP session scope mismatch")

    def _directory(self, cwd: str) -> Path:
        directory = Path(cwd).resolve()
        if not directory.is_dir() or not directory.is_relative_to(self.workspace):
            raise EffectRejected("cwd outside workspace")
        return directory

    async def _execute(self, request: OperationRequest, method: str, effect,
                       *, timeout: float) -> DispatchOutcome:
        reserved = False
        async def admitted():
            nonlocal reserved
            if self.store is not None and not callable(getattr(self.gate, "physical_context", None)):
                self.store.reserve(self.local_session_id, method, request)
                reserved = True
            return await effect()
        try:
            result = await self.gate.execute(request, admitted, timeout=timeout)
        except BaseException:
            if reserved:
                self.store.finish(request, "UNCERTAIN")
            raise
        if reserved:
            self.store.finish(request, result.operation.state)
        if self.store is not None and result.operation.state == "UNCERTAIN" and self.session_id:
            self.store.set_state(self.local_session_id, "UNCERTAIN")
        return result

    async def _initialize(self, timeout: float) -> None:
        async with self._initialization_lock:
            if self.protocol_version is not None:
                return
            if self._negotiation_attempted:
                raise ACPProtocolError("ACP initialize uncertain; reconnect explicitly")
            self._negotiation_attempted = True
            version = max(self.supported_versions)
            info = {"name": "sentra", "version": "1.0.0"}
            params = ({"protocolVersion": version, "info": info, "capabilities": {}}
                      if version == 2 else {"protocolVersion": 1, "clientInfo": info,
                          "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False},
                                                 "terminal": False}})
            response = await self.transport.request("initialize", params, timeout)
            chosen = response.get("protocolVersion")
            if type(chosen) is not int or chosen not in self.supported_versions:
                await self.transport.close()
                raise ACPProtocolError("incompatible ACP protocol version")
            caps = response.get("capabilities" if chosen == 2 else "agentCapabilities", {})
            if not isinstance(caps, Mapping):
                raise ACPProtocolError("invalid ACP capabilities")
            if chosen == 2:
                agent_info = response.get("info")
                if (not isinstance(agent_info, Mapping) or not isinstance(agent_info.get("name"), str)
                    or not isinstance(agent_info.get("version"), str)
                    or not isinstance(caps.get("session"), Mapping)):
                    raise ACPProtocolError("ACP v2 session surface unavailable")
            self.capabilities = dict(caps)
            self.protocol_version = chosen
            self.state = ACPSessionState(chosen)

    def supports(self, method: str) -> bool:
        if self.protocol_version is None:
            return False
        if method in {"session/new", "session/prompt", "session/cancel"}:
            return True
        if method == "session/set_config_option":
            return bool(self.state and self.state.config_options)
        if method == "session/set_mode":
            return self.protocol_version == 1 and bool(self.state and self.state.modes)
        if method == "session/load":
            return self.protocol_version == 1 and self.capabilities.get("loadSession") is True
        if self.protocol_version == 2:
            if method in {"session/resume", "session/list", "session/close"}:
                return True  # Baseline v2 session method surface in the pinned clone.
            if method != "session/delete":
                return False
            caps = self.capabilities.get("session", {})
        else:
            if method not in {"session/resume", "session/list", "session/close", "session/delete"}:
                return False
            caps = self.capabilities.get("sessionCapabilities", {})
        return (isinstance(caps, Mapping) and method.startswith("session/")
                and isinstance(caps.get(method.split("/", 1)[1]), Mapping))

    def _bind(self, session_id: str, directory: Path, response: Mapping[str, Any],
              request: OperationRequest) -> None:
        identity(session_id)
        if self.store is not None:
            self.store.bind(self.local_session_id, self.provider, session_id,
                            str(directory), self.protocol_version, request)
        self.session_id = session_id
        self._scope = (request.principal_id, request.machine_id, request.work_item_id)
        self._cancel_requested = False
        self.state.setup(response)

    async def open(self, request: OperationRequest, *, cwd: str, timeout: float = 30) -> DispatchOutcome:
        try:
            directory = self._directory(cwd)
            self._check(request, "acp:session", {"cwd": str(directory)})
            if self.store is not None and self.store.get(
                self.local_session_id, provider=self.provider, request=request) is not None:
                raise EffectRejected("durable ACP mapping exists; use explicit reattach")
        except (ValueError, OSError) as exc:
            return self._failure(request, str(exc))
        async def effect() -> str:
            async with self._session_lock:
                if self.session_id is not None:
                    raise EffectRejected("ACP session already established")
                if self.store is not None and self.store.get(
                    self.local_session_id, provider=self.provider, request=request) is not None:
                    raise EffectRejected("ACP mapping already exists")
                await self._initialize(timeout)
                response = await self.transport.request("session/new", {
                    "cwd": str(directory), "mcpServers": []}, timeout)
                session_id = identity(response.get("sessionId"))
                self._bind(session_id, directory, response, request)
                return session_id
        return await self._execute(request, "session/new", effect, timeout=timeout * 2 + 1)

    async def resume(self, request: OperationRequest, *, session_id: str, cwd: str,
                     timeout: float = 30, load_history: bool = False) -> DispatchOutcome:
        """Explicit remote resume; no fallback to session/new or prompt replay."""
        method = "session/load" if load_history else "session/resume"
        try:
            identity(session_id)
            directory = self._directory(cwd)
            self._check(request, "acp:load" if load_history else "acp:resume",
                        {"session_id": session_id, "cwd": str(directory)})
            if self.store is not None:
                old = self.store.get(self.local_session_id, provider=self.provider, request=request)
                if old is None or old.state == "DELETED" or old.session_id != session_id or old.cwd != str(directory):
                    raise EffectRejected("ACP resume mapping mismatch")
        except (ValueError, OSError) as exc:
            return self._failure(request, str(exc))
        async def effect():
            async with self._session_lock:
                if self.session_id is not None:
                    raise EffectRejected("ACP session already attached")
                await self._initialize(timeout)
                if not self.supports(method):
                    raise EffectRejected("ACP resume method not advertised")
                if self.store is not None and old.protocol_version != self.protocol_version:
                    raise EffectRejected("ACP durable session revision mismatch")
                response = await self.transport.request(method, {
                    "sessionId": session_id, "cwd": str(directory), "mcpServers": []}, timeout)
                if "sessionId" in response and response["sessionId"] != session_id:
                    raise ACPProtocolError("ACP resumed session identity mismatch")
                self._bind(session_id, directory, response, request)
                return {"sessionId": session_id, "historyReplayRequested": load_history}
        return await self._execute(request, method, effect, timeout=timeout * 2 + 1)

    async def reattach(self, request: OperationRequest, *, timeout: float = 30) -> DispatchOutcome:
        if self.store is None:
            return self._failure(request, "ACP durable store unavailable")
        try:
            binding = self.store.get(self.local_session_id, provider=self.provider, request=request)
            if binding is None or binding.state == "DELETED":
                raise EffectRejected("ACP durable session unavailable")
        except ValueError as exc:
            return self._failure(request, str(exc))
        return await self.resume(request, session_id=binding.session_id, cwd=binding.cwd, timeout=timeout)

    async def list_sessions(self, request: OperationRequest, *, cwd: str | None = None,
                            cursor: str | None = None, timeout: float = 30) -> DispatchOutcome:
        try:
            directory = str(self._directory(cwd)) if cwd is not None else None
            if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 4096):
                raise EffectRejected("invalid ACP list cursor")
            self._check(request, "acp:list", {"cwd": directory, "cursor": cursor})
        except (ValueError, OSError) as exc:
            return self._failure(request, str(exc))
        async def effect():
            await self._initialize(timeout)
            if not self.supports("session/list"):
                raise EffectRejected("ACP list not advertised")
            params = {k: v for k, v in {"cwd": directory, "cursor": cursor}.items() if v is not None}
            response = await self.transport.request("session/list", params, timeout)
            sessions = response.get("sessions")
            if not isinstance(sessions, list) or len(sessions) > 4096:
                raise ACPProtocolError("invalid ACP session list")
            for session in sessions:
                if not isinstance(session, Mapping):
                    raise ACPProtocolError("invalid ACP listed session")
                identity(session.get("sessionId"))
                if not isinstance(session.get("cwd"), str):
                    raise ACPProtocolError("invalid ACP listed cwd")
            next_cursor = response.get("nextCursor")
            if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > 4096):
                raise ACPProtocolError("invalid ACP pagination")
            return dict(response)
        return await self._execute(request, "session/list", effect, timeout=timeout * 2 + 1)

    async def close_session(self, request: OperationRequest, *, timeout: float = 30) -> DispatchOutcome:
        return await self._end_session(request, "close", self.session_id, timeout)

    async def delete_session(self, request: OperationRequest, *, session_id: str,
                             timeout: float = 30) -> DispatchOutcome:
        return await self._end_session(request, "delete", session_id, timeout)

    async def _end_session(self, request: OperationRequest, action: str,
                           session_id: str | None, timeout: float) -> DispatchOutcome:
        try:
            identity(session_id)
            self._check(request, "acp:" + action, {"session_id": session_id})
            if self.store is not None:
                binding = self.store.get(self.local_session_id, provider=self.provider, request=request)
                if binding is None or binding.session_id != session_id or binding.state == "DELETED":
                    raise EffectRejected("ACP session mapping mismatch")
            elif session_id != self.session_id:
                raise EffectRejected("ACP session is not bound")
        except ValueError as exc:
            return self._failure(request, str(exc))
        method = "session/" + action
        async def effect():
            async with self._session_lock:
                await self._initialize(timeout)
                if not self.supports(method):
                    raise EffectRejected("ACP lifecycle method not advertised")
                response = await self.transport.request(method, {"sessionId": session_id}, timeout)
                if self.store is not None:
                    self.store.set_state(self.local_session_id, "DELETED" if action == "delete" else "CLOSED")
                if session_id == self.session_id:
                    self.session_id = None
                return dict(response)
        return await self._execute(request, method, effect, timeout=timeout * 2 + 1)

    async def set_config_option(self, request: OperationRequest, *, config_id: str,
                                value: str | bool, timeout: float = 30) -> DispatchOutcome:
        try:
            self._check(request, "acp:config", {"session_id": self.session_id,
                        "config_id": config_id, "value": value}, bound=True)
            identity(config_id)
        except ValueError as exc:
            return self._failure(request, str(exc))
        async def effect():
            async with self._session_lock:
                option = next((o for o in self.state.config_options if o["id"] == config_id), None)
                if option is None:
                    raise EffectRejected("ACP option not advertised")
                if option["type"] == "boolean":
                    if type(value) is not bool:
                        raise EffectRejected("ACP option requires boolean")
                elif not isinstance(value, str) or value not in self.state.option_values(option):
                    raise EffectRejected("ACP option value not advertised")
                params = {"sessionId": self.session_id, "configId": config_id, "value": value}
                if option["type"] == "boolean":
                    params["type"] = "boolean"
                response = await self.transport.request("session/set_config_option", params, timeout)
                self.state.set_config(response.get("configOptions"))
                return dict(response)
        return await self._execute(request, "session/set_config_option", effect, timeout=timeout + 1)

    async def set_model(self, request: OperationRequest, *, model_id: str,
                        timeout: float = 30) -> DispatchOutcome:
        """Model category selector; never invent a removed session/set_model API."""
        models = [o for o in (self.state.config_options if self.state else []) if o.get("category") == "model"]
        if len(models) != 1:
            return self._failure(request, "ACP model selector unavailable or ambiguous")
        return await self.set_config_option(request, config_id=models[0]["id"], value=model_id, timeout=timeout)

    async def set_mode(self, request: OperationRequest, *, mode_id: str,
                       timeout: float = 30) -> DispatchOutcome:
        try:
            self._check(request, "acp:mode", {"session_id": self.session_id, "mode_id": mode_id}, bound=True)
            identity(mode_id)
        except ValueError as exc:
            return self._failure(request, str(exc))
        async def effect():
            async with self._session_lock:
                if not self.supports("session/set_mode") or mode_id not in {
                    m.get("id") for m in self.state.modes.get("availableModes", []) if isinstance(m, Mapping)}:
                    raise EffectRejected("ACP mode not advertised")
                response = await self.transport.request("session/set_mode", {
                    "sessionId": self.session_id, "modeId": mode_id}, timeout)
                self.state.modes["currentModeId"] = mode_id
                return dict(response)
        return await self._execute(request, "session/set_mode", effect, timeout=timeout + 1)

    async def prompt(self, request: OperationRequest, text: str, *, timeout: float = 120) -> DispatchOutcome:
        if request.capability_id != "acp:prompt" or not self.session_id:
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED", error="ACP session unavailable"))
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 32768:
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED", error="invalid prompt"))
        if request.arguments != {"session_id": self.session_id, "text": text}:
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED",
                                                   error="ACP prompt request payload mismatch"))
        session_id = self.session_id
        try:
            self._check(request, "acp:prompt", {"session_id": session_id, "text": text}, bound=True)
        except ValueError as exc:
            return self._failure(request, str(exc))

        async def effect() -> Mapping[str, Any]:
            async with self._session_lock:
                if self.session_id != session_id:
                    raise EffectRejected("ACP session changed before prompt")
                self._cancel_requested = False
                response = await self.transport.request("session/prompt", {
                    "sessionId": session_id, "prompt": [{"type": "text", "text": text}],
                }, timeout)
                if self.protocol_version == 2:
                    message_id = identity(response.get("messageId"))
                    return {"messageId": message_id, "completionConfirmed": False,
                            **({"_meta": response["_meta"]} if "_meta" in response else {})}
                reason = response.get("stopReason")
                if reason not in {"end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"}:
                    raise ACPProtocolError("invalid stopReason")
                if self._cancel_requested and reason != "cancelled":
                    raise ACPProtocolError("cancelled locally; remote completion cannot be trusted")
                payload = {"stopReason": reason,
                           **({"_meta": response["_meta"]} if "_meta" in response else {})}
                if reason == "cancelled" and callable(getattr(self.gate, "physical_context", None)):
                    # Central journal must record the terminal state once;
                    # never first commit SUCCEEDED and then overwrite it.
                    return OperationResult(request.operation_id, "CANCELLED", payload)
                return payload

        result = await self._execute(request, "session/prompt", effect, timeout=timeout + 1)
        if (result.operation.state == "SUCCEEDED" and isinstance(result.payload, Mapping)
            and result.payload.get("stopReason") == "cancelled"):
            cancelled = OperationResult(request.operation_id, "CANCELLED")
            await self.gate.journal.finish(request, cancelled)
            if self.store is not None and not callable(getattr(self.gate, "physical_context", None)):
                self.store.finish(request, "CANCELLED")
            return DispatchOutcome(cancelled, result.payload)
        return result

    async def cancel(self, request: OperationRequest) -> OperationResult:
        """A sent cancellation is UNCERTAIN until a remote stopReason confirms it."""
        if request.capability_id != "acp:cancel" or not self.session_id:
            return OperationResult(request.operation_id, "FAILED", error="ACP session unavailable")
        if request.arguments != {"session_id": self.session_id}:
            return OperationResult(request.operation_id, "FAILED", error="ACP cancellation payload mismatch")
        try:
            self._check(request, "acp:cancel", {"session_id": self.session_id}, bound=True)
        except ValueError as exc:
            return OperationResult(request.operation_id, "FAILED", error=str(exc))
        if not (await self.gate.decision(request)).allowed:
            return OperationResult(request.operation_id, "FAILED", error="policy denied")
        existing = await self.gate.journal.reserve(request)
        if existing is not None:
            return existing
        local_receipt = self.store is not None and not callable(getattr(self.gate, "physical_context", None))
        if local_receipt:
            try:
                self.store.reserve(self.local_session_id, "session/cancel", request)
            except EffectRejected:
                blocked = OperationResult(request.operation_id, "FAILED", error="durable ACP cancellation already recorded")
                await self.gate.journal.finish(request, blocked)
                return blocked
        self._cancel_requested = True
        try:
            async def notify():
                await self.transport.notify("session/cancel", {"sessionId": self.session_id})
            physical_context = getattr(self.gate, "physical_context", None)
            if callable(physical_context):
                await physical_context(request).run_async(notify)
            else:
                await notify()
        except Exception:
            pass
        state = OperationResult(request.operation_id, "UNCERTAIN",
                                error="cancellation requested; not remotely confirmed")
        await self.gate.journal.finish(request, state)
        if local_receipt:
            self.store.finish(request, "UNCERTAIN")
        return state

    async def updates(self, *, timeout: float = 30) -> AsyncIterator[Mapping[str, Any]]:
        if not self.session_id:
            raise ACPProtocolError("ACP session unavailable")
        while True:
            update = await self.transport.next_update(timeout)
            if not isinstance(update, Mapping) or update.get("sessionId") != self.session_id:
                raise ACPProtocolError("ACP session identity mismatch")
            event = update.get("update")
            if not isinstance(event, Mapping):
                raise ACPProtocolError("invalid ACP update")
            try:
                self.state.apply(event)
            except (ValueError, TypeError) as exc:
                raise ACPProtocolError(str(exc)) from exc
            yield dict(event)

    def detach(self) -> None:
        """Drop local attachment only; never close/delete/resend remotely."""
        if self.store is not None and self.session_id is not None:
            self.store.set_state(self.local_session_id, "DETACHED")
        self.session_id = None
