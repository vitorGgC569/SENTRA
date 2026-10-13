"""Dot canvas projections and scoped access to existing machine services.

This composes registered machines; it does not provision virtual machines or
create grants. Provider sessions and input possession retain their existing
central admission checks.
"""
from .shell_dot_canvas import dots_for_root
from .shell_machines import MACHINE_ACTIONS, MACHINE_READS, ShellMachineServices, _FIELDS
from .store import Denied
from contextlib import closing

DOT_COMPUTER_READS = frozenset({"dot_computer_get", "dot_computer_read"})
DOT_COMPUTER_ACTIONS = DOT_COMPUTER_READS | frozenset({"dot_computer_action"})


class DotComputerServices:
    def __init__(self, canvas):
        self.canvas = canvas
        self.host = canvas._machine_service()
        # Reuse the same provider tickets and transport as the existing panel.
        with canvas._lock:
            if canvas._shell_machines is None:
                canvas._shell_machines = ShellMachineServices(canvas)
            self.machines = canvas._shell_machines
        self.viewers = {}

    def dispatch(self, project_id, action, params, request_key=None):
        if action not in DOT_COMPUTER_ACTIONS or set(params) - {"dot_id", "space_id", "conversation_id", "request"}:
            raise ValueError("unsupported Dot computer request")
        if not {"dot_id", "space_id"} <= params.keys():
            raise ValueError("canonical Dot and Space required")
        root, dots = dots_for_root(self.canvas._shell_service(), self.host.owner,
            project_id, params["dot_id"], params["space_id"])
        agents = {dot["agent_id"] for dot in dots}
        conversation_id = params.get('conversation_id')
        if conversation_id:
            control = self.canvas._shell_service()
            with closing(control.store.connect('shell')) as db:
                conversation = control.shell._entity(db, self.host.owner, project_id, 'conversation',
                    conversation_id, space_id=params['space_id'])
            if conversation['dot_id'] not in {dot['dot_id'] for dot in dots}:
                raise Denied('conversation belongs to another Dot canvas')
        def check_conversation(item):
            bound = item.get('metadata', {}).get('conversation_id')
            if bound and bound != conversation_id:
                raise Denied('work belongs to another conversation')
        inventory = [m for m in self.host.inventory(project_id) if m["agent_id"] in agents]
        work_items = self.host.task_catalog(workspace_id=project_id, agent_ids=agents)
        if conversation_id:
            work_items = [item for item in work_items if not item.get('conversation_id') or item['conversation_id'] == conversation_id]
        if action == "dot_computer_get":
            if "request" in params:
                raise ValueError("inventory cannot carry a machine intention")
            resources = [self.canvas.store.resource("agents", agent, project_id) for agent in agents]
            terminals = [self.canvas.store.resource("terminals", agent["terminal_id"], project_id)
                for agent in resources if agent.get("terminal_id")]
            return {"canvas_root_dot_id": root, "dots": dots, "machines": inventory,
                "work_items": work_items, "agents": resources, "terminals": terminals,
                "restore_errors": [e for e in self.host.restore_errors
                    if e.get("machine_id") in {m["machine_id"] for m in inventory}]}
        request = params.get("request")
        if not isinstance(request, dict):
            raise ValueError("machine intention must be an object")
        request = dict(request)
        nested_action = request.pop("action", None)
        allowed = MACHINE_READS - {"machine_list"} if action == "dot_computer_read" else MACHINE_ACTIONS - MACHINE_READS
        if nested_action not in allowed:
            raise ValueError("unsupported Dot machine action")
        if set(request) & {"project_id", "space_id", "conversation_id", "dot_id", "request_key",
                "owner", "principal_id", "agent_id", "run_id", "grant_id", "operation_id"}:
            raise ValueError("machine scope is derived from the authenticated Dot")
        if set(request) - _FIELDS[nested_action]:
            raise ValueError("unsupported scoped machine fields")
        scope = (project_id, root)
        if nested_action == "remote_viewer_close":
            with self.canvas._lock:
                if self.viewers.get(request.get("viewer_id")) != scope:
                    raise Denied("viewer belongs to another Dot canvas")
        elif nested_action == "machine_observe":
            row = self.host.control.durable.operation_status(request.get("target_operation_id"), self.host.owner)
            progress = row.get("progress") or {}
            item = self.host.control.work_item_info(progress.get("work_item_id"), self.host.owner)
            if item.get("assignee_agent_id") not in agents or progress.get("principal_id") not in agents:
                raise Denied("operation belongs to another Dot canvas")
            check_conversation(item)
            return self.host.observe(workspace_id=project_id,
                operation_id=request.get("target_operation_id"), as_owner=True)
        else:
            machine = next((m for m in inventory if m["machine_id"] == request.get("machine_id")), None)
            if machine is None:
                raise Denied("machine belongs to another Dot canvas")
            if request.get("work_item_id"):
                item = self.host.control.work_item_info(request["work_item_id"], self.host.owner)
                if item.get("assignee_agent_id") not in agents:
                    raise Denied("work belongs to another Dot canvas")
                check_conversation(item)
        result = self.machines.dispatch(project_id, nested_action,
            {"space_id": params["space_id"], **request}, request_key)
        if nested_action == "remote_viewer_open" and result.get("viewer_id"):
            with self.canvas._lock:
                self.viewers[result["viewer_id"]] = scope
                if len(self.viewers) > 512:
                    for ident in list(self.viewers)[:128]:
                        if not self.machines._tunnel or ident not in self.machines._tunnel.viewers:
                            self.viewers.pop(ident, None)
        return result
