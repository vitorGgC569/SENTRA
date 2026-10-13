"""Space documents backed by the existing ControlPlane, not a second authority.

All entry points take trusted server identity. Browser payloads cannot choose a
principal, owner, Grant or filesystem path. Immutable revisions, tombstones,
idempotency receipts and collaborative snapshots share canvas_collaboration.
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import json
import secrets
import time
from contextlib import contextmanager

from sentra_collab.authority import CollaborationDenied, SnapshotConflict, _id
from sentra_collab.authority_guard import begin_authority_guard, guard_query

DOCUMENT_ACTIONS = frozenset({
    "document_list", "document_get", "document_create", "document_save",
    "document_history", "document_restore", "document_delete", "document_diff",
    "document_export", "document_session", "document_session_close",
})
DOCUMENT_HOST_METHODS = frozenset({"documentResolveGrant", "documentCheckGrant",
    "documentConsumeNonce", "documentLoadSnapshot", "documentCommitSnapshot"})
MAX_CONTENT = 524288


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _content(value):
    if not isinstance(value, str) or "\0" in value or len(value.encode("utf-8")) > MAX_CONTENT:
        raise ValueError("document content exceeds bounded UTF-8 limit")
    return value


def _metadata(payload):
    title = payload.get("title", "Untitled")
    fmt, language = payload.get("format", "markdown"), payload.get("language", "")
    if not isinstance(title, str) or not title.strip() or len(title) > 240:
        raise ValueError("document title required (1..240 characters)")
    if fmt not in {"markdown", "text", "code"}:
        raise ValueError("unsupported document format")
    import re
    if not isinstance(language, str) or (language and not re.fullmatch(r"[A-Za-z0-9_+-]{1,40}", language)):
        raise ValueError("invalid document language")
    return {"title": title.strip(), "format": fmt, "language": language}


class ProjectDocuments:
    def __init__(self, control, *, owner, resolve_space, resolve_run=None, clock=time.time):
        if not owner or not callable(resolve_space):
            raise ValueError("trusted owner and Space resolver required")
        self.control, self.owner, self.clock = control, owner, clock
        self.resolve_space, self.resolve_run = resolve_space, resolve_run
        self.store = control.store
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS project_documents(
                  document_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, space_id TEXT NOT NULL,
                  parent_id TEXT, revision INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
                  title TEXT NOT NULL, format TEXT NOT NULL, language TEXT NOT NULL,
                  content TEXT NOT NULL, sha256 TEXT NOT NULL, updated_at REAL NOT NULL,
                  snapshot BLOB, snapshot_sha256 TEXT);
                CREATE INDEX IF NOT EXISTS project_document_scope ON project_documents(project_id,space_id,updated_at);
                CREATE TABLE IF NOT EXISTS document_versions(
                  document_id TEXT NOT NULL, revision INTEGER NOT NULL, value_json TEXT NOT NULL,
                  snapshot BLOB, principal_id TEXT NOT NULL, work_item_id TEXT NOT NULL,
                  receipt_id TEXT NOT NULL, PRIMARY KEY(document_id,revision));
                CREATE TABLE IF NOT EXISTS document_mutations(
                  project_id TEXT NOT NULL, space_id TEXT NOT NULL, principal_id TEXT NOT NULL,
                  mutation_id TEXT NOT NULL, intent_sha256 TEXT NOT NULL, result_json TEXT NOT NULL,
                  PRIMARY KEY(project_id,space_id,principal_id,mutation_id));
                CREATE TABLE IF NOT EXISTS document_tasks(
                  document_id TEXT NOT NULL, principal_id TEXT NOT NULL, principal_type TEXT NOT NULL,
                  work_item_id TEXT NOT NULL, PRIMARY KEY(document_id,principal_id,principal_type));
                CREATE TABLE IF NOT EXISTS document_tickets(
                  epoch INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT UNIQUE NOT NULL,
                  project_id TEXT NOT NULL, space_id TEXT NOT NULL, document_id TEXT NOT NULL,
                  principal_id TEXT NOT NULL, principal_type TEXT NOT NULL, work_item_id TEXT NOT NULL,
                  permission TEXT NOT NULL, read_grant TEXT NOT NULL, write_grant TEXT,
                  expires_at INTEGER NOT NULL, consumed INTEGER NOT NULL DEFAULT 0, closed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS document_session_commands(
                  project_id TEXT NOT NULL, space_id TEXT NOT NULL, document_id TEXT NOT NULL,
                  principal_id TEXT NOT NULL, mutation_id TEXT NOT NULL, action TEXT NOT NULL,
                  intent TEXT NOT NULL, response TEXT NOT NULL,
                  PRIMARY KEY(project_id,space_id,principal_id,mutation_id));
            """)

    @contextmanager
    def _db(self):
        db = self.store.connect("canvas_collaboration")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _space(self, project_id, space_id):
        project_id, space_id = _id(project_id), _id(space_id)
        value = self.resolve_space(space_id, project_id)
        if not isinstance(value, dict) or value.get("project_id") != project_id or value.get("space_id") != space_id:
            raise CollaborationDenied("document Space does not belong to project")
        return value

    @staticmethod
    def _view(row, *, content=True):
        keys = ["document_id", "project_id", "space_id", "parent_id", "revision", "deleted",
                "title", "format", "language", "sha256", "updated_at"]
        result = {k: row[k] for k in keys}
        result["deleted"] = bool(result["deleted"])
        if content:
            result["content"] = row["content"]
        return result

    def _document(self, db, project_id, space_id, document_id, *, deleted=False):
        row = db.execute("SELECT * FROM project_documents WHERE document_id=? AND project_id=? AND space_id=?",
                         (_id(document_id), project_id, space_id)).fetchone()
        if row is None or (row["deleted"] and not deleted):
            raise FileNotFoundError("document unavailable")
        if hashlib.sha256(row["content"].encode()).hexdigest() != row["sha256"]:
            raise RuntimeError("document revision integrity failure")
        return row

    def prepare(self, *, project_id, space_id, document_id, principal_id, principal_type="user", permission="write"):
        """Explicit owner-UI admission. Agent callers must supply an existing task.

        This method must only be composed behind the existing owner bearer gate.
        Never call it to repair a revoked grant or a paused task automatically.
        """
        space = self._space(project_id, space_id)
        _id(document_id); _id(principal_id)
        if principal_type != "user" or permission not in {"read", "write"}:
            raise CollaborationDenied("only authenticated user can prepare document task")
        run_id = self.resolve_run(project_id) if self.resolve_run else space.get("run_id")
        if not run_id or self.control.durable.run_status(run_id, self.owner)["state"] != "RUNNING":
            raise CollaborationDenied("resume project run before editing documents")
        with self._db() as db:
            existing = db.execute("SELECT work_item_id FROM document_tasks WHERE document_id=? AND principal_id=? AND principal_type=?",
                                  (document_id, principal_id, principal_type)).fetchone()
        if existing:
            previous_task = self.control.work_item_info(existing["work_item_id"], self.owner)
            if previous_task["run_id"] == run_id:
                return existing["work_item_id"]
        if getattr(self.store, "backend", "sqlite") == "postgres":
            self.store.require_membership(write=True)
        caps = ["canvas.collab.read"] + (["canvas.collab.write"] if permission == "write" else [])
        # Stable identity prevents duplicate task admission after a lost response.
        digest = hashlib.sha256(_json([project_id, space_id, document_id, principal_id, run_id]).encode()).hexdigest()[:32]
        task = self.control.create_work_item(run_id, self.owner, work_item_id="WI-document-" + digest,
            external_key="document-task-" + digest,
            objective="Edit Space document", assignee_user_id=principal_id, required_capabilities=caps,
            metadata={"workspace_id": project_id, "space_id": space_id, "document_id": document_id,
                      "canvas_collaboration": True, "owner_configured": True})
        if task["state"] == "PENDING":
            current = self.control.authorization.list_grants(self.owner, principal_type="user", principal_id=principal_id)["items"]
            for cap in caps:
                if not any(g["capability"] == cap and g["scope_type"] == "work_item" and g["scope_id"] == task["work_item_id"] for g in current):
                    self.control.authorization_grant(self.owner, principal_type="user", principal_id=principal_id,
                        capability=cap, scope_type="work_item", scope_id=task["work_item_id"])
            self.control.transition_work_item(task["work_item_id"], self.owner, "RUNNING")
        with self._db() as db:
            db.execute("INSERT INTO document_tasks VALUES(?,?,?,?) ON CONFLICT(document_id,principal_id,principal_type) DO UPDATE SET work_item_id=excluded.work_item_id",
                       (document_id, principal_id, principal_type, task["work_item_id"]))
        return task["work_item_id"]

    def _authorization(self, *, project_id, space_id, document_id, principal_id, principal_type, work_item_id, action):
        self._space(project_id, space_id)
        _id(principal_id)
        if principal_type not in {"user", "agent"}:
            raise CollaborationDenied("invalid document principal")
        if not work_item_id:
            with self._db() as db:
                row = db.execute("SELECT work_item_id FROM document_tasks WHERE document_id=? AND principal_id=? AND principal_type=?",
                                 (document_id, principal_id, principal_type)).fetchone()
            if not row:
                raise CollaborationDenied("document task required")
            work_item_id = row["work_item_id"]
        item = self.control.work_item_info(work_item_id, self.owner)
        meta = item.get("metadata", {})
        assigned = "assignee_user_id" if principal_type == "user" else "assignee_agent_id"
        if (item["state"] != "RUNNING" or item.get(assigned) != principal_id or
            any(meta.get(k) != v for k, v in {"workspace_id": project_id, "space_id": space_id, "document_id": document_id}.items()) or
            self.control.durable.run_status(item["run_id"], self.owner)["state"] != "RUNNING"):
            raise CollaborationDenied("document task inactive or scope mismatch")
        grants = {}
        for mode in ("read", "write") if action == "write" else ("read",):
            cap = "canvas.collab." + mode
            if cap not in item.get("required_capabilities", []):
                raise CollaborationDenied("document task capability missing")
            decision = self.control.authorization.authorize(self.owner, principal_type=principal_type,
                principal_id=principal_id, capability=cap, scope_type="work_item", scope_id=work_item_id,
                context={"actual_cost": 0.0, "interactive": principal_type == "user"}, local_owner=False)
            if decision.get("allowed") is not True or not decision.get("grant_id"):
                raise CollaborationDenied("document Grant missing or revoked")
            grants[mode] = decision["grant_id"]
        return {"project_id": project_id, "space_id": space_id, "document_id": document_id,
                "principal_id": principal_id, "principal_type": principal_type,
                "work_item_id": work_item_id, "run_id": item["run_id"], "grants": grants}

    def _guard(self, db, auth, action):
        """Order snapshot writes against central revocation/run/task changes."""
        role = begin_authority_guard(db, self.store, self.control.durable.root / "durable.sqlite3", owner=self.owner)
        if action == "write" and role == "reader":
            raise CollaborationDenied("document tenant is read-only")
        item = guard_query(db, self.store, "SELECT * FROM gov.work_items WHERE work_item_id=? AND owner=?",
                          (auth["work_item_id"], self.owner)).fetchone()
        assigned = "assignee_user_id" if auth["principal_type"] == "user" else "assignee_agent_id"
        if not item or item["state"] != "RUNNING" or item[assigned] != auth["principal_id"]:
            raise CollaborationDenied("document task no longer active")
        meta = json.loads(item["metadata_json"])
        if any(meta.get(k) != auth[v] for k, v in {"workspace_id": "project_id", "space_id": "space_id", "document_id": "document_id"}.items()):
            raise CollaborationDenied("document task scope changed")
        run = guard_query(db, self.store, "SELECT state FROM core.runs WHERE run_id=? AND owner=?", (item["run_id"], self.owner)).fetchone()
        if not run or run["state"] != "RUNNING":
            raise CollaborationDenied("document run no longer active")
        for mode, grant_id in auth["grants"].items():
            grant = guard_query(db, self.store, "SELECT * FROM auth.authorization_grants WHERE grant_id=? AND owner=?", (grant_id, self.owner)).fetchone()
            if (not grant or grant["revoked"] or grant["principal_id"] != auth["principal_id"] or
                grant["principal_type"] != auth["principal_type"] or grant["capability"] != "canvas.collab." + mode or
                grant["scope_type"] != "work_item" or grant["scope_id"] != auth["work_item_id"] or
                "canvas.collab." + mode not in json.loads(item["required_capabilities_json"]) or
                (grant["expires_at"] is not None and grant["expires_at"] <= self.control.authorization.clock())):
                raise CollaborationDenied("document Grant no longer active")

    def dispatch(self, action, payload, *, project_id, principal_id, principal_type="user", work_item_id=None):
        if action not in DOCUMENT_ACTIONS or not isinstance(payload, dict):
            raise ValueError("unsupported document action")
        if set(payload) & {"owner", "principal", "principal_id", "principal_type", "grant", "grant_id", "grants", "permission", "work_item_id", "run_id", "capabilities", "path"}:
            raise CollaborationDenied("browser cannot supply document authority")
        space_id = _id(payload.get("space_id"))
        self._space(project_id, space_id)
        if action == "document_list":
            limit = payload.get("limit", 50)
            if type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError("document limit must be 1..100")
            cursor = payload.get("cursor", "")
            if not isinstance(cursor, str) or len(cursor) > 80:
                raise ValueError("invalid document cursor")
            with self._db() as db:
                rows = db.execute("SELECT * FROM project_documents WHERE project_id=? AND space_id=? AND deleted=0 AND document_id>? ORDER BY document_id LIMIT ?",
                                  (project_id, space_id, cursor, limit + 1)).fetchall()
            items = []
            for row in rows[:limit]:
                try:
                    self._authorization(project_id=project_id, space_id=space_id, document_id=row["document_id"],
                        principal_id=principal_id, principal_type=principal_type, work_item_id=work_item_id, action="read")
                except CollaborationDenied:
                    continue
                items.append(self._view(row, content=False))
            return {"items": items, "next_cursor": rows[limit - 1]["document_id"] if len(rows) > limit else None}
        mutation_id = payload.get("mutation_id") or payload.get("request_key")
        document_id = payload.get("document_id")
        if action == "document_create" and not document_id:
            if not isinstance(mutation_id, str) or not 1 <= len(mutation_id) <= 160:
                raise ValueError("document mutation_id required")
            document_id = "doc-" + hashlib.sha256(_json([project_id, space_id, principal_id, mutation_id]).encode()).hexdigest()[:32]
        document_id = _id(document_id)
        # Admission only on explicit user create/session. Ordinary reads/saves
        # never recreate revoked rights. Existing agent tasks are supplied by host.
        if action in {"document_create", "document_session"} and not work_item_id and principal_type == "user":
            work_item_id = self.prepare(project_id=project_id, space_id=space_id, document_id=document_id,
                                        principal_id=principal_id, permission="write")
        writable = action in {"document_create", "document_save", "document_restore", "document_delete"}
        auth = self._authorization(project_id=project_id, space_id=space_id, document_id=document_id,
            principal_id=principal_id, principal_type=principal_type, work_item_id=work_item_id,
            action="write" if writable else "read")
        if action == "document_session":
            if not isinstance(mutation_id, str) or not 1 <= len(mutation_id) <= 160:
                raise ValueError("session mutation_id required")
            permission = "read"
            try:
                self._authorization(project_id=project_id, space_id=space_id, document_id=document_id,
                    principal_id=principal_id, principal_type=principal_type, work_item_id=auth["work_item_id"], action="write")
                permission = "write"
            except CollaborationDenied:
                pass
            return self.issue(**{k: auth[k] for k in ("project_id", "space_id", "document_id", "principal_id", "principal_type", "work_item_id")},
                              permission=permission, mutation_id=mutation_id)
        if action == "document_session_close":
            if not isinstance(mutation_id, str) or not 1 <= len(mutation_id) <= 160:
                raise ValueError("session mutation_id required")
            epoch = payload.get("epoch")
            if type(epoch) is not int or epoch < 1:
                raise ValueError("session epoch required")
            scope = (project_id, space_id, principal_id, mutation_id)
            intent = _json([document_id, epoch])
            with self._db() as db:
                self._guard(db, auth, "read")
                if db.execute("SELECT 1 FROM document_mutations WHERE project_id=? AND space_id=? AND principal_id=? AND mutation_id=?", scope).fetchone():
                    raise SnapshotConflict("request key already used by a document mutation")
                replay = db.execute("SELECT * FROM document_session_commands WHERE project_id=? AND space_id=? AND principal_id=? AND mutation_id=?", scope).fetchone()
                if replay:
                    if replay["action"] != action or replay["intent"] != intent:
                        raise SnapshotConflict("session key already bound to another command")
                    return json.loads(replay["response"])
                db.execute("UPDATE document_tickets SET closed=1 WHERE document_id=? AND principal_id=? AND epoch=?",
                           (document_id, principal_id, epoch))
                result = {"closed": True, "receipt_id": "document-session-receipt-" + secrets.token_hex(16), "mutation_id": mutation_id}
                db.execute("INSERT INTO document_session_commands VALUES(?,?,?,?,?,?,?,?)", (project_id, space_id, document_id, principal_id, mutation_id, action, intent, _json(result)))
            return result
        if writable:
            return self._mutate(action, payload, auth, mutation_id)
        with self._db() as db:
            self._guard(db, auth, "read")
            row = self._document(db, project_id, space_id, document_id, deleted=action in {"document_history", "document_diff"})
            if action == "document_get":
                version = db.execute("SELECT receipt_id FROM document_versions WHERE document_id=? AND revision=?", (document_id, row["revision"])).fetchone()
                return {**self._view(row), "receipt_id": version["receipt_id"] if version else None, "committed": True}
            if action == "document_history":
                before = payload.get("before_revision", row["revision"] + 1)
                if type(before) is not int or before < 1:
                    raise ValueError("invalid history cursor")
                versions = db.execute("SELECT revision,value_json,principal_id,receipt_id FROM document_versions WHERE document_id=? AND revision<? ORDER BY revision DESC LIMIT 50", (document_id, before)).fetchall()
                return {"items": [{**{k: v[k] for k in ("revision", "principal_id", "receipt_id")},
                                   "document": {k: x for k, x in json.loads(v["value_json"]).items() if k != "content"}} for v in versions],
                        "next_revision": versions[-1]["revision"] if len(versions) == 50 else None}
            if action == "document_export":
                return {"filename": document_id + (".md" if row["format"] == "markdown" else ".txt"),
                        "content": row["content"], "media_type": "text/markdown" if row["format"] == "markdown" else "text/plain",
                        "revision": row["revision"], "sha256": row["sha256"]}
            if action == "document_diff":
                revision = payload.get("revision")
                if type(revision) is not int or revision < 1:
                    raise ValueError("revision required")
                previous = db.execute("SELECT value_json FROM document_versions WHERE document_id=? AND revision=?", (document_id, revision)).fetchone()
                if not previous:
                    raise FileNotFoundError("document revision unavailable")
                diff = "".join(difflib.unified_diff(json.loads(previous[0])["content"].splitlines(True), row["content"].splitlines(True),
                    fromfile=f"revision/{revision}", tofile=f"revision/{row['revision']}"))
                if len(diff.encode()) > MAX_CONTENT:
                    raise ValueError("document diff exceeds preview limit")
                return {"diff": diff, "revision": row["revision"], "previous_revision": revision}

    def _mutate(self, action, payload, auth, mutation_id, *, snapshot=None, session_context=None):
        if not isinstance(mutation_id, str) or not 1 <= len(mutation_id) <= 160:
            raise ValueError("mutation_id required (1..160 characters)")
        key = hashlib.sha256(_json([auth["project_id"], auth["space_id"], auth["principal_id"], mutation_id]).encode()).hexdigest()
        operation = self.control.durable.create_operation(auth["run_id"], self.owner,
            kind=action, idempotency_key="document-" + key, initial_state="RUNNING", cleanup_policy="preserve")
        if operation["state"] in {"FAILED", "CANCELLED", "CANCEL_REQUESTED"}:
            raise SnapshotConflict("document mutation refused previously; review and use a new mutation_id")
        try:
            result = self._mutate_transaction(action, payload, auth, mutation_id,
                snapshot=snapshot, session_context=session_context, operation_id=operation["operation_id"])
        except Exception:
            if operation["state"] == "RUNNING":
                self.control.durable.update_operation(operation["operation_id"], self.owner, state="FAILED",
                    error={"reason": "document mutation refused"})
            raise
        # The receipt and revision are already durable atomically. Repair a lost
        # projection response by consulting that same receipt, never reapplying.
        if operation["state"] in {"RUNNING", "UNCERTAIN"}:
            self.control.durable.update_operation(operation["operation_id"], self.owner, state="SUCCEEDED",
                result={k: result[k] for k in ("receipt_id", "document_id", "revision", "sha256", "work_item_id")})
        return result

    def _mutate_transaction(self, action, payload, auth, mutation_id, *, snapshot=None, session_context=None, operation_id=None):
        if not isinstance(mutation_id, str) or not 1 <= len(mutation_id) <= 160:
            raise ValueError("mutation_id required (1..160 characters)")
        expected = payload.get("expected_revision", 0 if action == "document_create" else None)
        if type(expected) is not int or expected < 0:
            raise ValueError("expected_revision required")
        intent = hashlib.sha256(_json([action, auth["document_id"], payload, hashlib.sha256(snapshot).hexdigest() if snapshot else None]).encode()).hexdigest()
        scope = (auth["project_id"], auth["space_id"], auth["principal_id"], mutation_id)
        with self._db() as db:
            self._guard(db, auth, "write")
            if db.execute("SELECT 1 FROM document_session_commands WHERE project_id=? AND space_id=? AND principal_id=? AND mutation_id=?", scope).fetchone():
                raise SnapshotConflict("request key already used by a document session command")
            if session_context is not None:
                current_ticket = self._ticket(db, session_context)
                if not current_ticket["consumed"] or current_ticket["permission"] != "write":
                    raise CollaborationDenied("document session not writable")
            replay = db.execute("SELECT * FROM document_mutations WHERE project_id=? AND space_id=? AND principal_id=? AND mutation_id=?", scope).fetchone()
            if replay:
                if replay["intent_sha256"] != intent:
                    raise SnapshotConflict("mutation_id already bound to different document content")
                return {**json.loads(replay["result_json"]), "idempotent_replay": True}
            operation = guard_query(db, self.store, "SELECT state,run_id FROM core.operations WHERE operation_id=? AND owner=?",
                                    (operation_id, self.owner)).fetchone()
            if not operation or operation["state"] != "RUNNING" or operation["run_id"] != auth["run_id"]:
                raise CollaborationDenied("document operation cancelled or no longer active")
            row = db.execute("SELECT * FROM project_documents WHERE document_id=?", (auth["document_id"],)).fetchone()
            if not row and db.execute("SELECT COUNT(*) FROM project_documents WHERE project_id=? AND deleted=0", (auth["project_id"],)).fetchone()[0] >= 512:
                raise ValueError("project document quota reached")
            if row and (row["project_id"] != auth["project_id"] or row["space_id"] != auth["space_id"]):
                raise CollaborationDenied("document scope mismatch")
            if (action == "document_create" and row) or (action != "document_create" and (not row or row["deleted"])):
                raise SnapshotConflict("document deleted or already exists")
            if (row["revision"] if row else 0) != expected:
                raise SnapshotConflict("document revision changed; keep draft and reload")
            value = self._view(row) if row else {"document_id": auth["document_id"], "project_id": auth["project_id"], "space_id": auth["space_id"], "parent_id": None, "deleted": False, "content": ""}
            if action == "document_restore":
                rev = payload.get("revision")
                if type(rev) is not int or rev < 1:
                    raise ValueError("restore revision required")
                previous = db.execute("SELECT value_json FROM document_versions WHERE document_id=? AND revision=?", (auth["document_id"], rev)).fetchone()
                if not previous:
                    raise FileNotFoundError("restore revision unavailable")
                restored = json.loads(previous[0])
                if restored["deleted"]:
                    raise ValueError("cannot restore a tombstone")
                value.update({k: restored[k] for k in ("title", "format", "language", "content", "parent_id")})
            elif action == "document_delete":
                if db.execute("SELECT 1 FROM project_documents WHERE parent_id=? AND deleted=0", (auth["document_id"],)).fetchone():
                    raise SnapshotConflict("move or delete child documents first")
                value["deleted"] = True
            else:
                value.update(_metadata({**value, **payload}))
                value["content"] = _content(payload.get("content", value["content"]))
                value["parent_id"] = payload.get("parent_id", value.get("parent_id"))
            if action != "document_delete":
                parent = value.get("parent_id")
                seen = {auth["document_id"]}
                while parent:
                    if parent in seen:
                        raise ValueError("document hierarchy cycle")
                    seen.add(parent)
                    parent_row = self._document(db, auth["project_id"], auth["space_id"], parent)
                    parent = parent_row["parent_id"]
            value.update(revision=expected + 1, updated_at=self.clock(), sha256=hashlib.sha256(value["content"].encode()).hexdigest())
            digest = hashlib.sha256(snapshot).hexdigest() if snapshot is not None else None
            db.execute("INSERT INTO project_documents(document_id,project_id,space_id,parent_id,revision,deleted,title,format,language,content,sha256,updated_at,snapshot,snapshot_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET parent_id=excluded.parent_id,revision=excluded.revision,deleted=excluded.deleted,title=excluded.title,format=excluded.format,language=excluded.language,content=excluded.content,sha256=excluded.sha256,updated_at=excluded.updated_at,snapshot=excluded.snapshot,snapshot_sha256=excluded.snapshot_sha256",
                tuple(value[k] for k in ("document_id", "project_id", "space_id", "parent_id", "revision", "deleted", "title", "format", "language", "content", "sha256", "updated_at")) + (snapshot, digest))
            receipt_id = "document-receipt-" + secrets.token_hex(16)
            result = {**value, "receipt_id": receipt_id, "mutation_id": mutation_id,
                      "work_item_id": auth["work_item_id"], "run_id": auth["run_id"], "committed": True}
            result["operation_id"] = operation_id
            db.execute("INSERT INTO document_versions VALUES(?,?,?,?,?,?,?)", (auth["document_id"], value["revision"], _json(value), snapshot, auth["principal_id"], auth["work_item_id"], receipt_id))
            db.execute("INSERT INTO document_mutations VALUES(?,?,?,?,?,?)", scope + (intent, _json(result)))
            if action == "document_delete" or snapshot is None:
                # An external CAS edit invalidates live CRDT sessions. A fresh
                # connection must load/reseed from the new authoritative source.
                db.execute("UPDATE document_tickets SET closed=1 WHERE document_id=?", (auth["document_id"],))
        return result

    def issue(self, *, project_id, space_id, document_id, principal_id, work_item_id,
              principal_type="user", permission="read", ttl_seconds=300, mutation_id=None):
        if permission not in {"read", "write"} or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
            raise ValueError("invalid document session settings")
        auth = self._authorization(project_id=project_id, space_id=space_id, document_id=document_id,
            principal_id=principal_id, principal_type=principal_type, work_item_id=work_item_id, action=permission)
        token = secrets.token_urlsafe(48)
        expires = int((self.clock() + ttl_seconds) * 1000)
        intent = _json([document_id, work_item_id, permission, ttl_seconds])
        if mutation_id is not None and (not isinstance(mutation_id, str) or not 1 <= len(mutation_id) <= 160):
            raise ValueError("session mutation_id required")
        from sentra_remote.secrets import protect_secret, unprotect_secret
        with self._db() as db:
            self._guard(db, auth, permission)
            self._document(db, project_id, space_id, document_id)
            if mutation_id is not None:
                if db.execute("SELECT 1 FROM document_mutations WHERE project_id=? AND space_id=? AND principal_id=? AND mutation_id=?", (project_id, space_id, principal_id, mutation_id)).fetchone():
                    raise SnapshotConflict("request key already used by a document mutation")
                replay = db.execute("SELECT * FROM document_session_commands WHERE project_id=? AND space_id=? AND principal_id=? AND mutation_id=?", (project_id, space_id, principal_id, mutation_id)).fetchone()
                if replay:
                    if replay["action"] != "document_session" or replay["intent"] != intent:
                        raise SnapshotConflict("session key already bound to another command")
                    result = json.loads(unprotect_secret(replay["response"]))
                    ticket = db.execute("SELECT consumed,closed,expires_at FROM document_tickets WHERE epoch=?", (result["epoch"],)).fetchone()
                    if not ticket or ticket["closed"] or ticket["consumed"] or ticket["expires_at"] <= int(self.clock()*1000):
                        raise CollaborationDenied("session ticket consumed or expired; reconnect with new request_key")
                    return result
            db.execute("DELETE FROM document_tickets WHERE expires_at<=?", (int(self.clock()*1000),))
            if db.execute("SELECT COUNT(*) FROM document_tickets").fetchone()[0] >= 10000:
                raise CollaborationDenied("document session quota reached")
            cur = db.execute("INSERT INTO document_tickets(fingerprint,project_id,space_id,document_id,principal_id,principal_type,work_item_id,permission,read_grant,write_grant,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), project_id, space_id, document_id, principal_id,
                 principal_type, work_item_id, permission, auth["grants"]["read"], auth["grants"].get("write"), expires))
            epoch = db.execute("SELECT epoch FROM document_tickets WHERE fingerprint=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()["epoch"]
            result = {"token": token, "project_id": project_id, "space_id": space_id, "document_id": document_id,
                "documentName": f"sentra-document:v1:{project_id}:{document_id}", "permission": permission,
                "epoch": epoch, "expiresAt": expires, "receipt_id": "document-session-receipt-" + secrets.token_hex(16)}
            if mutation_id is not None:
                protected = protect_secret(_json(result))
                if not protected.startswith(("dpapi:", "keyring:")):
                    raise RuntimeError("document session replay requires OS protected storage")
                db.execute("INSERT INTO document_session_commands VALUES(?,?,?,?,?,?,?,?)", (project_id, space_id, document_id, principal_id, mutation_id, "document_session", intent, protected))
        return result

    @staticmethod
    def _context(row):
        return {"workspaceId": row["project_id"], "spaceId": row["space_id"], "documentId": row["document_id"],
                "principalId": row["principal_id"], "permission": row["permission"], "epoch": row["epoch"], "expiresAt": row["expires_at"]}

    def _ticket(self, db, params, *, token=False):
        if token:
            secret = params.get("token")
            if not isinstance(secret, str) or not 24 <= len(secret) <= 4096:
                raise CollaborationDenied("invalid document ticket")
            row = db.execute("SELECT * FROM document_tickets WHERE fingerprint=?", (hashlib.sha256(secret.encode()).hexdigest(),)).fetchone()
        else:
            row = db.execute("SELECT * FROM document_tickets WHERE epoch=?", (params.get("epoch"),)).fetchone()
        if not row or row["closed"] or row["expires_at"] <= int(self.clock()*1000):
            raise CollaborationDenied("document ticket expired or revoked")
        for key, value in self._context(row).items():
            if ((token and key in {"workspaceId", "documentId"}) or not token) and params.get(key) != value:
                raise CollaborationDenied("document ticket scope mismatch")
        return row

    def host_call(self, method, params):
        if method not in DOCUMENT_HOST_METHODS or not isinstance(params, dict):
            raise ValueError("unsupported document host callback")
        context = params.get("context", params)
        with self._db() as db:
            ticket = self._ticket(db, context, token=method == "documentResolveGrant")
        if any(k in params and params[k] != ticket[v] for k, v in {
            "workspaceId": "project_id", "spaceId": "space_id", "documentId": "document_id", "principalId": "principal_id", "epoch": "epoch"}.items()):
            raise CollaborationDenied("document callback scope mismatch")
        action = "write" if method == "documentCommitSnapshot" else params.get("action", "read")
        if action not in {"read", "write"} or (action == "write" and ticket["permission"] != "write"):
            raise CollaborationDenied("read-only document session")
        auth = self._authorization(**{k: ticket[k] for k in ("project_id", "space_id", "document_id", "principal_id", "principal_type", "work_item_id")}, action=action)
        for mode, grant_id in auth["grants"].items():
            if ticket[mode + "_grant"] != grant_id:
                raise CollaborationDenied("document session Grant changed")
        if method == "documentResolveGrant":
            if ticket["consumed"]:
                raise CollaborationDenied("document ticket already consumed")
            return self._context(ticket)
        if method == "documentCheckGrant":
            return True
        if method == "documentConsumeNonce":
            if params.get("fingerprint") != ticket["fingerprint"]:
                return False
            with self._db() as db:
                self._guard(db, auth, "read")
                return db.execute("UPDATE document_tickets SET consumed=1 WHERE epoch=? AND consumed=0 AND closed=0 AND expires_at>?",
                                  (ticket["epoch"], int(self.clock()*1000))).rowcount == 1
        if not ticket["consumed"]:
            raise CollaborationDenied("document session not authenticated")
        if method == "documentLoadSnapshot":
            with self._db() as db:
                self._guard(db, auth, "read")
                self._ticket(db, context)
                row = self._document(db, ticket["project_id"], ticket["space_id"], ticket["document_id"])
                snapshot = bytes(row["snapshot"]) if row["snapshot"] is not None else None
                if snapshot is not None and hashlib.sha256(snapshot).hexdigest() != row["snapshot_sha256"]:
                    raise RuntimeError("document snapshot integrity failure")
                return {"revision": row["revision"], "snapshot": base64.b64encode(snapshot).decode() if snapshot is not None else None,
                        "document": self._view(row)}
        raw = params.get("snapshot")
        if not isinstance(raw, str) or len(raw) > 1400000:
            raise ValueError("invalid bounded document snapshot")
        snapshot = base64.b64decode(raw, validate=True)
        if len(snapshot) > 1048576:
            raise ValueError("document snapshot too large")
        projection = params.get("presentation")
        if not isinstance(projection, dict) or set(projection) != {"content", "metadata"}:
            raise ValueError("document projection required")
        if not isinstance(projection["metadata"], dict) or set(projection["metadata"]) - {"title", "format", "language"}:
            raise ValueError("invalid document metadata projection")
        meta = _metadata(projection["metadata"])
        content = _content(projection["content"])
        # The trusted sidecar validates Yjs binary and derives this projection.
        # Its private bearer never reaches the renderer.
        payload = {**meta, "content": content, "expected_revision": params.get("expectedRevision")}
        mutation_id = params.get("mutation_id")
        return self._mutate("document_save", payload, auth, mutation_id, snapshot=snapshot, session_context=context)
