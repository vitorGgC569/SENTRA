"""Live shell-turn capabilities for the CLI, distinct from the owner bearer."""
from contextlib import closing
import json
import secrets
import time

from sentra_core.conversations import _decode
from sentra_runtime.effect_boundary import current_effect_context
from .store import Denied

_GUEST_SECRET_KEYS = frozenset({"password", "guest_password"})


def _redact_guest_secret(value, secret):
    """Drop a Dot VM password from a dispatch result. Never log the secret."""
    if not isinstance(secret, str) or secret == "":
        return value
    if isinstance(value, str):
        return value.replace(secret, "")
    if isinstance(value, dict):
        return {
            key: _redact_guest_secret(item, secret)
            for key, item in value.items()
            if key not in _GUEST_SECRET_KEYS
        }
    if isinstance(value, list):
        return [_redact_guest_secret(item, secret) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_guest_secret(item, secret) for item in value)
    return value


def _vm_input_identity(arguments):
    """Identity of one VM click or key chord. A different chord is a different effect."""
    action = arguments.get("action") if isinstance(arguments, dict) else None
    if action=='input.tap':
        if set(arguments)!={'action','x','y'} or any(type(arguments.get(k)) is not int for k in ('x','y')):return None
        return 'mouse',f"tap:{arguments['x']}:{arguments['y']}",None
    if action == "input.mouse":
        x, y, buttons = arguments.get("x"), arguments.get("y"), arguments.get("buttons")
        wheel = arguments.get("wheel", 0)
        if type(x) is not int or type(y) is not int or type(buttons) is not int or type(wheel) is not int:
            return None
        selector = f"mouse:{x}:{y}:{buttons}:{wheel}"
        if len(selector) > 200:
            return None
        return "mouse", selector, None
    if action == "input.bios_dvd":
        if set(arguments) != {"action"}:
            return None
        return "keyboard", "vm-bios-dvd-shortcut", "ctrl-alt-del-then-space"
    if action == "input.key":
        scans = arguments.get("scancodes")
        if (not isinstance(scans, list) or not scans or len(scans) > 32
                or any(type(item) is not int or not 0 <= item <= 255 for item in scans)):
            return None
        return "keyboard", "vm-scancodes", json.dumps(scans, separators=(",", ":"))
    return None


def _scrub_guest_secret(exc, secret):
    if not isinstance(secret, str) or secret == "":
        return
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if current.args:
            current.args = tuple(
                arg.replace(secret, "") if isinstance(arg, str) else arg
                for arg in current.args
            )
        current = current.__cause__ or current.__context__


