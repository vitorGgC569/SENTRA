"""Spaces, Dots and conversations projected from the existing Control Plane.

No prose is interpreted as authority. A durable request claim precedes every
runtime call; an interrupted claim is reconciled, never silently replayed.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from typing import Any

from sentra_core.conversations import _encode, _decode


class ShellConflict(RuntimeError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _text(value, name, maximum=128, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > maximum or "\x00" in value:
        raise ValueError("invalid " + name)
    return value.strip()


def _id(value, name):
    result = _text(value, name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", result):
        raise ValueError("invalid " + name)
    return result


READS = frozenset({"home", "space_list", "space_get", "dot_list", "conversation_list", "message_list", "message_content", "events"})
MUTATIONS = frozenset({"space_create", "dot_create", "dot_update", "conversation_create", "message_send", "coordinate"})
VOICE_READS = frozenset({"voice_status", "attachment_upload_status"})


def dot_manages_canvas(dot):
    return (dot.get("canvas_root_dot_id") or dot["dot_id"]) == dot["dot_id"] or str(dot.get("role", "")).lower() in {"coordinator", "coordenador"}

VOICE_MUTATIONS = frozenset({"voice_start", "voice_signal", "voice_stop", "voice_revoke", "attachment_register",
    "attachment_upload_begin", "attachment_upload_chunk", "attachment_upload_complete", "attachment_upload_abort"})
INTENT_FIELDS = {
    "create_team": {"kind", "name", "coordinator_dot_id", "worker_dot_ids"},
    "connect": {"kind", "source_dot_id", "target_dot_id"},
    "delegate": {"kind", "team_id", "dot_id", "objective"},
    "handoff": {"kind", "source_dot_id", "target_dot_id", "content"},
    "pause": {"kind"}, "resume": {"kind"}, "cancel": {"kind"},
    "reassign": {"kind", "work_item_id", "dot_id"},
    "pause_dot": {"kind", "dot_id"}, "resume_dot": {"kind", "dot_id"},
}


class ShellCoordinatorService:
    @staticmethod
    def _mascot(value):
        if value not in {"blue", "mint", "orange", "purple"}:
            raise ValueError("unsupported Dot mascot")
        return value

    def __init__(self, control):
        self.control = control
        self.store = control.store
        self.runtime = None
        self.lock = threading.RLock()
        with self.store.connect("shell") as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS shell_entities(
                    owner TEXT NOT NULL, project_id TEXT NOT NULL, kind TEXT NOT NULL,
                    entity_id TEXT NOT NULL, space_id TEXT NOT NULL, body TEXT NOT NULL,
                    revision INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY(owner,project_id,kind,entity_id));
                CREATE INDEX IF NOT EXISTS shell_entities_space
                    ON shell_entities(owner,project_id,space_id,kind,updated_at);
                CREATE TABLE IF NOT EXISTS shell_requests(
                    owner TEXT NOT NULL, project_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    action TEXT NOT NULL, fingerprint TEXT NOT NULL, protected_payload TEXT NOT NULL,
                    state TEXT NOT NULL, protected_result TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY(owner,project_id,request_key));
                CREATE TABLE IF NOT EXISTS shell_message_requests(
                    owner TEXT NOT NULL, project_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    request_key TEXT NOT NULL, PRIMARY KEY(owner,project_id,message_id));
                CREATE TABLE IF NOT EXISTS shell_events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                    owner TEXT NOT NULL, project_id TEXT NOT NULL, space_id TEXT NOT NULL,
                    kind TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS shell_events_scope ON shell_events(owner,project_id,seq);
                CREATE TABLE IF NOT EXISTS shell_messages(
                    message_id TEXT PRIMARY KEY, owner TEXT NOT NULL, project_id TEXT NOT NULL,
                    space_id TEXT NOT NULL, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
                    protected_content TEXT NOT NULL, status TEXT NOT NULL, operation_id TEXT,
                    work_item_id TEXT, receipt_id TEXT, protected_delivery TEXT,
                    revision INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(owner,project_id,conversation_id,message_id));
                CREATE INDEX IF NOT EXISTS shell_messages_conversation
                    ON shell_messages(owner,project_id,conversation_id,created_at);
                CREATE TABLE IF NOT EXISTS shell_receipts(
                    receipt_id TEXT PRIMARY KEY, owner TEXT NOT NULL, project_id TEXT NOT NULL,
                    request_key TEXT NOT NULL, operation_id TEXT NOT NULL, kind TEXT NOT NULL,
                    result_digest TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS shell_message_contents(
                    owner TEXT NOT NULL, project_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, chunk_offset INTEGER NOT NULL, protected_content TEXT NOT NULL,
                    PRIMARY KEY(owner,project_id,message_id,revision,chunk_offset));
            """)

    def attach_runtime(self, runtime):
        for method in ("resolve_project", "admit_dot", "dispatch_message", "coordinate"):
            if not callable(getattr(runtime, method, None)):
                raise ValueError("shell runtime missing " + method)
        self.runtime = runtime

    def _project(self, owner, project_id):
        _text(owner, "authenticated owner", 256)
        _id(project_id, "project_id")
        if self.runtime is None:
            raise RuntimeError("shell runtime is not configured")
        project = self.runtime.resolve_project(project_id, owner)
        if not isinstance(project, dict) or project.get("project_id", project.get("id")) != project_id:
            raise PermissionError("project identity mismatch")
        run_id = _id(project.get("run_id"), "run_id")
        run = self.control.durable.run_status(run_id, owner, include_details=False)
        return {**project, "project_id": project_id, "run_id": run_id, "workspace": run.get("workspace"), "run": {"run_id": run_id, "state": run["state"]}}

    def resolve_run(self, project_id: str, owner: str) -> str:
        project = self._project(owner, project_id)
        if project["run"]["state"] != "RUNNING":
            raise PermissionError("project run is not active")
        return project["run_id"]

    @staticmethod
    def _stable(owner, project_id, key, kind):
        return kind + "-" + hashlib.sha256(_json([owner, project_id, key, kind]).encode()).hexdigest()[:32]

    def _entity(self, db, owner, project_id, kind, ident, *, space_id=None):
        _id(ident, kind + "_id")
        row = db.execute("SELECT body FROM shell_entities WHERE owner=? AND project_id=? AND kind=? AND entity_id=?",
                         (owner, project_id, kind, ident)).fetchone()
        if row is None:
            raise FileNotFoundError(kind + " not found in project")
        value = _decode(row["body"])
        if space_id is not None and value.get("space_id") != space_id:
            raise PermissionError(kind + " belongs to another Space")
        return value

    def _put(self, db, owner, project_id, kind, value):
        ident = value[kind + "_id"]
        changed = db.execute("INSERT INTO shell_entities(owner,project_id,kind,entity_id,space_id,body,revision,created_at,updated_at) "
                   "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(owner,project_id,kind,entity_id) DO UPDATE SET "
                   "body=excluded.body,revision=excluded.revision,updated_at=excluded.updated_at WHERE shell_entities.revision=excluded.revision-1",
                   (owner, project_id, kind, ident, value["space_id"], _encode(value), value.get("revision", 1), value["created_at"], value["updated_at"])).rowcount
        if changed != 1:
            raise ShellConflict("shell entity revision changed during mutation")

    def _event(self, db, owner, project_id, space_id, kind, payload):
        event_id = "shell-event-" + uuid.uuid4().hex
        db.execute("INSERT INTO shell_events(event_id,owner,project_id,space_id,kind,payload,created_at) VALUES(?,?,?,?,?,?,?)",
                   (event_id, owner, project_id, space_id, kind, _json(payload), time.time()))
        return event_id

    def _migrate(self, owner, project):
        """Additive, repeatable migration: preserve Canvas IDs and all source data."""
        pid = project["project_id"]
        sid = self._stable(owner, pid, "canvas-migration-v1", "space")
        now = time.time()
        with self.store.connect("shell") as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT 1 FROM shell_entities WHERE owner=? AND project_id=? AND kind='space' AND entity_id=?", (owner, pid, sid)).fetchone()
            if row is None:
                self._put(db, owner, pid, "space", {"space_id": sid, "project_id": pid, "name": project.get("name", "Workspace"),
                    "description": "", "run_id": project["run_id"], "revision": 1, "created_at": now, "updated_at": now, "migration_version": 1})
                self._event(db, owner, pid, sid, "space.migrated", {"space_id": sid, "source_project_id": pid})
            else:
                space = self._entity(db, owner, pid, "space", sid)
                if space["run_id"] != project["run_id"]:
                    space.update(run_id=project["run_id"], revision=space["revision"] + 1, updated_at=now)
                    self._put(db, owner, pid, "space", space)
            # All Spaces keep their identity while the Canvas project advances Run.
            spaces = db.execute("SELECT body FROM shell_entities WHERE owner=? AND project_id=? AND kind='space'", (owner,pid)).fetchall()
            for row in spaces:
                space = _decode(row["body"])
                if space["run_id"] != project["run_id"]:
                    space.update(run_id=project["run_id"], revision=space["revision"] + 1, updated_at=now)
                    self._put(db, owner, pid, "space", space)
            dot_bindings = db.execute("SELECT body FROM shell_entities WHERE owner=? AND project_id=? AND kind='dot'", (owner, pid)).fetchall()
            bound_agents = {_decode(binding['body']).get('agent_id') for binding in dot_bindings}
            for agent in project.get("agents", []):
                aid = _id(agent.get("agent_id", agent.get("id")), "agent_id")
                if aid in bound_agents:
                    continue
                did = self._stable(owner, pid, aid, "dot")
                existing = db.execute("SELECT 1 FROM shell_entities WHERE owner=? AND project_id=? AND kind='dot' AND entity_id=?", (owner, pid, did)).fetchone()
                if existing is None:
                    self._put(db, owner, pid, "dot", {"dot_id": did, "space_id": sid, "project_id": pid, "agent_id": aid,
                        "name": agent.get("name", aid), "role": agent.get("role", "worker"), "model": agent.get("model"),
                        "effort": agent.get("effort"), "status": agent.get("status", agent.get("state", "available")),
                        "run_id": project["run_id"], "instructions": "", "revision": 1, "created_at": now, "updated_at": now,
                        "migrated": True})
                    bound_agents.add(aid)
            team_bindings = db.execute("SELECT body FROM shell_entities WHERE owner=? AND project_id=? AND kind='team'", (owner, pid)).fetchall()
            bound_teams = {_decode(binding['body']).get('canvas_team_id') for binding in team_bindings}
            for team in project.get("teams", []):
                tid = _id(team.get("team_id", team.get("id")), "team_id")
                if tid in bound_teams:
                    continue
                ident = self._stable(owner, pid, tid, "team")
                if db.execute("SELECT 1 FROM shell_entities WHERE owner=? AND project_id=? AND kind='team' AND entity_id=?", (owner, pid, ident)).fetchone() is None:
                    self._put(db, owner, pid, "team", {"team_id": ident, "canvas_team_id": tid, "space_id": sid, "project_id": pid,
                        "name": team.get("name", tid), "coordinator_agent_id": team.get("coordinator", team.get("coordinator_agent_id")),
                        "worker_agent_ids": team.get("workers", []), "revision": 1, "created_at": now, "updated_at": now})
                    bound_teams.add(tid)
        return sid

    def get_space(self, space_id: str, owner: str, *, project_id: str) -> dict[str, Any]:
        self._project(owner, project_id)
        with self.store.connect("shell") as db:
            return self._entity(db, owner, project_id, "space", space_id)

    @staticmethod
    def _page(payload):
        offset, limit = payload.get("offset", 0), payload.get("limit", 50)
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 200:
            raise ValueError("invalid page")
        return offset, limit

    def _list(self, db, owner, pid, kind, payload, space_id=None):
        offset, limit = self._page(payload)
        clause = "owner=? AND project_id=? AND kind=?"
        args = [owner, pid, kind]
        if space_id is not None:
            clause += " AND space_id=?"
            args.append(space_id)
        total = db.execute("SELECT COUNT(*) AS total FROM shell_entities WHERE " + clause, args).fetchone()["total"]
        rows = db.execute("SELECT body FROM shell_entities WHERE " + clause + " ORDER BY updated_at DESC,entity_id LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
        items = [_decode(row["body"]) for row in rows]
        if kind == "dot":
            for item in items:
                try:
                    agent = self.control.durable.agent_info(item["agent_id"], owner)
                    item["status"] = "paused" if agent["desired_state"] == "WAITING" else str(agent["state"]).lower()
                    item["run_id"] = agent["run_id"]
                except FileNotFoundError:
                    item["status"] = "unavailable"
        return {"project_id": pid, "items": items, "page": {"offset": offset, "limit": limit, "returned": len(items), "total": total,
                "next_offset": offset + len(items) if offset + len(items) < total else None}}

    def _events(self, db, owner, pid, payload, space_id=None):
        after = payload.get("after_seq", 0)
        _, limit = self._page(payload)
        if type(after) is not int or after < 0:
            raise ValueError("invalid event cursor")
        clause = "owner=? AND project_id=? AND seq>?"
        args = [owner, pid, after]
        if space_id:
            clause += " AND space_id=?"
            args.append(space_id)
        rows = db.execute("SELECT * FROM shell_events WHERE " + clause + " ORDER BY seq LIMIT ?", (*args, limit + 1)).fetchall()
        items = [{"event_id": r["event_id"], "seq": r["seq"], "project_id": pid, "space_id": r["space_id"], "kind": r["kind"],
                  "payload": json.loads(r["payload"]), "created_at": r["created_at"]} for r in rows[:limit]]
        cursor = items[-1]["seq"] if items else after
        return {"project_id": pid, "items": items, "cursor": cursor, "next_cursor": cursor, "has_more": len(rows) > limit}

    def _read(self, owner, project, action, payload, default_sid):
        pid = project["project_id"]
        with self.store.connect("shell") as db:
            sid = payload.get("space_id", default_sid)
            if action != "space_list":
                space = self._entity(db, owner, pid, "space", sid)
            if action == "space_list":
                return self._list(db, owner, pid, "space", payload)
            if action in {"dot_list", "conversation_list"}:
                return self._list(db, owner, pid, action.split("_")[0], payload, sid)
            if action == "events":
                return self._events(db, owner, pid, payload, sid)
            if action in {"home", "space_get"}:
                dots = self._list(db, owner, pid, "dot", {}, sid)["items"]
                conversations = self._list(db, owner, pid, "conversation", {}, sid)["items"]
                teams = self._list(db, owner, pid, "team", {}, sid)["items"]
                if action == "space_get":
                    return {**space, "dots": dots, "conversations": conversations, "teams": teams, "documents": []}
                voice = {"available": False, "reason": "voice provider is not configured"}
                attachments = {"available": False, "reason": "attachment model transport is not configured"}
                if callable(getattr(self.runtime, "voice_availability", None)):
                    voice = self.runtime.voice_availability(pid, owner)
                if callable(getattr(self.runtime, "attachment_availability", None)):
                    attachments = self.runtime.attachment_availability(pid, owner)
                return {"project_id": pid, "space": space, "spaces": self._list(db, owner, pid, "space", {})["items"],
                        "dots": dots, "conversations": conversations, "teams": teams, "documents": [], "run": project["run"],
                        "activity": self._events(db, owner, pid, {}, sid), "capabilities": project.get("capabilities", []), "voice": voice, "attachments": attachments}
            if action == "message_content":
                cid = payload.get("conversation_id")
                self._entity(db,owner,pid,"conversation",cid,space_id=sid)
                row = db.execute("SELECT * FROM shell_messages WHERE owner=? AND project_id=? AND conversation_id=? AND message_id=?",
                                 (owner,pid,cid,payload.get("message_id"))).fetchone()
                if row is None:
                    raise FileNotFoundError("message not found")
                revision = payload.get("revision",row["revision"])
                offset,limit = payload.get("offset",0),payload.get("limit",65536)
                if (type(revision) is not int or revision != row["revision"] or type(offset) is not int
                        or offset < 0 or type(limit) is not int or not 1 <= limit <= 65536):
                    raise ValueError("invalid message content revision/page")
                value = _decode(row["protected_content"])
                if isinstance(value,str):
                    content,total,digest = value[offset:offset+limit],len(value),hashlib.sha256(value.encode()).hexdigest()
                else:
                    total,digest = value["total_chars"],value["sha256"]
                    start = (offset // 65536)*65536
                    chunks = db.execute("SELECT protected_content FROM shell_message_contents WHERE owner=? AND project_id=? AND message_id=? AND revision=? AND chunk_offset>=? AND chunk_offset<? ORDER BY chunk_offset",
                        (owner,pid,row["message_id"],revision,start,offset+limit)).fetchall()
                    content = "".join(_decode(chunk["protected_content"]) for chunk in chunks)[offset-start:offset-start+limit]
                    if offset < total and len(content) != min(limit,total-offset):
                        raise RuntimeError("protected message overflow is incomplete")
                return {"project_id":pid,"space_id":sid,"conversation_id":cid,"message_id":row["message_id"],
                    "revision":revision,"content":content,"offset":offset,"total_chars":total,"sha256":digest,
                    "next_offset":offset+len(content) if offset+len(content)<total else None}
            if action == "message_list":
                cid = payload.get("conversation_id")
                self._entity(db, owner, pid, "conversation", cid, space_id=sid)
                offset, limit = self._page(payload)
                total = db.execute("SELECT COUNT(*) AS total FROM shell_messages WHERE owner=? AND project_id=? AND conversation_id=?", (owner, pid, cid)).fetchone()["total"]
                rows = db.execute("SELECT * FROM shell_messages WHERE owner=? AND project_id=? AND conversation_id=? ORDER BY created_at,message_id LIMIT ? OFFSET ?", (owner, pid, cid, limit, offset)).fetchall()
                items = [self._message_view(row) for row in rows]
                if callable(getattr(self.runtime, "reconcile_message", None)):
                    for index, message in enumerate(items):
                        if message["role"] == "user" and message["status"] in {"queued", "running", "uncertain", "waiting_approval"}:
                            self.reconcile_message(owner, project_id=pid, message_id=message["message_id"])
                            fresh = db.execute("SELECT * FROM shell_messages WHERE message_id=? AND owner=? AND project_id=?", (message["message_id"], owner, pid)).fetchone()
                            items[index] = self._message_view(fresh)
                if items:
                    ids = [message["message_id"] for message in items]
                    placeholders = ','.join('?' for _ in ids)
                    keys = {row['message_id']: row['request_key'] for row in db.execute(
                        'SELECT message_id,request_key FROM shell_message_requests WHERE owner=? AND project_id=? AND message_id IN (' + placeholders + ')',
                        (owner, pid, *ids)).fetchall()}
                    for message in items:
                        if message['message_id'] in keys:
                            message['request_key'] = keys[message['message_id']]
                return {"project_id": pid, "items": items, "page": {"offset": offset, "limit": limit, "returned": len(items), "total": total,
                    "next_offset": offset + len(items) if offset + len(items) < total else None}}
        raise ValueError("unsupported shell read")

    @staticmethod
    def _message_view(row):
        value = _decode(row["protected_content"])
        content = {"content":value} if isinstance(value,str) else {"content":value["preview"],"content_ref":{
            "message_id":row["message_id"],"revision":row["revision"],"total_chars":value["total_chars"],
            "sha256":value["sha256"],"action":"message_content"},"content_truncated":True}
        delivery = _decode(row["protected_delivery"]) if row["protected_delivery"] else {}
        reason = delivery.get("reason") if isinstance(delivery, dict) else None
        return {key: row[key] for key in ("message_id", "project_id", "space_id", "conversation_id", "role", "status", "operation_id", "work_item_id", "receipt_id", "revision", "created_at", "updated_at")} | content | ({"reason": str(reason)[:2000]} if reason else {})

    @staticmethod
    def _persist_content(db,owner,pid,mid,revision,content):
        if len(content) <= 100000:
            return _encode(content)
        for offset in range(0,len(content),65536):
            db.execute("INSERT INTO shell_message_contents VALUES(?,?,?,?,?,?) ON CONFLICT(owner,project_id,message_id,revision,chunk_offset) DO NOTHING",
                       (owner,pid,mid,revision,offset,_encode(content[offset:offset+65536])))
        return _encode({"preview":content[:65536],"total_chars":len(content),"sha256":hashlib.sha256(content.encode()).hexdigest()})

    def _authority(self, owner, project, sid, key, action, *, agent_id=None,
                   create_operation=True, assignee_user_id=None, required_capabilities=None):
        rid = project["run_id"]
        oid = self._stable(owner, project["project_id"], key, "op")
        wid = self._stable(owner, project["project_id"], key, "work")
        parent_work_item_id = None
        lineage = {}
        if action == "message_send":
            from sentra_runtime.effect_boundary import current_effect_context
            context = current_effect_context.get()
            if context is not None and context.request.capability_id in {"canvas.coordinator.delegate","canvas.coordinator.handoff"}:
                if (context.authority.durable is not self.control.durable
                        or context.receipt.owner != owner or context.receipt.run_id != rid
                        or context.request.arguments.get("project_id") != project["project_id"]):
                    raise PermissionError("descendant message differs from central coordinator scope")
                context.checkpoint()
                parent_work_item_id = context.request.work_item_id
                lineage = {"parent_coordinator_operation_id":context.request.operation_id,
                           "parent_coordinator_agent_id":context.request.principal_id}
        work = self.control.create_work_item(rid, owner, work_item_id=wid, external_key=wid,
            objective="Shell " + action, assignee_agent_id=agent_id, assignee_user_id=assignee_user_id,
            required_capabilities=required_capabilities,parent_work_item_id=parent_work_item_id,
            metadata={"workspace_id": project["project_id"], "space_id": sid, "request_key": key, "shell_action": action,**lineage},
            execution_policy={"require_quality_gate": False})
        if create_operation:
            operation = self.control.durable.create_operation(rid, owner, kind="shell." + action, operation_id=oid,
                idempotency_key=oid, cleanup_policy="manual")
            oid = operation["operation_id"]
            self.control.durable.update_operation(oid, owner, progress={"work_item_id": work["work_item_id"],
                "principal_id": agent_id or assignee_user_id or owner, "project_id": project["project_id"], "space_id": sid})
        return {"run_id": rid, "work_item_id": work["work_item_id"], "operation_id": oid}

    def _intent(self, db, owner, project, sid, payload):
        intent = payload.get("intent")
        if not isinstance(intent, dict) or intent.get("kind") not in INTENT_FIELDS or set(intent) - INTENT_FIELDS[intent["kind"]]:
            raise ValueError("structured allowlisted coordination intent required")
        result = dict(intent)
        kind = result["kind"]
        def dot(field):
            value = self._entity(db, owner, project["project_id"], "dot", result[field], space_id=sid)
            result[field.replace("dot_id", "agent_id")] = value["agent_id"]
            return value
        if kind == "create_team":
            result["name"] = _text(result.get("name"), "team name", 80)
            coordinator = dot("coordinator_dot_id")
            workers = result.get("worker_dot_ids")
            if not isinstance(workers, list) or not 1 <= len(workers) <= 12 or len(set(workers)) != len(workers) or coordinator["dot_id"] in workers:
                raise ValueError("team requires distinct coordinator and workers")
            result["worker_agent_ids"] = [self._entity(db, owner, project["project_id"], "dot", wid, space_id=sid)["agent_id"] for wid in workers]
        elif kind in {"connect", "handoff"}:
            source, target = dot("source_dot_id"), dot("target_dot_id")
            if source["dot_id"] == target["dot_id"]:
                raise ValueError("distinct coordination agents required")
            if kind == "handoff":
                result["content"] = _text(result.get("content"), "handoff content", 100000)
        elif kind in {"pause_dot", "resume_dot"}:
            dot("dot_id")
        elif kind in {"delegate", "reassign"}:
            target = dot("dot_id")
            if kind == "delegate":
                team = self._entity(db, owner, project["project_id"], "team", result.get("team_id"), space_id=sid)
                members = team.get("worker_agent_ids", []) + [team.get("coordinator_agent_id")]
                if target["agent_id"] not in members:
                    raise PermissionError("delegation target is not a team member")
                result["canvas_team_id"] = team["canvas_team_id"]
                result["objective"] = _text(result.get("objective"), "objective", 100000)
            else:
                item = self.control.work_item_info(result.get("work_item_id"), owner)
                if item["run_id"] != project["run_id"] or item["metadata"].get("workspace_id") != project["project_id"] or item["metadata"].get("space_id") not in {None, sid}:
                    raise PermissionError("WorkItem outside project/Space")
                if item["state"] not in {"PENDING", "QUEUED", "BLOCKED"}:
                    raise ShellConflict("only inactive WorkItems may be reassigned")
        return result

    def dispatch(self, owner: str, *, project_id: str, action: str, payload: dict, request_key: str | None = None) -> dict:
        if action not in READS | MUTATIONS | VOICE_READS | VOICE_MUTATIONS or not isinstance(payload, dict):
            raise ValueError("unsupported shell action")
        if payload.get("project_id", project_id) != project_id or payload.get("ws", project_id) != project_id:
            raise PermissionError("shell project scope mismatch")
        if set(payload) & {"owner", "principal", "principal_id", "principal_type", "grant", "grant_id", "permissions", "path", "workspace_root", "run_id", "operation_id", "work_item_id"} - ({"work_item_id"} if action == "coordinate" else set()):
            raise PermissionError("server-owned shell authority field")
        project = self._project(owner, project_id)
        sid = self._migrate(owner, project)
        if action in READS:
            return {"ok": True, "value": self._read(owner, project, action, payload, sid)}
        if action in VOICE_READS:
            return {"ok": True, "value": self._optional(owner, project, action, payload, None)}
        key = _text(request_key, "request_key", 200)
        digest = hashlib.sha256(_json([action, payload]).encode()).hexdigest()
        with self.lock:
            with self.store.connect("shell") as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM shell_requests WHERE owner=? AND project_id=? AND request_key=?", (owner, project_id, key)).fetchone()
                if row is not None:
                    if row["fingerprint"] != digest:
                        raise ShellConflict("request_key already used for another intent")
                    if row["protected_result"]:
                        previous = _decode(row["protected_result"])
                        if row["state"] == "waiting_approval" and action in VOICE_MUTATIONS:
                            db.execute("UPDATE shell_requests SET state='claimed',protected_result=NULL WHERE owner=? AND project_id=? AND request_key=? AND state='waiting_approval'", (owner, project_id, key))
                            db.commit()
                            value = self._optional(owner, project, action, _decode(row["protected_payload"]), key)
                            result = {"ok": True, "request_key": key, "value": value}
                            db.execute("UPDATE shell_requests SET state=?,protected_result=?,updated_at=? WHERE owner=? AND project_id=? AND request_key=?", (value.get("status", "committed"), _encode(result), time.time(), owner, project_id, key))
                            return result
                        if row["state"] == "rejected":
                            raise ValueError("shell request rejected before dispatch")
                        if action == "message_send" and previous.get("value", {}).get("message_id") and callable(getattr(self.runtime, "reconcile_message", None)):
                            db.commit()
                            current = self.reconcile_message(owner, project_id=project_id, message_id=previous["value"]["message_id"])
                            return {"ok": True, "request_key": key, "value": current}
                        return previous
                    return {"ok": True, "request_key": key, "value": {"status": "uncertain", "operation_id": self._stable(owner, project_id, key, "op"), "receipt_id": None, "reason": "interrupted request requires reconciliation"}}
                # Private intent is protected; event journal only contains IDs/status.
                db.execute("INSERT INTO shell_requests VALUES(?,?,?,?,?,?,?,?,?,?)", (owner, project_id, key, action, digest, _encode(payload), "claimed", None, time.time(), time.time()))
            try:
                value = self._mutate(owner, project, action, payload, key, sid) if action in MUTATIONS else self._optional(owner, project, action, payload, key)
                if action in {"space_create", "dot_create", "dot_update", "conversation_create", "coordinate"}:
                    value = self._local_ack(owner, project, value.get("space_id", payload.get("space_id", sid)), key, action, value)
                result = {"ok": True, "value": value, "request_key": key}
                with self.store.connect("shell") as db:
                    db.execute("UPDATE shell_requests SET state=?,protected_result=?,updated_at=? WHERE owner=? AND project_id=? AND request_key=?", (value.get("status", "committed"), _encode(result), time.time(), owner, project_id, key))
                return result
            except BaseException:
                with self.store.connect("shell") as db:
                    state = db.execute("SELECT state FROM shell_requests WHERE owner=? AND project_id=? AND request_key=?", (owner, project_id, key)).fetchone()["state"]
                    rejected = state == "claimed"
                    db.execute("UPDATE shell_requests SET state=?,protected_result=?,updated_at=? WHERE owner=? AND project_id=? AND request_key=?", ("rejected" if rejected else "uncertain", _encode({"ok": False, "error": "shell request rejected before dispatch"}) if rejected else None, time.time(), owner, project_id, key))
                raise

    def _runtime_call(self, owner, project_id, key, callback, *arguments):
        with self.store.connect("shell") as db:
            db.execute("UPDATE shell_requests SET state='dispatching',updated_at=? WHERE owner=? AND project_id=? AND request_key=?", (time.time(), owner, project_id, key))
        return callback(*arguments)

    def _local_ack(self, owner, project, sid, key, action, value):
        if value.get("status") in {"uncertain", "waiting_approval", "failed"}:
            return value
        authority = self._authority(owner, project, sid, key, action)
        receipt = self._stable(owner, project["project_id"], key, "receipt")
        with self.store.connect("shell") as db:
            db.execute("INSERT INTO shell_receipts VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(receipt_id) DO NOTHING",
                (receipt, owner, project["project_id"], key, authority["operation_id"], "control_mutation", hashlib.sha256(_json(value).encode()).hexdigest(), time.time()))
        operation = self.control.durable.operation_status(authority["operation_id"], owner)
        if operation["state"] == "QUEUED":
            self.control.durable.update_operation(operation["operation_id"], owner, state="RUNNING", event_type="SHELL_CONTROL_MUTATION_COMMITTED")
        if operation["state"] in {"QUEUED", "RUNNING"}:
            self.control.durable.update_operation(operation["operation_id"], owner, state="SUCCEEDED", result={"receipt_id": receipt, "control_mutation_only": True, "external_completion_claimed": False})
        self.control.governance.complete_control_mutation(authority["work_item_id"], owner, receipt_id=receipt)
        return {**value, **authority, "shell_receipt_id": receipt}

    def _mutate(self, owner, project, action, payload, key, default_sid):
        pid, now = project["project_id"], time.time()
        sid = payload.get("space_id", default_sid)
        with self.store.connect("shell") as db:
            if action != "space_create":
                self._entity(db, owner, pid, "space", sid)
            if action == "space_create":
                sid = self._stable(owner, pid, key, "space")
                value = {"space_id": sid, "project_id": pid, "name": _text(payload.get("name"), "Space name", 80),
                         "description": _text(payload.get("description", ""), "description", 4000, empty=True), "run_id": project["run_id"],
                         "revision": 1, "created_at": now, "updated_at": now}
            elif action in {"dot_create", "dot_update"}:
                if action == "dot_create":
                    if project["run"]["state"] != "RUNNING":
                        raise PermissionError("project run is not active")
                    did = self._stable(owner, pid, key, "dot")
                    value = {"dot_id": did, "space_id": sid, "project_id": pid,
                        "name": _text(payload.get("name"), "Dot name", 80), "role": _text(payload.get("role", "worker"), "role", 80),
                        "model": _text(payload.get("model"), "model", 200), "effort": payload.get("effort"),
                        "instructions": _text(payload.get("instructions", ""), "instructions", 16000, empty=True),
                        "run_id": project["run_id"], "revision": 1, "created_at": now, "updated_at": now}
                    value["mascot"] = self._mascot(payload.get("mascot", "blue"))
                    root_id = payload.get("canvas_root_dot_id", did)
                    if root_id != did:
                        root = self._entity(db, owner, pid, "dot", root_id, space_id=sid)
                        root_id = root.get("canvas_root_dot_id", root["dot_id"])
                    value["canvas_root_dot_id"] = root_id
                    if value["effort"] is not None and value["effort"] not in {"low", "medium", "high", "xhigh", "max", "ultra", "automatic"}:
                        raise ValueError("unsupported effort")
                    authority = self._authority(owner, project, sid, key, action)
                    admitted = self._runtime_call(owner, pid, key, self.runtime.admit_dot, pid, owner, {**value, **authority}, key)
                    if not isinstance(admitted, dict) or not admitted.get("agent_id"):
                        raise RuntimeError("Dot admission did not return an agent identity")
                    value.update(agent_id=_id(admitted["agent_id"], "agent_id"), status=admitted.get("status", "available"), **authority)
                    self.control.ensure_agent(project["run_id"], owner, agent_id=value["agent_id"], role=value["role"], metadata={"workspace_id": pid, "space_id": sid, "dot_id": did})
                else:
                    value = self._entity(db, owner, pid, "dot", payload.get("dot_id"), space_id=sid)
                    if type(payload.get("expected_revision")) is not int or payload["expected_revision"] != value["revision"]:
                        raise ShellConflict("Dot revision conflict")
                    for field, maximum in (("name", 80), ("role", 80), ("instructions", 16000)):
                        if field in payload:
                            value[field] = _text(payload[field], field, maximum, empty=field == "instructions")
                    if "mascot" in payload:
                        value["mascot"] = self._mascot(payload["mascot"])
                    if "model" in payload:
                        value["model"] = _text(payload["model"], "model", 200)
                    if "effort" in payload:
                        if payload["effort"] not in {None, "low", "medium", "high", "xhigh", "max", "ultra", "automatic"}:
                            raise ValueError("unsupported effort")
                        value["effort"] = payload["effort"]
                    value.update(revision=value["revision"] + 1, updated_at=now)
                    # Runtime metadata update is mandatory when offered; no process is restarted.
                    updater = getattr(self.runtime, "update_dot", None)
                    if not callable(updater):
                        raise RuntimeError("Dot update runtime is not configured")
                    self._runtime_call(owner, pid, key, updater, pid, owner, value, key)
            elif action == "conversation_create":
                dot = self._entity(db, owner, pid, "dot", payload.get("dot_id"), space_id=sid)
                parent = payload.get("parent_conversation_id")
                if parent:
                    self._entity(db, owner, pid, "conversation", parent, space_id=sid)
                value = {"conversation_id": self._stable(owner, pid, key, "conversation"), "project_id": pid, "space_id": sid,
                         "dot_id": dot["dot_id"], "title": _text(payload.get("title", dot["name"]), "conversation title", 200),
                         "parent_conversation_id": parent, "created_at": now, "updated_at": now, "revision": 1}
            elif action == "message_send":
                conversation = self._entity(db, owner, pid, "conversation", payload.get("conversation_id"), space_id=sid)
                dot = self._entity(db, owner, pid, "dot", conversation["dot_id"], space_id=sid)
                if not any(agent.get("agent_id", agent.get("id")) == dot["agent_id"] for agent in project.get("agents", [])):
                    raise FileNotFoundError("Dot agent is unavailable in this project")
                content = _text(payload.get("content"), "content", 100000)
                native_generation = payload.get('native_generation')
                if native_generation is not None and native_generation != 'image':
                    raise ValueError('supported native generation mode required')
                refs = payload.get("attachments", [])
                if not isinstance(refs, list) or len(refs) > 16:
                    raise ValueError("bounded attachment references required")
                if refs:
                    validator = getattr(self.runtime, "validate_attachments", None)
                    if not callable(validator):
                        raise RuntimeError("attachment provider is not configured")
                    refs = validator(pid, owner, conversation, refs)
                declarations = None
                capability_callback = getattr(self.runtime,"message_capabilities",None)
                if callable(capability_callback):
                    declarations = capability_callback(pid,owner,dot,{**conversation,
                        **({'native_generation':native_generation} if native_generation else {})},refs)
                    if (not isinstance(declarations,list) or len(declarations) > 64
                            or any(not isinstance(cap,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}",cap) for cap in declarations)
                            or len(set(declarations)) != len(declarations)):
                        raise ValueError("runtime message capabilities require exact bounded declarations")
                authority = self._authority(owner, project, sid, key, action, agent_id=dot["agent_id"],
                                            required_capabilities=declarations)
                mid = self._stable(owner, pid, key, "message")
                with self.store.connect("shell") as outbox:
                    outbox.execute("INSERT INTO shell_messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (mid, owner, pid, sid, conversation["conversation_id"], "user", _encode(content), "queued", authority["operation_id"], authority["work_item_id"], None, None, 1, now, now))
                    outbox.execute('INSERT INTO shell_message_requests VALUES(?,?,?,?)', (owner, pid, mid, key))
                    self._event(outbox, owner, pid, sid, "message.queued", {"message_id": mid, "conversation_id": conversation["conversation_id"], **authority})
                message = {"message_id": mid, "conversation_id": conversation["conversation_id"], "space_id": sid, "project_id": pid,
                           "content": content, "attachments": refs, **authority,
                           **({'native_generation':native_generation} if native_generation else {})}
                try:
                    # Runtime persists its queue even for paused Runs; admission
                    # and resume remain under the same authoritative Run state.
                    delivery = self._runtime_call(owner, pid, key, self.runtime.dispatch_message, pid, owner, dot, message, key)
                except Exception:
                    delivery = {"status": "uncertain", "reason": "runtime delivery acknowledgement unavailable"}
                return self._record_delivery(owner, pid, sid, mid, authority, delivery, key)
            elif action == "coordinate":
                intent = self._intent(db, owner, project, sid, payload)
                if payload.get("conversation_id"):
                    self._entity(db, owner, pid, "conversation", payload["conversation_id"], space_id=sid)
                kind = intent["kind"]
                if project["run"]["state"] != "RUNNING" and kind not in {"resume", "cancel"}:
                    raise PermissionError("project run is not active")
                authority = self._authority(owner, project, sid, key, action)
                # reassign preserves the target WorkItem identity under another field.
                if kind == "reassign":
                    intent["target_work_item_id"] = intent["work_item_id"]
                intent.update(**authority, space_id=sid, project_id=pid)
                if kind in {"pause_dot", "resume_dot"}:
                    with self.store.connect("shell") as claim:
                        claim.execute("UPDATE shell_requests SET state='dispatching',updated_at=? WHERE owner=? AND project_id=? AND request_key=?",
                                      (time.time(),owner,pid,key))
                    result = {"status": "applied", "result": self.control.set_agent_paused(project["run_id"], owner,
                        agent_id=intent["agent_id"], paused=kind == "pause_dot")}
                else:
                    result = self._runtime_call(owner, pid, key, self.runtime.coordinate, pid, owner, intent, key)
                if not isinstance(result, dict):
                    raise RuntimeError("invalid coordination acknowledgement")
                value = {**authority, "status": result.get("status", "uncertain"), "receipt_id": result.get("receipt_id"), "result": result.get("result", result)}
                if kind == "create_team" and value["status"] not in {"uncertain", "waiting_approval", "failed"}:
                    resource = result.get("result", result)
                    resource = resource.get("resource", resource)
                    team_id = resource.get("team_id", resource.get("id"))
                    if not team_id:
                        raise RuntimeError("team creation acknowledgement missing identity")
                    team = {"team_id": self._stable(owner, pid, key, "team"), "canvas_team_id": _id(team_id, "team_id"), "project_id": pid, "space_id": sid,
                            "name": intent["name"], "coordinator_agent_id": intent["coordinator_agent_id"], "worker_agent_ids": intent["worker_agent_ids"],
                            "coordinator_dot_id": intent["coordinator_dot_id"], "worker_dot_ids": intent["worker_dot_ids"], "revision": 1, "created_at": now, "updated_at": now}
                    self._put(db, owner, pid, "team", team)
                    value["team"] = team
                self._event(db, owner, pid, sid, "coordinate." + kind, {**authority, "status": value["status"]})
                return value
            else:
                raise ValueError("unsupported shell mutation")
            kind = action.split("_")[0]
            with self.store.connect("shell") as claim:
                claim.execute("UPDATE shell_requests SET state='committing',updated_at=? WHERE owner=? AND project_id=? AND request_key=?", (time.time(), owner, pid, key))
            self._put(db, owner, pid, kind, value)
            self._event(db, owner, pid, sid, action.replace("_", "."), {kind + "_id": value[kind + "_id"], "revision": value["revision"]})
            return value

    def _record_delivery(self, owner, pid, sid, mid, authority, delivery, key):
        if not isinstance(delivery, dict) or delivery.get("status") not in {"queued", "running", "dispatched", "waiting_approval", "uncertain"}:
            delivery = {"status": "uncertain", "reason": "invalid runtime delivery receipt"}
        if delivery["status"] == "dispatched" and not delivery.get("receipt_id"):
            delivery = {**delivery, "status": "uncertain", "reason": "dispatch receipt absent"}
        value = {"message_id": mid, **authority, "status": delivery["status"], "receipt_id": delivery.get("receipt_id")}
        if delivery.get("reason"):
            value["reason"] = str(delivery["reason"])[:2000]
        # Runtime may return an admitted Canvas task operation; retain both links.
        if delivery.get("operation_id"):
            operation = self.control.durable.operation_status(delivery["operation_id"], owner)
            if operation["run_id"] != authority["run_id"]:
                raise PermissionError("delivery operation belongs to another run")
            value["shell_operation_id"] = authority["operation_id"]
            value["operation_id"] = operation["operation_id"]
        if delivery.get("work_item_id"):
            item = self.control.work_item_info(delivery["work_item_id"], owner)
            if item["run_id"] != authority["run_id"]:
                raise PermissionError("delivery WorkItem belongs to another run")
            value["work_item_id"] = item["work_item_id"]
        with self.store.connect("shell") as db:
            row = db.execute("SELECT conversation_id,status,operation_id,work_item_id,receipt_id,protected_delivery FROM shell_messages WHERE message_id=? AND owner=? AND project_id=?", (mid, owner, pid)).fetchone()
            value["conversation_id"] = row["conversation_id"]
            if all(row[field] == value[field] for field in ("status", "operation_id", "work_item_id", "receipt_id")) and row["protected_delivery"] and _decode(row["protected_delivery"]) == delivery:
                return value
            db.execute("UPDATE shell_messages SET status=?,operation_id=?,work_item_id=?,receipt_id=?,protected_delivery=?,updated_at=? WHERE message_id=? AND owner=? AND project_id=?",
                       (value["status"], value["operation_id"], value["work_item_id"], value["receipt_id"], _encode(delivery), time.time(), mid, owner, pid))
            self._event(db, owner, pid, sid, "message." + value["status"], {k: v for k, v in value.items() if k != "content"})
            conversation = self._entity(db, owner, pid, "conversation", value["conversation_id"], space_id=sid)
            conversation.update(updated_at=time.time(), revision=conversation["revision"] + 1)
            self._put(db, owner, pid, "conversation", conversation)
        return value

    def reconcile_message(self, owner, *, project_id, message_id):
        """Trusted runtime query only: this method never sends or reclaims an effect."""
        project = self._project(owner, project_id)
        reconciler = getattr(self.runtime, "reconcile_message", None)
        if not callable(reconciler):
            raise RuntimeError("message reconciliation runtime is not configured")
        with self.store.connect("shell") as db:
            row = db.execute("SELECT * FROM shell_messages WHERE owner=? AND project_id=? AND message_id=?", (owner, project_id, message_id)).fetchone()
            if row is None:
                raise FileNotFoundError("message not found")
            message = self._message_view(row)
        delivery = reconciler(project_id, owner, message)
        return self._record_delivery(owner, project_id, row["space_id"], message_id,
            {"run_id": project["run_id"], "operation_id": row["operation_id"], "work_item_id": row["work_item_id"]}, delivery, "reconcile")

    def record_runtime_message(self, owner, *, project_id, space_id, conversation_id, message_id, content, revision, receipt_id, operation_id, role="assistant", status="dispatched"):
        """Server-only stream ingest with identity/revision CAS, no per-frame rows."""
        project = self._project(owner, project_id)
        _id(message_id, "message_id")
        if role not in {"assistant", "tool"} or type(revision) is not int or revision < 1 or status not in {"queued", "dispatched", "waiting_approval", "uncertain"}:
            raise ValueError("invalid runtime message")
        if status == "dispatched" and not receipt_id:
            raise ValueError("runtime receipt required")
        operation = self.control.durable.operation_status(operation_id, owner)
        if operation["run_id"] != project["run_id"]:
            raise PermissionError("runtime message operation outside project")
        _text(content, "content", 20_000_000, empty=True)
        if len(content.encode()) > 20_000_000:
            raise ValueError("runtime content exceeds protected overflow bound")
        now = time.time()
        with self.store.connect("shell") as db:
            db.execute("BEGIN IMMEDIATE")
            self._entity(db, owner, project_id, "conversation", conversation_id, space_id=space_id)
            row = db.execute("SELECT * FROM shell_messages WHERE message_id=?", (message_id,)).fetchone()
            if row:
                if (row["owner"], row["project_id"], row["conversation_id"], row["role"], row["operation_id"]) != (owner, project_id, conversation_id, role, operation_id):
                    raise PermissionError("message identity changed")
                if row["revision"] >= revision:
                    previous = _decode(row["protected_content"])
                    matches = previous == content if isinstance(previous,str) else previous["sha256"] == hashlib.sha256(content.encode()).hexdigest()
                    if row["revision"] == revision and not matches:
                        raise ShellConflict("runtime message revision conflict")
                    return self._message_view(row)
                protected = self._persist_content(db,owner,project_id,message_id,revision,content)
                db.execute("UPDATE shell_messages SET protected_content=?,status=?,receipt_id=?,revision=?,updated_at=? WHERE message_id=?", (protected, status, receipt_id, revision, now, message_id))
            else:
                protected = self._persist_content(db,owner,project_id,message_id,revision,content)
                db.execute("INSERT INTO shell_messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (message_id, owner, project_id, space_id, conversation_id, role, protected, status, operation_id, None, receipt_id, None, revision, now, now))
            self._event(db, owner, project_id, space_id, "message.updated", {"message_id": message_id, "conversation_id": conversation_id, "revision": revision, "status": status})
            return self._message_view(db.execute("SELECT * FROM shell_messages WHERE message_id=?", (message_id,)).fetchone())

    def _optional(self, owner, project, action, payload, key):
        sid = payload.get("space_id")
        self.get_space(sid, owner, project_id=project["project_id"])
        cid = payload.get("conversation_id")
        with self.store.connect("shell") as db:
            conversation = self._entity(db, owner, project["project_id"], "conversation", cid, space_id=sid)
        if action.startswith("voice_") and not callable(getattr(self.runtime, "voice_dispatch", None)):
            raise RuntimeError("voice provider is not configured")
        method = "voice_dispatch" if action.startswith("voice_") else "attachment_dispatch"
        callback = getattr(self.runtime, method, None)
        if callback is None and action == "attachment_register":
            callback = getattr(self.runtime, "attachment_register", None)
        if not callable(callback):
            raise RuntimeError("attachment provider is not configured")
        if action in VOICE_MUTATIONS:
            if project["run"]["state"] != "RUNNING" and action not in {"voice_stop", "voice_revoke", "attachment_upload_abort"}:
                raise PermissionError("project run is not active")
            from sentra_runtime.shell_optional_authority import execute_optional
            return execute_optional(self, owner=owner, project=project, action=action,
                payload={**payload, "project_id": project["project_id"], "space_id": sid,
                         "conversation_id": conversation["conversation_id"], "conversation": conversation}, key=key, callback=callback)
        arguments = (project["project_id"], owner, action, {**payload, "project_id": project["project_id"],
            "space_id": sid, "conversation_id": conversation["conversation_id"], "conversation": conversation}, key)
        return self._runtime_call(owner, project["project_id"], key, callback, *arguments) if key is not None else callback(*arguments)

    def _entity_for_callback(self, owner, project_id, kind, entity_id, space_id):
        with self.store.connect("shell") as db:
            return self._entity(db, owner, project_id, kind, entity_id, space_id=space_id)
