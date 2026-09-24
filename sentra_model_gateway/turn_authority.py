"""Durable authority for tool-capable Web turns and their physical browser tabs."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import ctypes
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sentra_mcp.services.durable import DurableRunService, DurableStateConflict, StaleFenceError


@dataclass
class TurnCapability:
    token_hash: str
    run_id: str
    operation_id: str
    owner: str
    broker_registered: bool = False
    conversation_uri: str | None = None
    trace_id: str | None = None
    physical_key: str | None = None
    physical_fence: int | None = None
    logical_key: str | None = None
    logical_fence: int | None = None
    conversation_key: str | None = None
    conversation_fence: int | None = None
    completed_revision: int | None = None
    allowed_tools: frozenset[str] | None = None


class TurnAuthority:
    def __init__(self, state_root: Path, descriptor: Path, *, clock=time.time) -> None:
        self.durable = DurableRunService(state_root)
        self.descriptor = descriptor
        self.clock = clock
        self.lock = threading.RLock()
        self.capabilities: dict[str, TurnCapability] = {}

    def issue(self, *, conversation_uri: str | None = None, request_identity: str | None = None) -> str:
        token = "stc_" + secrets.token_urlsafe(36)
        key = hashlib.sha256(token.encode()).hexdigest()
        identity_hash = hashlib.sha256(request_identity.encode()).hexdigest() if request_identity else None
        owner = "sentra:web-model-gateway"
        run = self.durable.create_run(
            owner,
            idempotency_key="web-turn:" + (identity_hash or key),
            required_capabilities=["model:chatgpt-web"],
            capability_snapshot={
                "kind": "chatgpt-web-turn",
                "token_hash": key,
                "conversation_uri": conversation_uri,
                "request_identity_hash": identity_hash,
            },
        )
        if run.get("idempotent_replay"):
            raise DurableStateConflict("duplicate Web turn identity; automatic replay is disabled")
        operation = self.durable.create_operation(
            run["run_id"], owner, kind="chatgpt-web-turn",
            idempotency_key="turn:" + run["run_id"], initial_state="RUNNING",
        )
        with self.lock:
            self.capabilities[key] = TurnCapability(key, run["run_id"], operation["operation_id"], owner,
                                                     conversation_uri=conversation_uri)
        return token

    def active_leases(self) -> list[dict[str, Any]]:
        with self.lock:
            return [
                {"run_id": cap.run_id, "operation_id": cap.operation_id,
                 "trace_id": cap.trace_id, "conversation_uri": cap.conversation_uri,
                 "logical_resource": cap.logical_key, "logical_fencing_token": cap.logical_fence,
                 "physical_resource": cap.physical_key, "fencing_token": cap.physical_fence}
                for cap in self.capabilities.values() if cap.physical_key is not None
            ]

    def _rehydrate(self, key: str) -> TurnCapability | None:
        owner = "sentra:web-model-gateway"
        runs = self.durable.list_runs(owner, offset=0, limit=1000)
        for run in runs.get("items", []):
            snapshot = run.get("capability_snapshot") or {}
            stored = str(snapshot.get("token_hash") or "")
            if snapshot.get("kind") != "chatgpt-web-turn" or not stored or not hmac.compare_digest(stored, key):
                continue
            if run.get("terminal") or run.get("state") != "RUNNING":
                return None
            detail = self.durable.run_status(str(run["run_id"]), owner)
            operations = [
                item for item in detail.get("operations", [])
                if item.get("kind") in {"chatgpt-web-turn", "chatgpt-web-browser-phase"}
            ]
            if not operations:
                return None
            operation = operations[-1]
            progress = operation.get("progress") or {}
            trace_id = progress.get("trace_id")
            if not isinstance(trace_id, str):
                trace_id = None
            result = operation.get("result") or {}
            completed_revision = result.get("broker_revision")
            if not isinstance(completed_revision, int):
                completed_revision = None
            capability = TurnCapability(
                key,
                str(run["run_id"]),
                str(operation["operation_id"]),
                owner,
                broker_registered=bool(progress.get("broker_registered")),
                conversation_uri=(
                    snapshot.get("conversation_uri")
                    if isinstance(snapshot.get("conversation_uri"), str)
                    else None
                ),
                trace_id=trace_id,
                completed_revision=completed_revision,
                allowed_tools=(
                    frozenset(str(item) for item in progress.get("allowed_tools", []) if isinstance(item, str))
                    if isinstance(progress.get("allowed_tools"), list)
                    else None
                ),
            )
            for lease in detail.get("leases", []):
                if lease.get("operation_id") != capability.operation_id:
                    continue
                resource_key = str(lease.get("resource_key") or "")
                fence = lease.get("fencing_token")
                if not isinstance(fence, int):
                    continue
                if resource_key.startswith("browser-tab:"):
                    capability.physical_key = resource_key
                    capability.physical_fence = fence
                elif resource_key.startswith("conversation-uri:"):
                    capability.logical_key = resource_key
                    capability.logical_fence = fence
                elif resource_key.startswith("conversation:"):
                    capability.conversation_key = resource_key
                    capability.conversation_fence = fence
            self.capabilities[key] = capability
            return capability
        return None

    def _capability(self, token: str) -> TurnCapability:
        if not isinstance(token, str) or not token.startswith("stc_"):
            raise PermissionError("invalid TurnCapability")
        key = hashlib.sha256(token.encode()).hexdigest()
        capability = self.capabilities.get(key)
        if capability is None:
            capability = self._rehydrate(key)
        if capability is None or not hmac.compare_digest(key, capability.token_hash):
            raise PermissionError("TurnCapability is unknown or retired")
        return capability

    def _physical_tab(self, trace_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            descriptor = json.loads(self.descriptor.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StaleFenceError("Browser Host descriptor is unavailable") from exc
        if descriptor.get("version") != 3 or descriptor.get("kind") != "codex-web-gpt-launcher":
            raise StaleFenceError("Browser Host descriptor is invalid")
        if descriptor.get("sentraManaged") is not True:
            raise StaleFenceError("Browser Host was not launched under SENTRA authority")
        pid = descriptor.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            raise StaleFenceError("Browser Host pid is invalid")
        if os.name == "nt":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
            kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                raise StaleFenceError("Browser Host process has exited")
            try:
                exit_code = ctypes.c_ulong()
                if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259:
                    raise StaleFenceError("Browser Host process has exited")
            finally:
                kernel.CloseHandle(handle)
        else:
            try:
                os.kill(pid, 0)
            except OSError as exc:
                raise StaleFenceError("Browser Host process has exited") from exc
        matches = [tab for tab in descriptor.get("sentraTabs", [])
                   if isinstance(tab, dict) and tab.get("traceId") == trace_id
                   and tab.get("status") == "running"]
        if len(matches) != 1:
            raise StaleFenceError("no unique running physical tab owns this turn")
        tab = matches[0]
        surface = tab.get("surfaceId")
        if not isinstance(surface, str) or (tab.get("interactionMode") != "manual"
                                               and surface not in descriptor.get("surfaceTargets", {})):
            raise StaleFenceError("physical browser surface is unavailable")
        heartbeat = tab.get("lastHeartbeatAt")
        if not isinstance(heartbeat, (int, float)) or self.clock() * 1000 - heartbeat > 90_000:
            raise StaleFenceError("physical browser tab heartbeat expired")
        return descriptor, tab

    def _bind_physical(self, cap: TurnCapability, trace_id: str) -> None:
        descriptor, tab = self._physical_tab(trace_id)
        key = f"browser-tab:{descriptor['pid']}:{tab['tabId']}"
        if cap.physical_key is not None and cap.physical_key != key:
            raise StaleFenceError("physical browser tab changed during the turn")
        if cap.physical_key is None:
            lease = self.durable.acquire_lease(cap.run_id, cap.owner, key,
                                                operation_id=cap.operation_id, ttl_s=120)
            cap.physical_key = key
            cap.physical_fence = lease["fencing_token"]
        else:
            self.durable.renew_lease(key, cap.owner, cap.physical_fence, ttl_s=120)
        if cap.conversation_uri:
            logical_key = "conversation-uri:" + hashlib.sha256(cap.conversation_uri.encode()).hexdigest()
            if cap.logical_key is not None and cap.logical_key != logical_key:
                raise StaleFenceError("logical conversation identity changed during the turn")
            if cap.logical_key is None:
                lease = self.durable.acquire_lease(
                    cap.run_id, cap.owner, logical_key,
                    operation_id=cap.operation_id, ttl_s=120,
                )
                cap.logical_key = logical_key
                cap.logical_fence = lease["fencing_token"]
            else:
                self.durable.renew_lease(logical_key, cap.owner, cap.logical_fence, ttl_s=120)
        conversation = tab.get("conversationKey")
        if isinstance(conversation, str) and conversation:
            conversation_key = "conversation:" + hashlib.sha256(conversation.encode()).hexdigest()
            if cap.conversation_key is not None and cap.conversation_key != conversation_key:
                raise StaleFenceError("conversation changed during the turn")
            if cap.conversation_key is None:
                lease = self.durable.acquire_lease(cap.run_id, cap.owner, conversation_key,
                                                    operation_id=cap.operation_id, ttl_s=120)
                cap.conversation_key = conversation_key
                cap.conversation_fence = lease["fencing_token"]
            else:
                self.durable.renew_lease(conversation_key, cap.owner, cap.conversation_fence, ttl_s=120)

    def _advance_phase(self, cap: TurnCapability, trace_id: str) -> None:
        if cap.trace_id is None or cap.trace_id == trace_id:
            cap.trace_id = trace_id
            return
        state = self.durable.operation_status(cap.operation_id, cap.owner)["state"]
        if state != "SUCCEEDED":
            raise StaleFenceError("previous browser phase has not completed")
        for key, fence in ((cap.logical_key, cap.logical_fence),
                           (cap.conversation_key, cap.conversation_fence),
                           (cap.physical_key, cap.physical_fence)):
            if key is not None and fence is not None:
                self.durable.release_lease(key, cap.owner, fence)
        operation = self.durable.create_operation(
            cap.run_id, cap.owner, kind="chatgpt-web-browser-phase",
            idempotency_key="browser-phase:" + trace_id, initial_state="RUNNING",
        )
        cap.operation_id = operation["operation_id"]
        cap.trace_id = trace_id
        cap.broker_registered = False
        cap.physical_key = None
        cap.physical_fence = None
        cap.logical_key = None
        cap.logical_fence = None
        cap.conversation_key = None
        cap.conversation_fence = None
        cap.completed_revision = None
        cap.allowed_tools = None

    def authorize(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        token = payload.get("capability")
        trace_id = payload.get("traceId")
        if not isinstance(trace_id, str) or not trace_id or len(trace_id) > 128:
            raise ValueError("invalid turn trace")
        with self.lock:
            cap = self._capability(token)
            state = self.durable.operation_status(cap.operation_id, cap.owner)["state"]
            if cap.trace_id is not None and cap.trace_id != trace_id:
                if action not in {"register", "browser-start"}:
                    raise StaleFenceError("TurnCapability belongs to another browser phase")
                self._advance_phase(cap, trace_id)
                state = self.durable.operation_status(cap.operation_id, cap.owner)["state"]
            if action == "register":
                if state != "RUNNING":
                    raise StaleFenceError("turn operation is no longer running")
                raw_tools = payload.get("allowedTools")
                if not isinstance(raw_tools, list) or len(raw_tools) > 512:
                    raise ValueError("allowedTools must be a list with at most 512 entries")
                allowed_tools: set[str] = set()
                for item in raw_tools:
                    if (not isinstance(item, str) or not item or len(item) > 256
                            or any(char in item for char in ("\n", "\r", "\x00"))):
                        raise ValueError("invalid allowed tool name")
                    allowed_tools.add(item)
                cap.trace_id = trace_id
                cap.broker_registered = True
                cap.allowed_tools = frozenset(allowed_tools)
                self.durable.heartbeat(
                    cap.operation_id,
                    cap.owner,
                    progress={
                        "trace_id": trace_id,
                        "broker_registered": True,
                        "conversation_uri": cap.conversation_uri,
                        "allowed_tools": sorted(cap.allowed_tools),
                    },
                )
                return {"authorized": True, "run_id": cap.run_id, "operation_id": cap.operation_id}
            if action == "browser-start":
                if state != "RUNNING":
                    raise StaleFenceError("turn operation is no longer running")
                cap.trace_id = trace_id
                self._bind_physical(cap, trace_id)
                self.durable.heartbeat(cap.operation_id, cap.owner,
                                       progress={"trace_id": trace_id,
                                                 "broker_registered": cap.broker_registered,
                                                 "physical_resource": cap.physical_key,
                                                 "conversation_uri": cap.conversation_uri},
                                       resource_key=cap.physical_key, fencing_token=cap.physical_fence)
                return {"authorized": True, "operation_id": cap.operation_id,
                        "physical_resource": cap.physical_key}
            if cap.trace_id is None:
                raise PermissionError("TurnCapability has not been registered by the broker")
            if action == "browser-heartbeat":
                if state != "RUNNING":
                    raise StaleFenceError("turn operation is no longer running")
                self._bind_physical(cap, trace_id)
                self.durable.heartbeat(
                    cap.operation_id, cap.owner,
                    progress={"trace_id": trace_id,
                              "broker_registered": cap.broker_registered,
                              "physical_resource": cap.physical_key,
                              "conversation_uri": cap.conversation_uri},
                    resource_key=cap.physical_key, fencing_token=cap.physical_fence,
                )
                return {"authorized": True, "operation_id": cap.operation_id,
                        "physical_resource": cap.physical_key}
            if action == "browser-complete":
                if cap.broker_registered or state != "RUNNING":
                    raise StaleFenceError("read-only browser completion is unavailable")
                self._bind_physical(cap, trace_id)
                self.durable.update_operation(
                    cap.operation_id, cap.owner, state="SUCCEEDED", event_type="WEB_BROWSER_FENCED",
                    result={"trace_id": trace_id, "physical_resource": cap.physical_key,
                            "conversation_uri": cap.conversation_uri},
                    resource_key=cap.physical_key, fencing_token=cap.physical_fence,
                )
                return {"authorized": True}
            if action in {"prepare", "complete"} and state == "SUCCEEDED" and cap.completed_revision == payload.get("revision"):
                return {"authorized": True, "idempotent_replay": True}
            if state != "RUNNING":
                raise StaleFenceError("turn operation is no longer running")
            if action not in {"tool", "prepare", "complete"}:
                raise ValueError("invalid turn authority action")
            self._bind_physical(cap, trace_id)
            if action == "tool":
                wire_name = payload.get("wireName")
                if not isinstance(wire_name, str) or not wire_name or len(wire_name) > 256:
                    raise ValueError("invalid tool name")
                if cap.allowed_tools is None:
                    raise PermissionError("turn tool contract was not registered")
                if wire_name not in cap.allowed_tools:
                    raise PermissionError("tool is outside the TurnCapability allowlist")
                self.durable.heartbeat(cap.operation_id, cap.owner,
                                       progress={"tool": wire_name, "physical_resource": cap.physical_key},
                                       resource_key=cap.physical_key, fencing_token=cap.physical_fence)
                self.durable.record_capabilities_used(cap.run_id, cap.owner, ["model:chatgpt-web", "browser:physical-tab", "tool:" + wire_name])
            else:
                revision = payload.get("revision")
                if not isinstance(revision, int) or revision < 0:
                    raise ValueError("invalid broker completion revision")
                if action == "prepare":
                    self.durable.heartbeat(cap.operation_id, cap.owner,
                                           progress={"completion_revision": revision,
                                                     "physical_resource": cap.physical_key},
                                           resource_key=cap.physical_key, fencing_token=cap.physical_fence)
                    return {"authorized": True, "prepared": True}
                self.durable.update_operation(
                    cap.operation_id, cap.owner, state="SUCCEEDED", event_type="WEB_TURN_FENCED",
                    result={"trace_id": trace_id, "broker_revision": revision,
                            "physical_resource": cap.physical_key,
                            "conversation_uri": cap.conversation_uri},
                    resource_key=cap.physical_key, fencing_token=cap.physical_fence,
                )
                cap.completed_revision = revision
            return {"authorized": True, "run_id": cap.run_id, "operation_id": cap.operation_id}

    def retire(self, token: str, *, failed: bool = False) -> None:
        with self.lock:
            cap = self._capability(token)
            state = self.durable.operation_status(cap.operation_id, cap.owner)["state"]
            if os.getenv("SENTRA_GATEWAY_DEBUG_TURN", "").strip() == "1":
                print(
                    "SENTRA_TURN_RETIRE "
                    + json.dumps({
                        "trace_id": cap.trace_id,
                        "run_id": cap.run_id,
                        "operation_id": cap.operation_id,
                        "state_before": state,
                        "failed": failed,
                        "completed_revision": cap.completed_revision,
                    }, separators=(",", ":")),
                    flush=True,
                )
            if state == "RUNNING":
                self.durable.update_operation(cap.operation_id, cap.owner, state="UNCERTAIN",
                                              error={"reason": "broker completion fence was not committed"})
                state = "UNCERTAIN"
            for key, fence in ((cap.logical_key, cap.logical_fence),
                               (cap.conversation_key, cap.conversation_fence),
                               (cap.physical_key, cap.physical_fence)):
                if key is not None and fence is not None:
                    try:
                        self.durable.release_lease(key, cap.owner, fence)
                    except StaleFenceError:
                        pass
            self.capabilities.pop(cap.token_hash, None)
            delivered = state == "SUCCEEDED" and not failed
            if state == "SUCCEEDED" and failed:
                self.durable.checkpoint(cap.run_id, cap.owner, {"operation_id": cap.operation_id, "delivery_state": "UNCERTAIN"}, label="web-response-delivery")
            self.durable.transition_run(cap.run_id, cap.owner,
                                        "SUCCEEDED" if delivered else "BLOCKED",
                                        reason="Web turn completed and response delivery was confirmed" if delivered else "Web model execution or response delivery is uncertain")
