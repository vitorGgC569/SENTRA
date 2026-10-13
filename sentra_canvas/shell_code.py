"""Shell Code Mode actions projected through the same configured MachineHost."""
from .code_machine import CODE_ACTIONS
from .store import Denied

CODE_READS = frozenset({"code_status", "code_discovery"})
_FIELDS = {"code_propose": {"machine_id", "work_item_id", "source"},
    "code_execute": {"machine_id", "work_item_id", "proposal_id"},
    "code_cancel": {"machine_id", "work_item_id", "proposal_id"},
    "code_status": {"machine_id", "proposal_id"}, "code_discovery": {"machine_id"}}


def dispatch_code(canvas, project_id, action, params, request_key):
    if action not in CODE_ACTIONS or set(params) - (_FIELDS[action] | {"space_id", "conversation_id"}):
        raise ValueError("unknown Code Mode bridge fields")
    host = canvas._machine_service()
    if params.get("space_id") is not None:
        host.control.shell.get_space(params["space_id"], host.owner, project_id=project_id)
    if params.get("conversation_id") is not None:
        from contextlib import closing
        with closing(host.control.store.connect("shell")) as db:
            host.control.shell._entity(db, host.owner, project_id, "conversation",
                params["conversation_id"], space_id=params.get("space_id"))
    machines = [m for m in host.inventory(project_id) if m["kind"] == "code-mode"]
    selected = next((m for m in machines if m["machine_id"] == params.get("machine_id")), None)
    if action == "code_discovery" and params.get("machine_id") is None:
        return {"items": machines, "configured": bool(machines), "execution_verified": False}
    if selected is None:
        raise Denied("configured Code Mode machine required in this project")
    if action in CODE_READS:
        async def read():
            factory = host._factories[selected["machine_id"]]
            return factory.status(params["proposal_id"]) if action == "code_status" else factory.catalog()
        return host._call(read(), timeout=15)
    from .shell_machines import ShellMachineServices
    with canvas._lock:
        if canvas._shell_machines is None:
            canvas._shell_machines = ShellMachineServices(canvas)
    arguments = {k:v for k,v in params.items() if k in {"source", "proposal_id"}}
    values = {"machine_id": selected["machine_id"], "work_item_id": params["work_item_id"],
        "capability_id": CODE_ACTIONS[action], "arguments": arguments,
        **{k:params[k] for k in ("space_id", "conversation_id") if k in params}}
    return canvas._shell_machines.dispatch(project_id, "machine_execute", values, request_key)
