"""Production audit of a runner final answer against the central receipt.

Fleet admission is a deterministic fallback. It is not a model decision and it
does not seal a chain. A model decision is sealed only from the runner result:
the model name, the instruction hash, the stdout hash, the tool that ran, and
the lease row that already exists for the Operation. Resource key and fencing
token are copied from that row. This module does not mint lease or fence labels,
issue a Grant, reserve an intent, or dispatch an effect.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .decision_receipt_audit import (
    AuditRefusal,
    AuthorizationObservation,
    DecisionObservation,
    DecisionReceiptLedger,
    ExecutionObservation,
    ResultObservation,
)

_AUTHORITY = ("owner", "run_id", "work_item_id", "operation_id", "grant_id", "agent_id")
_SHA = re.compile(r"[0-9a-f]{64}")


def production_contract() -> dict[str, Any]:
    """Call contract. Admission is not a decision. A sealed chain is not homologation."""
    return {
        "version": 2,
        "fallback_entry": "sentra_quality.production_audit.record_fleet_admission",
        "entry": "sentra_quality.production_audit.record_runner_final_answer",
        "flint_integration": "sentra_runtime.dot_tool_dispatch runner final answer",
        "flint_function_not_edited": "orchestrator.dispatcher.central_effect_admission",
        "authority_fields": list(_AUTHORITY),
        "counts_as_model_decision_requires": [
            "source=model",
            "live_model_verified",
            "evidence_source=native_process",
            "instruction_sha256",
            "stdout_sha256",
            "tool",
            "leases.resource_key",
            "leases.fencing_token",
        ],
        "authorizes_effect": False,
        "paywall": False,
        "local_use_blocked": False,
        "homologated": False,
        "physical_proof": False,
        "uncertain_resend": False,
    }


def _fallback(reason: str) -> dict[str, Any]:
    return {
        "source": "deterministic_fallback",
        "counts_as_model_decision": False,
        "sealed": False,
        "central_receipt_reached": False,
        "authorizes_effect": False,
        "resend_allowed": False,
        "inference_executed": False,
        "homologated": False,
        "physical_proof": False,
        "reason": reason,
    }


def _authority(admission: dict[str, Any]) -> dict[str, str]:
    raw = admission.get("authority")
    if not isinstance(raw, dict):
        raise AuditRefusal("fleet admission has no authority binding")
    missing = [field for field in _AUTHORITY if not isinstance(raw.get(field), str) or not raw[field].strip()]
    if missing:
        raise AuditRefusal("fleet admission authority is incomplete")
    return {field: raw[field] for field in _AUTHORITY}


def _refuse_admission_shape(admission: dict[str, Any]) -> None:
    if not isinstance(admission, dict) or admission.get("admitted") is not True:
        raise AuditRefusal("fleet admission required")
    if admission.get("inference_executed") is True:
        raise AuditRefusal("admission must not claim inference")
    lanes = admission.get("lanes") or []
    if not isinstance(lanes, list):
        raise AuditRefusal("fleet admission lanes must be a list")
    for lane in lanes:
        if isinstance(lane, dict) and (
            lane.get("delivery_state") == "UNCERTAIN" or lane.get("execution_uncertain") is True
        ):
            raise AuditRefusal("UNCERTAIN operation is not resent")
    placement = admission.get("placement")
    if isinstance(placement, dict) and placement.get("placement") == "guest":
        from sentra_executors.guest_execution import safe_vm_id
        registry_bound = (
            placement.get("vm_registry_bound") is True
            and safe_vm_id(placement.get("vm_id")) is not None
        )
        if type(placement.get("pid")) is int:
            raise AuditRefusal("a process id is not a guest execution")
        if registry_bound and placement.get("claims_guest_execution") is True:
            raise AuditRefusal("vm registry binding is not a guest execution")
        if (not registry_bound or placement.get("guest_process_verified") is True
                or placement.get("claims_guest_execution") is True):
            raise AuditRefusal("guest admission requires the Dot VM registry")


def record_fleet_admission(
    ledger: DecisionReceiptLedger,
    admission: dict[str, Any],
    *,
    durable: Any,
    governance: Any,
    authorization: Any,
) -> dict[str, Any]:
    """Record that an admission is not a model decision. No chain is sealed."""
    if not isinstance(ledger, DecisionReceiptLedger):
        raise TypeError("DecisionReceiptLedger required")
    del durable, governance, authorization
    _refuse_admission_shape(admission)
    _authority(admission)
    return _fallback("fleet admission is not a model decision")


def _operation_lease(durable: Any, operation_id: str, owner: str) -> tuple[Any, Any]:
    """Read the Operation row and the lease row that already points at it."""
    db = getattr(durable, "db", None)
    if db is None:
        raise AuditRefusal("central operation receipt unavailable")
    lock = getattr(durable, "lock", None)

    def read():
        operation = db.execute(
            "SELECT operation_id, run_id, owner, intent_sha256, resource_key, fencing_token, state "
            "FROM operations WHERE operation_id=? AND owner=?",
            (operation_id, owner),
        ).fetchone()
        lease = db.execute(
            "SELECT resource_key, run_id, operation_id, owner, fencing_token "
            "FROM leases WHERE operation_id=? AND owner=?",
            (operation_id, owner),
        ).fetchone()
        return operation, lease

    if lock is None:
        operation, lease = read()
    else:
        with lock:
            operation, lease = read()
    if operation is None or not operation["intent_sha256"] or not operation["resource_key"]:
        raise AuditRefusal("central operation receipt unavailable")
    if lease is None:
        raise AuditRefusal("central lease is not recorded")
    if (
        lease["resource_key"] != operation["resource_key"]
        or lease["run_id"] != operation["run_id"]
        or type(operation["fencing_token"]) is not int
        or int(lease["fencing_token"]) != int(operation["fencing_token"])
        or int(operation["fencing_token"]) <= 0
    ):
        raise AuditRefusal("central fence does not match the lease")
    return operation, lease


def record_runner_final_answer(
    ledger: DecisionReceiptLedger,
    receipt: dict[str, Any],
    *,
    instruction: str,
    authority: dict[str, str],
    durable: Any,
    governance: Any,
    authorization: Any,
) -> dict[str, Any]:
    """Seal a live runner result. A fallback or an injected runner does not seal."""
    if not isinstance(ledger, DecisionReceiptLedger):
        raise TypeError("DecisionReceiptLedger required")
    if not isinstance(receipt, dict):
        raise AuditRefusal("runner receipt required")
    if receipt.get("execution_uncertain") is True or receipt.get("status") == "UNCERTAIN":
        raise AuditRefusal("UNCERTAIN operation is not resent")
    if receipt.get("live_model_verified") is not True or receipt.get("evidence_source") != "native_process":
        return _fallback("runner result is not a live model decision")
    if not isinstance(instruction, str) or not instruction:
        raise AuditRefusal("runner instruction required")
    tool = receipt.get("tool")
    model = receipt.get("effective_model") or receipt.get("model")
    output_sha = receipt.get("stdout_sha256")
    if not isinstance(tool, str) or tool in {"fleet.admit", ""}:
        raise AuditRefusal("runner tool is not an operational observation")
    if not isinstance(model, str) or model in {"fleet-admission", ""}:
        raise AuditRefusal("runner model is not an operational observation")
    if not isinstance(output_sha, str) or not _SHA.fullmatch(output_sha):
        raise AuditRefusal("runner stdout hash is not an operational observation")
    bound = _authority({"authority": authority, "admitted": True})
    owner = bound["owner"]
    input_sha = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    if input_sha == output_sha:
        raise AuditRefusal("runner input and output hashes must be distinct observations")
    try:
        from sentra_runtime.central_authority import CentralDurableIntentAuthority
        central = CentralDurableIntentAuthority(durable).receipt_for_operation(bound["operation_id"], owner)
        grant = authorization.info(bound["grant_id"], owner)
        run = durable.run_status(bound["run_id"], owner, include_details=False)
        operation, lease = _operation_lease(durable, bound["operation_id"], owner)
    except AuditRefusal:
        raise
    except Exception as exc:
        raise AuditRefusal("central operation receipt unavailable") from exc
    if central.run_id != bound["run_id"] or central.intent_sha256 != operation["intent_sha256"]:
        raise AuditRefusal("central receipt Run mismatch")
    if int(central.fencing_token) != int(operation["fencing_token"]):
        raise AuditRefusal("central fence does not match the lease")
    if grant.get("principal_id") != bound["agent_id"] or grant.get("revoked") is True:
        raise AuditRefusal("central receipt Grant mismatch")
    workspace = run.get("workspace")
    if not isinstance(workspace, str) or not workspace:
        raise AuditRefusal("central run has no workspace")
    resource_key = str(lease["resource_key"])
    fencing_token = int(lease["fencing_token"])
    decision = DecisionObservation(
        decision_id="dec-" + output_sha[:32],
        owner=owner,
        dot_id=bound["agent_id"],
        workspace_id=workspace,
        run_id=bound["run_id"],
        work_item_id=bound["work_item_id"],
        model=model,
        choice="answer",
        confidence=1.0,
        prompt_sha256=input_sha,
        source="model",
    )
    opened = ledger.open_chain(decision)
    chain_id = opened["chain_id"]
    dot_id = bound["agent_id"]
    ledger.observe_tool(
        chain_id, owner=owner, dot_id=dot_id, tool_name=tool, args_sha256=input_sha,
    )
    ledger.observe_authorization(
        chain_id, owner=owner, dot_id=dot_id,
        observation=AuthorizationObservation(
            owner=owner,
            principal_type=str(grant["principal_type"]),
            principal_id=str(grant["principal_id"]),
            capability=str(grant["capability"]),
            scope_type=str(grant["scope_type"]),
            scope_id=grant.get("scope_id"),
            allowed=True,
            source="grant",
            grant_id=bound["grant_id"],
            reason="runner final answer observed against the central grant",
        ),
    )
    ledger.observe_execution(
        chain_id, owner=owner, dot_id=dot_id,
        observation=ExecutionObservation(
            operation_id=bound["operation_id"],
            run_id=bound["run_id"],
            work_item_id=bound["work_item_id"],
            lease_id=resource_key,
            fence_token=resource_key,
            fencing_token=fencing_token,
            effect_started=operation["state"] in {"RUNNING", "SUCCEEDED"},
        ),
    )
    ledger.observe_result(
        chain_id, owner=owner, dot_id=dot_id,
        observation=ResultObservation(outcome="observed", evidence_sha256=output_sha),
    )
    sealed = ledger.bind_central_receipt(
        chain_id, owner=owner, dot_id=dot_id,
        durable=durable, governance=governance, authorization=authorization,
    )
    return {
        "chain_id": chain_id,
        "source": "model",
        "counts_as_model_decision": True,
        "sealed": True,
        "central_receipt_reached": True,
        "model": model,
        "tool": tool,
        "instruction_sha256": input_sha,
        "stdout_sha256": output_sha,
        "lease_resource_key": resource_key,
        "fencing_token": fencing_token,
        "run_id": sealed["run_id"],
        "work_item_id": sealed["work_item_id"],
        "operation_id": sealed["operation_id"],
        "grant_id": sealed["grant_id"],
        "intent_sha256": sealed["intent_sha256"],
        "central_state": sealed["central_state"],
        "authorizes_effect": False,
        "resend_allowed": False,
        "homologated": False,
        "physical_proof": False,
    }


def audit_runner_final_answer(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Dispatcher-safe wrapper. A refusal stays on the outcome and does not resend."""
    try:
        return record_runner_final_answer(*args, **kwargs)
    except AuditRefusal as exc:
        refused = _fallback(str(exc))
        refused["resend_allowed"] = False
        return refused
