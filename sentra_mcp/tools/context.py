"""Compact MCP surface for SENTRA shared context and claims."""
from __future__ import annotations

from typing import Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from ..errors import SentraSemanticError, error_envelope
from ..identity import resolve_owner
from ..models import ResponseEnvelope
from ..services.control_plane import ControlPlaneService
from ..services.durable import DurableStateConflict, StaleFenceError


def _fail(exc: Exception) -> ResponseEnvelope:
    if isinstance(exc, SentraSemanticError):
        return error_envelope(exc)
    if isinstance(exc, StaleFenceError):
        return error_envelope(SentraSemanticError(
            "STALE_FENCE", str(exc), category="concurrency", retryable=False
        ))
    if isinstance(exc, DurableStateConflict):
        return error_envelope(SentraSemanticError(
            "STATE_CONFLICT", str(exc), category="state", retryable=False
        ))
    if isinstance(exc, PermissionError):
        code = "forbidden"
    elif isinstance(exc, FileNotFoundError):
        code = "not_found"
    elif isinstance(exc, FileExistsError):
        code = "conflict"
    elif isinstance(exc, (ValueError, TypeError)):
        code = "invalid_request"
    else:
        code = "context_error"
    return error_envelope(exc, code=code)


def _required(name: str, value: Any) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{name} is required for this action")
    return value


