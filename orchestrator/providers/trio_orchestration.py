"""Close the coordinator trio only through Run, WorkItem, Operation, Grant and receipt.

This module does not start SENTRA CLI, OpenCode, Codex, or a guest process.
A shaped receipt without the central services does not close the front.
UNCERTAIN delivery is recorded and is not resent. Promotion to COMPLETED stays
outside this step.
"""
from __future__ import annotations

from typing import Any, Mapping

from .fleet_admission import (
    FleetAdmissionError,
    claim_effect,
    note_uncertain_effect,
    place_execution,
)

TRIO_LANES = ("sentra-cli", "opencode", "codex")
LANE_MODELS = {
    "sentra-cli": "sentra/chatgpt-web/gpt-6",
    "opencode": "opencode/muse-spark-1.3-contributor-free#high",
    "codex": "sentra/codex/",
}
PARENT_CAPABILITY = "canvas.coordinator.dot_tool_dispatch"
CHILD_CAPABILITY = "model:invoke"
_SHA_OK = set("0123456789abcdef")


class TrioClosureError(FleetAdmissionError):
    pass


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value or len(value) > 128:
        raise TrioClosureError(f"invalid {field}")
    return value


def _sha256(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in _SHA_OK for ch in value):
        raise TrioClosureError("receipt hash is required")
    return value


def _model_matches(lane: str, model: Any) -> bool:
    expected = LANE_MODELS[lane]
    if not isinstance(model, str) or not model.strip():
        return False
    if lane == "codex":
        return model.startswith(expected) and len(model) > len(expected)
    return model == expected


def _refuse_uncertain(operation_id: str, raw: Mapping[str, Any], receipt: Any) -> None:
    uncertain = raw.get("execution_uncertain") is True or str(raw.get("state") or "").upper() == "UNCERTAIN"
    if isinstance(receipt, Mapping):
        uncertain = uncertain or receipt.get("execution_uncertain") is True or receipt.get("status") == "UNCERTAIN"
    if uncertain:
        note_uncertain_effect(operation_id)
        raise TrioClosureError("UNCERTAIN operation is not resent")


def _receipt(raw: object, *, lane: str | None) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TrioClosureError("receipt is required")
    if raw.get("ack_only") is True or raw.get("status") in {"ADMITTED", "ACK"}:
        raise TrioClosureError("ACK is not an inference receipt")
    if raw.get("echo_only_detected") is True:
        raise TrioClosureError("echo is not an inference receipt")
    if raw.get("status") != "SUCCEEDED":
        raise TrioClosureError("only a SUCCEEDED receipt can close a lane")
    if raw.get("verified") is not True:
        raise TrioClosureError("unverified receipt cannot close a lane")
    if raw.get("execution_uncertain") is True:
        raise TrioClosureError("UNCERTAIN operation is not resent")
    if raw.get("execution_uncertain") is not False:
        raise TrioClosureError("receipt must mark execution_uncertain false")
    if raw.get("echo_only_detected") is not False:
        raise TrioClosureError("echo is not an inference receipt")
    if raw.get("ack_only") is not False:
        raise TrioClosureError("ACK is not an inference receipt")
    if raw.get("launch_failed") is not False:
        raise TrioClosureError("launch failure is not an inference receipt")
    if raw.get("effort") != "high":
        raise TrioClosureError("lane effort must be high")
    model = raw.get("model")
    if lane is not None and not _model_matches(lane, model):
        raise TrioClosureError("receipt model does not match the admitted lane")
    return {
        "status": "SUCCEEDED",
        "verified": True,
        "execution_uncertain": False,
        "echo_only_detected": False,
        "ack_only": False,
        "launch_failed": False,
        "effort": "high",
        "model": model,
        "stdout_sha256": _sha256(raw.get("stdout_sha256")),
    }


def _require_grant(authorizer: Any, *, owner: str, agent_id: str, capability: str,
                   scope_id: str, expected_grant_id: str) -> dict[str, Any]:
    decision = authorizer.require(
        owner,
        principal_type="agent",
        principal_id=agent_id,
        capability=capability,
        scope_type="work_item",
        scope_id=scope_id,
        local_owner=False,
    )
    if decision.get("source") != "grant" or decision.get("grant_id") != expected_grant_id:
        raise TrioClosureError("effect requires its own current Grant")
    return decision


