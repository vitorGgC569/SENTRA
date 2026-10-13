"""Authenticated shell projections and scoped Guacamole viewer composition."""
import secrets
import threading
from contextlib import closing

from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import OperationRequest
from .store import Denied
from .shell_requests import ShellHostRequests

MACHINE_READS = frozenset({"machine_list", "input_status", "machine_observe"})
MACHINE_ACTIONS = MACHINE_READS | frozenset({"input_handoff", "remote_viewer_open",
    "remote_viewer_close", "machine_execute"})
_FIELDS = {
    "machine_list": set(),
    "input_status": {"machine_id", "work_item_id", "capability_id"},
    "input_handoff": {"machine_id", "work_item_id", "capability_id", "holder",
        "expected_epoch", "ttl_seconds", "arguments"},
    "remote_viewer_open": {"machine_id", "work_item_id", "capability_id", "session_id",
        "control_mode", "expected_epoch"},
    "remote_viewer_close": {"viewer_id"},
    "machine_execute": {"machine_id", "work_item_id", "capability_id", "arguments"},
    "machine_observe": {"target_operation_id"},
}


class ShellMachineServices:
    def __init__(self, canvas):
        self.canvas = canvas
        self.host = canvas._machine_service()
        self.requests = ShellHostRequests(self.host.control, self.host.owner)
        self._lock = threading.RLock()
        self._tunnel = self._listener = self._thread = None
        self._issued = {}  # Closed viewers remain scoped for idempotent close.

    def _scope(self, project_id, params, *, grant=False):
        self.canvas.store.workspace(project_id)
        machine = next((m for m in self.host.inventory(project_id)
            if m["machine_id"] == params.get("machine_id")), None)
        if machine is None:
            raise Denied("machine is outside the authenticated project")
        item = self.host.control.work_item_info(params.get("work_item_id"), self.host.owner)
        cap = params.get("capability_id")
        if cap is None:
            candidates = sorted(set(machine["capabilities"]) & set(item["required_capabilities"]))
            if len(candidates) != 1:
                raise ValueError("select an unambiguous WorkItem capability")
            cap = candidates[0]
        run = self.canvas._runtime().run(project_id)
        if (item["run_id"] != run["run_id"] or item.get("metadata", {}).get("workspace_id") != project_id
                or item.get("metadata", {}).get("machine_id") != machine["machine_id"]
                or item.get("assignee_agent_id") != machine["agent_id"]
                or cap not in machine["capabilities"] or cap not in item["required_capabilities"]):
            raise Denied("WorkItem/capability is outside the project machine scope")
        if grant:
            probe = OperationRequest("op-viewer-admission", machine["agent_id"], machine["machine_id"],
                cap, item["work_item_id"], "viewer-admission", {})
            policy = BoundWorkItemPolicy(owner=self.host.owner, principal_type="agent",
                authorization=self.host.control.authorization, governance=self.host.control.governance)
            if policy(probe).allowed is not True or item["state"] != "RUNNING" or run["state"] != "RUNNING":
                raise Denied("viewer requires a live WorkItem and its existing central grant")
        return machine, item, cap

    def dispatch(self, project_id, action, params, request_key):
        common = {"space_id", "conversation_id"}
        if action not in MACHINE_ACTIONS or set(params) - (_FIELDS[action] | common):
            raise ValueError("unsupported machine bridge fields")
        sid = params.get("space_id")
        if sid is not None:
            self.host.control.shell.get_space(sid, self.host.owner, project_id=project_id)
        if params.get("conversation_id") is not None:
            with closing(self.host.control.store.connect("shell")) as db:
                self.host.control.shell._entity(db, self.host.owner, project_id, "conversation",
                    params["conversation_id"], space_id=sid)
        action_params = {k: v for k, v in params.items() if k not in common}
        if action in MACHINE_READS:
            return self._dispatch(project_id, action, action_params, request_key)
        return self.requests.invoke(project_id, action, params, request_key,
            lambda: self._dispatch(project_id, action, action_params, request_key))

    def _dispatch(self, pid, action, p, key):
        if action == "machine_list":
            return {"machines": self.host.inventory(pid), "work_items": self.host.task_catalog(workspace_id=pid),
                "restore_errors": self.host.restore_errors}
        if action == "machine_observe":
            return self.host.observe(workspace_id=pid, operation_id=p["target_operation_id"], as_owner=True)
        if action == "input_status":
            return {**self.host.input_status(workspace_id=pid, **p), "machine_id": p["machine_id"]}
        if action == "remote_viewer_close":
            with self._lock:
                viewer_id = p["viewer_id"]
                if self._issued.get(viewer_id) != pid:
                    raise Denied("viewer is outside the authenticated project")
                # The retained project binding also permits a second close after
                # the tunnel removed an expired or disconnected ticket.
                return self._tunnel.revoke(viewer_id)
        if action == "input_handoff":
            if p.get("holder") == "agent":
                self._scope(pid, p, grant=True)
            receipt = self.host.input_handoff(workspace_id=pid, **p,
                operation_id=self.requests.operation_id(pid, key, action), request_key=key)
            fresh = self.host.input_status(workspace_id=pid, machine_id=p["machine_id"],
                work_item_id=p.get("work_item_id"), capability_id=p.get("capability_id"))
            return {**fresh, "machine_id": p["machine_id"], "request_key": key, "handoff_recorded": receipt.get("handoff_recorded", True),
                "grant_created": False}
        machine, item, cap = self._scope(pid, p, grant=action == "remote_viewer_open")
        oid = self.requests.operation_id(pid, key, action)
        if action == "machine_execute":
            arguments = p.get("arguments")
            if not isinstance(arguments, dict):
                raise ValueError("machine arguments must be an object")
            result = self.host.dispatch(workspace_id=pid, work_item_id=item["work_item_id"],
                machine_id=machine["machine_id"], capability_id=cap, operation_id=oid,
                arguments=arguments, idempotency_key=key)
            if machine["kind"] == "code-mode" and result.get("state") == "SUCCEEDED":
                value = self.host._factories[machine["machine_id"]].result(oid)
                if value is not None:
                    result = {**result, "value": value}
            return result
        if machine["kind"] != "guacamole":
            raise ValueError("viewer requires a configured Guacamole machine")
        mode = p.get("control_mode", "view")
        if mode not in {"view", "human"}:
            raise ValueError("viewer control_mode must be view or human")
        epoch = p.get("expected_epoch")
        status = self.host.input_status(workspace_id=pid, machine_id=machine["machine_id"],
            work_item_id=item["work_item_id"], capability_id=cap)
        if mode == "human" and (type(epoch) is not int or status.get("epoch") != epoch
                or status.get("holder") != "human" or status.get("live") is not True):
            raise Denied("human viewer requires live input possession at expected_epoch")
        if mode == "view" and epoch is not None:
            raise ValueError("view ticket cannot carry an input epoch")
        # A centrally authorized status call resolves the provider's exact
        # session scope. An arbitrary browser session ID cannot become a ticket.
        result = self.host.dispatch(workspace_id=pid, work_item_id=item["work_item_id"],
            machine_id=machine["machine_id"], capability_id=cap, operation_id=oid,
            arguments={"action": "status", "session_id": p.get("session_id")}, idempotency_key=key)
        if result.get("state") != "SUCCEEDED":
            return {"status": "uncertain", "operation_id": oid, "viewer_id": None,
                "receipt_id": result.get("receipt_id"), "reason": "provider session was not confirmed"}
        evidence = result.get("evidence") or {}
        if evidence.get("scope_verified") is not True or evidence.get("local_transport_connected") is not True:
            return {"status": "unavailable", "viewer_id": None, "operation_id": oid,
                "reason": "session requires an explicit authorized open or reattach"}
        input_channels = [c for c in evidence.get("allowed_input", []) if c in {"key", "mouse", "touch"}]
        if mode == "human" and (evidence.get("view_only") is not False or not input_channels):
            raise Denied("configured Guacamole session does not permit human input")
        with self._lock:
            tunnel = self._ensure_tunnel()
            issued = tunnel.issue(session_id=p["session_id"], machine_id=machine["machine_id"],
                principal_id=machine["agent_id"], capability_id=cap, work_item_id=item["work_item_id"],
                run_id=item["run_id"], workspace_id=pid, control_mode=mode,
                input_epoch=epoch, lifetime_seconds=30)
            self._issued[issued["viewer_id"]] = pid
            if len(self._issued) > 512:
                for old in list(self._issued)[:128]:
                    if old not in tunnel.viewers:
                        self._issued.pop(old, None)
        ws_url = issued.pop("url")
        return {**issued, "ws_url": ws_url, "machine_id": machine["machine_id"],
            "work_item_id": item["work_item_id"], "session_id": p["session_id"],
            "capability_id": cap, "project_id": pid, "grant_status": "granted",
            "input_channels": input_channels if mode == "human" else [],
            "operation_id": oid}

    def _ensure_tunnel(self):
        if self._tunnel is not None:
            return self._tunnel
        origins = tuple(getattr(self.canvas, "_shell_origins", ()))
        if not origins:
            raise RuntimeError("viewer requires the authenticated Canvas HTTP host")
        from sentra_executors.remote_guacamole_tunnel import GuacamoleTunnelServer
        tunnel = GuacamoleTunnelServer(dispatch=self._tunnel_dispatch, port=0,
            allowed_origins=origins, max_connection_seconds=300)
        listener = tunnel.serve()
        tunnel.port = listener.socket.getsockname()[1]
        thread = threading.Thread(target=listener.serve_forever, daemon=True, name="sentra-guacamole-viewer")
        self._tunnel, self._listener, self._thread = tunnel, listener, thread
        thread.start()
        return tunnel

    def _tunnel_dispatch(self, ticket, arguments):
        p = {"machine_id": ticket.machine_id, "work_item_id": ticket.work_item_id,
             "capability_id": ticket.capability_id}
        machine, item, cap = self._scope(ticket.workspace_id, p, grant=True)
        if machine["agent_id"] != ticket.principal_id or item["run_id"] != ticket.run_id:
            raise Denied("viewer ticket authority changed")
        # Socket packets never select principal, workspace, WorkItem or epoch.
        human = arguments.get("action") == "write" and arguments.get("opcode") in {"key", "mouse", "touch"}
        key = "viewer-" + secrets.token_hex(20)
        values = dict(workspace_id=ticket.workspace_id, work_item_id=ticket.work_item_id,
            machine_id=ticket.machine_id, capability_id=ticket.capability_id,
            operation_id="op-" + key, arguments=arguments, idempotency_key=key)
        if human:
            if ticket.control_mode != "human":
                raise Denied("readonly viewer cannot send input")
            return self.host.dispatch_human(**values, expected_epoch=ticket.input_epoch)
        return self.host.dispatch(**values)

    def close(self):
        with self._lock:
            if self._tunnel is None:
                return
            self._tunnel.revoke_all()
            self._listener.shutdown()
            thread = self._thread
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("viewer listener has not stopped")
