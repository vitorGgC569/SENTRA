"""Compact MCP surface for durable SENTRA execution.

The durable runtime intentionally exposes four stable tools instead of one tool
per state-machine action. This keeps tools/list small and reduces schema drift.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from pydantic import Field

from ..errors import SentraSemanticError, error_envelope
from ..identity import resolve_owner
from ..models import ResponseEnvelope
from ..services.capabilities import CapabilityService
from ..services.durable import DurableRunService, DurableStateConflict, StaleFenceError
from ..services.filesystem import FilesystemService


def _ok(value: dict[str, Any]) -> ResponseEnvelope:
    return ResponseEnvelope.success(value)


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
        code = "durable_error"
    return error_envelope(exc, code=code)


def _required(name: str, value: Any) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{name} is required for this action")
    return value


def register_durable_tools(
    mcp: MCPServer,
    durable: DurableRunService,
    capabilities: CapabilityService,
    filesystem: FilesystemService,
    processes: Any | None = None,
) -> None:
    """Register the compact durable execution/control surface."""

    @mcp.tool()
    async def sentra_run(
        action: Literal[
            "contract_manifest", "contract_negotiate",
            "create", "status", "resume", "transition", "list",
            "events", "events_wait", "checkpoint", "reconcile", "capabilities_used",
            "agent_assign", "agent_update",
            "chat_bind", "chat_update", "chat_rebind"
        ],
        ctx: Context,
        run_id: str | None = None,
        workspace: str | None = None,
        idempotency_key: str | None = None,
        required_capabilities: list[str] | None = None,
        target: Literal["edge", "browser", "chatgpt"] | None = None,
        client_protocol_version: str | None = None,
        client_schema_hash: str | None = None,
        client_capabilities: dict[str, Any] | list[str] | None = None,
        capabilities_used: list[str] | None = None,
        agent_id: str | None = None,
        chat_id: str | None = None,
        role: str | None = None,
        task_id: str | None = None,
        agent_state: Literal[
            "AVAILABLE", "ACTIVE", "WAITING", "SUSPECTED_STALL",
            "RECOVERING", "ORPHANED", "DEAD"
        ] | None = None,
        agent_desired_state: Literal[
            "AVAILABLE", "ACTIVE", "WAITING", "SUSPECTED_STALL",
            "RECOVERING", "ORPHANED", "DEAD"
        ] | None = None,
        chat_state: Literal[
            "READY", "GENERATING", "TOOL_WAIT", "PLATFORM_HOLD",
            "WAITING_USER", "IDLE", "DISCONNECTED"
        ] | None = None,
        chat_desired_state: Literal[
            "READY", "GENERATING", "TOOL_WAIT", "PLATFORM_HOLD",
            "WAITING_USER", "IDLE", "DISCONNECTED"
        ] | None = None,
        provider: str | None = None,
        conversation_id: str | None = None,
        conversation_url: str | None = None,
        project_id: str | None = None,
        project_url: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
        state: Literal[
            "RUNNING", "PAUSED", "RECOVERING", "BLOCKED",
            "SUCCEEDED", "FAILED", "CANCELLED"
        ] | None = None,
        reason: str = "",
        result: dict[str, Any] | None = None,
        rollback: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        label: str = "checkpoint",
        stale_after_s: Annotated[float, Field(ge=5, le=86400)] = 120.0,
        after_seq: Annotated[int, Field(ge=0)] = 0,
        wait_timeout_s: Annotated[float, Field(gt=0, le=25)] = 5.0,
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Inspect/negotiate the contract or control a durable Run."""
        try:
            if action == "contract_manifest":
                return _ok(await capabilities.manifest(target))
            if action == "contract_negotiate":
                return _ok(await capabilities.negotiate(
                    client_protocol_version=client_protocol_version,
                    client_schema_hash=client_schema_hash,
                    client_capabilities=client_capabilities,
                    required_capabilities=required_capabilities,
                    target=target,
                ))

            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            if action == "create":
                negotiation = await capabilities.negotiate(
                    client_protocol_version=client_protocol_version,
                    client_schema_hash=client_schema_hash,
                    client_capabilities=client_capabilities,
                    required_capabilities=required_capabilities,
                    target=target,
                )
                if not negotiation["compatible"]:
                    first = negotiation["reasons"][0]
                    raise SentraSemanticError(
                        str(first["code"]),
                        str(first["message"]),
                        category="contract",
                        retryable=False,
                        details=first,
                    )
                return _ok(durable.create_run(
                    owner,
                    workspace=workspace,
                    run_id=run_id,
                    idempotency_key=idempotency_key,
                    required_capabilities=required_capabilities,
                    capability_snapshot=negotiation,
                ))
            if action == "list":
                return _ok(durable.list_runs(owner, offset=offset, limit=limit))

            rid = str(_required("run_id", run_id))
            if action == "status":
                return _ok(durable.run_status(rid, owner))
            if action == "resume":
                return _ok(durable.resume(rid, owner))
            if action == "events":
                return _ok(durable.events(rid, owner, offset=offset, limit=limit))
            if action == "events_wait":
                deadline = asyncio.get_running_loop().time() + wait_timeout_s
                while True:
                    page = durable.events_after(
                        rid, owner, after_seq=after_seq, limit=limit
                    )
                    if page["items"]:
                        page["wait_timed_out"] = False
                        return _ok(page)
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        page["wait_timed_out"] = True
                        return _ok(page)
                    await asyncio.sleep(min(0.1, remaining))
            if action == "checkpoint":
                return _ok(durable.checkpoint(
                    rid, owner, data or {}, label=label
                ))
            if action == "reconcile":
                return _ok(durable.reconcile(
                    rid, owner, stale_after_s=stale_after_s
                ))
            if action == "capabilities_used":
                return _ok(durable.record_capabilities_used(
                    rid, owner, capabilities_used or []
                ))
            if action == "agent_assign":
                return _ok(durable.assign_agent(
                    rid,
                    owner,
                    role=str(_required("role", role)),
                    task_id=task_id,
                    agent_id=agent_id,
                    state=agent_state or "ACTIVE",
                    desired_state=agent_desired_state or agent_state or "ACTIVE",
                    metadata=metadata,
                ))
            if action == "agent_update":
                return _ok(durable.update_agent(
                    str(_required("agent_id", agent_id)),
                    owner,
                    state=agent_state,
                    desired_state=agent_desired_state,
                    task_id=task_id,
                    chat_id=chat_id,
                    metadata=metadata,
                ))
            if action == "chat_bind":
                return _ok(durable.bind_chat(
                    rid,
                    owner,
                    agent_id=agent_id,
                    provider=provider,
                    conversation_id=conversation_id,
                    conversation_url=conversation_url,
                    project_id=project_id,
                    project_url=project_url,
                    title=title,
                    chat_id=chat_id,
                    state=chat_state or "READY",
                    desired_state=chat_desired_state or chat_state or "READY",
                    metadata=metadata,
                ))
            if action == "chat_update":
                return _ok(durable.update_chat(
                    str(_required("chat_id", chat_id)),
                    owner,
                    state=chat_state,
                    desired_state=chat_desired_state,
                    metadata=metadata,
                ))
            if action == "chat_rebind":
                return _ok(durable.rebind_chat(
                    str(_required("chat_id", chat_id)),
                    owner,
                    conversation_id=conversation_id,
                    conversation_url=conversation_url,
                    provider=provider,
                    project_id=project_id,
                    project_url=project_url,
                    reason=reason or "recovery",
                ))
            if action == "transition":
                target_state = str(_required("state", state))
                transitioned = durable.transition_run(
                    rid, owner, target_state,
                    reason=reason, result=result, rollback=rollback,
                )
                cleanup = None
                if target_state in {"SUCCEEDED", "FAILED", "CANCELLED"} and processes is not None:
                    cleanup = processes.cleanup_run(rid, owner)
                return _ok({"run": transitioned, "cleanup": cleanup})
            raise ValueError("unsupported run action")
        except Exception as exc:
            return _fail(exc)

    @mcp.tool()
    def sentra_operation(
        action: Literal[
            "create", "status", "wait", "progress", "complete", "fail",
            "cancel", "lease_acquire", "lease_renew", "lease_release",
            "process_tree"
        ],
        ctx: Context,
        run_id: str | None = None,
        operation_id: str | None = None,
        kind: str | None = None,
        idempotency_key: str | None = None,
        cleanup_policy: Literal["terminate_on_run_end", "preserve", "manual"] = "terminate_on_run_end",
        state: Literal[
            "QUEUED", "STARTING", "RUNNING", "WAITING_EXTERNAL",
            "SUCCEEDED", "FAILED", "UNCERTAIN", "CANCEL_REQUESTED", "CANCELLED"
        ] | None = None,
        readiness: Literal[
            "UNKNOWN", "PROCESS_STARTED", "PORT_LISTENING",
            "TRANSPORT_CONNECTED", "PLUGIN_HANDSHAKE",
            "CAPABILITY_NEGOTIATED", "SESSION_READY", "PRODUCT_READY"
        ] | None = None,
        progress: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        rollback: dict[str, Any] | None = None,
        uncertain: bool = False,
        side_effect_may_have_started: bool = True,
        timeout_s: Annotated[float, Field(gt=0, le=25)] = 5.0,
        resource_key: str | None = None,
        fencing_token: int | None = None,
        ttl_s: Annotated[float, Field(ge=1, le=3600)] = 60.0,
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Control durable Operations, leases/fencing, and managed process inspection."""
        try:
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            if action == "create":
                return _ok(durable.create_operation(
                    str(_required("run_id", run_id)),
                    owner,
                    kind=str(_required("kind", kind)),
                    idempotency_key=str(_required("idempotency_key", idempotency_key)),
                    operation_id=operation_id,
                    cleanup_policy=cleanup_policy,
                ))
            if action == "lease_acquire":
                return _ok(durable.acquire_lease(
                    str(_required("run_id", run_id)),
                    owner,
                    str(_required("resource_key", resource_key)),
                    operation_id=operation_id,
                    ttl_s=ttl_s,
                ))
            if action == "lease_renew":
                return _ok(durable.renew_lease(
                    str(_required("resource_key", resource_key)),
                    owner,
                    int(_required("fencing_token", fencing_token)),
                    ttl_s=ttl_s,
                ))
            if action == "lease_release":
                return _ok(durable.release_lease(
                    str(_required("resource_key", resource_key)),
                    owner,
                    int(_required("fencing_token", fencing_token)),
                ))
            if action == "process_tree":
                if processes is None:
                    raise SentraSemanticError(
                        "CAPABILITY_MISSING",
                        "process inspection is unavailable",
                        category="capability",
                    )
                return _ok(processes.process_tree(
                    owner, run_id=run_id, offset=offset, limit=limit
                ))

            oid = str(_required("operation_id", operation_id))
            if action == "status":
                return _ok(durable.operation_status(oid, owner))
            if action == "wait":
                waited = durable.wait_operation(
                    oid, owner, timeout_s=timeout_s
                )
                if waited.get("wait_timed_out") and waited.get("state") not in {
                    "SUCCEEDED", "FAILED", "CANCELLED", "UNCERTAIN"
                }:
                    waited["semantic_status"] = "OPERATION_STILL_RUNNING"
                return _ok(waited)
            if action == "progress":
                return _ok(durable.update_operation(
                    oid, owner,
                    state=state,
                    readiness=readiness,
                    progress=progress,
                    event_type="OPERATION_PROGRESS",
                    resource_key=resource_key,
                    fencing_token=fencing_token,
                ))
            if action == "complete":
                return _ok(durable.update_operation(
                    oid, owner,
                    state="SUCCEEDED",
                    readiness="PRODUCT_READY",
                    event_type="OPERATION_SUCCEEDED",
                    result=result or {},
                    rollback=rollback,
                ))
            if action == "fail":
                final_state = "UNCERTAIN" if uncertain else "FAILED"
                return _ok(durable.update_operation(
                    oid, owner,
                    state=final_state,
                    event_type=(
                        "OPERATION_UNCERTAIN" if uncertain else "OPERATION_FAILED"
                    ),
                    error=error or {},
                ))
            if action == "cancel":
                return _ok(durable.request_cancel(
                    oid, owner,
                    side_effect_may_have_started=side_effect_may_have_started,
                ))
            raise ValueError("unsupported operation action")
        except Exception as exc:
            return _fail(exc)

    @mcp.tool()
    def sentra_artifact(
        action: Literal["register", "info", "read_binary"],
        ctx: Context,
        run_id: str | None = None,
        artifact_id: str | None = None,
        path: str | None = None,
        workspace: str | None = None,
        operation_id: str | None = None,
        mime_type: str | None = None,
        offset: Annotated[int, Field(ge=0)] = 0,
        length: Annotated[int | None, Field(gt=0)] = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Register/inspect artifacts or read bounded binary/image bytes as base64."""
        try:
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            if action == "info":
                return _ok(durable.artifact_info(
                    str(_required("artifact_id", artifact_id)), owner
                ))
            if action == "read_binary":
                aid = str(_required("artifact_id", artifact_id))
                info = durable.artifact_info(aid, owner)
                target = Path(str(info["path"])).resolve()
                if not target.is_file():
                    raise FileNotFoundError("artifact file is no longer available")

                digest = hashlib.sha256()
                with target.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != info["sha256"]:
                    raise RuntimeError("artifact content hash changed after registration")

                size = int(info["size_bytes"])
                selected = min(
                    length or filesystem.max_read_bytes,
                    filesystem.max_read_bytes,
                )
                with target.open("rb") as handle:
                    handle.seek(offset)
                    payload = handle.read(selected)
                truncated = offset + len(payload) < size
                return _ok({
                    "artifact_id": aid,
                    "resource_uri": info["resource_uri"],
                    "offset": offset,
                    "bytes_returned": len(payload),
                    "total_bytes": size,
                    "truncated": truncated,
                    "next_offset": offset + len(payload) if truncated else None,
                    "mime_type": info["mime_type"],
                    "sha256": info["sha256"],
                    "base64": base64.b64encode(payload).decode("ascii"),
                })

            file_path = str(_required("path", path))
            _, target, relative, view = filesystem._resolve_access(
                file_path, workspace=workspace, owner=owner, permission="read"
            )
            if action == "register":
                return _ok(durable.register_artifact(
                    str(_required("run_id", run_id)),
                    owner,
                    target,
                    operation_id=operation_id,
                    mime_type=mime_type,
                ))
            raise ValueError("unsupported artifact action")
        except Exception as exc:
            return _fail(exc)
