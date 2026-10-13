"""Agent coordinator effects admitted by the parent WorkItem's existing Grants.

Root owns token/process/Canvas composition. This helper owns central identity,
scope, immutable intent, budget and fencing. No owner shortcut or Grant minting.
"""
import hashlib
import json
from contextlib import closing

from sentra_core.conversations import _decode
from .authority_bridge import BoundWorkItemPolicy
from .central_authority import CentralDurableIntentAuthority
from .contracts import OperationRequest, OperationResult, PolicyDecision
from .effect_boundary import CentralEffectContext
from .executor import _request_snapshot
from .machine_budget import BudgetedMachinePolicy


COORDINATOR_CAPABILITIES = {
    "create_dot": "canvas.coordinator.dot_create",
    "create_team": "canvas.coordinator.team_create",
    "connect": "canvas.coordinator.connect",
    "delegate": "canvas.coordinator.delegate",
    "handoff": "canvas.coordinator.handoff",
    "pause": "canvas.coordinator.pause", "resume": "canvas.coordinator.resume",
    "cancel": "canvas.coordinator.cancel", "reassign": "canvas.coordinator.reassign",
    "pause_dot": "canvas.coordinator.pause_dot", "resume_dot": "canvas.coordinator.resume_dot",
    "dot_tool_dispatch.sentra_cli": "canvas.coordinator.dot_tool_dispatch.sentra_cli",
    "dot_tool_dispatch.opencode": "canvas.coordinator.dot_tool_dispatch.opencode",
    "dot_tool_dispatch.codex": "canvas.coordinator.dot_tool_dispatch.codex",
}