class ShellActorService:
    def __init__(self, runtime):
        self.runtime, self.canvas, self.control = runtime, runtime.canvas, runtime.control
        self.owner = runtime.owner
        self.records = {}

    def register(self, message, dot, *, deadline):
        token = secrets.token_urlsafe(36)
        record = {"message": dict(message), "dot": dict(dot), "deadline": deadline,
            "epoch": secrets.token_hex(16)}
        with self.canvas._lock:
            if self.canvas._closing:
                raise Denied("Canvas is shutting down")
            self.records[token] = record
            self.canvas._agent_tokens[token] = (message["project_id"], "shell:" + message["operation_id"])
        return token

    def revoke(self, token):
        with self.canvas._lock:
            self.records.pop(token, None)
            self.canvas._agent_tokens.pop(token, None)

    def subject(self, token, payload):
        with self.canvas._lock:
            record = self.records.get(token)
            if record is None:
                raise Denied("unknown shell turn capability")
            message, dot = record["message"], record["dot"]
            pid, oid = message["project_id"], message["operation_id"]
            workspace = self.canvas.store.workspace(pid)
            process = self.runtime._processes.get(oid)
            if (payload.get("workspace") != workspace["path"] or time.monotonic() >= record["deadline"]
                    or self.canvas._agent_tokens.get(token) != (pid, "shell:" + oid)
                    or process is None or process.poll() is not None):
                raise Denied("shell capability is expired or outside the live project turn")
        work = self.control.work_item_info(message["work_item_id"], self.owner)
        from .shell_access import AccessStore
        if AccessStore(self.control, self.owner).profile(message['conversation_id']).get('delegation_revoked'):
            raise Denied('full-access delegation was revoked')
        operation = self.control.durable.operation_status(oid, self.owner)
        run = self.control.durable.run_status(message["run_id"], self.owner, include_details=False)
        agent = self.control.durable.agent_info(dot["agent_id"], self.owner)
        if (work["run_id"] != message["run_id"] or work["state"] != "RUNNING"
                or work["assignee_agent_id"] != dot["agent_id"]
                or work.get("metadata", {}).get("workspace_id") != pid
                or operation["run_id"] != message["run_id"] or operation["state"] not in {"STARTING", "RUNNING"}
                or run["state"] != "RUNNING" or agent["run_id"] != message["run_id"]
                or agent["desired_state"] == "WAITING"):
            raise Denied("shell turn authority was revoked, paused, or reassigned")
        with closing(self.control.store.connect("shell")) as db:
            binding = db.execute("SELECT * FROM canvas_shell_provider_bindings WHERE owner=? "
                "AND project_id=? AND conversation_id=?", (self.owner, pid, message["conversation_id"])).fetchone()
            queued = db.execute("SELECT protected_input FROM canvas_shell_queue WHERE operation_id=? AND owner=?",
                (oid, self.owner)).fetchone()
        if binding is None or queued is None or any(binding[field] != value for field, value in (
                ("run_id", message["run_id"]), ("work_item_id", message["work_item_id"]),
                ("operation_id", oid), ("agent_id", dot["agent_id"]), ("principal", self.canvas.store.principal))):
            raise Denied("shell capability no longer matches the current provider binding")
        original = _decode(queued["protected_input"])
        if original["message"] != message or original["dot"] != dot:
            raise Denied("shell capability differs from the protected original turn")
        return record

    def connected_agents(self, project_id, agent_id):
        from .shell_dot_canvas import dots_for_root
        with closing(self.control.store.connect("shell")) as db:
            rows = db.execute("SELECT body FROM shell_entities WHERE owner=? AND project_id=? AND kind='dot'",
                (self.owner, project_id)).fetchall()
        own = next((d for d in (_decode(row["body"]) for row in rows) if d["agent_id"] == agent_id), None)
        if own is None:
            return []
        _, members = dots_for_root(self.control, self.owner, project_id, own["dot_id"])
        allowed = {member["agent_id"] for member in members}
        graph = self.canvas.graph_detail(project_id)
        origins = {node["id"] for node in graph["nodes"]
            if node["kind"] == "agent" and node["resource_id"] == agent_id}
        targets = {link["target"] for link in graph["links"] if link["source"] in origins}
        return sorted({node["resource_id"] for node in graph["nodes"]
            if node["kind"] == "agent" and node["id"] in targets and node["resource_id"] in allowed})

    def _dots(self, message, *, include_self=True):
        agents = set(self.connected_agents(message["project_id"], self._agent(message)))
        if include_self:
            agents.add(self._agent(message))
        with closing(self.control.store.connect("shell")) as db:
            rows = db.execute("SELECT body FROM shell_entities WHERE owner=? AND project_id=? "
                "AND kind='dot' AND space_id=?", (self.owner, message["project_id"], message["space_id"])).fetchall()
        return [dot for dot in (_decode(row["body"]) for row in rows) if dot["agent_id"] in agents]

    def _agent(self, message):
        work = self.control.work_item_info(message["work_item_id"], self.owner)
        return work["assignee_agent_id"]

    def _resolve_dot(self, message, selector):
        graph = self.canvas.graph_detail(message["project_id"])
        nodes = {node["resource_id"]: node["id"] for node in graph["nodes"] if node["kind"] == "agent"}
        matches = [dot for dot in self._dots(message)
            if selector in {dot["dot_id"], dot["agent_id"], dot["name"], nodes.get(dot["agent_id"])}]
        if len(matches) != 1:
            raise Denied("unique directed Dot in the current Space required")
        return matches[0]

    def _intent(self, message, payload):
        action, value = payload["action"], payload.get("value", "")
        if action in {"coordinator_intent", "coordinate", "dot_tool_dispatch"}:
            if action == "dot_tool_dispatch":
                intent = payload.get("intent") if "intent" in payload else (json.loads(value) if value.strip().startswith("{") else dict(payload))
                if not isinstance(intent, dict):
                    raise ValueError("structured coordinator intent required")
                intent["kind"] = "dot_tool_dispatch"
                return intent
            intent = payload.get("intent") if "intent" in payload else json.loads(value)
            if not isinstance(intent, dict):
                raise ValueError("structured coordinator intent required")
            return intent
        if not isinstance(value, str) or len(value) > 4000:
            raise ValueError("bounded Canvas command value required")
        if action == "create_agent":
            if value.lstrip().startswith("{"):
                spec = json.loads(value)
                if not isinstance(spec, dict) or set(spec) - {"name", "model", "role", "brief"}:
                    raise ValueError("invalid structured Dot creation")
                return {"kind": "create_dot", "name": spec.get("name"), "model": spec.get("model"),
                    "role": spec.get("role", "worker"), "instructions": spec.get("brief") or ""}
            fields = value.split("|")
            if not 2 <= len(fields) <= 3:
                raise ValueError("creation requires name|model|optional role")
            return {"kind": "create_dot", "name": fields[0], "model": fields[1],
                "role": fields[2] if len(fields) == 3 else "worker"}
        own = next(dot for dot in self._dots(message) if dot["agent_id"] == self._agent(message))
        fields = value.split("|")
        if action == "connect":
            if len(fields) not in {1, 2}:
                raise ValueError("connect requires target or source|target")
            source = own if len(fields) == 1 else self._resolve_dot(message, fields[0].strip())
            target = self._resolve_dot(message, fields[-1].strip())
            return {"kind": "connect", "source_dot_id": source["dot_id"], "target_dot_id": target["dot_id"]}
        if action == "create_team":
            if len(fields) != 3:
                raise ValueError("create_team requires name|coordinator|workers")
            coordinator = self._resolve_dot(message, fields[1].strip())
            workers = [self._resolve_dot(message, field.strip())["dot_id"] for field in fields[2].split(",")]
            return {"kind": "create_team", "name": fields[0], "coordinator_dot_id": coordinator["dot_id"],
                "worker_dot_ids": workers}
        if action == "dispatch":
            target, separator, content = value.partition("|")
            if not separator:
                raise ValueError("dispatch requires target|message")
            return {"kind": "handoff", "source_dot_id": own["dot_id"],
                "target_dot_id": self._resolve_dot(message, target.strip())["dot_id"], "content": content}
        raise Denied("shell turns cannot invoke legacy terminal bootstrap or unfenced mutations")

    @staticmethod
    def _checkpoint():
        context = current_effect_context.get()
        if context is None:
            raise Denied("coordinator composition requires an active central fence")
        context.checkpoint()

    def _dot_vm_record(self, intent, authority):
        """Read the target Dot's VM row. Missing rows stay empty; no hypervisor call."""
        from .shell_dot_canvas import canvas_root
        from .shell_dot_vm import VmStore
        project_id = authority.get("project_id")
        dot_id = intent.get("target_dot_id") if isinstance(intent, dict) else None
        if not isinstance(project_id, str) or not project_id or not isinstance(dot_id, str) or not dot_id:
            return None
        space_id = authority.get("space_id")
        with closing(self.control.store.connect("shell")) as db:
            dot = self.control.shell._entity(
                db, self.owner, project_id, "dot", dot_id,
                space_id=space_id if isinstance(space_id, str) else None,
            )
        if not isinstance(dot, dict):
            return None
        root = canvas_root(dot)
        if not isinstance(root, str) or not root:
            return None
        return VmStore(self.control, self.owner).get(project_id, root)

    def _targets_another_canvas(self, intent, authority):
        """True only when both Dots load and they do not share a canvas root."""
        from .shell_dot_canvas import canvas_root
        project_id = authority.get("project_id") if isinstance(authority, dict) else None
        target_id = intent.get("target_dot_id") if isinstance(intent, dict) else None
        conversation_id = authority.get("conversation_id") if isinstance(authority, dict) else None
        if not all(isinstance(value, str) and value for value in (project_id, target_id, conversation_id)):
            return False
        space_id = authority.get("space_id") if isinstance(authority.get("space_id"), str) else None
        try:
            with closing(self.control.store.connect("shell")) as db:
                target = self.control.shell._entity(
                    db, self.owner, project_id, "dot", target_id, space_id=space_id)
                conversation = self.control.shell._entity(
                    db, self.owner, project_id, "conversation", conversation_id, space_id=space_id)
                owner_dot = self.control.shell._entity(
                    db, self.owner, project_id, "dot", conversation["dot_id"], space_id=space_id)
            return canvas_root(target) != canvas_root(owner_dot)
        except Exception:
            return False

    def _authority_with_dot_vm(self, intent, authority):
        """Place a Canvas tool on the Dot VM when the caller did not force the host.

        The model cannot choose placement. An explicit host authority stays on
        the host. A registered VM id selects the guest and blocks the turn when
        the registry is incomplete, instead of substituting a host process.
        """
        specified = authority.get("placement")
        if specified == "host":
            return authority
        if specified not in {None, "", "guest"}:
            return authority
        if self._targets_another_canvas(intent, authority):
            blocked = dict(authority)
            blocked["placement"] = "guest"
            for key in ("vm_id", "username", "password", "guest_password", "guest_executor",
                        "guest_workspace", "guest_process"):
                blocked.pop(key, None)
            return blocked
        record = self._dot_vm_record(intent, authority)
        vm_id = record.get("vm_id") if isinstance(record, dict) else None
        has_vm = isinstance(vm_id, str) and bool(vm_id.strip()) and "\0" not in vm_id and len(vm_id.strip()) <= 128
        if specified in {None, ""} and not has_vm:
            return authority
        enriched = dict(authority)
        enriched["placement"] = "guest"
        if not has_vm:
            return enriched
        vm_id = vm_id.strip()
        enriched["guest_process"] = {
            "vm_registry_bound": True,
            "vm_id": vm_id,
            "verified": False,
        }
        username = record.get("username")
        if not isinstance(username, str) or not username.strip() or "\0" in username:
            username = record.get("guest_username")
        password = record.get("password")
        if not isinstance(password, str) or password == "" or "\0" in password or "\n" in password or "\r" in password:
            password = record.get("guest_password")
        # An incomplete row cannot build a guest executor. Leave the three
        # absent so the dispatch stays blocked and the password is not forwarded.
        if not (isinstance(username, str) and username.strip() and "\0" not in username
                and isinstance(password, str) and password and "\0" not in password
                and "\n" not in password and "\r" not in password):
            enriched.pop("vm_id", None)
            enriched.pop("username", None)
            enriched.pop("password", None)
            enriched.pop("guest_password", None)
            enriched.pop("guest_executor", None)
            return enriched
        enriched["vm_id"] = vm_id
        enriched["username"] = username
        enriched["password"] = password
        family = record.get("os_family")
        if isinstance(family, str) and family.strip().lower() in {"linux", "windows"}:
            enriched["os_family"] = family.strip().lower()
        from .shell_dot_canvas import _imported_guest_workspace
        imported = _imported_guest_workspace(record, enriched.get("os_family") or "linux")
        if imported:
            enriched["guest_workspace"] = imported
        return enriched

    def compose(self, intent, authority):
        self._checkpoint()
        pid, sid, oid = authority["project_id"], authority["space_id"], authority["operation_id"]
        kind = intent["kind"]
        key = "coordinator-child:" + oid
        if kind == "create_dot":
            from .shell_dot_canvas import canvas_root
            with closing(self.control.store.connect("shell")) as db:
                conversation = self.control.shell._entity(db, self.owner, pid, "conversation",
                    authority["conversation_id"], space_id=sid)
                parent = self.control.shell._entity(db, self.owner, pid, "dot", conversation["dot_id"], space_id=sid)
            value = self.control.shell_dispatch(self.owner, project_id=pid, action="dot_create",
                payload={"space_id": sid, **{k: v for k, v in intent.items() if k != "kind"},
                    "canvas_root_dot_id": canvas_root(parent)}, request_key=key)["value"]
            self._checkpoint()
            source = self.runtime._node(pid, authority["agent_id"])
            target = self.runtime._node(pid, value["agent_id"])
            link = self.canvas.graph_link(pid, source["id"], target["id"])
            return {"status": "created", "dot": value, "link": link, "child_model_started": False}
        if kind in {"delegate", "handoff"}:
            target_dot_id = intent["dot_id"] if kind == "delegate" else intent["target_dot_id"]
            content = intent["objective"] if kind == "delegate" else intent["content"]
            conversation = self.control.shell_dispatch(self.owner, project_id=pid, action="conversation_create",
                payload={"space_id": sid, "dot_id": target_dot_id,
                    "parent_conversation_id": authority["conversation_id"]}, request_key=key + ":conversation")["value"]
            self._checkpoint()
            message = self.control.shell_dispatch(self.owner, project_id=pid, action="message_send",
                payload={"space_id": sid, "conversation_id": conversation["conversation_id"], "content": content},
                request_key=key + ":message")["value"]
            return {"status": "recorded", "child": message, "conversation": conversation,
                "child_model_started": False, "child_grant_required": True}
        if kind == "reassign":
            value = self.control.reassign_work_item(intent["work_item_id"], self.owner, agent_id=intent["agent_id"])
            return {"status": "applied", "result": value}
        if kind == "dot_tool_dispatch":
            from sentra_runtime.dot_tool_dispatch import compose_dot_tool_dispatch, retain_coordinator_turn
            from orchestrator.providers.fleet_admission import prepare_live_trio
            # Guest credentials come from the Dot VM registry, not from model intent.
            # The password is forwarded only to the dispatch and then stripped from
            # anything this turn returns or raises.
            dispatch_authority = self._authority_with_dot_vm(intent, authority)
            secret = None
            if dispatch_authority.get("placement") == "guest":
                candidate = dispatch_authority.get("password")
                if isinstance(candidate, str) and candidate:
                    secret = candidate
            guest_process = dispatch_authority.get("guest_process")
            if not isinstance(guest_process, dict):
                guest_process = authority.get("guest_process")
            try:
                dispatched = compose_dot_tool_dispatch(self.control, self.owner, intent, dispatch_authority)
                dispatched["trio_preparation"] = prepare_live_trio(
                    placement=dispatch_authority.get("placement") or "host",
                    guest_process=guest_process if isinstance(guest_process, dict) else None,
                    operation_id=authority.get("parent_operation_id"),
                )
                dispatched["retention"] = retain_coordinator_turn(
                    self.control, self.owner, project_id=pid,
                    coordinator_work_item_id=authority["work_item_id"],
                    journal_receipt=authority.get("journal_receipt"),
                    reviewer_agent_id=authority.get("agent_id"),
                )
            except Exception as exc:
                _scrub_guest_secret(exc, secret)
                raise
            return _redact_guest_secret(dispatched, secret)
        if kind in {"consolidate_dispatches", "consolidate_tool_dispatches"}:
            from sentra_runtime.dot_tool_dispatch import consolidate_tool_dispatches
            return consolidate_tool_dispatches(
                self.control, self.owner, pid, authority["work_item_id"],
                intent.get("child_work_item_ids", [])
            )
        from sentra_mcp.services.shell_coordinator import INTENT_FIELDS
        public = {field: intent[field] for field in INTENT_FIELDS[kind] if field in intent}
        value = self.control.shell_dispatch(self.owner, project_id=pid, action="coordinate",
            payload={"space_id": sid, "conversation_id": authority["conversation_id"], "intent": public},
            request_key=key)["value"]
        return {"status": value.get("status", "uncertain"), "result": value}

    def _eligible_child_conversations(self, message):
        """Return only direct child conversations for outgoing connected Dots."""
        from .shell_dot_canvas import dots_for_root
        own_dot = next(d for d in self._dots(message) if d["agent_id"] == self._agent(message))
        root, _ = dots_for_root(self.control, self.owner, message["project_id"], own_dot["dot_id"], message["space_id"])
        connected = {dot["agent_id"]: dot for dot in self._dots(message, include_self=False)}
        dots_by_id = {dot["dot_id"]: dot for dot in connected.values()}
        with closing(self.control.store.connect("shell")) as db:
            rows = db.execute("SELECT body FROM shell_entities WHERE owner=? AND project_id=? "
                "AND kind='conversation' AND space_id=?", (self.owner, message["project_id"], message["space_id"])).fetchall()
            conversations = [_decode(row["body"]) for row in rows]
        result = []
        for conversation in conversations:
            if conversation.get("parent_conversation_id") != message["conversation_id"]:
                continue
            child = dots_by_id.get(conversation.get("dot_id"))
            if child is None or (child.get("canvas_root_dot_id") or child["dot_id"]) != root:
                continue
            with closing(self.control.store.connect("shell")) as db:
                latest_user = db.execute("SELECT * FROM shell_messages WHERE owner=? AND project_id=? "
                    "AND space_id=? AND conversation_id=? AND role='user' "
                    "ORDER BY created_at DESC,message_id DESC LIMIT 1",
                    (self.owner, message["project_id"], message["space_id"], conversation["conversation_id"])).fetchone()
                latest_assistant = None
                if latest_user is not None:
                    latest_assistant = db.execute("SELECT * FROM shell_messages WHERE owner=? AND project_id=? "
                        "AND space_id=? AND conversation_id=? AND role='assistant' AND operation_id=? "
                        "ORDER BY created_at DESC,message_id DESC LIMIT 1",
                        (self.owner, message["project_id"], message["space_id"], conversation["conversation_id"],
                         latest_user["operation_id"])).fetchone()
            user_state = None
            if latest_user is not None:
                operation = self.control.durable.operation_status(latest_user["operation_id"], self.owner)
                user_state = {"message_id": latest_user["message_id"], "status": latest_user["status"],
                    "operation_id": latest_user["operation_id"], "operation_state": operation["state"],
                    "work_item_id": latest_user["work_item_id"]}
            reply = None if latest_assistant is None else {
                "message_id": latest_assistant["message_id"],
                "content": _decode(latest_assistant["protected_content"])[:32768],
                "status": latest_assistant["status"], "operation_id": latest_assistant["operation_id"]}
            result.append({"conversation_id": conversation["conversation_id"], "dot_id": child["dot_id"],
                "agent_id": child["agent_id"], "name": child["name"],
                "parent_conversation_id": message["conversation_id"], "latest_user": user_state,
                "latest_assistant": reply})
        return sorted(result, key=lambda item: (item["name"], item["conversation_id"]))

    def _reply_to_child(self, message, conversation_id, content, authority, target_agent_id):
        self._checkpoint()
        child = next((item for item in self._eligible_child_conversations(message)
            if item["conversation_id"] == conversation_id and item["agent_id"] == target_agent_id), None)
        if child is None:
            raise Denied("child conversation is outside this parent and its outgoing Dot connections")
        key = "child-reply:" + authority["operation_id"]
        value = self.control.shell_dispatch(self.owner, project_id=message["project_id"], action="message_send",
            payload={"space_id": message["space_id"], "conversation_id": conversation_id, "content": content},
            request_key=key)["value"]
        self._checkpoint()
        return {"status": "recorded", "child": value, "conversation_id": conversation_id,
            "child_grant_required": True, "grant_inherited": False}

    def _vm_action(self, token, payload, message, dot):
        from .shell_dot_vm import DotVmServices
        from .shell_access import AccessStore
        from sentra_runtime.authority_bridge import BoundWorkItemPolicy
        from sentra_runtime.contracts import OperationRequest
        with self.canvas._lock:
            if getattr(self.canvas, '_shell_dot_vm', None) is None:
                self.canvas._shell_dot_vm = DotVmServices(self.canvas)
            service = self.canvas._shell_dot_vm
        scope = {'dot_id': dot['dot_id'], 'space_id': message['space_id'],
                 'conversation_id': message['conversation_id']}
        if payload['action'] == 'vm_status':
            return service.dispatch(message['project_id'], 'dot_vm_status', scope)
        if payload['action'] in {'vm_frame', 'vm_input'}:
            configured = service.store.get(message['project_id'], dot['dot_id'])
            work = (configured or {}).get('work_items', {}).get(message['conversation_id'])
            if not configured or not work or configured['agent_id'] != dot['agent_id']:
                raise Denied('this Dot conversation has no configured VM WorkItem')
            # Never let model JSON select a machine, WorkItem, agent or VM ID.
            if payload['action'] == 'vm_frame':
                if payload.get('value', '').strip():
                    raise ValueError('frame observation takes no arguments')
                import uuid
                return service.host.dispatch(workspace_id=message['project_id'],
                    machine_id=configured['machine_id'], work_item_id=work,
                    capability_id='vm:observe', operation_id='vm-frame-' + uuid.uuid4().hex,
                    arguments={'action': 'frame'})
            from .shell_access import AccessStore
            # The exclusive VM has its own WorkItem/Grants. A host-file access
            # profile cannot confer or remove VM authority.
            key = payload.get('request_key')
            value = payload.get('value')
            if not isinstance(key, str) or not 1 <= len(key) <= 128 or not isinstance(value,str) or len(value) > 4000:
                raise ValueError('VM input requires bounded JSON and an original request identity')
            arguments = json.loads(value)
            if not isinstance(arguments, dict) or arguments.get('action') not in {'input.key','input.mouse'}:
                raise ValueError('only keyboard/mouse actions can be submitted to this Dot VM')
            import hashlib
            identity = hashlib.sha256((message['operation_id'] + '\x00' + key).encode()).hexdigest()
            fence_key = _vm_input_identity(arguments)
            from sentra_executors.input_control import InputControl
            vm_input = InputControl(self.control, owner=self.owner)
            if fence_key is None:
                return {
                    "state": "BLOCKED", "dispatched": False, "automatic_resend": False,
                    "reason": "VM input cannot be fenced, so it was not sent",
                }
            if fence_key is not None:
                kind, selector, text = fence_key
                prior = vm_input.uncertain_effect(
                    work_item_id=work, kind=kind, selector_key=selector, text=text)
                if prior is not None:
                    return {
                        "state": "UNCERTAIN", "dispatched": False, "automatic_resend": False,
                        "reason": "uncertain VM input is not sent again",
                        "fenced_by": prior["operation_id"],
                    }
            possession = service.host.input_status(workspace_id=message['project_id'],
                machine_id=configured['machine_id'], work_item_id=work, capability_id='vm:input')
            if possession.get('grant_status') != 'granted':
                return {'state': 'BLOCKED', 'reason': 'VM input grant is not active; no input was sent'}
            if possession.get('live'):
                if possession.get('holder') != 'agent' or possession.get('work_item_id') != work:
                    return {'state': 'BLOCKED', 'reason': 'VM control is held by a human or another conversation; no input was sent'}
            else:
                # An expired lease is acquired only for this current, granted
                # WorkItem. The central atomic guard also protects a human who
                # takes control between this status read and the acquisition.
                from sentra_runtime.executor import AuthorizationRequired
                try:
                    service.host.input_handoff(workspace_id=message['project_id'], machine_id=configured['machine_id'],
                        work_item_id=work, capability_id='vm:input', holder='agent',
                        expected_epoch=possession['epoch'], ttl_seconds=300,
                        operation_id='vm-lease-' + identity[:40], request_key='vm-lease-' + identity,
                        arguments=arguments, only_if_available=True)
                except (AuthorizationRequired, ValueError):
                    return {'state': 'BLOCKED', 'reason': 'VM control changed or permission was revoked; no input was sent'}
            result = service.host.dispatch(workspace_id=message['project_id'],
                machine_id=configured['machine_id'], work_item_id=work,
                capability_id='vm:input', operation_id='vm-input-' + identity[:40],
                idempotency_key='vm-input-' + identity, arguments=arguments)
            if isinstance(result, dict) and result.get("state") == "UNCERTAIN" and fence_key is not None:
                kind, selector, text = fence_key
                operation_id = result.get("operation_id")
                if isinstance(operation_id, str) and operation_id:
                    vm_input.note_uncertain(
                        work_item_id=work, kind=kind, selector_key=selector,
                        operation_id=operation_id, text=text)
                result = {**result, "automatic_resend": False}
            return result
        profile = AccessStore(self.control, self.owner).profile(message['conversation_id'])
        if profile.get('scope') != 'computer' or profile.get('approval') != 'never':
            raise Denied('select full access before asking the Dot to create its VM')
        policy = BoundWorkItemPolicy(owner=self.owner, principal_type='agent',
            authorization=self.control.authorization, governance=self.control.governance)
        probe = OperationRequest('vm-configure-probe', dot['agent_id'], profile.get('machine_id', ''),
            'computer:execute', profile.get('work_item_id', ''), 'vm-configure-probe', {})
        if not policy(probe).allowed:
            raise Denied('VM configuration requires the active full-access grant of this conversation')
        value = payload.get('value', '')
        if not isinstance(value, str) or len(value) > 4000:
            raise ValueError('bounded VM configuration JSON required')
        spec = json.loads(value)
        if not isinstance(spec, dict) or set(spec) - {'os_family', 'cpus', 'memory_mb', 'disk_gb', 'iso_path', 'username'}:
            raise ValueError('VM configuration may select only OS, CPU, RAM, disk and local ISO')
        key = payload.get('request_key')
        if not isinstance(key, str) or not 1 <= len(key) <= 128:
            raise ValueError('persistent VM request identity required')
        # Already registered physical VMs are observations, not an invitation
        # to create another VM or replay a previous uncertain provision.
        current = service.dispatch(message['project_id'], 'dot_vm_status', scope)
        vm = current.get('vm') or {}
        existing = vm.get('vm_state') in {'running','poweroff','paused','saved','aborted','stuck'}
        if existing and vm.get('conversation_authorized'):
            return {'status':'existing_vm','vm':vm,'new_vm_created':False,
                'automatic_retry':False, 'next_step':'vm_frame or vm_input'}
        configured = service.dispatch(message['project_id'], 'dot_vm_configure', {**scope, **spec},
            'vm-configure:' + key)
        if configured.get('status') == 'uncertain':
            return configured
        after = configured.get('vm') or {}
        if after.get('vm_state') in {'running','poweroff','paused','saved','aborted','stuck'}:
            return {'status':'existing_vm','vm':after,'new_vm_created':False,
                'automatic_retry':False,'next_step':'vm_frame or vm_input'}
        self.subject(token, payload)
        return service.dispatch(message['project_id'], 'dot_vm_execute',
            {**scope, 'arguments': {'action': 'provision'}}, 'vm-provision:' + key)

    def dispatch(self, token, payload):
        if not isinstance(payload, dict) or set(payload) - {"action", "workspace", "value", "request_key", "intent"}:
            raise Denied("shell actor envelope cannot select authority")
        record = self.subject(token, payload)
        message, dot = record["message"], record["dot"]
        action = payload["action"]
        if action == 'isolate_work':
            from .task_workspace import isolate
            return isolate(self,message,dot,payload)
        if action == 'review_worktrees':
            from .task_workspace import review
            spec=json.loads(payload.get('value',''))
            if not isinstance(spec,dict) or set(spec)!={'conversation_ids'}:raise ValueError('conversation_ids required')
            return review(self.canvas,message['project_id'],{**spec,'dot_id':dot['dot_id'],'space_id':message['space_id']},
                allowed_dot_ids={d['dot_id'] for d in self._dots(message)})
        if action == 'verify_result':
            from .task_verification import verify
            return verify(self,message,dot,payload)
        if action == "checkpoint":
            # subject() just checked the process, protected queue, current
            # binding and central Run/WorkItem/operation. ModelInvocationFence
            # independently checks the current model Grant; no authority cache.
            return {"shell_scope": self._scope(message, dot)}
        if action in {'vm_create', 'vm_status', 'vm_frame', 'vm_input'}:
            return self._vm_action(token, payload, message, dot)
        from .shell_dot_canvas import dot_graph
        graph = dot_graph(self.canvas, message["project_id"], dot["dot_id"], message["space_id"])
        origins = {node["id"] for node in graph["nodes"] if node["kind"] == "agent" and node["resource_id"] == dot["agent_id"]}
        if action == "context":
            from .shell_goals import goal_context
            from sentra_mcp.services.shell_coordinator import dot_manages_canvas
            context = self.canvas._working_context_snapshot(message["project_id"], {dot["agent_id"]}, origins, graph)
            from .shell_access import AccessStore
            access = AccessStore(self.control, self.owner).profile(message['conversation_id'])
            from .task_workspace import for_work_item
            execution_workspace=for_work_item(self.control,self.owner,message['work_item_id'],dot['agent_id'])
            machines = self.canvas._agent_machine_control(token, {'action': 'machine_list', 'workspace': payload['workspace']})
            return {**context, "conversation_access": access, "machine_catalog": machines,
                'execution_workspace':execution_workspace,'coding_isolation_available':True,
                "conversation_goal": goal_context(self.control, self.owner, message["conversation_id"]),
                "canvas_root_dot_id": graph["canvas_root_dot_id"], "shell_scope": self._scope(message, dot),
                "dots": [{key: d.get(key) for key in ("dot_id", "agent_id", "name", "role", "model")} for d in self._dots(message)],
                "coordination_requires_grant": True, "child_execution_requires_own_grant": True,
                "automatic_permission_management": access.get('mode')=='full',
                "result_verification_available": True,
                "automatic_coordination_available": dot_manages_canvas(dot)}
        if action == "list":
            return [{key: d.get(key) for key in ("dot_id", "agent_id", "name", "role", "model")}
                for d in self._dots(message, include_self=False)]
        if action == "note_read":
            targets = {link["target"] for link in graph["links"] if link["source"] in origins}
            targets |= {link["source"] for link in graph["links"] if link["target"] in origins}
            matches = [node for node in graph["nodes"] if node["kind"] == "note" and node["id"] in targets
                and payload.get("value", "").strip() in {node["id"], node["title"]}]
            if len(matches) != 1:
                raise Denied("unique directed note required")
            return {"id": matches[0]["id"], "body": matches[0]["body"], "access": "read_only"}
        if action == "children":
            return {"parent_conversation_id": message["conversation_id"],
                "items": self._eligible_child_conversations(message), "access": "read_only"}
        if action == "child_reply":
            try:
                request = json.loads(payload.get("value", ""))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("child reply requires JSON with conversation_id and content") from exc
            if (not isinstance(request, dict) or set(request) != {"conversation_id", "content"}
                    or not isinstance(request["conversation_id"], str)
                    or not isinstance(request["content"], str) or not 1 <= len(request["content"]) <= 100000):
                raise ValueError("child reply requires only a canonical conversation_id and bounded content")
            child = next((item for item in self._eligible_child_conversations(message)
                if item["conversation_id"] == request["conversation_id"]), None)
            if child is None:
                raise Denied("child conversation is outside this parent and its outgoing Dot connections")
            intent = {"kind": "handoff", "source_dot_id": dot["dot_id"],
                "target_dot_id": child["dot_id"], "content": request["content"]}
            return self.control.execute_coordinator_intent(self.owner, project_id=message["project_id"],
                conversation_id=message["conversation_id"], run_id=message["run_id"],
                work_item_id=message["work_item_id"], parent_operation_id=message["operation_id"],
                agent_id=dot["agent_id"], intent=intent, request_key=payload.get("request_key"),
                compose=lambda resolved, authority: self._reply_to_child(message, request["conversation_id"],
                    request["content"], authority, resolved["target_agent_id"]),
                process_alive=lambda: self._alive(token, payload), connected_agents=self.connected_agents)
        intent = self._intent(message, payload)
        return self.control.execute_coordinator_intent(self.owner, project_id=message["project_id"],
            conversation_id=message["conversation_id"], run_id=message["run_id"], work_item_id=message["work_item_id"],
            parent_operation_id=message["operation_id"], agent_id=dot["agent_id"], intent=intent,
            request_key=payload.get("request_key"), compose=self.compose,
            process_alive=lambda: self._alive(token, payload), connected_agents=self.connected_agents)

    def _alive(self, token, payload):
        try:
            self.subject(token, payload)
            return True
        except (PermissionError, FileNotFoundError):
            return False

    @staticmethod
    def _scope(message, dot):
        return {"project_id": message["project_id"], "space_id": message["space_id"],
            "conversation_id": message["conversation_id"], "dot_id": dot["dot_id"],
            "agent_id": dot["agent_id"], "run_id": message["run_id"],
            "work_item_id": message["work_item_id"], "parent_operation_id": message["operation_id"]}
