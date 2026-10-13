"""Explicit user controls over central Grants scoped to a canonical shell turn."""
from contextlib import closing
import hashlib
import json
import math
import time

from sentra_core.conversations import _decode
from sentra_runtime.coordinator_admission import COORDINATOR_CAPABILITIES
from .shell_requests import ShellHostRequests
from .store import Denied

TURN_PERMISSION_ACTIONS = frozenset({"turn_permission_list", "turn_permission_grant", "turn_permission_revoke"})
_FIELDS = {"space_id", "conversation_id", "work_item_id"}


class ShellTurnPermissions:
    def __init__(self, canvas):
        self.canvas = canvas
        self.control = canvas._shell_service()
        self.owner = canvas._runtime().owner
        self.requests = ShellHostRequests(self.control, self.owner)

    def _scope(self, project_id, params):
        self.canvas.store.workspace(project_id)
        sid, cid = params["space_id"], params["conversation_id"]
        self.control.shell.get_space(sid, self.owner, project_id=project_id)
        with closing(self.control.store.connect("shell")) as db:
            conversation = self.control.shell._entity(db, self.owner, project_id, "conversation", cid, space_id=sid)
            dot = self.control.shell._entity(db, self.owner, project_id, "dot", conversation["dot_id"], space_id=sid)
            wid = params.get("work_item_id")
            if wid is None:
                row = db.execute("SELECT work_item_id FROM shell_messages WHERE owner=? AND project_id=? "
                    "AND conversation_id=? AND role='user' ORDER BY created_at DESC,message_id DESC LIMIT 1",
                    (self.owner, project_id, cid)).fetchone()
                if row is None:
                    return dot, None, None
                wid = row["work_item_id"]
            message = db.execute("SELECT operation_id FROM shell_messages WHERE owner=? AND project_id=? "
                "AND space_id=? AND conversation_id=? AND work_item_id=? AND role='user'",
                (self.owner, project_id, sid, cid, wid)).fetchone()
        if message is None:
            raise Denied("WorkItem does not belong to the selected shell conversation")
        item = self.control.work_item_info(wid, self.owner)
        operation = self.control.durable.operation_status(message["operation_id"], self.owner)
        current = self.canvas._runtime().run(project_id)
        if (item["run_id"] != current["run_id"] or operation["run_id"] != item["run_id"]
                or item.get("metadata", {}).get("workspace_id") != project_id
                or item.get("metadata", {}).get("space_id") != sid or item["assignee_agent_id"] != dot["agent_id"]):
            raise Denied("shell turn was reassigned or is outside the current project Run")
        return dot, item, operation

    def _allowed(self, dot, item, operation):
        if item is None:
            return []
        allowed = set(item.get("required_capabilities", [])) & (
            set(COORDINATOR_CAPABILITIES.values()) | {"model:invoke", "web:send", "web:attach"})
        with closing(self.control.store.connect("shell")) as db:
            queued = db.execute("SELECT protected_input FROM canvas_shell_queue WHERE owner=? AND operation_id=?",
                (self.owner, operation["operation_id"])).fetchone()
        if queued is not None:
            message = _decode(queued["protected_input"])["message"]
            if message.get("coordinator_child"):
                allowed.add("model:invoke")
            if message.get("attachments"):
                allowed.update({"web:send", "web:attach"})
        from sentra_mcp.services.shell_coordinator import dot_manages_canvas
        if not dot_manages_canvas(dot):
            allowed -= set(COORDINATOR_CAPABILITIES.values())
        return sorted(allowed)

    def _view(self, pid, params):
        dot, item, operation = self._scope(pid, params)
        if item is None:
            return {"project_id": pid, "conversation_id": params["conversation_id"], "dot_id": dot["dot_id"],
                "work_item_id": None, "capabilities": [], "grant_created": False}
        grants = self.control.authorization.list_grants(self.owner, principal_type="agent", principal_id=dot["agent_id"])["items"]
        capabilities = []
        for cap in self._allowed(dot, item, operation):
            provider = "canvas-coordinator" if cap.startswith("canvas.coordinator.") else "chatgpt" if cap.startswith("web:") else "shell-model"
            decision = self.control.authorization.authorize(self.owner, principal_type="agent", principal_id=dot["agent_id"],
                capability=cap, scope_type="work_item", scope_id=item["work_item_id"],
                context={"provider": provider, "actual_cost": 0.0 if provider == "canvas-coordinator" else float("inf")}, local_owner=False)
            scoped = [g for g in grants if g["scope_type"] == "work_item" and g.get("scope_id") == item["work_item_id"]
                and g["capability"] == cap and not g["revoked"]]
            capabilities.append({"capability": cap, "allowed": decision["allowed"],
                "source": decision.get("source"), "has_turn_grant": bool(scoped)})
        return {"project_id": pid, "space_id": params["space_id"], "conversation_id": params["conversation_id"],
            "dot_id": dot["dot_id"], "agent_id": dot["agent_id"], "work_item_id": item["work_item_id"],
            "operation_id": operation["operation_id"], "work_item_state": item["state"], "operation_state": operation["state"],
            "capabilities": capabilities, "grant_created": False}

    def dispatch(self, pid, action, params, key):
        if action not in TURN_PERMISSION_ACTIONS or set(params) - (_FIELDS | (
                {"capabilities", "ttl_seconds"} if action == "turn_permission_grant" else
                {"capabilities"} if action == "turn_permission_revoke" else set())):
            raise ValueError("unsupported turn permission fields")
        if not {"space_id", "conversation_id"} <= params.keys():
            raise ValueError("canonical Space/conversation required")
        if action == "turn_permission_list":
            return self._view(pid, params)
        if not params.get("work_item_id"):
            raise ValueError("mutating turn permissions require an explicit WorkItem")
        capabilities = params.get("capabilities")
        if (not isinstance(capabilities, list) or not 1 <= len(capabilities) <= 16
                or any(not isinstance(c, str) for c in capabilities) or len(set(capabilities)) != len(capabilities)):
            raise ValueError("distinct exact turn capabilities required")
        ttl = params.get("ttl_seconds", 300)
        if type(ttl) not in {int, float} or not math.isfinite(ttl) or not 1 <= ttl <= 3600:
            raise ValueError("turn Grant lifetime must be 1..3600 seconds")
        def mutate():
            dot, item, operation = self._scope(pid, params)
            if item is None or not set(capabilities) <= set(self._allowed(dot, item, operation)):
                raise Denied("requested capabilities are outside this declared shell turn")
            if action == "turn_permission_grant":
                if item["state"] not in {"PENDING", "QUEUED", "BLOCKED", "RUNNING"} or operation["state"] not in {"QUEUED", "STARTING", "RUNNING", "WAITING_EXTERNAL"}:
                    raise Denied("cannot grant execution authority to a terminal or uncertain turn")
            oid = self.requests.operation_id(pid, key, action)
            work = self.control.create_work_item(item["run_id"], self.owner,
                work_item_id="permission-" + oid, objective="Shell turn permission change",
                assignee_user_id=self.canvas.store.principal,
                metadata={"workspace_id": pid, "space_id": params["space_id"],
                    "target_work_item_id": item["work_item_id"], "shell_action": action, "request_key": key},
                execution_policy={"require_quality_gate": False})
            audit = self.control.durable.create_operation(item["run_id"], self.owner,
                kind="shell.turn_permission", operation_id=oid, idempotency_key=oid, cleanup_policy="manual")
            self.control.durable.update_operation(audit["operation_id"], self.owner, state="RUNNING",
                event_type="SHELL_TURN_PERMISSION_ADMITTED", progress={"work_item_id": work["work_item_id"],
                    "principal_id": self.canvas.store.principal, "target_work_item_id": item["work_item_id"]})
            if action == "turn_permission_grant":
                for cap in capabilities:
                    self.control.authorization_grant(self.owner, principal_type="agent", principal_id=dot["agent_id"],
                        capability=cap, scope_type="work_item", scope_id=item["work_item_id"], ttl_s=ttl)
            else:
                grants = self.control.authorization.list_grants(self.owner, principal_type="agent", principal_id=dot["agent_id"])["items"]
                for grant in grants:
                    if grant["scope_type"] == "work_item" and grant.get("scope_id") == item["work_item_id"] and grant["capability"] in capabilities and not grant["revoked"]:
                        self.control.authorization.revoke(grant["grant_id"], self.owner)
            receipt = "turn-permission:" + oid
            proof = {"operation_id": oid, "target_work_item_id": item["work_item_id"],
                "capabilities": capabilities, "action": action}
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("INSERT INTO shell_receipts VALUES(?,?,?,?,?,?,?,?)",
                    (receipt, self.owner, pid, key, oid, "control_mutation",
                        hashlib.sha256(json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), time.time()))
            self.control.durable.update_operation(oid, self.owner, state="SUCCEEDED",
                event_type="SHELL_TURN_PERMISSION_COMMITTED", result={"receipt_id": receipt,
                    "capabilities": capabilities, "target_work_item_id": item["work_item_id"],
                    "control_mutation_only": True, "external_completion_claimed": False})
            self.control.governance.complete_control_mutation(work["work_item_id"], self.owner, receipt_id=receipt)
            return {**self._view(pid, params), "permission_change_recorded": True,
                "grant_created": action == "turn_permission_grant", "automatic_retry": False,
                "permission_operation_id": oid, "permission_work_item_id": work["work_item_id"],
                "permission_operation_state": "SUCCEEDED", "receipt_id": receipt,
                "control_mutation_only": True, "external_completion_claimed": False}
        return self.requests.invoke(pid, action, params, key, mutate)