def execute_coordinator_intent(control, owner, *, project_id, conversation_id,
        run_id, work_item_id, parent_operation_id, agent_id, intent, request_key,
        compose, process_alive, connected_agents):
    """Server-only callbacks: compose(resolved_intent, authority)->dict;
    process_alive()->bool; connected_agents(project_id,agent_id)->agent IDs.
    Metadata admission never confers child execution capabilities or Grants.
    """
    if not all(callable(cb) for cb in (compose,process_alive,connected_agents)):
        raise ValueError("trusted live-process and Canvas composition callbacks required")
    if (not isinstance(intent,dict) or intent.get("kind") not in COORDINATOR_CAPABILITIES
            or not isinstance(request_key,str) or not 1 <= len(request_key) <= 128 or "\0" in request_key):
        raise ValueError("bounded structured coordinator intent required")
    project = control.shell._project(owner,project_id)
    if project["run_id"] != run_id:
        raise PermissionError("coordinator Run is not current for this project")
    with closing(control.store.connect("shell")) as db:
        binding = db.execute("SELECT * FROM canvas_shell_provider_bindings WHERE owner=? AND project_id=? AND conversation_id=?",
                             (owner,project_id,conversation_id)).fetchone()
        if binding is None or any(binding[field] != value for field,value in
            (("run_id",run_id),("work_item_id",work_item_id),("operation_id",parent_operation_id),("agent_id",agent_id))):
            raise PermissionError("coordinator token differs from current shell execution")
        conversation = control.shell._entity(db,owner,project_id,"conversation",conversation_id)
        dot = control.shell._entity(db,owner,project_id,"dot",conversation["dot_id"],space_id=conversation["space_id"])
        from sentra_mcp.services.shell_coordinator import dot_manages_canvas
        if dot["agent_id"] != agent_id or not dot_manages_canvas(dot):
            raise PermissionError("only the bound coordinator Dot may coordinate")
        kind = intent["kind"]
        if kind in {"pause", "resume", "cancel"}:
            raise PermissionError("Dot coordination is scoped to its own canvas; project controls belong to the owner")
        if kind == "create_dot":
            from sentra_mcp.services.shell_coordinator import _text
            if set(intent)-{"kind","name","role","model","effort","instructions"}:
                raise ValueError("unsupported Dot creation fields")
            resolved = {"kind":kind,"name":_text(intent.get("name"),"name",80),
                "role":_text(intent.get("role","worker"),"role",80),
                "model":_text(intent.get("model"),"model",200),
                "instructions":_text(intent.get("instructions",""),"instructions",16000,empty=True),
                "effort":intent.get("effort")}
            if resolved["effort"] not in {None,"automatic","low","medium","high","xhigh","max","ultra"}:
                raise ValueError("invalid model effort")
        else:
            resolved = control.shell._intent(db,owner,project,conversation["space_id"],{"intent":intent})
        allowed = set(connected_agents(project_id,agent_id)) | {agent_id}
        targets = {resolved[field] for field in ("agent_id","source_agent_id","target_agent_id","coordinator_agent_id") if resolved.get(field)}
        targets.update(resolved.get("worker_agent_ids",[]))
        if targets - allowed:
            raise PermissionError("coordinator intent targets an agent outside its directed connections")
        if kind == "reassign" and control.work_item_info(resolved["work_item_id"], owner).get("assignee_agent_id") not in allowed:
            raise PermissionError("cannot reassign work owned by another Dot canvas")
        if kind == "handoff" and resolved.get("source_agent_id") != agent_id:
            raise PermissionError("coordinator cannot impersonate another handoff source")
    def live():
        run = control.durable.run_status(run_id,owner,include_details=False)
        current = control.work_item_info(work_item_id,owner)
        operation = control.durable.operation_status(parent_operation_id,owner)
        actor = control.durable.agent_info(agent_id,owner)
        with closing(control.store.connect("shell")) as db:
            bound = db.execute("SELECT operation_id,work_item_id,agent_id,run_id FROM canvas_shell_provider_bindings WHERE owner=? AND project_id=? AND conversation_id=?",
                               (owner,project_id,conversation_id)).fetchone()
            current_dot = control.shell._entity(db,owner,project_id,"dot",dot["dot_id"],space_id=conversation["space_id"])
        return (process_alive() is True and run["state"] == "RUNNING" and run["desired_state"] == "RUNNING"
            and current_dot["agent_id"] == agent_id and dot_manages_canvas(current_dot)
            and current["run_id"] == run_id and current["state"] == "RUNNING"
            and current["assignee_agent_id"] == agent_id and actor["run_id"] == run_id and actor["desired_state"] != "WAITING"
            and current["metadata"].get("workspace_id") == project_id and operation["run_id"] == run_id
            and operation["state"] in {"STARTING","RUNNING"} and bound is not None
            and tuple(bound[field] for field in ("operation_id","work_item_id","agent_id","run_id")) == (parent_operation_id,work_item_id,agent_id,run_id))
    if not live():
        raise PermissionError("coordinator parent execution is not live")
    cap = COORDINATOR_CAPABILITIES[kind]
    if cap not in control.work_item_info(work_item_id,owner).get("required_capabilities",[]):
        raise PermissionError("coordinator capability is not explicitly declared by the parent WorkItem")
    identity = hashlib.sha256(json.dumps([owner,project_id,parent_operation_id,request_key],separators=(",",":")).encode()).hexdigest()
    oid = "coordinator-" + identity[:48]
    arguments = {"intent":resolved,"project_id":project_id,"conversation_id":conversation_id,
                 "space_id":conversation["space_id"],"parent_operation_id":parent_operation_id}
    request = OperationRequest(oid,agent_id,"coordinator-"+agent_id,cap,work_item_id,oid,arguments)
    bound_policy = BoundWorkItemPolicy(owner=owner,principal_type="agent",authorization=control.authorization,
        governance=control.governance, trusted_context=lambda _: {"actual_cost":0.0,"provider":"canvas-coordinator"})
    policy = BudgetedMachinePolicy(bound_policy,control=control,owner=owner)
    def authorize(candidate):
        if not live():
            return PolicyDecision(False,"coordinator parent authority revoked")
        requirements = control.work_item_info(work_item_id,owner).get("required_capabilities")
        if not isinstance(requirements,list) or candidate.capability_id not in requirements:
            return PolicyDecision(False,"coordinator capability was not explicitly declared by the parent WorkItem")
        current_allowed = set(connected_agents(project_id,agent_id)) | {agent_id}
        if targets-current_allowed:
            return PolicyDecision(False,"coordinator connection scope changed")
        return policy(candidate)
    if authorize(request).allowed is not True:
        # Persist an owner-visible request, not a Grant or a fabricated operation
        # receipt. Approval can authorize this turn, but never auto-replays it.
        from .coordinator_approvals import CoordinatorApprovalInbox
        CoordinatorApprovalInbox(control, owner).record(project_id=project_id,
            space_id=conversation['space_id'], conversation_id=conversation_id,
            parent_operation_id=parent_operation_id, work_item_id=work_item_id,
            agent_id=agent_id, approval_id=oid, capability=cap, intent=resolved)
        return {"status":"waiting_approval","operation_id":oid,"work_item_id":work_item_id,
                "capability":cap,"receipt_id":None,"grant_created":False,"external_completion_claimed":False}
    authority = CentralDurableIntentAuthority(control.durable,budgets=control.budgets,release_on_terminal=True)
    _,digest = _request_snapshot(request)
    receipt = authority.reserve_intent(run_id=run_id,owner=owner,request=request,intent_sha256=digest)
    if receipt.status != "RESERVED":
        recorded = authority.result_for_receipt(receipt)
        if recorded is not None:
            return {**recorded.evidence,"operation_id":oid,"idempotent_replay":True}
        return {"status":"uncertain","operation_id":oid,"receipt_id":None,"automatic_retry":False}
    context = CentralEffectContext(authority,receipt,request,authorize)
    ids = {"run_id":run_id,"work_item_id":work_item_id,"operation_id":oid,
           "parent_operation_id":parent_operation_id,"agent_id":agent_id,"project_id":project_id,
           "conversation_id":conversation_id,"space_id":conversation["space_id"],"request_key":request_key,
           "capability":cap,"grant_created":False,"metadata_only":True,"child_execution_requires_own_grant":True}
    def invoke():
        value = compose(dict(resolved),dict(ids))
        if not isinstance(value,dict):
            raise RuntimeError("coordinator composition did not acknowledge")
        status = value.get("status","recorded")
        return OperationResult(oid,"UNCERTAIN" if status == "uncertain" else "FAILED" if status == "failed" else "SUCCEEDED",
            {**value,**ids,"receipt_id":"coordinator:"+oid,"external_completion_claimed":False})
    try:
        result = context.run_sync(invoke)
    except Exception:
        result = OperationResult(oid,"UNCERTAIN",{**ids,"status":"uncertain","receipt_id":None,
            "external_completion_claimed":False},"coordinator acknowledgement unavailable")
    terminal = kind in {"pause","cancel"} or kind == "pause_dot" and resolved.get("agent_id") == agent_id
    if result.state == "SUCCEEDED" and not terminal and authorize(request).allowed is not True:
        result = OperationResult(oid,"UNCERTAIN",{**ids,"status":"uncertain","receipt_id":None,
            "external_completion_claimed":False},"coordinator authority changed before acknowledgement")
    recorded = authority.record_metadata_transition(receipt,request,result) if terminal and result.state == "SUCCEEDED" else authority.record_result(receipt,result)
    if not recorded:
        return {**ids,"status":"uncertain","receipt_id":None,"automatic_retry":False}
    if terminal and result.state == "SUCCEEDED":
        return {**result.evidence,"terminal_metadata_transition_ack":True,"subsequent_effects_denied":True}
    return {**result.evidence,"status":"uncertain" if result.state == "UNCERTAIN" else result.evidence.get("status","recorded")}