def _child_records(admission: Mapping[str, Any], children: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    authority = admission["authority"]
    if not isinstance(children, list) or len(children) != 3:
        raise TrioClosureError("the coordinator trio requires three lanes")
    seen: set[str] = set()
    records = []
    operation_ids = {authority["operation_id"]}
    work_ids = {authority["work_item_id"]}
    grant_ids = {authority["grant_id"]}
    for raw in children:
        if not isinstance(raw, Mapping):
            raise TrioClosureError("child lane is required")
        lane = _token(raw.get("lane"), "lane")
        if lane not in TRIO_LANES or lane in seen:
            raise TrioClosureError("the coordinator trio requires sentra-cli, opencode and codex once each")
        seen.add(lane)
        operation_id = _token(raw.get("operation_id"), "operation_id")
        work_item_id = _token(raw.get("work_item_id"), "work_item_id")
        grant_id = _token(raw.get("grant_id"), "grant_id")
        agent_id = _token(raw.get("agent_id"), "agent_id")
        if raw.get("run_id") != authority["run_id"] or raw.get("owner") != authority["owner"]:
            raise TrioClosureError("child lane left the coordinator Run")
        if operation_id in operation_ids or work_item_id in work_ids or grant_id in grant_ids:
            raise TrioClosureError("child lane must use its own WorkItem, Operation and Grant")
        if raw.get("state") != "IN_REVIEW":
            raise TrioClosureError("child WorkItem must be IN_REVIEW before reconciliation")
        _refuse_uncertain(operation_id, raw, raw.get("receipt"))
        try:
            claim_effect(operation_id)
        except FleetAdmissionError as exc:
            raise TrioClosureError(str(exc)) from exc
        receipt = _receipt(raw.get("receipt"), lane=lane)
        operation_ids.add(operation_id)
        work_ids.add(work_item_id)
        grant_ids.add(grant_id)
        records.append({
            "lane": lane,
            "owner": authority["owner"],
            "run_id": authority["run_id"],
            "work_item_id": work_item_id,
            "operation_id": operation_id,
            "grant_id": grant_id,
            "agent_id": agent_id,
            "state": "IN_REVIEW",
            "receipt": receipt,
        })
    if seen != set(TRIO_LANES):
        raise TrioClosureError("the coordinator trio requires sentra-cli, opencode and codex once each")
    return records


def _coordinator_receipt(admission: Mapping[str, Any], raw: Mapping[str, Any], used_operations: set[str]) -> dict[str, Any]:
    authority = admission["authority"]
    if not isinstance(raw, Mapping):
        raise TrioClosureError("coordinator receipt is required")
    operation_id = _token(raw.get("operation_id"), "operation_id")
    if operation_id in used_operations:
        raise TrioClosureError("coordinator response needs its own Operation")
    if raw.get("work_item_id") != authority["work_item_id"]:
        raise TrioClosureError("coordinator response must stay on the coordinator WorkItem")
    if raw.get("grant_id") != authority["grant_id"]:
        raise TrioClosureError("coordinator response must use the coordinator Grant")
    _refuse_uncertain(operation_id, raw, raw)
    receipt = _receipt(raw, lane=None)
    receipt["text_sha256"] = _sha256(raw.get("text_sha256"))
    receipt["operation_id"] = operation_id
    receipt["work_item_id"] = authority["work_item_id"]
    receipt["grant_id"] = authority["grant_id"]
    return receipt


def _verify_central(durable: Any, governance: Any, authorizer: Any, admission: Mapping[str, Any],
                    children: list[dict[str, Any]], coordinator: dict[str, Any]) -> None:
    authority = admission["authority"]
    owner = authority["owner"]
    run = durable.run_status(authority["run_id"], owner)
    if run.get("state") != "RUNNING" or run.get("desired_state") != "RUNNING":
        raise TrioClosureError("Run must be RUNNING")
    if run.get("run_id") != authority["run_id"] or run.get("owner") != owner:
        raise TrioClosureError("Run does not match the admission")
    _require_operation(durable, owner, authority["run_id"], authority["operation_id"], allow_running=True)
    _require_grant(
        authorizer, owner=owner, agent_id=authority["agent_id"],
        capability=PARENT_CAPABILITY, scope_id=authority["work_item_id"],
        expected_grant_id=authority["grant_id"],
    )
    parent = governance.work_item_info(authority["work_item_id"], owner)
    if parent.get("run_id") != authority["run_id"] or parent.get("state") in {"COMPLETED", "FAILED", "CANCELLED"}:
        raise TrioClosureError("coordinator WorkItem is not open on this Run")
    if PARENT_CAPABILITY not in (parent.get("required_capabilities") or []):
        raise TrioClosureError("coordinator WorkItem is missing its dispatch capability")
    for child in children:
        info = governance.work_item_info(child["work_item_id"], owner)
        if info.get("state") != "IN_REVIEW" or info.get("run_id") != authority["run_id"]:
            raise TrioClosureError("stored WorkItem is not IN_REVIEW on the coordinator Run")
        if info.get("parent_work_item_id") != authority["work_item_id"]:
            raise TrioClosureError("stored WorkItem is not a child of the coordinator")
        if info.get("assignee_agent_id") != child["agent_id"]:
            raise TrioClosureError("stored WorkItem assignee differs from the lane")
        if CHILD_CAPABILITY not in (info.get("required_capabilities") or []):
            raise TrioClosureError("child WorkItem is missing model:invoke")
        _require_operation(durable, owner, authority["run_id"], child["operation_id"], allow_running=False)
        _require_grant(
            authorizer, owner=owner, agent_id=child["agent_id"],
            capability=CHILD_CAPABILITY, scope_id=child["work_item_id"],
            expected_grant_id=child["grant_id"],
        )
    _require_operation(durable, owner, authority["run_id"], coordinator["operation_id"], allow_running=False)


def _require_operation(durable: Any, owner: str, run_id: str, operation_id: str, *, allow_running: bool) -> None:
    try:
        operation = durable.operation_status(operation_id, owner)
    except Exception as exc:
        raise TrioClosureError("Operation is not on the central Run") from exc
    if operation.get("run_id") != run_id or operation.get("owner") != owner:
        raise TrioClosureError("Operation is not on the central Run")
    state = operation.get("state")
    if state == "UNCERTAIN":
        note_uncertain_effect(operation_id)
        raise TrioClosureError("UNCERTAIN operation is not resent")
    allowed = {"SUCCEEDED", "RUNNING", "STARTING", "WAITING_EXTERNAL"} if allow_running else {"SUCCEEDED"}
    if state not in allowed:
        raise TrioClosureError("Operation receipt is not SUCCEEDED")


def reconcile_trio(
    admission: Mapping[str, Any],
    children: list[Mapping[str, Any]],
    coordinator_receipt: Mapping[str, Any],
    *,
    placement: str = "host",
    guest_process: Mapping[str, Any] | None = None,
    authorizer: Any = None,
    durable: Any = None,
    governance: Any = None,
) -> dict[str, Any]:
    if not isinstance(admission, Mapping) or admission.get("admitted") is not True:
        raise TrioClosureError("trio closure requires the single fleet admission")
    if admission.get("inference_executed") is True:
        raise TrioClosureError("admission cannot claim inference by itself")
    placed = place_execution(placement, guest_process)
    records = _child_records(admission, children)
    used = {admission["authority"]["operation_id"], *(record["operation_id"] for record in records)}
    coordinator = _coordinator_receipt(admission, coordinator_receipt, used)
    decision = {
        "reconciled": False,
        "applied": False,
        "closed": False,
        "promoted": False,
        "physical_inference": False,
        "placement": placed,
        "admission_id": admission.get("admission_id"),
        "run_id": admission["authority"]["run_id"],
        "coordinator_work_item_id": admission["authority"]["work_item_id"],
        "coordinator_operation_id": coordinator["operation_id"],
        "work_items": {
            record["lane"]: {
                "work_item_id": record["work_item_id"],
                "operation_id": record["operation_id"],
                "grant_id": record["grant_id"],
                "from": "IN_REVIEW",
                "to": "READY_FOR_PROMOTION",
            }
            for record in records
        },
        "reason": "central Run, Operation, Grant and WorkItem services are required to apply reconciliation",
    }
    if authorizer is None or durable is None or governance is None:
        return decision
    _verify_central(durable, governance, authorizer, admission, records, coordinator)
    owner = admission["authority"]["owner"]
    for record in records:
        governance.transition_work_item(
            record["work_item_id"], owner, "READY_FOR_PROMOTION",
            reason="coordinator trio receipt verified",
        )
    decision["reconciled"] = True
    decision["applied"] = True
    decision["closed"] = True
    decision["reason"] = "WorkItems moved to READY_FOR_PROMOTION; promotion to COMPLETED remains explicit"
    return decision
