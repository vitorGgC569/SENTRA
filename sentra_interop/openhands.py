"""OpenHands EventBridge: typed, metadata-only, transport-neutral and opt-in.

Based on upstream OpenHands SDK event identity/source/kind. No OpenHands
backend/SDK import, no tool invocation and no payload forwarding.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from sentra_runtime.contracts import OperationRequest, OperationResult
from .gate import DispatchOutcome, EffectRejected, InteropGate
from .requests import InteropMappingDenied, _bounded

SOURCE_TYPES = frozenset({"agent", "user", "environment", "hook"})
EVENT_KINDS = frozenset({
    "action", "observation", "message", "system_prompt", "agent_error",
    "streaming_delta", "conversation_state_update",
})

SDK_EVENT_KINDS = frozenset({"ActionEvent","ObservationEvent","MessageEvent","SystemPromptEvent",
    "ConversationErrorEvent","AgentErrorEvent","ConversationStateUpdateEvent","StreamingDeltaEvent",
    "Condensation","CondensationRequest","CondensationSummaryEvent","UserRejectObservation","ACPToolCallEvent",
    "HookExecutionEvent","LLMCompletionLogEvent","TokenEvent","InterruptEvent","PauseEvent"})


@dataclass(frozen=True, slots=True)
class OpenHandsSDKEvent:
    """Actual SDK kind discriminator and typed tool/evidence linkage.

    source_digest identifies the complete event. public() deliberately excludes
    raw inputs, output and model reasoning; those require protected content read.
    """
    event_id: str
    kind: str
    source: str
    timestamp: str
    parent_id: str | None
    tool_name: str | None
    tool_call_id: str | None
    action_id: str | None
    tool_status: str | None
    source_digest: str
    canonical_json: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]):
        if not isinstance(raw,Mapping): raise ValueError("invalid SDK event")
        def ident(key, optional=False):
            value = raw.get(key)
            if optional and value is None: return None
            if not isinstance(value,str) or not value or len(value)>256 or "\0" in value:
                raise ValueError("invalid SDK event identity")
            return value
        event_id, kind, source = ident("id"), raw.get("kind"), raw.get("source")
        if event_id == "__root__" or kind not in SDK_EVENT_KINDS or source not in SOURCE_TYPES:
            raise ValueError("unknown SDK event kind/source")
        timestamp = ident("timestamp")
        parent = ident("parent_id", True)
        if parent == event_id: raise ValueError("SDK event self parent")
        tool, call, action = ident("tool_name",True), ident("tool_call_id",True), ident("action_id",True)
        if kind in {"ActionEvent","ObservationEvent","UserRejectObservation"} and (tool is None or call is None):
            raise ValueError("SDK tool event missing tool linkage")
        if kind == "ObservationEvent" and (action is None or not isinstance(raw.get("observation"),Mapping)):
            raise ValueError("SDK observation missing evidence linkage")
        if kind == "ActionEvent" and raw.get("action") is not None and not isinstance(raw["action"],Mapping):
            raise ValueError("SDK action must be typed JSON")
        if kind == "ACPToolCallEvent" and call is None: raise ValueError("ACP tool event missing call ID")
        status = raw.get("status")
        if status is not None and not isinstance(status,str): raise ValueError("invalid provider tool status")
        text = json.dumps(raw,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":"))
        if len(text.encode())>512000: raise ValueError("SDK event exceeds protected evidence bound")
        return cls(event_id,kind,source,timestamp,parent,tool,call,action,status,
                   hashlib.sha256(text.encode()).hexdigest(),text)

    def public(self):
        return {"event_id":self.event_id,"kind":self.kind,"source":self.source,"timestamp":self.timestamp,
                "parent_id":self.parent_id,"tool_name":self.tool_name,"tool_call_id":self.tool_call_id,
                "action_id":self.action_id,"tool_status":self.tool_status,"sha256":self.source_digest,
                "evidence_origin":"openhands-agent-server","verified_sentra_effect":False}


@dataclass(frozen=True, slots=True)
class OpenHandsEvent:
    conversation_id: str
    event_id: str
    kind: str
    source: str
    sequence: int
    parent_id: str | None = None

    @classmethod
    def from_mapping(
        cls, event: Mapping[str, Any], *, conversation_id: str, sequence: int
    ) -> "OpenHandsEvent":
        if not isinstance(event, Mapping):
            raise ValueError("invalid event")
        if not isinstance(conversation_id, str) or not conversation_id or len(conversation_id) > 256:
            raise ValueError("invalid conversation")
        if type(sequence) is not int or sequence < 0:
            raise ValueError("invalid sequence")
        event_id, kind, source = event.get("id"), event.get("kind"), event.get("source")
        if not isinstance(event_id, str) or not event_id or len(event_id) > 256 or event_id == "__root__":
            raise ValueError("invalid event ID")
        if not isinstance(kind, str) or kind not in EVENT_KINDS:
            raise ValueError("unrecognized OpenHands event kind")
        if not isinstance(source, str) or source not in SOURCE_TYPES:
            raise ValueError("invalid event source")
        parent_id = event.get("parent_id")
        if parent_id is not None and (not isinstance(parent_id, str) or not parent_id
                                       or len(parent_id) > 256 or parent_id == event_id):
            raise ValueError("invalid OpenHands parent ID")
        return cls(conversation_id, event_id, kind, source, sequence, parent_id)

    def metadata(self) -> dict[str, Any]:
        """Only stable routing metadata; excludes raw events/messages/secrets."""
        return {
            "conversation_id": self.conversation_id, "event_id": self.event_id,
            "kind": self.kind, "source": self.source, "sequence": self.sequence,
            "parent_id": self.parent_id,
        }


class OpenHandsEventBridge:
    """Fail-closed, sequential OpenHands event metadata ingestion.

    The enclosing caller MUST authenticate the origin and bind a specific
    conversation to one SENTRA work item before calling this bridge.
    """

    def __init__(self, gate: InteropGate, *, conversation_id: str,
                 principal_id: str, work_item_id: str) -> None:
        if not all(isinstance(x, str) and x and len(x) <= 256 for x in
                   (conversation_id, principal_id, work_item_id)):
            raise ValueError("verified OpenHands identity and workspace required")
        self.gate = gate
        self.conversation_id = conversation_id
        self.principal_id = principal_id
        self.work_item_id = work_item_id
        self._lock = asyncio.Lock()
        self._events: dict[str, OpenHandsEvent] = {}
        self._last_sequence = -1

    async def accept(
        self, request: OperationRequest, raw_event: Mapping[str, Any], *,
        authenticated_conversation_id: str, sequence: int,
    ) -> DispatchOutcome:
        if authenticated_conversation_id != self.conversation_id:
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED",
                                                   error="untrusted OpenHands conversation"))
        if (request.capability_id != "openhands:event"
            or request.principal_id != self.principal_id
            or request.work_item_id != self.work_item_id
            or request.machine_id != self.gate.machine.machine_id):
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED",
                                                   error="OpenHands scope mismatch"))
        try:
            # Do not trust raw OpenHands payloads as authority, or allow
            # secrets into telemetry/authorized OperationRequest arguments.
            _bounded(raw_event)
            event = OpenHandsEvent.from_mapping(raw_event,
                                                 conversation_id=self.conversation_id,
                                                 sequence=sequence)
        except (InteropMappingDenied, ValueError, TypeError):
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED",
                                                   error="OpenHands event validation failed"))
        if request.arguments != event.metadata():
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED",
                                                   error="OpenHands metadata binding mismatch"))

        async def apply() -> dict[str, Any]:
            async with self._lock:
                if not (await self.gate.decision(request)).allowed:
                    raise EffectRejected("OpenHands policy revoked")
                if event.event_id in self._events:
                    raise EffectRejected("duplicate OpenHands event")
                if event.sequence <= self._last_sequence:
                    raise EffectRejected("OpenHands sequence replay")
                self._events[event.event_id] = event
                self._last_sequence = event.sequence
                return event.metadata()

        return await self.gate.execute(request, apply)

    async def observe(self, event_id: str) -> OpenHandsEvent | None:
        async with self._lock:
            return self._events.get(event_id)
