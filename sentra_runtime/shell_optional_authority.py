"""Fenced optional signaling/storage over the same Run/WorkItem/Grant authority."""
import hashlib
import json

from .central_authority import CentralDurableIntentAuthority
from .contracts import OperationRequest, OperationResult, PolicyDecision
from .effect_boundary import CentralEffectContext
from .executor import _request_snapshot


def capability(action):
    return "shell.voice." + action.removeprefix("voice_") if action.startswith("voice_") else "shell.attachments." + action.removeprefix("attachment_")


def execute_optional(shell, *, owner, project, action, payload, key, callback):
    control = shell.control
    cap = capability(action)
    cleanup = action in {"voice_stop", "voice_revoke", "attachment_upload_abort"}
    bound = shell._authority(owner, project, payload["space_id"], key, action, create_operation=False,
                             assignee_user_id=owner, required_capabilities=[cap])
    payload = {**payload, **bound}
    machine_id = "shell-optional-" + hashlib.sha256(json.dumps([project["project_id"], payload["conversation_id"], "voice" if action.startswith("voice_") else "attachment"]).encode()).hexdigest()[:32]
    arguments = {k:v for k,v in payload.items() if k not in {"run_id", "work_item_id", "operation_id", "conversation"}}
    request = OperationRequest(bound["operation_id"], owner, machine_id, cap, bound["work_item_id"], bound["operation_id"], arguments)
    _, digest = _request_snapshot(request)
    context = {"work_item_id": bound["work_item_id"], "principal_id": owner, "machine_id": machine_id, "capability_id": cap}
    control.durable.pending_operation_intent(bound["run_id"], owner, operation_id=request.operation_id,
        idempotency_key=request.idempotency_key, intent_sha256=digest, resource_key="machine:" + machine_id, operation_context=context)

    # The local-owner shortcut is existing Control Plane authority, derived
    # from the actual Canvas session. Hosted users require persisted Grants.
    from sentra_canvas.shell_runtime import CanvasShellRuntime
    local_owner = control.store.backend == "sqlite" and isinstance(shell.runtime, CanvasShellRuntime) and shell.runtime.owner == owner
    def policy(intent):
        item = control.work_item_info(intent.work_item_id, owner)
        if (item["run_id"] != project["run_id"] or item.get("assignee_user_id") != owner
                or item.get("metadata", {}).get("workspace_id") != project["project_id"]):
            return PolicyDecision(False, "optional WorkItem scope changed")
        decision = control.authorization.authorize(owner, principal_type="user", principal_id=owner,
            capability=cap, scope_type="work_item", scope_id=item["work_item_id"],
            context={"workspace": project.get("workspace"), "space_id": payload["space_id"],
                     "conversation_id": payload["conversation_id"], "operation_id": intent.operation_id,
                     "arguments_sha256": digest}, local_owner=local_owner)
        return PolicyDecision(decision.get("allowed") is True, "central optional interaction policy")
    if policy(request).allowed is not True:
        return {**bound, "status": "waiting_approval", "receipt_id": None, "capability": cap,
                "reason": "user capability Grant required", "external_completion_claimed": False}
    quota = {"allowed": True, "evaluations": []} if cleanup else control.budgets.check_quota(owner, event_id=bound["operation_id"], workspace=project.get("workspace"),
        work_item_id=bound["work_item_id"], run_id=project["run_id"], operation_id=bound["operation_id"],
        provider="voice" if action.startswith("voice_") else "attachments")
    for evaluation in quota.get("evaluations", []):
        if action.startswith("voice_") and evaluation["mode"] == "hard_stop" and {"actual_cost", "market_cost"} & evaluation["limits"].keys():
            raise PermissionError("voice provider pricing is not supplied for this hard monetary budget")
    if quota.get("allowed") is not True:
        raise PermissionError("optional interaction budget denied")
    item = control.work_item_info(bound["work_item_id"], owner)
    if item["state"] == "PENDING":
        control.transition_work_item(item["work_item_id"], owner, "QUEUED")
        if cleanup:
            control.governance.start_execution(item["work_item_id"], owner, run_id=project["run_id"])
        else:
            control.start_work_item_execution(item["work_item_id"], owner, run_id=project["run_id"])
    authority = CentralDurableIntentAuthority(control.durable, budgets=control.budgets,
        release_on_terminal=True, allow_cleanup=cleanup,
        budget_provider="voice" if action.startswith("voice_") else "attachments")
    receipt = authority.reserve_intent(run_id=project["run_id"], owner=owner, request=request, intent_sha256=digest)
    if receipt.status != "RESERVED":
        return {**bound, "status": "uncertain", "receipt_id": None, "external_completion_claimed": False}
    effect = CentralEffectContext(authority, receipt, request, policy)
    response = {}
    safe_receipt = shell._stable(owner, project["project_id"], key, "receipt")
    receipt_kind = "signaling" if action.startswith("voice_") else "storage"
    def invoke():
        value = shell._runtime_call(owner, project["project_id"], key, callback,
            project["project_id"], owner, action, payload, key)
        if not isinstance(value, dict):
            raise RuntimeError("optional callback acknowledgement invalid")
        response.update(value)
        unknown = value.get("status") == "uncertain" or value.get("state") == "uncertain"
        failed = str(value.get("status", "")).lower() == "failed" or str(value.get("state", "")).lower() == "failed"
        return OperationResult(request.operation_id, "UNCERTAIN" if unknown else "FAILED" if failed else "SUCCEEDED",
            {"receipt_id": safe_receipt, "receipt_kind": receipt_kind, "call_id": value.get("call_id"),
             "upload_id": value.get("upload_id"), "attachment_ids": [r["attachment_id"] for r in value.get("attachments", []) if isinstance(r, dict) and r.get("attachment_id")],
             "external_completion_claimed": False})
    try:
        result = effect.run_sync(invoke)
        if policy(request).allowed is not True:
            result = OperationResult(request.operation_id, "UNCERTAIN", {"receipt_kind": receipt_kind, "external_completion_claimed": False}, "optional authority revoked during effect")
    except Exception:
        result = OperationResult(request.operation_id, "UNCERTAIN", {"receipt_kind": receipt_kind, "external_completion_claimed": False}, "optional provider acknowledgement unavailable")
    if not authority.record_result(receipt, result):
        return {**bound, "status": "uncertain", "receipt_id": None, "external_completion_claimed": False}
    if result.state == "SUCCEEDED":
        control.governance.complete_receipted_interaction(bound["work_item_id"], owner, operation_id=bound["operation_id"])
    return {**response, **bound, "status": response.get("status", "recorded") if result.state == "SUCCEEDED" else "failed" if result.state == "FAILED" else "uncertain",
            "receipt_id": safe_receipt if result.state in {"SUCCEEDED","FAILED"} else None, "receipt_kind": receipt_kind, "external_completion_claimed": False}
