"""Fail-closed Dot retirement inventory and reversible, *local-only* archive receipts.

A shell projection is not a ChatGPT archive receipt, a VM deletion receipt, or
revocation of central authority. Pause and resume hold the whole canvas family
and write one receipt per request. Archive and restore cover every family
member so a child is not left active under an archived root. A deletion
request records the family and stops: it does not remove a Dot, conversation,
Grant, VM or VDI. Physical deletion waits for a separate user approval.

Remote archive is verified only from a provider attestation. This module does
not call the provider and does not accept a local receipt, a web binding, or
a caller-supplied dict as that attestation. Without it, the projection stays
explicitly not archived on the provider.
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


def _provider_archive_is_attested(provider_receipt):
    """True only for a receipt a provider adapter has already attested.

    No adapter is connected. Booleans, strings, local receipt ids, web
    conversation rows and caller-supplied dicts are not provider proof, so
    this returns false for every value this process can construct.
    """
    if provider_receipt is None or isinstance(provider_receipt, (bool, int, float, str, dict, list, tuple)):
        return False
    return False


def remote_archive_projection(provider_receipt=None):
    """Explicit remote-archive state.

    Verified would require a provider attestation this module can check.
    No provider archive adapter is connected, so a caller-supplied receipt
    is rejected and the projection stays not archived. This does not mark
    the remote conversation as verified.
    """
    if _provider_archive_is_attested(provider_receipt):
        raise RuntimeError("provider archive attestation is not wired in this process")
    return {"archive_scope": "local_projection_only", "remote_archive_verified": False,
        "remote_archived": False, "remote_archive_state": "not_archived",
        "provider_archive_receipt": None, "claims_remote_archived": False}


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
            db.execute("""CREATE TABLE IF NOT EXISTS shell_dot_family_jobs(
                owner TEXT NOT NULL, project_id TEXT NOT NULL, request_key TEXT NOT NULL,
                space_id TEXT NOT NULL, root_dot_id TEXT NOT NULL, action TEXT NOT NULL,
                intent_hash TEXT NOT NULL, state TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(owner,project_id,request_key))""")
            db.execute("""CREATE TABLE IF NOT EXISTS shell_dot_family_steps(
                owner TEXT NOT NULL, project_id TEXT NOT NULL, request_key TEXT NOT NULL,
                ordinal INTEGER NOT NULL, member_dot_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                kind TEXT NOT NULL, prior_desired_state TEXT NOT NULL,
                state TEXT NOT NULL, receipt_id TEXT, updated_at REAL NOT NULL,
                PRIMARY KEY(owner,project_id,request_key,ordinal))""")
            db.execute("""CREATE TABLE IF NOT EXISTS shell_dot_family_members(
                owner TEXT NOT NULL, project_id TEXT NOT NULL, space_id TEXT NOT NULL,
                root_dot_id TEXT NOT NULL, member_dot_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                phase TEXT NOT NULL, prior_desired_state TEXT NOT NULL,
                receipt_id TEXT NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(owner,project_id,space_id,member_dot_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS shell_dot_family_requests(
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
        phase = self.family_phase(project_id, space_id, dot["dot_id"])
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
            "operations": sorted((op["operation_id"], op["state"]) for op in operations),
            "lifecycle_phase": phase})
        return {"status": "blocked", "removed": False, "project_id": project_id,
            "space_id": space_id, "dot_id": dot["dot_id"], "name": dot["name"],
            "resources": resources, "blockers": blockers, "archived_local": archived,
            "lifecycle_phase": phase, "family_dot_ids": sorted(dot_ids),
            "archive_ready": not archive_blockers, "archive_blockers": archive_blockers,
            "authority_close_ready": not authority_close_blockers,
            "authority_close_blockers": authority_close_blockers,
            **remote_archive_projection(),
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
        family_ids = [member["dot_id"] for member in self._family(project_id, space_id, dot)]
        now = time.time()
        receipt = "dot-local-" + _fingerprint([self.owner, project_id, request_key])[:32]
        result = {"status": "archived_local" if state else "restored_local",
            "dot_id": dot["dot_id"], "space_id": space_id, "project_id": project_id,
            "receipt_id": receipt, "archived_local": state,
            **remote_archive_projection(),
            "effects": ["local_archive_projection"], "retained": True,
            "family_dot_ids": family_ids, "orphans_created": [],
            "physical_effect_performed": False, "dot_deleted": False,
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
            for member_id in family_ids:
                db.execute("INSERT INTO shell_dot_local_archives VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(owner,project_id,space_id,dot_id) DO UPDATE SET "
                    "archived=excluded.archived,receipt_id=excluded.receipt_id,updated_at=excluded.updated_at",
                    (self.owner, project_id, space_id, member_id, int(state), receipt, now))
            holders = ",".join("?" for _ in family_ids)
            rows = db.execute(
                f"SELECT dot_id,archived FROM shell_dot_local_archives WHERE owner=? "
                f"AND project_id=? AND space_id=? AND dot_id IN ({holders})",
                (self.owner, project_id, space_id, *family_ids)).fetchall()
            found = {row["dot_id"]: bool(row["archived"]) for row in rows}
            if set(found) != set(family_ids) or any(found[member_id] is not state for member_id in family_ids):
                raise Denied("family archive did not cover every member")
            db.execute("INSERT INTO shell_dot_archive_requests VALUES(?,?,?,?,?)",
                (self.owner, project_id, request_key, intent, _encode(result)))
        return result

    def _require_key(self, request_key):
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 200:
            raise ValueError("durable request_key required")

    def _family(self, project_id, space_id, dot):
        graph = dot_graph(self.canvas, project_id, dot["dot_id"], space_id)
        members, seen = [], set()
        for item in graph["dots"]:
            if item["dot_id"] in seen:
                continue
            if not item.get("agent_id"):
                raise Denied("Dot family member has no agent")
            seen.add(item["dot_id"])
            members.append({"dot_id": item["dot_id"], "agent_id": item["agent_id"]})
        if dot["dot_id"] not in seen:
            raise Denied("Dot is outside its canvas family")
        if len({member["agent_id"] for member in members}) != len(members):
            raise Denied("family shares an agent identity")
        agent_ids = {member["agent_id"] for member in members}
        with closing(self.control.store.connect("shell")) as db:
            rows = db.execute("SELECT body FROM shell_entities WHERE owner=? AND project_id=? AND kind='dot'",
                (self.owner, project_id)).fetchall()
        for row in rows:
            item = _decode(row["body"])
            if item.get("agent_id") in agent_ids and item.get("dot_id") not in seen:
                raise Denied("agent belongs to another Dot/root")
        members.sort(key=lambda member: (member["dot_id"] != dot["dot_id"], member["dot_id"]))
        return members

    def family_phase(self, project_id, space_id, root_dot_id):
        with closing(self.control.store.connect("shell")) as db:
            open_job = db.execute(
                "SELECT 1 FROM shell_dot_family_jobs WHERE owner=? AND project_id=? "
                "AND space_id=? AND root_dot_id=? AND state IN ('running','uncertain') LIMIT 1",
                (self.owner, project_id, space_id, root_dot_id)).fetchone()
            rows = db.execute(
                "SELECT phase FROM shell_dot_family_members WHERE owner=? AND project_id=? "
                "AND space_id=? AND root_dot_id=?",
                (self.owner, project_id, space_id, root_dot_id)).fetchall()
        if open_job:
            return "uncertain"
        phases = {row["phase"] for row in rows}
        if not phases or phases == {"active"}:
            return "active"
        if phases == {"paused"}:
            return "paused"
        return "mixed"

    def _job(self, db, project_id, request_key):
        return db.execute("SELECT * FROM shell_dot_family_jobs WHERE owner=? AND project_id=? AND request_key=?",
            (self.owner, project_id, request_key)).fetchone()

    def _family_projection(self, db, row):
        steps = db.execute(
            "SELECT ordinal,kind,member_dot_id,agent_id,state,receipt_id FROM shell_dot_family_steps "
            "WHERE owner=? AND project_id=? AND request_key=? ORDER BY ordinal",
            (self.owner, row["project_id"], row["request_key"])).fetchall()
        succeeded = row["state"] == "succeeded"
        status = {"pause_family": "paused", "resume_family": "resumed"}.get(row["action"], row["state"])
        return {"status": status if succeeded else "uncertain", "action": row["action"],
            "state": row["state"], "project_id": row["project_id"], "space_id": row["space_id"],
            "dot_id": row["root_dot_id"], "request_key": row["request_key"],
            "automatic_retry": False, "effects_replayed": 0, "effects_executed": 0,
            "receipt_id": "dot-family-" + _fingerprint(
                [self.owner, row["project_id"], row["request_key"]])[:32] if succeeded else None,
            "steps": [dict(step) for step in steps],
            "family_dot_ids": [step["member_dot_id"] for step in steps],
            "orphans_created": [], "physical_effect_performed": False,
            "dot_deleted": False, "vm_deleted": False, "conversations_deleted": False,
            "grants_revoked": False, "work_items_cancelled": False}

    def family_status(self, project_id, space_id, dot, request_key):
        self._require_key(request_key)
        with closing(self.control.store.connect("shell")) as db:
            row = self._job(db, project_id, request_key)
            if not row or row["root_dot_id"] != dot["dot_id"] or row["space_id"] != space_id:
                raise Denied("family journal does not belong to this Dot")
            return self._family_projection(db, row)

    def _prepared_family(self, project_id, space_id, dot):
        prepared = []
        allowed = {"AVAILABLE", "ACTIVE", "WAITING", "SUSPECTED_STALL", "RECOVERING", "ORPHANED", "DEAD"}
        for member in self._family(project_id, space_id, dot):
            desired = self.control.durable.agent_info(member["agent_id"], self.owner)["desired_state"]
            if desired not in allowed:
                raise Denied("agent desired state is not a durable SENTRA state")
            with closing(self.control.store.connect("shell")) as db:
                held = db.execute(
                    "SELECT root_dot_id,phase FROM shell_dot_family_members WHERE owner=? "
                    "AND project_id=? AND space_id=? AND member_dot_id=?",
                    (self.owner, project_id, space_id, member["dot_id"])).fetchone()
            if held and held["root_dot_id"] != dot["dot_id"] and held["phase"] == "paused":
                raise Denied("family member is paused under another root")
            prepared.append({**member, "prior": desired})
        return prepared

    def _paused_members(self, project_id, space_id, dot):
        with closing(self.control.store.connect("shell")) as db:
            rows = db.execute(
                "SELECT member_dot_id,agent_id,prior_desired_state FROM shell_dot_family_members "
                "WHERE owner=? AND project_id=? AND space_id=? AND root_dot_id=? AND phase='paused'",
                (self.owner, project_id, space_id, dot["dot_id"])).fetchall()
        members = [{"dot_id": row["member_dot_id"], "agent_id": row["agent_id"],
            "prior": row["prior_desired_state"]} for row in rows]
        members.sort(key=lambda member: (member["dot_id"] != dot["dot_id"], member["dot_id"]))
        return members

    def pause_family(self, project_id, space_id, dot, params, request_key):
        return self._family_effect("pause_family", "hold_agent", project_id, space_id, dot, params, request_key)

    def resume_family(self, project_id, space_id, dot, params, request_key):
        return self._family_effect("resume_family", "release_hold", project_id, space_id, dot, params, request_key)

    def _family_effect(self, action, kind, project_id, space_id, dot, params, request_key):
        self._require_key(request_key)
        if params.get("confirm_name") != dot["name"]:
            raise Denied("type the exact Dot name to confirm the family hold")
        intent = _fingerprint([action, space_id, dot["dot_id"], params.get("confirm_name")])
        with closing(self.control.store.connect("shell")) as db:
            existing = self._job(db, project_id, request_key)
            if existing:
                if existing["intent_hash"] != intent or existing["root_dot_id"] != dot["dot_id"]:
                    raise Denied("family request_key belongs to a different intention")
                return self._family_projection(db, existing)
        if self.archived(project_id, space_id).get(dot["dot_id"]):
            raise Denied("archived Dot must be restored before pause or resume")
        phase = self.family_phase(project_id, space_id, dot["dot_id"])
        if phase == "uncertain":
            raise Denied("family lifecycle journal is uncertain; reconcile it before another effect")
        if action == "pause_family" and phase == "paused":
            raise Denied("Dot family is already paused")
        if action == "resume_family" and phase != "paused":
            raise Denied("Dot family is not paused")
        if action == "pause_family":
            members = self._prepared_family(project_id, space_id, dot)
            again = [member["dot_id"] for member in self._family(project_id, space_id, dot)]
            if again != [member["dot_id"] for member in members]:
                raise Denied("family changed while preparing the pause")
        else:
            members = self._paused_members(project_id, space_id, dot)
            live = self._family(project_id, space_id, dot)
            if {member["dot_id"] for member in members} != {member["dot_id"] for member in live}:
                raise Denied("family changed since pause; reconcile before resume")
            if {member["agent_id"] for member in members} != {member["agent_id"] for member in live}:
                raise Denied("family agents changed since pause; reconcile before resume")
        now = time.time()
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = self._job(db, project_id, request_key)
            if existing:
                if existing["intent_hash"] != intent or existing["root_dot_id"] != dot["dot_id"]:
                    raise Denied("family request_key belongs to a different intention")
                return self._family_projection(db, existing)
            open_job = db.execute(
                "SELECT request_key FROM shell_dot_family_jobs WHERE owner=? AND project_id=? "
                "AND space_id=? AND root_dot_id=? AND state IN ('running','uncertain') LIMIT 1",
                (self.owner, project_id, space_id, dot["dot_id"])).fetchone()
            if open_job:
                raise Denied("a family journal is already open; reconcile it")
            db.execute("INSERT INTO shell_dot_family_jobs VALUES(?,?,?,?,?,?,?,?,?,?)",
                (self.owner, project_id, request_key, space_id, dot["dot_id"], action,
                 intent, "running", now, now))
            for ordinal, member in enumerate(members):
                db.execute("INSERT INTO shell_dot_family_steps VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (self.owner, project_id, request_key, ordinal, member["dot_id"], member["agent_id"],
                     kind, member["prior"], "pending", None, now))
        for ordinal, member in enumerate(members):
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "UPDATE shell_dot_family_steps SET state='claimed',updated_at=? "
                    "WHERE owner=? AND project_id=? AND request_key=? AND ordinal=? AND state='pending'",
                    (time.time(), self.owner, project_id, request_key, ordinal))
            try:
                self._apply_family(kind, member["agent_id"], member["prior"])
                if not self._observed_family(kind, member["agent_id"], member["prior"]):
                    raise RuntimeError("postcondition_not_attested")
            except Exception:
                self._mark_family_uncertain(project_id, request_key, ordinal)
                return self.family_status(project_id, space_id, dot, request_key)
            self._confirm_family_step(project_id, space_id, dot["dot_id"], request_key, ordinal, kind, member)
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("UPDATE shell_dot_family_jobs SET state='succeeded',updated_at=? "
                "WHERE owner=? AND project_id=? AND request_key=? AND state='running'",
                (time.time(), self.owner, project_id, request_key))
        return self.family_status(project_id, space_id, dot, request_key)

    def _apply_family(self, kind, agent_id, prior):
        current = self.control.durable.agent_info(agent_id, self.owner)["desired_state"]
        if kind == "hold_agent":
            if current != "WAITING":
                self.control.durable.update_agent(agent_id, self.owner, desired_state="WAITING",
                    event_type="DOT_FAMILY_PAUSE")
            return
        if kind == "release_hold":
            if prior == "WAITING" or current == prior:
                return
            if current != "WAITING":
                raise RuntimeError("desired_state_diverged")
            self.control.durable.update_agent(agent_id, self.owner, desired_state=prior,
                event_type="DOT_FAMILY_RESUME")
            return
        raise RuntimeError("unknown family step")

    def _observed_family(self, kind, agent_id, prior):
        current = self.control.durable.agent_info(agent_id, self.owner)["desired_state"]
        if kind == "hold_agent":
            return current == "WAITING"
        if kind == "release_hold":
            return current == ("WAITING" if prior == "WAITING" else prior)
        return False

    def _mark_family_uncertain(self, project_id, request_key, ordinal):
        now = time.time()
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("UPDATE shell_dot_family_steps SET state='uncertain',updated_at=? "
                "WHERE owner=? AND project_id=? AND request_key=? AND ordinal=?",
                (now, self.owner, project_id, request_key, ordinal))
            db.execute("UPDATE shell_dot_family_jobs SET state='uncertain',updated_at=? "
                "WHERE owner=? AND project_id=? AND request_key=?",
                (now, self.owner, project_id, request_key))

    def _confirm_family_step(self, project_id, space_id, root_dot_id, request_key, ordinal, kind, member):
        receipt = "dot-family-step-" + _fingerprint(
            [self.owner, project_id, request_key, ordinal, kind, member["dot_id"]])[:32]
        phase = "paused" if kind == "hold_agent" else "active"
        now = time.time()
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("UPDATE shell_dot_family_steps SET state='confirmed',receipt_id=?,updated_at=? "
                "WHERE owner=? AND project_id=? AND request_key=? AND ordinal=? "
                "AND state IN ('claimed','uncertain')",
                (receipt, now, self.owner, project_id, request_key, ordinal))
            db.execute("INSERT INTO shell_dot_family_members VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(owner,project_id,space_id,member_dot_id) DO UPDATE SET "
                "root_dot_id=excluded.root_dot_id,agent_id=excluded.agent_id,phase=excluded.phase,"
                "prior_desired_state=excluded.prior_desired_state,receipt_id=excluded.receipt_id,"
                "updated_at=excluded.updated_at",
                (self.owner, project_id, space_id, root_dot_id, member["dot_id"], member["agent_id"],
                 phase, member["prior"], receipt, now))

    def reconcile_family(self, project_id, space_id, dot, request_key):
        """Observe claimed holds. Pending steps are not executed."""
        self._require_key(request_key)
        with closing(self.control.store.connect("shell")) as db:
            job = self._job(db, project_id, request_key)
            if not job or job["root_dot_id"] != dot["dot_id"] or job["space_id"] != space_id:
                raise Denied("family journal does not belong to this Dot")
            steps = db.execute(
                "SELECT * FROM shell_dot_family_steps WHERE owner=? AND project_id=? AND request_key=? "
                "ORDER BY ordinal", (self.owner, project_id, request_key)).fetchall()
        for row in steps:
            if row["state"] not in {"claimed", "uncertain"}:
                continue
            member = {"dot_id": row["member_dot_id"], "agent_id": row["agent_id"],
                "prior": row["prior_desired_state"]}
            if not self._observed_family(row["kind"], row["agent_id"], row["prior_desired_state"]):
                if row["state"] == "claimed":
                    self._mark_family_uncertain(project_id, request_key, row["ordinal"])
                continue
            self._confirm_family_step(project_id, space_id, dot["dot_id"], request_key,
                row["ordinal"], row["kind"], member)
        with closing(self.control.store.connect("shell")) as db, db:
            states = [item["state"] for item in db.execute(
                "SELECT state FROM shell_dot_family_steps WHERE owner=? AND project_id=? AND request_key=?",
                (self.owner, project_id, request_key))]
            if states and all(state == "confirmed" for state in states):
                db.execute("UPDATE shell_dot_family_jobs SET state='succeeded',updated_at=? "
                    "WHERE owner=? AND project_id=? AND request_key=? AND state IN ('running','uncertain')",
                    (time.time(), self.owner, project_id, request_key))
        return self.family_status(project_id, space_id, dot, request_key)

    def request_deletion(self, project_id, space_id, dot, params, request_key):
        """Record a deletion request and perform no physical or central effect."""
        self._require_key(request_key)
        if params.get("confirm_name") != dot["name"] or params.get("confirm_phrase") != "EXCLUIR DOT":
            raise Denied("explicit human confirmation of this Dot required")
        intent = _fingerprint(["delete_request", space_id, dot["dot_id"], dot["name"]])
        with closing(self.control.store.connect("shell")) as db:
            previous = db.execute(
                "SELECT intent_hash,result FROM shell_dot_family_requests WHERE owner=? "
                "AND project_id=? AND request_key=?",
                (self.owner, project_id, request_key)).fetchone()
        if previous:
            if previous["intent_hash"] != intent:
                raise Denied("deletion request_key belongs to a different intention")
            return _decode(previous["result"])
        report = self.preflight(project_id, space_id, dot)
        family_ids = list(report["family_dot_ids"])
        result = {"status": "deletion_blocked_pending_user_approval",
            "project_id": project_id, "space_id": space_id, "dot_id": dot["dot_id"],
            "request_key": request_key, "awaiting_user_approval": True,
            "automatic_retry": False, "effects_executed": 0, "removed": False,
            "physical_effect_performed": False, "dot_deleted": False, "vm_deleted": False,
            "conversations_deleted": False, "grants_revoked": False,
            "work_items_cancelled": False, "retained": True,
            "family_dot_ids": family_ids,
            "would_orphan_if_root_removed_alone": [member_id for member_id in family_ids
                if member_id != dot["dot_id"]],
            "orphans_created": [], "resources_retained": report["resources"],
            "lifecycle_phase": report["lifecycle_phase"],
            **remote_archive_projection(),
            "receipt_id": "dot-delete-request-" + _fingerprint(
                [self.owner, project_id, request_key])[:32],
            "created_at": time.time()}
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT intent_hash,result FROM shell_dot_family_requests WHERE owner=? "
                "AND project_id=? AND request_key=?",
                (self.owner, project_id, request_key)).fetchone()
            if previous:
                if previous["intent_hash"] != intent:
                    raise Denied("deletion request_key belongs to a different intention")
                return _decode(previous["result"])
            db.execute("INSERT INTO shell_dot_family_requests VALUES(?,?,?,?,?)",
                (self.owner, project_id, request_key, intent, _encode(result)))
        return result
