"""A bounded local JSONL event stream for OpenHands-shaped SDK events.

NOT the OpenHands SDK wire protocol; no external server is contacted. Launch
is pinned and separately authorized. Reattach is a new authorized read cursor
on the same live connection; cross-process reconnect is unsupported.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from sentra_runtime.contracts import OperationRequest, OperationResult
from .gate import InteropGate, DispatchOutcome
from .openhands import OpenHandsEvent, OpenHandsEventBridge
from .requests import _bounded, InteropMappingDenied
from .acp_process import ACPProcessOwner, spawn_owned

MAX_LINE = 65536


class OpenHandsLocalError(ValueError):
    pass


def _serialize(msg: Mapping[str, Any]) -> bytes:
    raw = json.dumps(msg, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_LINE:
        raise OpenHandsLocalError("oversized OpenHands local frame")
    return raw + b"\n"


def _parse(raw: bytes) -> Mapping[str, Any]:
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise OpenHandsLocalError("duplicate frame key")
            obj[key] = value
        return obj
    result = json.loads(raw, object_pairs_hook=unique,
                        parse_constant=lambda _: (_ for _ in ()).throw(OpenHandsLocalError("nonfinite value")))
    if not isinstance(result, dict) or result.get("version") != 1:
        raise OpenHandsLocalError("unrecognized local stream protocol")
    return result


class OpenHandsLocalStream:
    """One controlled child plus immutable typed event snapshots."""

    def __init__(self, process: asyncio.subprocess.Process, *, gate: InteropGate,
                 conversation_id: str, principal_id: str, work_item_id: str,
                 process_owner: ACPProcessOwner | None = None) -> None:
        self.process, self.gate = process, gate
        self._process_owner = process_owner
        self.conversation_id, self.principal_id, self.work_item_id = (
            conversation_id, principal_id, work_item_id)
        self.bridge = OpenHandsEventBridge(
            gate, conversation_id=conversation_id, principal_id=principal_id,
            work_item_id=work_item_id)
        self._events: list[dict[str, Any]] = []
        self._artifacts: list[dict[str, Any]] = []
        self._pending_cancel: asyncio.Future | None = None
        self._write_lock = asyncio.Lock()
        self._closed = False
        self._reader_failure: Exception | None = None
        self._hello = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._reader_loop())

    @classmethod
    async def launch(cls, *, gate: InteropGate, request: OperationRequest,
                     executable: str, argv: tuple[str, ...], cwd: str,
                     conversation_id: str, timeout: float = 4) -> "OpenHandsLocalStream":
        if (request.capability_id != "openhands:launch"
            or not conversation_id or len(conversation_id) > 256
            or request.arguments != {"executable": executable, "args":list(argv),
                                     "cwd":cwd, "conversation_id":conversation_id}
            or not isinstance(argv, tuple) or any(not isinstance(a, str) or "\0" in a for a in argv)
            or not Path(executable).is_absolute() or not Path(executable).is_file()
            or not Path(cwd).is_absolute() or not Path(cwd).is_dir()):
            raise OpenHandsLocalError("unapproved OpenHands local launch")
        if not (await asyncio.wait_for(gate.decision(request),timeout)).allowed:
            raise OpenHandsLocalError("OpenHands launch denied")
        previous = await gate.journal.reserve(request)
        if previous is not None:
            raise OpenHandsLocalError("OpenHands launch replay denied")
        session = None
        owned = None
        try:
            physical = getattr(gate,"physical_context",None)
            context = physical(request) if callable(physical) else None
            async def spawn():
                nonlocal owned
                proc, owned = await spawn_owned(executable,argv,cwd=cwd,env={},
                    stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,limit=MAX_LINE+1,
                    checkpoint=context.checkpoint if context else None)
                return proc
            proc = await asyncio.wait_for(context.run_async(spawn) if context else spawn(),timeout)
            session = cls(proc, gate=gate, conversation_id=conversation_id,
                          principal_id=request.principal_id, work_item_id=request.work_item_id,process_owner=owned)
            hello = await asyncio.wait_for(session._hello, timeout)
            if hello.get("type") != "hello" or hello.get("conversation_id") != conversation_id:
                raise OpenHandsLocalError("bad conversation handshake")
            if not (await asyncio.wait_for(gate.decision(request), timeout)).allowed:
                raise OpenHandsLocalError("launch policy revoked")
            await gate.journal.finish(request, OperationResult(request.operation_id, "SUCCEEDED"))
            return session
        except BaseException:
            if session is not None:
                await asyncio.shield(session.close())
            elif owned is not None:
                await asyncio.shield(owned.close())
            await gate.journal.finish(request, OperationResult(
                request.operation_id, "UNCERTAIN", error="OpenHands local launch unknown"))
            raise

    async def _send(self, frame: Mapping[str, Any]) -> None:
        if self._closed or self.process.stdin is None or self._reader_failure:
            raise OpenHandsLocalError("OpenHands peer disconnected")
        async with self._write_lock:
            from sentra_runtime.effect_boundary import current_effect_context
            context=current_effect_context.get()
            if context is not None: context.checkpoint()
            self.process.stdin.write(_serialize(frame))
            await self.process.stdin.drain()

    def _request(self, event: OpenHandsEvent) -> OperationRequest:
        return OperationRequest(
            "oh-"+self.conversation_id+"-"+event.event_id, self.principal_id,
            self.gate.machine.machine_id, "openhands:event", self.work_item_id,
            "oh-key-"+self.conversation_id+"-"+event.event_id, event.metadata(),
        )

    async def _reader_loop(self) -> None:
        try:
            while True:
                if self.process.stdout is None:
                    raise OpenHandsLocalError("missing stdout")
                line = await self.process.stdout.readline()
                if not line or len(line) > MAX_LINE:
                    raise OpenHandsLocalError("invalid or disconnected peer")
                msg = _parse(line)
                kind = msg.get("type")
                if kind == "hello" and not self._hello.done():
                    if msg.get("conversation_id") != self.conversation_id:
                        raise OpenHandsLocalError("conversation handshake mismatch")
                    self._hello.set_result(msg)
                elif kind == "event":
                    if set(msg) != {"version", "type", "sequence", "event"}:
                        raise OpenHandsLocalError("unapproved event frame")
                    raw_event = msg["event"]
                    event = OpenHandsEvent.from_mapping(
                        raw_event, conversation_id=self.conversation_id, sequence=msg["sequence"])
                    outcome = await self.bridge.accept(
                        self._request(event), raw_event,
                        authenticated_conversation_id=self.conversation_id, sequence=msg["sequence"])
                    if outcome.operation.state != "SUCCEEDED":
                        raise OpenHandsLocalError("event rejected by SENTRA policy")
                    self._events.append(event.metadata())
                elif kind == "artifact":
                    if set(msg) != {"version", "type", "sequence", "artifact_id", "text"}:
                        raise OpenHandsLocalError("unapproved artifact frame")
                    ident, content, sequence = msg["artifact_id"], msg["text"], msg["sequence"]
                    if (not isinstance(ident, str) or not 0 < len(ident) <= 128
                        or not isinstance(content, str) or len(content.encode("utf-8")) > 16384
                        or type(sequence) is not int or sequence < 0):
                        raise OpenHandsLocalError("unsafe OpenHands artifact")
                    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    request = OperationRequest(
                        "oh-artifact-"+self.conversation_id+"-"+ident,
                        self.principal_id, self.gate.machine.machine_id, "openhands:artifact",
                        self.work_item_id, "oh-artifact-key-"+self.conversation_id+"-"+ident,
                        {"conversation_id":self.conversation_id, "artifact_id":ident,
                         "sha256":digest, "sequence":sequence})
                    async def admit():
                        self._artifacts.append({"artifact_id":ident, "text":content,
                                                "sha256":digest, "sequence":sequence})
                        return {"sha256":digest}
                    outcome = await self.gate.execute(request, admit)
                    if outcome.operation.state != "SUCCEEDED":
                        raise OpenHandsLocalError("artifact not authorized")
                elif kind == "tool_request":
                    ident = msg.get("id")
                    if type(ident) not in (int, str) or len(str(ident)) > 128:
                        raise OpenHandsLocalError("invalid agent tool request")
                    # Never honor agent-initiated terminal/filesystem/tools.
                    await self._send({"version":1, "type":"tool_denied","id":ident})
                elif kind == "cancel_ack":
                    if self._pending_cancel is not None and not self._pending_cancel.done():
                        self._pending_cancel.set_result(msg.get("conversation_id") == self.conversation_id)
                elif kind == "done":
                    if msg.get("conversation_id") != self.conversation_id:
                        raise OpenHandsLocalError("wrong session completion")
                    return
                else:
                    raise OpenHandsLocalError("unexpected OpenHands wire frame")
        except BaseException:
            self._reader_failure = OpenHandsLocalError("OpenHands stream disconnected")
            if not self._hello.done():
                self._hello.set_exception(self._reader_failure)
            if self._pending_cancel is not None and not self._pending_cancel.done():
                self._pending_cancel.set_result(False)
            if self._process_owner is not None:
                await self._process_owner.close()
            elif self.process.returncode is None:
                try:
                    self.process.terminate()
                except ProcessLookupError:
                    pass

    async def start(self, request: OperationRequest) -> DispatchOutcome:
        if (request.capability_id != "openhands:start"
            or request.arguments != {"conversation_id":self.conversation_id}
            or request.principal_id != self.principal_id
            or request.work_item_id != self.work_item_id):
            return DispatchOutcome(OperationResult(request.operation_id,"FAILED",
                                                   error="OpenHands start scope mismatch"))
        return await self.gate.execute(request, lambda: self._send({
            "version":1,"type":"start","conversation_id":self.conversation_id}),timeout=3)

    async def attach(self, request: OperationRequest, *, after_sequence: int = -1
                     ) -> tuple[Mapping[str, Any], ...]:
        """Authorized same-process reattach; never replays effects."""
        if (request.capability_id != "openhands:read"
            or request.principal_id != self.principal_id
            or request.work_item_id != self.work_item_id
            or request.arguments != {"conversation_id":self.conversation_id,
                                     "after_sequence":after_sequence}
            or not (await self.gate.decision(request)).allowed):
            raise OpenHandsLocalError("reattach denied")
        return tuple(dict(x) for x in self._events if x["sequence"] > after_sequence)

    async def artifacts(self, request: OperationRequest) -> tuple[Mapping[str, Any], ...]:
        if (request.capability_id != "openhands:read"
            or request.principal_id != self.principal_id
            or request.work_item_id != self.work_item_id
            or request.arguments != {"conversation_id":self.conversation_id,
                                     "after_sequence":-1}
            or not (await self.gate.decision(request)).allowed):
            raise OpenHandsLocalError("artifact read denied")
        return tuple(dict(x) for x in self._artifacts)

    async def cancel(self, request: OperationRequest, *, timeout: float = 2
                     ) -> OperationResult:
        if (request.capability_id != "openhands:cancel"
            or request.principal_id != self.principal_id
            or request.work_item_id != self.work_item_id
            or request.arguments != {"conversation_id":self.conversation_id}):
            return OperationResult(request.operation_id,"FAILED",
                                   error="OpenHands cancel scope mismatch")

        async def invoke() -> dict[str, bool]:
            if self._pending_cancel is not None:
                raise OpenHandsLocalError("cancellation already requested")
            self._pending_cancel = asyncio.get_running_loop().create_future()
            await self._send({"version":1,"type":"cancel","conversation_id":self.conversation_id})
            acknowledged = await asyncio.wait_for(self._pending_cancel, timeout)
            if not acknowledged:
                raise OpenHandsLocalError("cancel not acknowledged")
            if callable(getattr(self.gate,"physical_context",None)):
                return OperationResult(request.operation_id,"CANCELLED",{"fixture_ack":True})
            return {"ack":True}
        outcome = await self.gate.execute(request, invoke, timeout=timeout+0.1)
        if outcome.operation.state != "SUCCEEDED":
            return outcome.operation
        confirmation = OperationResult(request.operation_id,"CANCELLED")
        await self.gate.journal.finish(request, confirmation)
        return confirmation

    async def close(self) -> None:
        self._closed = True
        if self.process.stdin:
            self.process.stdin.close()
        if self._process_owner is not None:
            await self._process_owner.close()
        elif self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.process.wait(),3)
            except asyncio.TimeoutError:
                if self.process.returncode is None:
                    self.process.kill()
                await self.process.wait()
        self._task.cancel()
        await asyncio.gather(self._task,return_exceptions=True)
