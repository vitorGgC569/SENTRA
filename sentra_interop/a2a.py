"""A2A task/message envelope admission and monotonically validated event stream.

This is a transport-neutral boundary, NOT a running A2A server or authenticated
HTTP client. A trusted upstream MUST bind an authenticated principal to each
incoming event before calling this module.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from sentra_runtime.contracts import OperationRequest, OperationResult
from .gate import DispatchOutcome, EffectRejected, InteropGate

TERMINAL = frozenset({"completed", "failed", "canceled", "rejected"})
STATES = frozenset({"submitted", "working", "input-required", "auth-required", *TERMINAL})
PART_TYPES = frozenset({"text", "data"})
MAX_EVENT_BYTES = 65536


class A2AValidationError(ValueError):
    pass


def _required(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise A2AValidationError(f"invalid {field}")
    return value


def _bounded(payload: Any) -> None:
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise A2AValidationError("invalid JSON") from exc
    if len(encoded) > MAX_EVENT_BYTES:
        raise A2AValidationError("A2A payload too large")


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    principal_id: str
    agent_id: str
    trust_domain: str

    def __post_init__(self) -> None:
        _required(self.principal_id, "principal_id")
        _required(self.agent_id, "agent_id")
        _required(self.trust_domain, "trust_domain")


@dataclass(frozen=True, slots=True)
class A2AEnvelope:
    """Local SENTRA envelope carrying a strict A2A task status event.

    event_id/sequence are SENTRA stream metadata, not wire-level A2A fields.
    """

    identity: AgentIdentity
    task_id: str
    context_id: str
    event_id: str
    sequence: int
    state: str
    parts: tuple[Mapping[str, Any], ...] = ()
    artifact_id: str | None = None
    artifact_append: bool = False
    artifact_final: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.identity, AgentIdentity):
            raise A2AValidationError("invalid agent identity")
        for field in ("task_id", "context_id", "event_id"):
            _required(getattr(self, field), field)
        if type(self.sequence) is not int or self.sequence < 0:
            raise A2AValidationError("invalid stream sequence")
        if self.state not in STATES:
            raise A2AValidationError("unknown task state")
        if self.artifact_id is not None:
            _required(self.artifact_id, "artifact_id")
        if type(self.artifact_append) is not bool or type(self.artifact_final) is not bool:
            raise A2AValidationError("invalid artifact flags")
        if self.artifact_append and not self.artifact_id:
            raise A2AValidationError("append requires artifact identity")
        if len(self.parts) > 16:
            raise A2AValidationError("too many parts")
        for part in self.parts:
            if not isinstance(part, Mapping):
                raise A2AValidationError("part must be object")
            kind = part.get("type")
            if kind not in PART_TYPES:
                # filePart URI can be an SSRF or untrusted binary; intentionally denied.
                raise A2AValidationError("unsupported part type")
            expected = {"type", kind}
            if set(part) != expected:
                raise A2AValidationError("unexpected A2A part payload")
            if kind == "text" and (not isinstance(part.get("text"), str) or
                                    len(part["text"]) > 32768):
                raise A2AValidationError("invalid text part")
            if kind == "data" and not isinstance(part.get("data"), Mapping):
                raise A2AValidationError("invalid data part")
        _bounded({"parts": self.parts, "state": self.state})

    @classmethod
    def from_task_event(
        cls,
        event: Mapping[str, Any],
        *,
        identity: AgentIdentity,
        authenticated_principal_id: str,
        event_id: str,
        sequence: int,
    ) -> "A2AEnvelope":
        if not isinstance(event, Mapping) or identity.principal_id != authenticated_principal_id:
            raise A2AValidationError("A2A sender identity is not authenticated")
        if "id" in event and "taskId" in event and event["id"] != event["taskId"]:
            raise A2AValidationError("conflicting task identifiers")
        task_id = event.get("id") or event.get("taskId")
        context_id = event.get("contextId")
        status = event.get("status")
        if not isinstance(status, Mapping):
            raise A2AValidationError("missing A2A status")
        state = status.get("state")
        if isinstance(state, str):
            state = state.lower().replace("_", "-")
            if state.startswith("task-state-"):
                state = state[len("task-state-"):]
        message = status.get("message", {})
        parts: Any = []
        if message:
            if not isinstance(message, Mapping):
                raise A2AValidationError("invalid A2A message")
            parts = message.get("parts", [])
        if not isinstance(parts, list):
            raise A2AValidationError("invalid A2A parts")
        # Proto JSON uses text/data keys rather than an explicit "type".
        normalized: list[Mapping[str, Any]] = []
        for part in parts:
            if not isinstance(part, Mapping):
                raise A2AValidationError("invalid A2A part")
            if set(part) == {"text"} and isinstance(part["text"], str):
                normalized.append({"type": "text", "text": part["text"]})
            elif set(part) == {"data"} and isinstance(part["data"], Mapping):
                normalized.append({"type": "data", "data": dict(part["data"])})
            else:
                raise A2AValidationError("file/unknown parts are not accepted")
        return cls(identity, _required(task_id, "task_id"), _required(context_id, "context_id"),
                   event_id, sequence, state, tuple(normalized))

    @classmethod
    def from_stream_response(
        cls, response: Mapping[str, Any], *, identity: AgentIdentity,
        authenticated_principal_id: str, event_id: str, sequence: int,
        current_state: str | None = None,
    ) -> "A2AEnvelope":
        """Normalize A2A Task, TaskStatusUpdateEvent and artifact stream events."""
        if not isinstance(response, Mapping) or len(response) != 1:
            raise A2AValidationError("unexpected or ambiguous A2A streaming response")
        if "task" in response:
            return cls.from_task_event(response["task"], identity=identity,
                                       authenticated_principal_id=authenticated_principal_id,
                                       event_id=event_id, sequence=sequence)
        if "statusUpdate" in response:
            update = response["statusUpdate"]
            if not isinstance(update, Mapping):
                raise A2AValidationError("invalid status update")
            return cls.from_task_event(
                {"id": update.get("taskId"), "contextId": update.get("contextId"),
                 "status": update.get("status")},
                identity=identity, authenticated_principal_id=authenticated_principal_id,
                event_id=event_id, sequence=sequence,
            )
        if "artifactUpdate" in response:
            update = response["artifactUpdate"]
            if not isinstance(update, Mapping) or current_state not in STATES:
                raise A2AValidationError("artifact stream requires verified task state")
            artifact = update.get("artifact")
            if not isinstance(artifact, Mapping) or not set(artifact).issubset(
                {"artifactId", "parts", "name", "description", "metadata"}
            ):
                raise A2AValidationError("invalid artifact")
            base = cls.from_task_event(
                {"id": update.get("taskId"), "contextId": update.get("contextId"),
                 "status": {"state": current_state, "message": {"parts": artifact.get("parts", [])}}},
                identity=identity, authenticated_principal_id=authenticated_principal_id,
                event_id=event_id, sequence=sequence,
            )
            if type(update.get("append", False)) is not bool or type(update.get("lastChunk", False)) is not bool:
                raise A2AValidationError("invalid artifact flags")
            return cls(base.identity, base.task_id, base.context_id, base.event_id,
                       base.sequence, base.state, base.parts,
                       artifact_id=_required(artifact.get("artifactId"), "artifactId"),
                       artifact_append=update.get("append", False),
                       artifact_final=update.get("lastChunk", False))
        raise A2AValidationError("unsupported streaming response variant")

    def to_task_status_event(self) -> Mapping[str, Any]:
        """Protocol-shaped payload for an authenticated enclosing A2A transport."""
        parts = [
            {"text": part["text"]} if part["type"] == "text" else {"data": dict(part["data"])}
            for part in self.parts
        ]
        if self.artifact_id is not None:
            return {"taskId": self.task_id, "contextId": self.context_id,
                    "artifact": {"artifactId": self.artifact_id, "parts": parts},
                    "append": self.artifact_append, "lastChunk": self.artifact_final}
        status: dict[str, Any] = {"state": self.state}
        if parts:
            status["message"] = {"role": "agent", "parts": parts}
        return {"taskId": self.task_id, "contextId": self.context_id, "status": status,
                "final": self.state in TERMINAL}


def operation_arguments(event: A2AEnvelope) -> dict[str, Any]:
    """Stable, scope-bound A2A arguments; must not grant execution authority."""
    return {
        "task_id": event.task_id, "context_id": event.context_id,
        "event_id": event.event_id, "sequence": event.sequence,
        "state": event.state, "agent_id": event.identity.agent_id,
        "trust_domain": event.identity.trust_domain,
    }


class A2ACancelTransport(Protocol):
    async def cancel_task(self, task_id: str) -> Mapping[str, Any]: ...


class A2ATaskBoundary:
    """Validates identity, event dedupe and task transitions before state mutation."""

    def __init__(self, gate: InteropGate, *, trusted_agents: frozenset[AgentIdentity] = frozenset(),
                 require_mapped_arguments: bool = False) -> None:
        self.gate = gate
        self._trusted_agents = frozenset(trusted_agents)
        self._require_mapped_arguments = require_mapped_arguments
        self._lock = asyncio.Lock()
        self._tasks: dict[str, tuple[str, AgentIdentity, int, str]] = {}
        self._seen: dict[tuple[str, str], str] = {}
        self._operation_envelopes: dict[str, str] = {}
        self._artifacts: dict[tuple[str, str], bool] = {}

    async def accept(self, request: OperationRequest, event: A2AEnvelope) -> DispatchOutcome:
        if (request.capability_id != "a2a:ingest" or
            event.identity not in self._trusted_agents or
            request.principal_id != event.identity.principal_id or
            request.work_item_id != event.context_id):
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED", error="A2A identity/scope mismatch"))

        if self._require_mapped_arguments and request.arguments != operation_arguments(event):
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED",
                                                   error="A2A event arguments mismatch"))

        # Operation identity must bind to the *actual* event, not just to
        # OperationRequest.arguments. Otherwise a duplicate operation_id
        # could claim success for a different A2A event.
        try:
            envelope_signature = json.dumps({
                "event": event.to_task_status_event(),
                "event_id": event.event_id, "sequence": event.sequence,
                "identity": [event.identity.principal_id, event.identity.agent_id,
                             event.identity.trust_domain],
            }, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED",
                                                   error="invalid A2A payload"))

        async with self._lock:
            previous = self._operation_envelopes.get(request.operation_id)
            if previous is not None and previous != envelope_signature:
                return DispatchOutcome(OperationResult(request.operation_id, "FAILED",
                                                       error="A2A operation identity collision"))
            self._operation_envelopes[request.operation_id] = envelope_signature

        async def apply() -> Mapping[str, Any]:
            async with self._lock:
                # Revalidate after lock acquisition and immediately before
                # mutating local task/artifact state; no await after this check.
                if not (await self.gate.decision(request)).allowed:
                    raise EffectRejected("A2A authorization revoked")
                prior = self._tasks.get(event.task_id)
                fingerprint = json.dumps(event.to_task_status_event(), sort_keys=True)
                identity = (event.task_id, event.event_id)
                if identity in self._seen:
                    raise EffectRejected("replayed A2A event")
                if prior:
                    context, agent, sequence, state = prior
                    if context != event.context_id or agent != event.identity:
                        raise EffectRejected("task identity changed")
                    if state in TERMINAL or event.sequence <= sequence:
                        raise EffectRejected("terminal or out-of-order A2A update")
                    if event.state == "submitted" and state != "submitted":
                        raise EffectRejected("task cannot restart")
                elif event.sequence != 0 or event.state != "submitted":
                    raise EffectRejected("first event must submit new task at sequence zero")
                if event.artifact_id is not None:
                    key = (event.task_id, event.artifact_id)
                    previous_final = self._artifacts.get(key)
                    if event.artifact_append and previous_final is not False:
                        raise EffectRejected("artifact has no open predecessor")
                    if not event.artifact_append and previous_final is not None:
                        raise EffectRejected("artifact already exists")
                    self._artifacts[key] = event.artifact_final
                if event.state in TERMINAL and any(
                    artifact_task == event.task_id and not final
                    for (artifact_task, _), final in self._artifacts.items()
                ):
                    raise EffectRejected("terminal task has incomplete artifact")
                self._tasks[event.task_id] = (event.context_id, event.identity, event.sequence, event.state)
                self._seen[identity] = fingerprint
                return {"taskId": event.task_id, "state": event.state, "sequence": event.sequence}

        # A failed validation after uncertain backend is not retried automatically.
        return await self.gate.execute(request, apply)

    async def cancel(
        self, request: OperationRequest, *, task_id: str, transport: A2ACancelTransport
    ) -> DispatchOutcome:
        """Only a remote terminal 'canceled' response proves cancellation."""
        if request.capability_id != "a2a:cancel":
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED", error="invalid A2A capability"))
        async with self._lock:
            current = self._tasks.get(task_id)
        if current is None or current[0] != request.work_item_id or current[1].principal_id != request.principal_id:
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED", error="unknown A2A task"))
        if current[3] in TERMINAL:
            return DispatchOutcome(OperationResult(request.operation_id, "FAILED", error="task already terminal"))

        async def invoke() -> Mapping[str, Any]:
            return await transport.cancel_task(task_id)

        result = await self.gate.execute(request, invoke, timeout=15)
        if result.operation.state == "SUCCEEDED":
            value = result.payload
            if (not isinstance(value, Mapping)
                or (value.get("id") or value.get("taskId")) != task_id
                or value.get("contextId") != request.work_item_id):
                uncertain = OperationResult(request.operation_id, "UNCERTAIN",
                                            error="A2A cancellation response identity not verified")
                await self.gate.journal.finish(request, uncertain)
                return DispatchOutcome(uncertain)
            state = value.get("status", {}).get("state") if isinstance(value.get("status"), Mapping) else None
            if isinstance(state, str):
                state = state.lower().replace("_", "-")
                if state.startswith("task-state-"):
                    state = state[len("task-state-"):]
            if state == "canceled":
                async with self._lock:
                    latest = self._tasks.get(task_id)
                    competing_terminal = latest is None or latest[3] in (TERMINAL - {"canceled"})
                    if latest and not competing_terminal and latest[3] != "canceled":
                        self._tasks[task_id] = (latest[0], latest[1], latest[2], "canceled")
                if competing_terminal:
                    uncertain = OperationResult(request.operation_id, "UNCERTAIN",
                                                error="local task state changed during cancellation")
                    await self.gate.journal.finish(request, uncertain)
                    return DispatchOutcome(uncertain, value)
                cancelled = OperationResult(request.operation_id, "CANCELLED")
                await self.gate.journal.finish(request, cancelled)
                return DispatchOutcome(cancelled, value)
            uncertain = OperationResult(request.operation_id, "UNCERTAIN", error="cancel not confirmed by A2A peer")
            await self.gate.journal.finish(request, uncertain)
            return DispatchOutcome(uncertain, value)
        return result

    async def state(self, task_id: str) -> str | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            return task[3] if task else None
