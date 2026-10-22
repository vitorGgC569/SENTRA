"""Workspace receipt queries over the existing protected host journal.

Every query validates the original Dot/Space and intent fingerprint. It can
observe a central operation, but cannot dispatch, reserve, or repeat an effect.
"""
from .shell_dot_canvas import DOT_CANVAS_ACTIONS, dot_graph
from .shell_requests import ShellHostRequests
from .workspace_contract import delivery_projection


def inspect_request(canvas, project_id, params, *, exact_dot=False):
    if set(params) not in ({"space_id", "dot_id", "original"}, {"space_id", "dot_id", "selector"}):
        raise ValueError("exact workspace request scope required")
    dot_graph(canvas, project_id, params["dot_id"], params["space_id"])
    journal = ShellHostRequests(canvas._shell_service(), canvas._runtime().owner)
    original = params.get("original")
    if "selector" in params:
        selector = params["selector"]
        if not isinstance(selector, dict) or set(selector) - {"action", "request_key", "fingerprint", "conversation_id"}:
            raise ValueError("unsupported request selector")
        stored = journal.intent(project_id, selector.get("request_key"), selector.get("fingerprint"))
        if stored is None:
            return {"found": False, "resolved": False, "request_key": selector.get("request_key"),
                    "automatic_retry": False, "may_resend": False,
                    "receipt": delivery_projection({"state": "UNCERTAIN"})}
        if selector.get("action") == "dot_computer_action" and stored["action"] == "machine_execute":
            stored_payload = dict(stored["payload"])
            if stored_payload.pop("space_id", None) != params["space_id"]:
                raise PermissionError("original request belongs to another Space")
            original = {"action": selector["action"], "project_id": project_id,
                        "space_id": params["space_id"], "dot_id": params["dot_id"],
                        "request_key": selector["request_key"],
                        "request": {"action": "machine_execute", **stored_payload}}
            if selector.get("conversation_id"):
                original["conversation_id"] = selector["conversation_id"]
        elif selector.get("action") == stored["action"]:
            original = {"action": stored["action"], "project_id": project_id,
                        "request_key": selector["request_key"], **stored["payload"]}
        else:
            raise PermissionError("original request action mismatch")
    if not isinstance(original, dict) or original.get("project_id") != project_id:
        raise ValueError("original project scope required")
    if any(original.get(k) != params[k] for k in ("space_id", "dot_id")):
        raise PermissionError("original request belongs to another workspace")
    if set(original) & {"owner", "principal", "principal_id", "grant", "grant_id", "permissions", "ws"}:
        raise PermissionError("request query cannot select authority")
    action = original.get("action")
    key = original.get("request_key")
    payload = {k: v for k, v in original.items() if k not in {"action", "project_id", "request_key"}}
    computer = None
    if action in DOT_CANVAS_ACTIONS - {"dot_canvas_get"}:
        journal_action, journal_payload = action, payload
    elif action == "dot_computer_action":
        from .shell_dot_computer import DotComputerServices
        if set(payload) - {"space_id", "dot_id", "conversation_id", "request"}:
            raise ValueError("unsupported original computer fields")
        request = payload.get("request")
        if not isinstance(request, dict) or request.get("action") != "machine_execute":
            raise ValueError("only scoped machine execution is supported")
        computer = DotComputerServices(canvas)
        # Revalidate this conversation and family without a machine intention.
        inventory = computer.dispatch(project_id, "dot_computer_get",
            {k: v for k, v in payload.items() if k != "request"})
        if request.get("machine_id") not in {m["machine_id"] for m in inventory["machines"]}:
            raise PermissionError("original machine belongs to another Dot")
        if exact_dot:
            actor = next(d for d in inventory["dots"] if d["dot_id"] == params["dot_id"])
            machine = next(m for m in inventory["machines"] if m["machine_id"] == request["machine_id"])
            if machine["agent_id"] != actor["agent_id"]:
                raise PermissionError("original machine is outside this paired Dot")
        if request.get("work_item_id") not in {w["work_item_id"] for w in inventory["work_items"]}:
            raise PermissionError("original work belongs to another Dot")
        journal_action = request["action"]
        journal_payload = {"space_id": params["space_id"],
                           **{k: v for k, v in request.items() if k != "action"}}
    else:
        raise ValueError("request is not a workspace effect")
    value = journal.inspect(project_id, journal_action, journal_payload, key)
    result = value.get("result") or {}
    value["receipt"] = delivery_projection(result)
    if computer is not None:
        # Deterministic operation identity also permits observation when a host
        # stopped after admission but before storing its returned projection.
        oid = value.get("operation_id") or journal.operation_id(project_id, key, journal_action)
        try:
            operation = computer.dispatch(project_id, "dot_computer_read", {
                "space_id": params["space_id"], "dot_id": params["dot_id"],
                **({"conversation_id": payload["conversation_id"]} if payload.get("conversation_id") else {}),
                "request": {"action": "machine_observe", "target_operation_id": oid},
            })
        except (LookupError, ValueError, FileNotFoundError):
            value["observation_unavailable"] = True
        else:
            value["operation"] = operation
            value["receipt"] = delivery_projection(operation)
            value["resolved"] = operation.get("state") in {"SUCCEEDED", "FAILED", "CANCELLED"}
    return value
