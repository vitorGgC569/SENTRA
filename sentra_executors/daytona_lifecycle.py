"""Explicitly approved Daytona lifecycle; synchronous optional SDK boundary.

Creation/deletion are not part of the generic ExecutorRegistry protocol.
A trusted independent approval callback and real PolicyDecision are required;
execution of allowlisted commands remains DaytonaExecutor via the registry.
Records are process-local, not durable leases or remote attestation.
"""
from __future__ import annotations

import inspect
import threading
from dataclasses import dataclass
from typing import Any, Callable

from sentra_runtime.contracts import OperationRequest, PolicyDecision
from .rpa import effect_checkpoint


@dataclass(frozen=True)
class SandboxView:
    sandbox_id: str
    state: str
    private: bool
    network_blocked: bool


@dataclass(frozen=True)
class SandboxCreateSpec:
    name: str
    trusted_snapshot: str

    def __post_init__(self):
        if (not self.name or not self.name.startswith("sentra-lab-") or
                not self.trusted_snapshot or any(
                    c in self.trusted_snapshot for c in (" ", "/", "\\", "\n")
                )):
            raise ValueError("invalid_lab_create_spec")


class DaytonaSandboxLifecycle:
    """Only named resources, explicit approval, no default provisioning."""

    def __init__(self, *, machine_id: str, principal_id: str,
                 existing_ids: tuple[str, ...], policy: Callable,
                 client: Any = None, allow_provision: bool = False,
                 approve_provision: Callable[[SandboxCreateSpec, str], bool] | None = None):
        if not machine_id or not principal_id or not callable(policy):
            raise ValueError("policy_and_machine_required")
        if len(set(existing_ids)) != len(existing_ids) or any(not x for x in existing_ids):
            raise ValueError("invalid_sandbox_inventory")
        self.machine_id = machine_id
        self.principal_id = principal_id
        self.existing_ids = frozenset(existing_ids)
        self.policy = policy
        self.client = client
        self.allow_provision = bool(allow_provision)
        self.approve_provision = approve_provision
        self._managed: set[str] = set()
        self._created_operations: dict[str, str] = {}
        self._created_specs: dict[str, SandboxCreateSpec] = {}
        self._cleanup_operations: set[str] = set()
        self._uncertain: set[str] = set()
        self._lock = threading.RLock()

    def _sdk(self):
        if self.client is not None:
            return self.client
        try:
            from daytona import Daytona
        except ImportError as exc:
            raise RuntimeError("daytona_sdk_not_installed") from exc
        self.client = Daytona()
        return self.client

    def _allow(self, *, action: str, sandbox_id: str, operation_id: str):
        req = OperationRequest(
            operation_id=operation_id, principal_id=self.principal_id,
            machine_id=self.machine_id, capability_id="sandbox.lifecycle",
            work_item_id="sandbox-lifecycle", idempotency_key=operation_id,
            arguments={"action": action, "sandbox_id": sandbox_id},
        )
        result = self.policy(req)
        if inspect.isawaitable(result):
            raise PermissionError("async_policy_not_supported_for_sync_lifecycle")
        if (not isinstance(result, PolicyDecision) or result.allowed is not True or
                bool(result.constraints)):
            raise PermissionError("sandbox_lifecycle_policy_denied")

    @staticmethod
    def _view(sandbox, *, expected: str | None = None) -> SandboxView:
        sid = getattr(sandbox, "id", None)
        state = getattr(sandbox, "state", None)
        state = getattr(state, "value", state)
        if (not isinstance(sid, str) or not sid or
                expected is not None and sid != expected):
            raise RuntimeError("sandbox_id_mismatch")
        return SandboxView(
            sandbox_id=sid, state=str(state),
            private=getattr(sandbox, "public", None) is False,
            network_blocked=getattr(sandbox, "network_block_all", None) is True,
        )

    @staticmethod
    def _safe(view: SandboxView):
        if not view.private or not view.network_blocked:
            raise PermissionError("sandbox_not_private_and_network_blocked")

    def discover_existing(self, sandbox_id: str, *, operation_id: str) -> SandboxView:
        if sandbox_id not in self.existing_ids and sandbox_id not in self._managed:
            raise PermissionError("sandbox_not_in_inventory")
        self._allow(action="discover", sandbox_id=sandbox_id, operation_id=operation_id)
        effect_checkpoint()
        view = self._view(self._sdk().get(sandbox_id), expected=sandbox_id)
        self._allow(action="discover", sandbox_id=sandbox_id, operation_id=operation_id)
        self._safe(view)
        return view

    def status(self, sandbox_id: str, *, operation_id: str) -> SandboxView:
        if sandbox_id not in self.existing_ids and sandbox_id not in self._managed:
            raise PermissionError("sandbox_not_in_inventory")
        self._allow(action="status", sandbox_id=sandbox_id, operation_id=operation_id)
        if sandbox_id in self._cleanup_operations:
            return SandboxView(sandbox_id, "deleted", True, True)
        effect_checkpoint()
        view = self._view(self._sdk().get(sandbox_id), expected=sandbox_id)
        self._allow(action="status", sandbox_id=sandbox_id, operation_id=operation_id)
        return view

    def provision(self, spec: SandboxCreateSpec, *, operation_id: str,
                  approval_ref: str) -> SandboxView:
        if not isinstance(spec, SandboxCreateSpec) or not operation_id or not approval_ref:
            raise ValueError("invalid_provision_request")
        with self._lock:
            self._allow(action="provision", sandbox_id=spec.name, operation_id=operation_id)
            if not self.allow_provision or not callable(self.approve_provision):
                raise PermissionError("provision_disabled")
            if self.approve_provision(spec, approval_ref) is not True:
                raise PermissionError("provision_approval_denied")
            self._allow(action="provision", sandbox_id=spec.name, operation_id=operation_id)
            if operation_id in self._uncertain:
                raise RuntimeError("provision_uncertain_manual_reconcile")
            if (operation_id in self._created_specs and
                    self._created_specs[operation_id] != spec):
                raise ValueError("provision_idempotency_conflict")
            if operation_id in self._created_operations:
                sid = self._created_operations[operation_id]
                return self.discover_existing(sid, operation_id=operation_id + ":reobserve")
            # Explicitly private, network-blocked snapshot-only spec. No env,
            # volumes, arbitrary image builds or public services.
            # Official SDK exports the params type at package level, NOT
            # as an attribute on Daytona() client. Test doubles may supply
            # their constructor without importing or installing the SDK.
            params_type = getattr(self.client, "CreateSandboxFromSnapshotParams", None)
            if params_type is None:
                try:
                    from daytona import CreateSandboxFromSnapshotParams as params_type
                except ImportError as exc:
                    raise RuntimeError("daytona_sdk_not_installed") from exc
            params = params_type(
                name=spec.name, snapshot=spec.trusted_snapshot,
                public=False, network_block_all=True, env_vars={},
                network_allow_list=None, ephemeral=True,
            )
            self._uncertain.add(operation_id)  # reserve BEFORE remote create
            effect_checkpoint()
            sandbox = self._sdk().create(params)
            view = self._view(sandbox)
            self._managed.add(view.sandbox_id)
            self._created_operations[operation_id] = view.sandbox_id
            self._created_specs[operation_id] = spec
            self._safe(view)  # unsafe postcondition remains UNCERTAIN, never replay
            self._allow(action="provision", sandbox_id=spec.name, operation_id=operation_id)
            self._uncertain.discard(operation_id)
            return view

    def cleanup(self, sandbox_id: str, *, operation_id: str) -> str:
        with self._lock:
            self._allow(action="cleanup", sandbox_id=sandbox_id, operation_id=operation_id)
            if sandbox_id not in self._managed:
                raise PermissionError("cannot_delete_unmanaged_sandbox")
            if sandbox_id in self._cleanup_operations:
                return "DELETED"
            if sandbox_id in self._uncertain:
                raise RuntimeError("cleanup_uncertain_manual_reconcile")
            effect_checkpoint()
            sandbox = self._sdk().get(sandbox_id)
            self._view(sandbox, expected=sandbox_id)
            self._allow(action="cleanup", sandbox_id=sandbox_id, operation_id=operation_id)
            self._uncertain.add(sandbox_id)
            effect_checkpoint()
            self._sdk().delete(sandbox)
            self._allow(action="cleanup", sandbox_id=sandbox_id, operation_id=operation_id)
            self._cleanup_operations.add(sandbox_id)
            self._uncertain.discard(sandbox_id)
            return "DELETED"