def register_context_tools(mcp: MCPServer, control_plane: ControlPlaneService) -> None:
    """Register one stable context tool; authority remains in the Control Plane."""

    @mcp.tool()
    def sentra_context(
        action: Literal[
            "publish", "read", "subscribe", "ack", "snapshot",
            "message_send", "message_read",
            "claim_propose", "claim_challenge", "claim_get",
            "grant_create", "grant_revoke",
        ],
        ctx: Context,
        run_id: str | None = None,
        event_type: Literal[
            "FACT", "HYPOTHESIS", "DECISION", "OBJECTION",
            "RESULT", "FAILURE", "ARTIFACT", "QUESTION",
        ] | None = None,
        subject: str | None = None,
        payload: dict[str, Any] | None = None,
        evidence: list[str] | None = None,
        confidence: float | None = None,
        supersedes: list[str] | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        to_agent_id: str | None = None,
        body: str | None = None,
        reply_to: str | None = None,
        idempotency_key: str | None = None,
        consumer_id: str | None = None,
        types: list[str] | None = None,
        subject_prefixes: list[str] | None = None,
        after_seq: int | None = None,
        seq: int | None = None,
        limit: int = 100,
        claim_id: str | None = None,
        statement: str | None = None,
        reason: str | None = None,
        context_token: str | None = None,
        permissions: list[str] | None = None,
        ttl_hours: float = 24.0,
        grant_id: str | None = None,
        owner: str | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        try:
            resolved_owner = resolve_owner(
                ctx,
                owner,
                session_token=session_token,
                require_session=True,
            )

            def delegated(
                permission: str,
                *,
                requested_agent_id: str | None = None,
            ) -> tuple[str, str, str | None]:
                rid = str(_required("run_id", run_id))
                if not context_token:
                    return rid, resolved_owner, requested_agent_id
                grant = control_plane.authorize_context_grant(
                    rid,
                    context_token,
                    permission=permission,
                    agent_id=requested_agent_id,
                )
                return rid, str(grant["owner"]), str(grant["agent_id"])

            if action == "grant_create":
                if context_token:
                    raise PermissionError("delegated context cannot create grants")
                return ResponseEnvelope.success(control_plane.create_context_grant(
                    str(_required("run_id", run_id)),
                    resolved_owner,
                    agent_id=str(_required("agent_id", agent_id)),
                    permissions=list(permissions or []),
                    ttl_hours=ttl_hours,
                ))

            if action == "grant_revoke":
                if context_token:
                    raise PermissionError("delegated context cannot revoke grants")
                return ResponseEnvelope.success(control_plane.revoke_context_grant(
                    str(_required("grant_id", grant_id)),
                    resolved_owner,
                ))

            if action == "publish":
                rid, effective_owner, effective_agent = delegated(
                    "publish", requested_agent_id=agent_id if context_token else None
                )
                return ResponseEnvelope.success(control_plane.publish_context(
                    rid,
                    effective_owner,
                    event_type=str(_required("event_type", event_type)),
                    subject=str(_required("subject", subject)),
                    payload=payload,
                    evidence=evidence,
                    confidence=confidence,
                    supersedes=supersedes,
                    task_id=task_id,
                    agent_id=effective_agent if context_token else agent_id,
                    idempotency_key=str(_required("idempotency_key", idempotency_key)),
                ))

            if action == "subscribe":
                rid, effective_owner, effective_agent = delegated("read")
                effective_consumer = effective_agent if context_token else str(
                    _required("consumer_id", consumer_id)
                )
                return ResponseEnvelope.success(control_plane.subscribe(
                    rid,
                    effective_owner,
                    str(effective_consumer),
                    types=types,
                    subject_prefixes=subject_prefixes,
                ))

            if action == "read":
                rid, effective_owner, effective_agent = delegated("read")
                return ResponseEnvelope.success(control_plane.read_context(
                    rid,
                    effective_owner,
                    consumer_id=effective_agent if context_token else consumer_id,
                    after_seq=after_seq,
                    types=types,
                    subject_prefixes=subject_prefixes,
                    limit=limit,
                ))

            if action == "ack":
                rid, effective_owner, effective_agent = delegated("read")
                effective_consumer = effective_agent if context_token else str(
                    _required("consumer_id", consumer_id)
                )
                return ResponseEnvelope.success(control_plane.acknowledge(
                    rid,
                    effective_owner,
                    str(effective_consumer),
                    int(_required("seq", seq)),
                ))

            if action == "snapshot":
                rid, effective_owner, _ = delegated("read")
                return ResponseEnvelope.success(control_plane.snapshot(
                    rid,
                    effective_owner,
                    types=types,
                    subject_prefixes=subject_prefixes,
                    limit=limit,
                ))

            if action == "message_send":
                rid, effective_owner, effective_agent = delegated(
                    "message", requested_agent_id=agent_id if context_token else None
                )
                return ResponseEnvelope.success(control_plane.send_message(
                    rid,
                    effective_owner,
                    from_agent_id=str(
                        effective_agent if context_token else _required("agent_id", agent_id)
                    ),
                    to_agent_id=str(_required("to_agent_id", to_agent_id)),
                    body=str(_required("body", body)),
                    idempotency_key=str(_required("idempotency_key", idempotency_key)),
                    reply_to=reply_to,
                ))

            if action == "message_read":
                rid, effective_owner, effective_agent = delegated(
                    "message", requested_agent_id=agent_id if context_token else None
                )
                return ResponseEnvelope.success(control_plane.read_messages(
                    rid,
                    effective_owner,
                    agent_id=str(
                        effective_agent if context_token else _required("agent_id", agent_id)
                    ),
                    after_seq=after_seq,
                    limit=limit,
                ))

            if action == "claim_propose":
                rid, effective_owner, effective_agent = delegated(
                    "claims", requested_agent_id=agent_id if context_token else None
                )
                return ResponseEnvelope.success(control_plane.propose_claim(
                    rid,
                    effective_owner,
                    subject=str(_required("subject", subject)),
                    statement=str(_required("statement", statement)),
                    evidence=list(evidence or []),
                    idempotency_key=str(_required("idempotency_key", idempotency_key)),
                    confidence=confidence,
                    task_id=task_id,
                    agent_id=effective_agent if context_token else agent_id,
                ))

            if action == "claim_challenge":
                effective_owner = resolved_owner
                effective_agent = agent_id
                if context_token:
                    _, effective_owner, effective_agent = delegated(
                        "claims", requested_agent_id=agent_id
                    )
                return ResponseEnvelope.success(control_plane.challenge_claim(
                    str(_required("claim_id", claim_id)),
                    effective_owner,
                    reason=str(_required("reason", reason)),
                    evidence=evidence,
                    idempotency_key=str(_required("idempotency_key", idempotency_key)),
                    agent_id=effective_agent,
                ))

            if action == "claim_get":
                effective_owner = resolved_owner
                if context_token:
                    _, effective_owner, _ = delegated("claims")
                return ResponseEnvelope.success(control_plane.claim_info(
                    str(_required("claim_id", claim_id)),
                    effective_owner,
                ))

            raise ValueError("unsupported context action")
        except Exception as exc:
            return _fail(exc)
