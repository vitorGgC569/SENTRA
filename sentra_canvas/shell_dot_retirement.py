"""Fail-closed Dot retirement inventory and reversible, *local-only* archive receipts.

A shell projection is not a ChatGPT archive receipt, a VM deletion receipt, or
revocation of central authority. Do not add physical cleanup here without a
provider-attested, journalled retirement protocol.
"""
from contextlib import closing
import hashlib
import json
import time

from sentra_core.conversations import _decode, _encode
from .shell_dot_canvas import dot_graph
from .shell_dot_vm import VmStore
from .store import Denied


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


class DotRetirement:
    def __init__(self, canvas, control, owner):
        self.canvas, self.control, self.owner = canvas, control, owner
        with closing(control.store.connect("shell")) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS shell_dot_local_archives(
                owner TEXT NOT NULL, project_id TEXT NOT NULL, space_id TEXT NOT NULL,
                dot_id TEXT NOT NULL, archived INTEGER NOT NULL, receipt_id TEXT NOT NULL,
                updated_at REAL NOT NULL, PRIMARY KEY(owner,project_id,space_id,dot_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS shell_dot_archive_requests(
                owner TEXT NOT NULL, project_id TEXT NOT NULL, request_key TEXT NOT NULL,
                intent_hash TEXT NOT NULL, result TEXT NOT NULL,
                PRIMARY KEY(owner,project_id,request_key))""")

    def archived(self, project_id, space_id):
        with closing(self.control.store.connect("shell")) as db:
            rows = db.execute("SELECT dot_id,archived FROM shell_dot_local_archives "
                "WHERE owner=? AND project_id=? AND space_id=?",
                (self.owner, project_id, space_id)).fetchall()
        return {row["dot_id"]: bool(row["archived"]) for row in rows}

    def preflight(self, project_id, space_id, dot):
        graph = dot_graph(self.canvas, project_id, dot["dot_id"], space_id)
        dot_ids = {d["dot_id"] for d in graph["dots"]}
        agent_ids = {d["agent_id"] for d in graph["dots"]}
        with closing(self.control.store.connect("shell")) as db:
            rows = db.execute("SELECT body FROM shell_entities WHERE owner=? AND project_id=? "
                "AND space_id=? AND kind='conversation'", (self.owner, project_id, space_id)).fetchall()
            conversations = [c for c in (_decode(r["body"]) for r in rows) if c.get("dot_id") in dot_ids]
            conversation_ids = {c["conversation_id"] for c in conversations}
            remote = db.execute("SELECT conversation_id FROM canvas_shell_web_conversations "
                "WHERE owner=? AND project_id=?", (self.owner, project_id)).fetchall()
            remote_ids = {r["conversation_id"] for r in remote} & conversation_ids
            bindings = db.execute("SELECT conversation_id FROM canvas_shell_provider_bindings "
                "WHERE owner=? AND project_id=?", (self.owner, project_id)).fetchall()
            bound = {r["conversation_id"] for r in bindings} & conversation_ids
            queue = db.execute("SELECT conversation_id,state FROM canvas_shell_queue "
                "WHERE owner=? AND project_id=?", (self.owner, project_id)).fetchall()
            active_queue = [r for r in queue if r["conversation_id"] in conversation_ids
                and r["state"] in {"queued", "running", "uncertain"}]
        work = []
        # Central WorkItems are paginated: never silently omit a later page.
        offset = 0
        run_id = dot["run_id"]
        while True:
            page = self.control.list_work_items(self.owner, run_id=run_id, limit=1000, offset=offset)
            for item in page["items"]:
                metadata = item.get("metadata") or {}
                if item.get("assignee_agent_id") in agent_ids or (
                        metadata.get("workspace_id") == project_id and
                        (metadata.get("conversation_id") in conversation_ids or
                         metadata.get("root_dot_id") == dot["dot_id"])):
                    work.append(item)
            offset = page["page"]["next_offset"]
            if offset is None:
                break
        active_work = [w for w in work if not w.get("terminal", False)]
        grant_ids = set()
        for agent_id in agent_ids:
            grants = self.control.authorization.list_grants(self.owner, principal_type="agent",
                principal_id=agent_id)["items"]
            grant_ids.update(g["grant_id"] for g in grants)
        operations = []
        op_offset = 0
        work_ids = {item["work_item_id"] for item in work}
        while True:
            page = self.control.durable.list_operations(run_id, self.owner,
                offset=op_offset, limit=1000)
            operations.extend(op for op in page["items"] if
                op.get("principal_id") in agent_ids or op.get("work_item_id") in work_ids)
            op_offset = page["page"]["next_offset"]
            if op_offset is None:
                break
        unsettled_operations = [op for op in operations if
            not op.get("terminal") or op.get("state") == "UNCERTAIN"]
        agents = [self.control.durable.agent_info(aid, self.owner) for aid in sorted(agent_ids)]
        vm = VmStore(self.control, self.owner).get(project_id, dot["dot_id"])
        active_terminals = [t for t in graph["terminals"] if t.get("status") not in {"closed", "exited", "interrupted"}]
        graph_nodes = {n["id"] for n in graph["nodes"]}
        external_links = [link for link in self.canvas.graph_detail(project_id)["links"]
            if (link["source"] in graph_nodes) != (link["target"] in graph_nodes)]
        # Canvas tasks can reference the Dot even when no shell conversation exists.
        tasks = [task for task in self.canvas.store.list_resources("tasks", project_id)
            if task.get("agent_id") in agent_ids]
        pending_tasks = [task for task in tasks if task.get("status") not in
            {"done", "completed", "succeeded", "failed", "cancelled", "canceled"}]
        archived = self.archived(project_id, space_id).get(dot["dot_id"], False)
        resources = {"conversations": len(conversations), "canvas_dots": len(graph["dots"]),
            "canvas_links": len(graph["links"]), "canvas_terminals": len(graph["terminals"]),
            "vm_configured": bool(vm), "remote_conversations": len(remote_ids),
            "provider_bindings": len(bound), "pending_shell_turns": len(active_queue),
            "work_items": len(work), "active_work_items": len(active_work),
            "active_grants": len(grant_ids), "active_terminals": len(active_terminals),
            "external_links": len(external_links), "canvas_tasks": len(tasks),
            "pending_canvas_tasks": len(pending_tasks),
            "unsettled_operations": len(unsettled_operations)}
        blockers = []
        def block(kind, count, message):
            if count:
                blockers.append({"kind": kind, "count": count, "message": message})
        block("chatgpt_archive_confirmation", len(conversations),
            "Conversations are retained. No provider-attested ChatGPT archive primitive is implemented.")
        block("canvas_resources", len(graph["dots"]) - 1 + len(graph["links"]) + len(graph["terminals"]),
            "Canvas members, relationships and terminals require verified retirement.")
        block("external_links", len(external_links), "External graph relationships reference this Dot.")
        block("vm", int(bool(vm)), "VM reservation and VDI require exact-identity shutdown and retirement receipts.")
        block("work_items", len(work), "Central WorkItems must reach a verified terminal state.")
        block("grants", len(grant_ids), "Active Grants must be revoked with central receipts.")
        block("shell_turns", len(active_queue), "Queued, running or uncertain shell turns cannot be replayed.")
        block("canvas_tasks", len(tasks), "Canvas task history/references must be resolved.")
        block("unsettled_operations", len(unsettled_operations),
            "Central operations are still running or UNCERTAIN. Observe, never replay.")
        block("remote_conversations", len(remote_ids), "Remote ChatGPT conversations lack archive receipts.")
        block("provider_bindings", len(bound), "Provider bindings must be reconciled before retirement.")
        blockers.append({"kind": "dot_delete_unavailable", "count": 1,
            "message": "Permanent Dot deletion is disabled until full central/provider/VDI cleanup is provable."})
        # This is explicitly a UI-only archive; no Grants, live sessions or
        # provider data are changed, and the Dot remains addressable in the CP.
        archive_blockers = [item for item, n in (
            ("active_work_items", len(active_work)), ("active_grants", len(grant_ids)),
            ("active_terminals", len(active_terminals)), ("pending_shell_turns", len(active_queue)),
            ("pending_canvas_tasks", len(pending_tasks)), ("vm_configured", int(bool(vm))),
            ("unsettled_operations", len(unsettled_operations))) if n]
        authority_close_blockers = [item for item, n in (
            ("remote_conversations", len(remote_ids)), ("provider_bindings", len(bound)),
            ("pending_shell_turns", len(active_queue)), ("vm_configured", int(bool(vm))),
            ("pending_canvas_tasks", len(pending_tasks)),
            ("external_links", len(external_links)),
            ("unsettled_operations", len(unsettled_operations))) if n]
        snapshot = _fingerprint({"owner": self.owner, "project": project_id, "space": space_id,
            "dot": dot["dot_id"], "name": dot["name"], "archived": archived,
            "resources": resources, "dot_ids": sorted(dot_ids),
            "conversation_ids": sorted(conversation_ids),
            "work": sorted((w["work_item_id"], w["state"]) for w in work),
            "grant_ids": sorted(grant_ids),
            "agent_states": sorted((a["agent_id"], a["desired_state"]) for a in agents),
            "operations": sorted((op["operation_id"], op["state"]) for op in operations)})
        return {"status": "blocked", "removed": False, "project_id": project_id,
            "space_id": space_id, "dot_id": dot["dot_id"], "name": dot["name"],
            "resources": resources, "blockers": blockers, "archived_local": archived,
            "archive_ready": not archive_blockers, "archive_blockers": archive_blockers,
            "authority_close_ready": not authority_close_blockers,
            "authority_close_blockers": authority_close_blockers,
            "archive_scope": "local_projection_only", "remote_archive_verified": False,
            "snapshot": snapshot, "retention_policy": {
                "conversations": "retained", "messages": "retained", "grants": "unchanged",
                "work_items": "unchanged", "vm_and_vdi": "retained",
                "remote_chatgpt": "retained", "local_archive": "reversible"}}

    def mutate(self, project_id, space_id, dot, action, params, request_key):
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 200:
            raise ValueError("durable request_key required")
        if action not in {"dot_archive_local", "dot_restore_local"}:
            raise ValueError("unsupported Dot retirement action")
        intent = _fingerprint([action, space_id, dot["dot_id"], params])
        with closing(self.control.store.connect("shell")) as db:
            previous = db.execute("SELECT intent_hash,result FROM shell_dot_archive_requests "
                "WHERE owner=? AND project_id=? AND request_key=?",
                (self.owner, project_id, request_key)).fetchone()
        if previous:
            if previous["intent_hash"] != intent:
                raise Denied("archive request_key belongs to a different intention")
            return _decode(previous["result"])
        if action == "dot_archive_local":
            if params.get("confirm_name") != dot["name"]:
                raise Denied("type the exact Dot name to confirm local archival")
            preflight = self.preflight(project_id, space_id, dot)
            if params.get("snapshot") != preflight["snapshot"]:
                raise Denied("Dot resources changed; run the preflight again")
            if not preflight["archive_ready"]:
                raise Denied("Dot has active authority or live resources; cannot archive locally")
            state = True
        else:
            state = False
        now = time.time()
        receipt = "dot-local-" + _fingerprint([self.owner, project_id, request_key])[:32]
        result = {"status": "archived_local" if state else "restored_local",
            "dot_id": dot["dot_id"], "space_id": space_id, "project_id": project_id,
            "receipt_id": receipt, "archived_local": state, "remote_archive_verified": False,
            "effects": ["local_archive_projection"], "retained": True,
            "created_at": now}
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT intent_hash,result FROM shell_dot_archive_requests "
                "WHERE owner=? AND project_id=? AND request_key=?",
                (self.owner, project_id, request_key)).fetchone()
            if prior:
                if prior["intent_hash"] != intent:
                    raise Denied("archive request_key belongs to a different intention")
                return _decode(prior["result"])
            current = db.execute("SELECT archived FROM shell_dot_local_archives WHERE "
                "owner=? AND project_id=? AND space_id=? AND dot_id=?",
                (self.owner, project_id, space_id, dot["dot_id"])).fetchone()
            if current is not None and bool(current["archived"]):
                if state:
                    raise Denied("Dot is already archived locally; reconcile its existing receipt")
            elif not state:
                raise Denied("Dot is not archived locally")
            db.execute("INSERT INTO shell_dot_local_archives VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(owner,project_id,space_id,dot_id) DO UPDATE SET "
                "archived=excluded.archived,receipt_id=excluded.receipt_id,updated_at=excluded.updated_at",
                (self.owner, project_id, space_id, dot["dot_id"], int(state), receipt, now))
            db.execute("INSERT INTO shell_dot_archive_requests VALUES(?,?,?,?,?)",
                (self.owner, project_id, request_key, intent, _encode(result)))
        return result
