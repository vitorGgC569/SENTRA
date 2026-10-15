"""Owner-authenticated, centrally fenced metadata enrollment of exact VBox storage.

No VM lifecycle/input/disk-write effects. The one metadata write requires both
an unforgeable in-process owner scope from the authenticated shell route and a
real CentralEffectContext. Agents with vm:manage cannot approve storage alone.
Native-host wiring supplies callbacks; no JSON endpoint is exposed here.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
from pathlib import Path
import re
import time

from sentra_core.conversations import _decode, _encode
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.central_authority import CentralDurableIntentAuthority
from sentra_runtime.contracts import OperationRequest, PolicyDecision
from sentra_runtime.effect_boundary import CentralEffectContext, current_effect_context
from sentra_runtime.executor import _request_snapshot
from .rpa import ExecutorFailure
from .virtualbox_storage_binding import storage_binding_candidate


_HASH = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True)
class _OwnerEnrollment:
    control: object
    owner: str
    workspace_id: str
    root_dot_id: str
    conversation_id: str
    operation_id: str
    expected_sha256: str
    expires: float


_owner_enrollment = ContextVar("sentra_authenticated_storage_enrollment", default=None)


def storage_enrollment_policy(base_policy, *, control, owner, workspace_id, root_dot_id):
    """Additional native policy BEFORE reservation and on every checkpoint.

    Never widens the existing policy. Missing owner review is denied before an
    effect starts, rather than intentionally generating an uncertain VM effect.
    """
    if not isinstance(control, ControlPlaneService) or not callable(base_policy):
        raise TypeError("existing_control_plane_policy_required")
    def check(request):
        decision = base_policy(request)
        if decision.allowed is not True or request.arguments.get("action") != "storage.enroll":
            return decision
        try:
            scope = _owner_enrollment.get()
            item = control.work_item_info(request.work_item_id, owner)
            meta = item.get("metadata") or {}
            expected = request.arguments.get("expected_candidate_sha256")
            if (not isinstance(scope, _OwnerEnrollment) or scope.control is not control or scope.owner != owner
                    or scope.workspace_id != workspace_id or scope.root_dot_id != root_dot_id
                    or scope.operation_id != request.operation_id or scope.expected_sha256 != expected
                    or scope.conversation_id != meta.get("conversation_id") or scope.expires <= time.monotonic()
                    or meta.get("workspace_id") != workspace_id or meta.get("root_dot_id") != root_dot_id
                    or request.capability_id != "vm:manage"
                    or dict(request.arguments) != {"action":"storage.enroll", "expected_candidate_sha256":expected}):
                return PolicyDecision(False,"authenticated owner storage review required")
        except Exception:
            return PolicyDecision(False,"authenticated owner storage review unavailable")
        return decision
    return check


@contextmanager
def owner_storage_enrollment_scope(control, *, owner, workspace_id, root_dot_id,
                                   conversation_id, operation_id, expected_sha256):
    """TRUSTED authenticated owner handler only, never a model-supplied flag.

    Scope binds precisely one reviewed digest and one central Operation. This
    grants no capability, does not enroll storage, and cannot replace CP policy.
    """
    if (not isinstance(control, ControlPlaneService) or not isinstance(expected_sha256, str)
            or not _HASH.fullmatch(expected_sha256)
            or any(not isinstance(v, str) or not 1 <= len(v) <= 128 for v in
                   (owner, workspace_id, root_dot_id, conversation_id, operation_id))):
        raise ValueError("exact_authenticated_storage_approval_scope_required")
    scope = _OwnerEnrollment(control, owner, workspace_id, root_dot_id, conversation_id,
                             operation_id, expected_sha256, time.monotonic() + 30)
    token = _owner_enrollment.set(scope)
    try:
        yield
    finally:
        _owner_enrollment.reset(token)


def configured_storage_candidate(client, binding, cfg, *, host_storage_roots=None):
    """Only trusted host roots: configured VM folder and SENTRA's AppData folder.

    Optional roots are a native host dependency for fixtures/deployment; they
    must never be obtained from operation arguments or renderer JSON.
    """
    folder = Path(cfg["base_folder"]) / cfg["name"]
    roots = [folder]
    local = os.environ.get("LOCALAPPDATA")
    if local and Path(local).is_absolute():
        roots.append(Path(local) / "SENTRA-dot-vms" / cfg["name"])
    if host_storage_roots is not None:
        if not isinstance(host_storage_roots, tuple) or len(host_storage_roots) > 8:
            raise ValueError("bounded_host_storage_roots_required")
        roots.extend(Path(p) for p in host_storage_roots)
    attachments = client.disk_attachments(binding)
    if len(attachments) != 1:
        raise ExecutorFailure("virtualbox_install_requires_one_owned_virtual_disk")
    selected = Path(attachments[0].get("location", ""))
    allowed = {p.resolve() for p in roots if p.is_absolute()}
    if not selected.is_absolute() or selected.parent.resolve() not in allowed:
        raise ExecutorFailure("virtualbox_storage_outside_host_roots")
    return storage_binding_candidate(client, binding, cfg, storage_root=selected.parent)


def public_storage_candidate(candidate):
    record = candidate["record"]
    return {"kind": "virtualbox.storage.candidate", "vm_id": record["vm_id"],
            "disk_uuid": record["disk_uuid"], "capacity_bytes": record["capacity_bytes"],
            "candidate_sha256": candidate["sha256"], "slot": "SATA/0/0",
            "head_kind": record["head_kind"], "requires_authenticated_owner_approval": True,
            "parent_chain_supported": False, "applied": False, "authorization_granted": False}


def _bound_context(control, owner, workspace_id, root_dot_id, binding, cfg):
    context = current_effect_context.get()
    if (not isinstance(control, ControlPlaneService) or not isinstance(context, CentralEffectContext)
            or context.authority.durable is not control.durable or context.receipt.owner != owner):
        raise PermissionError("owning_central_storage_context_required")
    context.checkpoint()
    request = context.request
    if control.durable.run_status(context.receipt.run_id, owner, include_details=False)["state"] != "RUNNING":
        raise PermissionError("active_storage_run_required")
    item = control.work_item_info(request.work_item_id, owner)
    meta = item.get("metadata") or {}
    with closing(control.store.connect("shell")) as db:
        row = db.execute("SELECT body FROM shell_dot_vms WHERE owner=? AND project=? AND root=?",
                         (owner, workspace_id, root_dot_id)).fetchone()
    if row is None:
        raise PermissionError("owned_dot_storage_record_required")
    current = _decode(row["body"])
    cid = meta.get("conversation_id")
    if (item.get("state") != "RUNNING" or item.get("run_id") != context.receipt.run_id
            or item.get("assignee_agent_id") != request.principal_id
            or meta.get("workspace_id") != workspace_id or meta.get("root_dot_id") != root_dot_id
            or meta.get("machine_id") != request.machine_id
            or current.get("work_items", {}).get(cid) != request.work_item_id
            or current.get("machine_id") != request.machine_id or current.get("agent_id") != request.principal_id
            or current.get("vm_id") != binding.vm_id or current.get("marker") != binding.marker
            or current.get("root_dot_id") != root_dot_id
            or any(current.get(k) != cfg.get(k) for k in
                   ("vm_id", "marker", "machine_id", "agent_id", "base_folder", "name", "disk_gb", "work_items"))):
        raise PermissionError("central_storage_scope_or_configuration_changed")
    policy = BoundWorkItemPolicy(owner=owner, principal_type="agent", authorization=control.authorization,
                                governance=control.governance)
    if policy(request).allowed is not True:
        raise PermissionError("live_central_storage_grant_required")
    return context, item, current, row["body"]


def enroll_owned_storage(control, *, owner, workspace_id, root_dot_id,
                         client, binding, cfg, expected_sha256, host_storage_roots=None):
    context, item, current, original_body = _bound_context(control, owner, workspace_id, root_dot_id, binding, cfg)
    request = context.request
    active_operation = control.durable.operation_status(request.operation_id, owner)
    if (active_operation['kind'] != 'sentra.machine' or active_operation['state'] != 'RUNNING'
            or (active_operation.get('progress') or {}).get('effect_started') is not True):
        raise PermissionError('central_storage_effect_boundary_not_started')
    scope = _owner_enrollment.get()
    if (not isinstance(scope, _OwnerEnrollment) or scope.control is not control or scope.owner != owner
            or scope.workspace_id != workspace_id or scope.root_dot_id != root_dot_id
            or scope.conversation_id != item["metadata"]["conversation_id"]
            or scope.operation_id != request.operation_id or scope.expected_sha256 != expected_sha256
            or scope.expires <= time.monotonic() or request.capability_id != "vm:manage"
            or dict(request.arguments) != {"action": "storage.enroll", "expected_candidate_sha256": expected_sha256}):
        raise PermissionError("authenticated_owner_storage_review_required")
    candidate = configured_storage_candidate(client, binding, current, host_storage_roots=host_storage_roots)
    if candidate["sha256"] != expected_sha256:
        raise PermissionError("reviewed_storage_candidate_changed")
    envelope = {key: candidate[key] for key in ("schema", "record", "sha256")}
    envelope["approval_operation_id"] = request.operation_id
    updated = {**current, "storage_binding": envelope}
    # Recheck authority immediately before the single metadata write. Its
    # activation additionally requires the canonical terminal receipt below.
    context.checkpoint()
    with closing(control.store.connect("shell")) as db, db:
        db.execute("BEGIN IMMEDIATE")
        result = db.execute("UPDATE shell_dot_vms SET body=? WHERE owner=? AND project=? AND root=? AND body=?",
                            (_encode(updated), owner, workspace_id, root_dot_id, original_body))
        if result.rowcount != 1:
            raise PermissionError("storage_configuration_revision_conflict")
    return {"kind": "virtualbox.storage.enrollment", "vm_id": binding.vm_id,
            "disk_uuid": candidate["record"]["disk_uuid"], "storage_binding_sha256": expected_sha256,
            "workspace_id": workspace_id, "root_dot_id": root_dot_id,
            "machine_id": request.machine_id, "approval_operation_id": request.operation_id,
            "metadata_recorded": True, "activation_requires_operation_succeeded": True,
            "vm_or_disk_mutated": False, "automatic_retry": False}


def verify_owned_storage_approval(control, *, owner, workspace_id, root_dot_id, binding, cfg, envelope):
    context, _, current, _ = _bound_context(control, owner, workspace_id, root_dot_id, binding, cfg)
    if current.get("storage_binding") != envelope:
        raise PermissionError("storage_approval_not_from_current_protected_record")
    authority = CentralDurableIntentAuthority(control.durable)
    receipt = authority.receipt_for_operation(envelope["approval_operation_id"], owner)
    row = control.durable.operation_status(receipt.operation_id, owner)
    progress = row.get("progress") or {}
    if (receipt.run_id != context.receipt.run_id or row["kind"] != "sentra.machine" or row["state"] != "SUCCEEDED"
            or progress.get("machine_id") != context.request.machine_id
            or progress.get("capability_id") != "vm:manage"):
        raise PermissionError("canonical_storage_approval_not_succeeded")
    approved_request = OperationRequest(receipt.operation_id, progress["principal_id"], progress["machine_id"],
                                        "vm:manage", progress["work_item_id"], row["idempotency_key"],
                                        {"action": "storage.enroll", "expected_candidate_sha256": envelope["sha256"]})
    if _request_snapshot(approved_request)[1] != receipt.intent_sha256:
        raise PermissionError("canonical_storage_approval_intent_mismatch")
    result = authority.result_for_receipt(receipt)
    expected = {"kind": "virtualbox.storage.enrollment", "vm_id": binding.vm_id,
                "disk_uuid": envelope["record"]["disk_uuid"], "storage_binding_sha256": envelope["sha256"],
                "workspace_id": workspace_id, "root_dot_id": root_dot_id,
                "machine_id": context.request.machine_id, "approval_operation_id": receipt.operation_id,
                "metadata_recorded": True, "vm_or_disk_mutated": False}
    if result is None or result.state != "SUCCEEDED" or any(result.evidence.get(k) != v for k,v in expected.items()):
        raise PermissionError("canonical_storage_approval_evidence_mismatch")
    context.checkpoint()
    return True


def storage_enrollment_callbacks(control, *, owner, workspace_id, root_dot_id, host_storage_roots=None):
    """Native configure_virtualbox_machine wiring; no ambient authority lookup."""
    if not isinstance(control, ControlPlaneService):
        raise TypeError("real_control_plane_required")
    def enroll(client, binding, cfg, expected):
        return enroll_owned_storage(control, owner=owner, workspace_id=workspace_id, root_dot_id=root_dot_id,
                                    client=client, binding=binding, cfg=cfg, expected_sha256=expected,
                                    host_storage_roots=host_storage_roots)
    def verify(binding, cfg, envelope):
        return verify_owned_storage_approval(control, owner=owner, workspace_id=workspace_id,
                                             root_dot_id=root_dot_id, binding=binding, cfg=cfg, envelope=envelope)
    return enroll, verify


def dispatch_owner_storage_enrollment(vm_service, project_id, params, request_key):
    """One-call native authenticated shell wiring; NEVER call from ShellActor.

    Authentication is the native owner's shell boundary, not a JSON `approved`
    flag. Existing Dot scope, ShellHostRequests journal and machine gates remain.
    service.py must select this function only for owner-origin storage.enroll.
    """
    if (not isinstance(params, dict) or set(params) != {"dot_id","space_id","conversation_id","arguments"}
            or not isinstance(params.get("arguments"), dict)
            or set(params["arguments"]) != {"action","expected_candidate_sha256"}
            or params["arguments"].get("action") != "storage.enroll"
            or not isinstance(request_key,str) or not 8 <= len(request_key) <= 200):
        raise ValueError("exact_owner_storage_enrollment_request_required")
    root, _, convo = vm_service.scope(project_id, params)
    expected = params["arguments"]["expected_candidate_sha256"]
    operation_id = vm_service.requests.operation_id(project_id,request_key,"dot_vm_execute")
    with owner_storage_enrollment_scope(vm_service.host.control,owner=vm_service.host.owner,
            workspace_id=project_id,root_dot_id=root,conversation_id=convo["conversation_id"],
            operation_id=operation_id,expected_sha256=expected):
        return vm_service.dispatch(project_id,"dot_vm_execute",params,request_key)
