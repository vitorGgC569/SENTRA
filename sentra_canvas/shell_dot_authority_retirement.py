"""Owner-approved closure of Dot authority with per-effect durable receipts.

Never archives provider conversations or erases VM/VDI. Each external
ControlPlane mutation is CLAIMED *before* execution. Interrupted claims may
only be reconciled by observation; they are never automatically re-issued.
"""
from contextlib import closing
import hashlib
import json
import time

from sentra_core.conversations import _decode, _encode
from .shell_dot_canvas import dot_graph
from .store import Denied


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class DotAuthorityRetirement:
    def __init__(self, retirement):
        self.retirement = retirement
        self.canvas, self.control, self.owner = retirement.canvas, retirement.control, retirement.owner
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS shell_dot_authority_jobs(
                owner TEXT NOT NULL, project_id TEXT NOT NULL, request_key TEXT NOT NULL,
                space_id TEXT NOT NULL, dot_id TEXT NOT NULL, intent_hash TEXT NOT NULL,
                state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(owner,project_id,request_key))""")
            db.execute("""CREATE INDEX IF NOT EXISTS shell_dot_authority_target
                ON shell_dot_authority_jobs(owner,project_id,space_id,dot_id)""")
            db.execute("""CREATE TABLE IF NOT EXISTS shell_dot_authority_steps(
                owner TEXT NOT NULL, project_id TEXT NOT NULL, request_key TEXT NOT NULL,
                ordinal INTEGER NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL,
                state TEXT NOT NULL, receipt_id TEXT, updated_at REAL NOT NULL,
                PRIMARY KEY(owner,project_id,request_key,ordinal))""")

    def _job(self, db, project_id, request_key):
        return db.execute("SELECT * FROM shell_dot_authority_jobs WHERE owner=? "
            "AND project_id=? AND request_key=?", (self.owner, project_id, request_key)).fetchone()

    def _projection(self, db, row):
        steps = db.execute("SELECT ordinal,kind,state,receipt_id FROM shell_dot_authority_steps "
            "WHERE owner=? AND project_id=? AND request_key=? ORDER BY ordinal",
            (self.owner, row["project_id"], row["request_key"])).fetchall()
        return {"status": "authority_closed" if row["state"] == "succeeded" else "uncertain",
            "state": row["state"], "project_id": row["project_id"], "space_id": row["space_id"],
            "dot_id": row["dot_id"], "request_key": row["request_key"],
            "automatic_retry": False,
            "receipt_id": "dot-authority-" + _digest([self.owner, row["project_id"], row["request_key"]])[:32]
                if row["state"] == "succeeded" else None,
            "steps": [dict(s) for s in steps],
            "remote_archive_verified": False, "vm_deleted": False, "dot_deleted": False}

    def status(self, project_id, space_id, dot, request_key=None):
        with closing(self.control.store.connect("shell")) as db:
            if request_key is not None:
                row = self._job(db, project_id, request_key)
                if row and (row["dot_id"] != dot["dot_id"] or row["space_id"] != space_id):
                    raise Denied("request key belongs to another Dot")
            else:
                row = db.execute("SELECT * FROM shell_dot_authority_jobs WHERE "
                    "owner=? AND project_id=? AND space_id=? AND dot_id=? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (self.owner, project_id, space_id, dot["dot_id"])).fetchone()
            return self._projection(db, row) if row else {
                "status": "not_started", "project_id": project_id, "space_id": space_id,
                "dot_id": dot["dot_id"], "automatic_retry": False}

    def _inventory(self, project_id, space_id, dot):
        graph = dot_graph(self.canvas, project_id, dot["dot_id"], space_id)
        agent_ids = {item["agent_id"] for item in graph["dots"]}
        # A Dot principal must not share an agent identity with another root.
        with closing(self.control.store.connect("shell")) as db:
            rows = db.execute("SELECT body FROM shell_entities WHERE owner=? AND "
                "project_id=? AND kind='dot'", (self.owner, project_id)).fetchall()
        for row in rows:
            item = _decode(row["body"])
            if item["agent_id"] in agent_ids and item["dot_id"] not in {
                    d["dot_id"] for d in graph["dots"]}:
                raise Denied("agent belongs to another Dot/root")
        agents = [self.control.durable.agent_info(aid, self.owner) for aid in sorted(agent_ids)]
        work = []
        offset = 0
        conversation_ids = set()
        with closing(self.control.store.connect("shell")) as db:
            rows = db.execute("SELECT body FROM shell_entities WHERE owner=? AND "
                "project_id=? AND space_id=? AND kind='conversation'",
                (self.owner, project_id, space_id)).fetchall()
            conversation_ids = {item["conversation_id"] for item in (
                _decode(r["body"]) for r in rows) if item.get("dot_id") in {
                    d["dot_id"] for d in graph["dots"]}}
        while True:
            page = self.control.list_work_items(self.owner, run_id=dot["run_id"],
                limit=1000, offset=offset)
            for item in page["items"]:
                meta = item.get("metadata") or {}
                if item.get("assignee_agent_id") in agent_ids or (
                        meta.get("workspace_id") == project_id and
                        (meta.get("conversation_id") in conversation_ids or
                         meta.get("root_dot_id") == dot["dot_id"])):
                    work.append(item)
            offset = page["page"]["next_offset"]
            if offset is None:
                break
        grants = []
        for agent in agents:
            grants += self.control.authorization.list_grants(self.owner,
                principal_type="agent", principal_id=agent["agent_id"])["items"]
        # Ensure each target is scoped to this one actual Dot's identities.
        if any(item.get("assignee_agent_id") not in agent_ids
                for item in work if not item["terminal"]):
            raise Denied("shared WorkItem cannot be cancelled by a Dot retirement")
        terminals = sorted(graph["terminals"], key=lambda t: t["id"])
        all_agents = self.canvas.store.list_resources("agents", project_id)
        for terminal in terminals:
            users = {agent["id"] for agent in all_agents
                if agent.get("terminal_id") == terminal["id"]}
            if not users or not users <= agent_ids:
                raise Denied("terminal is shared with a foreign Dot or has no owner")
        return agents, work, grants, terminals

    def close(self, project_id, space_id, dot, params, request_key):
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 200:
            raise ValueError("durable request key required")
        intent = _digest([space_id, dot["dot_id"], params])
        with closing(self.control.store.connect("shell")) as db:
            old = self._job(db, project_id, request_key)
            if old:
                if old["intent_hash"] != intent or old["dot_id"] != dot["dot_id"]:
                    raise Denied("request key belongs to another retirement intention")
                return self._projection(db, old)  # NEVER repeat effects
        if params.get("confirm_name") != dot["name"] or params.get("confirm_phrase") != "ENCERRAR AUTORIZACOES":
            raise Denied("explicit human confirmation of this Dot required")
        report = self.retirement.preflight(project_id, space_id, dot)
        if params.get("snapshot") != report["snapshot"]:
            raise Denied("Dot changed since preflight; obtain a fresh snapshot")
        if not report["authority_close_ready"]:
            raise Denied("provider, VM, active terminal or unresolved operation prevents authority closure")
        agents, work, grants, terminals = self._inventory(project_id, space_id, dot)
        # Recheck the complete central/provider snapshot after resolving targets;
        # never broaden a human-approved plan to freshly admitted authority.
        reread = self.retirement.preflight(project_id, space_id, dot)
        if reread["snapshot"] != report["snapshot"] or not reread["authority_close_ready"]:
            raise Denied("authority changed while building the retirement plan")
        effects = ([("close_terminal", terminal["id"]) for terminal in terminals
            if terminal["status"] != "closed"] +
            [("pause_agent", agent["agent_id"]) for agent in agents
            if agent["desired_state"] != "WAITING"] +
            [("revoke_grant", g["grant_id"]) for g in sorted(grants, key=lambda g: g["grant_id"])] +
            [("cancel_work", w["work_item_id"]) for w in sorted(work, key=lambda w: w["work_item_id"])
             if not w["terminal"]])
        now = time.time()
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = self._job(db, project_id, request_key)
            if old:
                if old["intent_hash"] != intent:
                    raise Denied("request key belongs to another retirement intention")
                return self._projection(db, old)
            prior = db.execute("SELECT request_key FROM shell_dot_authority_jobs "
                "WHERE owner=? AND project_id=? AND space_id=? AND dot_id=? LIMIT 1",
                (self.owner, project_id, space_id, dot["dot_id"])).fetchone()
            if prior:
                raise Denied("a retirement journal already owns this Dot; reconcile it")
            db.execute("INSERT INTO shell_dot_authority_jobs VALUES(?,?,?,?,?,?,?, ?,?)",
                (self.owner, project_id, request_key, space_id, dot["dot_id"],
                 intent, "running", now, now))
            for n, (kind, target) in enumerate(effects):
                db.execute("INSERT INTO shell_dot_authority_steps VALUES(?,?,?,?,?,?,?,?,?)",
                    (self.owner, project_id, request_key, n, kind, target, "pending", None, now))
        for n, (kind, target) in enumerate(effects):
            # Each step is durably claimed before any central mutation.
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("UPDATE shell_dot_authority_steps SET state='claimed',updated_at=? "
                    "WHERE owner=? AND project_id=? AND request_key=? AND ordinal=? AND state='pending'",
                    (time.time(), self.owner, project_id, request_key, n))
            try:
                self._apply(project_id, kind, target)
                if not self._observed(project_id, kind, target):
                    raise RuntimeError("postcondition_not_attested")
            except BaseException:
                with closing(self.control.store.connect("shell")) as db, db:
                    db.execute("UPDATE shell_dot_authority_steps SET state='uncertain',updated_at=? "
                        "WHERE owner=? AND project_id=? AND request_key=? AND ordinal=?",
                        (time.time(), self.owner, project_id, request_key, n))
                    db.execute("UPDATE shell_dot_authority_jobs SET state='uncertain',updated_at=? "
                        "WHERE owner=? AND project_id=? AND request_key=?",
                        (time.time(), self.owner, project_id, request_key))
                return self.status(project_id, space_id, dot, request_key)
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("UPDATE shell_dot_authority_steps SET state='confirmed',receipt_id=?,updated_at=? "
                    "WHERE owner=? AND project_id=? AND request_key=? AND ordinal=?",
                    ("authority-step-" + _digest([self.owner, project_id, request_key, n, kind, target])[:32],
                     time.time(), self.owner, project_id, request_key, n))
        final = self.retirement.preflight(project_id, space_id, dot)
        residual = any(final["resources"].get(key, 0) for key in (
            "active_grants", "active_work_items", "active_terminals",
            "pending_shell_turns", "unsettled_operations", "pending_canvas_tasks",
            "remote_conversations", "provider_bindings", "vm_configured"))
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("UPDATE shell_dot_authority_jobs SET state=?,updated_at=? "
                "WHERE owner=? AND project_id=? AND request_key=?",
                ("uncertain" if residual else "succeeded", time.time(),
                 self.owner, project_id, request_key))
        return self.status(project_id, space_id, dot, request_key)

    def _apply(self, project_id, kind, target):
        if kind == "close_terminal":
            self.canvas.terminal_close(project_id, target)
        elif kind == "pause_agent":
            self.control.durable.update_agent(target, self.owner, desired_state="WAITING",
                event_type="DOT_RETIREMENT_HOLD")
        elif kind == "revoke_grant":
            self.control.authorization_revoke(target, self.owner)
        elif kind == "cancel_work":
            self.control.transition_work_item(target, self.owner, "CANCELLED",
                reason="Explicit owner-approved Dot retirement")
        else:
            raise RuntimeError("unknown retirement step")

    def _observed(self, project_id, kind, target):
        if kind == "close_terminal":
            return self.canvas.store.resource("terminals", target, project_id)["status"] == "closed"
        if kind == "pause_agent":
            return self.control.durable.agent_info(target, self.owner)["desired_state"] == "WAITING"
        if kind == "revoke_grant":
            return bool(self.control.authorization.info(target, self.owner)["revoked"])
        if kind == "cancel_work":
            return self.control.work_item_info(target, self.owner)["state"] == "CANCELLED"
        return False

    def reconcile(self, project_id, space_id, dot, request_key):
        """Read-only authority observations; no effect ever replayed."""
        with closing(self.control.store.connect("shell")) as db:
            job = self._job(db, project_id, request_key)
            if not job or job["dot_id"] != dot["dot_id"] or job["space_id"] != space_id:
                raise Denied("retirement journal does not belong to this Dot")
            steps = db.execute("SELECT * FROM shell_dot_authority_steps WHERE owner=? "
                "AND project_id=? AND request_key=? ORDER BY ordinal",
                (self.owner, project_id, request_key)).fetchall()
        # Never skip a pending effect by assuming it ran. Only claimed or
        # uncertain effects are eligible for observation of completed state.
        for row in steps:
            if row["state"] not in {"claimed", "uncertain"}:
                continue
            if not self._observed(project_id, row["kind"], row["target"]):
                continue
            receipt = "authority-step-" + _digest([self.owner, project_id,
                request_key, row["ordinal"], row["kind"], row["target"]])[:32]
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("UPDATE shell_dot_authority_steps SET state='confirmed',"
                    "receipt_id=?,updated_at=? WHERE owner=? AND project_id=? "
                    "AND request_key=? AND ordinal=? AND state IN ('claimed','uncertain')",
                    (receipt, time.time(), self.owner, project_id, request_key, row["ordinal"]))
        with closing(self.control.store.connect("shell")) as db, db:
            states = [r["state"] for r in db.execute(
                "SELECT state FROM shell_dot_authority_steps WHERE owner=? "
                "AND project_id=? AND request_key=?", (self.owner, project_id, request_key))]
            if states and all(state == "confirmed" for state in states):
                # All originally claimed effects were observed; don't infer
                # closure if *new* authority was granted in the meantime.
                report = self.retirement.preflight(project_id, space_id, dot)
                residual = any(report["resources"].get(key, 0) for key in (
                    "active_grants", "active_work_items", "active_terminals",
                    "pending_shell_turns", "unsettled_operations", "pending_canvas_tasks",
                    "remote_conversations", "provider_bindings", "vm_configured"))
                if not residual:
                    db.execute("UPDATE shell_dot_authority_jobs SET state='succeeded',updated_at=? "
                        "WHERE owner=? AND project_id=? AND request_key=?",
                        (time.time(), self.owner, project_id, request_key))
        return self.status(project_id, space_id, dot, request_key)
