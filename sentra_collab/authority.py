"""Real ControlPlane authorization for presentation-only collaboration.

The store contains opaque one-use tickets and CRDT snapshots, not another grant
or membership authority. Every read/write reconsults the existing authorization
service and the original grant IDs. A new equivalent grant cannot resurrect a
ticket issued under a revoked grant. Namespace persistence uses the central
ControlPlaneStore, with shared nonce consumption and snapshot CAS transactions.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager

from sentra_mcp.services.control_plane import ControlPlaneService


ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MAX_SNAPSHOT_BYTES = 1024 * 1024


class CollaborationDenied(PermissionError):
    pass


class SnapshotConflict(RuntimeError):
    pass


def _id(value):
    if not isinstance(value, str) or not ID.fullmatch(value) or value in {"__proto__", "constructor", "prototype"}:
        raise CollaborationDenied("invalid collaboration scope")
    return value


def validate_presentation(value):
    """Mirror the allowed Yjs projection; authoritative state is never accepted."""
    if not isinstance(value, dict) or set(value) != {"layout", "nodes", "notes"}:
        raise CollaborationDenied("invalid presentation roots")
    layout, nodes, notes = value["layout"], value["nodes"], value["notes"]
    if (not isinstance(layout, dict) or set(layout) - {"viewport"}
            or not isinstance(nodes, dict) or len(nodes) > 512
            or not isinstance(notes, dict) or len(notes) > 128):
        raise CollaborationDenied("invalid presentation collection")
    def number(n, low, high):
        return type(n) in (float, int) and math.isfinite(n) and low <= n <= high
    if "viewport" in layout:
        viewport = layout["viewport"]
        if (not isinstance(viewport, dict) or set(viewport) != {"x", "y", "zoom"}
                or not number(viewport["x"], -1e6, 1e6)
                or not number(viewport["y"], -1e6, 1e6)
                or not number(viewport["zoom"], .1, 5)):
            raise CollaborationDenied("invalid viewport")
    for key, node in nodes.items():
        _id(key)
        if (not isinstance(node, dict) or set(node) != {"x", "y", "width", "height"}
                or not number(node["x"], -1e6, 1e6) or not number(node["y"], -1e6, 1e6)
                or not number(node["width"], 100, 2000) or not number(node["height"], 80, 1600)):
            raise CollaborationDenied("invalid node geometry")
    for key, text in notes.items():
        _id(key)
        if not isinstance(text, str) or len(text) > 12000:
            raise CollaborationDenied("invalid note")
    return value


class CollaborationAuthority:
    def __init__(self, control: ControlPlaneService, *, owner: str, clock=time.time):
        if not isinstance(control, ControlPlaneService) or not owner:
            raise ValueError("real control plane and owner required")
        self.control, self.owner, self.clock = control, owner, clock
        self.store = control.store
        with self._db() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("collaboration store requires a newer runtime")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS collaboration_tickets(
                  epoch INTEGER PRIMARY KEY AUTOINCREMENT,
                  fingerprint TEXT UNIQUE NOT NULL, workspace TEXT NOT NULL,
                  principal TEXT NOT NULL, principal_type TEXT NOT NULL,
                  work_item TEXT NOT NULL, permission TEXT NOT NULL,
                  read_grant TEXT NOT NULL, write_grant TEXT,
                  expires INTEGER NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS collab_ticket_scope ON collaboration_tickets(workspace,principal,epoch);
                CREATE TABLE IF NOT EXISTS collaboration_snapshots(
                  workspace TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                  snapshot BLOB NOT NULL, sha256 TEXT NOT NULL,
                  presentation TEXT NOT NULL, updated INTEGER NOT NULL);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def _db(self):
        db = self.store.connect("canvas_collaboration")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _now(self):
        return int(self.clock() * 1000)

    def _authorize(self, row, action):
        if action not in {"read", "write"} or (action == "write" and row["permission"] != "write"):
            return False
        item = self.control.work_item_info(row["work_item"], self.owner)
        run = self.control.durable.run_status(item["run_id"], self.owner)
        assigned = "assignee_user_id" if row["principal_type"] == "user" else "assignee_agent_id"
        if (run["state"] != "RUNNING" or item["state"] != "RUNNING" or item.get(assigned) not in {None, "", row["principal"]}
                or item.get("metadata", {}).get("workspace_id") != row["workspace"]
                or "canvas.collab." + action not in (item.get("required_capabilities") or [])):
            return False
        result = self.control.authorization.authorize(self.owner,
            principal_type=row["principal_type"], principal_id=row["principal"],
            capability="canvas.collab." + action, scope_type="work_item", scope_id=row["work_item"],
            context={"actual_cost": 0.0, "interactive": row["principal_type"] == "user"},
            local_owner=False)
        return result.get("allowed") is True and result.get("grant_id") == row[action + "_grant"]

    def _begin_authority_guard(self, db):
        # These databases are read guards, not replicated grant authorities.
        # BEGIN IMMEDIATE locks attached writers through the snapshot commit,
        # ordering it against revoke, task state changes and run cancellation.
        for alias, path in (("auth", self.store.path_for("authorization")),
                            ("gov", self.store.path_for("governance")),
                            ("core", self.control.durable.root / "durable.sqlite3")):
            db.execute("ATTACH DATABASE ? AS " + alias, (str(path),))
        db.execute("BEGIN IMMEDIATE")

    def _guard_current(self, db, row, action):
        item = db.execute("SELECT * FROM gov.work_items WHERE work_item_id=? AND owner=?",
                          (row["work_item"], self.owner)).fetchone()
        if item is None or item["state"] != "RUNNING":
            raise CollaborationDenied("collaboration task no longer active")
        assigned = "assignee_user_id" if row["principal_type"] == "user" else "assignee_agent_id"
        if (item[assigned] not in {None, "", row["principal"]}
                or json.loads(item["metadata_json"]).get("workspace_id") != row["workspace"]
                or "canvas.collab." + action not in json.loads(item["required_capabilities_json"])):
            raise CollaborationDenied("collaboration task scope changed")
        run = db.execute("SELECT state FROM core.runs WHERE run_id=? AND owner=?",
                         (item["run_id"], self.owner)).fetchone()
        if run is None or run["state"] != "RUNNING":
            raise CollaborationDenied("collaboration run no longer active")
        for permission in ("read", "write") if action == "write" else ("read",):
            grant = db.execute("SELECT * FROM auth.authorization_grants WHERE grant_id=? AND owner=?",
                               (row[permission + "_grant"], self.owner)).fetchone()
            if (grant is None or grant["revoked"] or grant["principal_id"] != row["principal"]
                    or grant["principal_type"] != row["principal_type"]
                    or (grant["expires_at"] is not None and grant["expires_at"] <= self.control.authorization.clock())):
                raise CollaborationDenied("collaboration grant no longer active")

    def issue(self, *, workspace_id, principal_id, work_item_id,
              principal_type="user", permission="read", ttl_seconds=300):
        workspace_id, principal_id = _id(workspace_id), _id(principal_id)
        if (principal_type not in {"user", "agent"} or permission not in {"read", "write"}
                or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900):
            raise CollaborationDenied("invalid collaboration ticket configuration")
        item = self.control.work_item_info(work_item_id, self.owner)
        if item.get("metadata", {}).get("workspace_id") != workspace_id or item["state"] != "RUNNING":
            raise CollaborationDenied("collaboration task not active in workspace")
        grants = {}
        for action in (["read", "write"] if permission == "write" else ["read"]):
            assigned = "assignee_user_id" if principal_type == "user" else "assignee_agent_id"
            if (item.get(assigned) not in {None, "", principal_id}
                    or "canvas.collab." + action not in (item.get("required_capabilities") or [])):
                raise CollaborationDenied("collaboration principal/capability not bound to task")
            decision = self.control.authorization.authorize(self.owner,
                principal_type=principal_type, principal_id=principal_id,
                capability="canvas.collab." + action, scope_type="work_item", scope_id=work_item_id,
                context={"actual_cost": 0.0, "interactive": principal_type == "user"}, local_owner=False)
            if decision.get("allowed") is not True or not decision.get("grant_id"):
                raise CollaborationDenied("collaboration grant missing")
            grants[action] = decision["grant_id"]
        token = secrets.token_urlsafe(48)
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        expires = self._now() + ttl_seconds * 1000
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM collaboration_tickets WHERE expires<=?", (self._now(),))
            if db.execute("SELECT COUNT(*) FROM collaboration_tickets").fetchone()[0] >= 10000:
                raise CollaborationDenied("collaboration ticket quota reached")
            cur = db.execute("INSERT INTO collaboration_tickets(fingerprint,workspace,principal,principal_type,"
                "work_item,permission,read_grant,write_grant,expires) VALUES(?,?,?,?,?,?,?,?,?)",
                (fingerprint,workspace_id,principal_id,principal_type,work_item_id,permission,
                 grants["read"],grants.get("write"),expires))
            epoch = cur.lastrowid
        return {"token": token, "workspaceId": workspace_id, "principalId": principal_id,
                "permission": permission, "epoch": epoch, "expiresAt": expires,
                "documentName": "sentra-collab:v1:" + workspace_id}

    @staticmethod
    def _context(row):
        return {"workspaceId":row["workspace"], "principalId":row["principal"],
                "permission":row["permission"], "epoch":row["epoch"], "expiresAt":row["expires"]}

    def _row(self, db, context, *, require_permission=True):
        if (not isinstance(context, dict) or type(context.get("epoch")) is not int
                or type(context.get("expiresAt")) is not int):
            raise CollaborationDenied("collaboration context missing")
        row = db.execute("SELECT * FROM collaboration_tickets WHERE epoch=?", (context.get("epoch"),)).fetchone()
        if (row is None or row["expires"] <= self._now()
                or any(context.get(k) != v for k,v in self._context(row).items()
                       if k != "permission" or require_permission or "permission" in context)):
            raise CollaborationDenied("collaboration context does not match issued ticket")
        return row

    def resolve(self, *, token, workspace_id):
        _id(workspace_id)
        if not isinstance(token, str) or not 24 <= len(token) <= 4096:
            raise CollaborationDenied("invalid collaboration token")
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        with self._db() as db:
            row = db.execute("SELECT * FROM collaboration_tickets WHERE fingerprint=?", (fingerprint,)).fetchone()
            if (row is None or row["workspace"] != workspace_id or row["consumed"]
                    or row["expires"] <= self._now() or not self._authorize(row, "read")):
                raise CollaborationDenied("collaboration token not authorized")
            return self._context(row)

    def check(self, context, *, action="read"):
        try:
            with self._db() as db:
                row = self._row(db, context)
                return self._authorize(row, action)
        except (CollaborationDenied, FileNotFoundError, PermissionError, ValueError, sqlite3.Error):
            return False

    def consume(self, context, *, fingerprint):
        with self._db() as db:
            row = self._row(db, context, require_permission=False)
            if row["fingerprint"] != fingerprint or row["consumed"] or not self._authorize(row, "read"):
                return False
            self._begin_authority_guard(db)
            row = self._row(db, context, require_permission=False)
            self._guard_current(db, row, "read")
            return db.execute("UPDATE collaboration_tickets SET consumed=1 WHERE epoch=? AND consumed=0",
                              (row["epoch"],)).rowcount == 1

    def load(self, workspace_id):
        _id(workspace_id)
        with self._db() as db:
            row = db.execute("SELECT * FROM collaboration_snapshots WHERE workspace=?", (workspace_id,)).fetchone()
        if row is None:
            return {"revision": 0, "snapshot": None, "presentation": {"layout":{},"nodes":{},"notes":{}}}
        data = bytes(row["snapshot"])
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise RuntimeError("collaboration snapshot integrity failure")
        return {"revision":row["revision"], "snapshot":base64.b64encode(data).decode(),
                "presentation":json.loads(row["presentation"]), "sha256":row["sha256"]}

    def commit(self, *, context, expected_revision, snapshot, presentation):
        if type(expected_revision) is not int or expected_revision < 0 or not isinstance(snapshot, str):
            raise CollaborationDenied("invalid collaboration snapshot revision")
        if len(snapshot) > (MAX_SNAPSHOT_BYTES * 4 // 3 + 8):
            raise CollaborationDenied("collaboration snapshot exceeds limit")
        try:
            data = base64.b64decode(snapshot, validate=True)
        except (ValueError, TypeError) as exc:
            raise CollaborationDenied("invalid collaboration snapshot encoding") from exc
        if len(data) > MAX_SNAPSHOT_BYTES:
            raise CollaborationDenied("collaboration snapshot exceeds limit")
        validate_presentation(presentation)
        with self._db() as db:
            row = self._row(db, context)
            if not row["consumed"] or not self._authorize(row, "write"):
                raise CollaborationDenied("collaboration write grant not active")
            self._begin_authority_guard(db)
            row = self._row(db, context)
            self._guard_current(db, row, "write")
            current = db.execute("SELECT revision FROM collaboration_snapshots WHERE workspace=?", (row["workspace"],)).fetchone()
            revision = current["revision"] if current else 0
            if revision != expected_revision:
                raise SnapshotConflict("collaboration snapshot changed; reload required")
            revision += 1
            digest = hashlib.sha256(data).hexdigest()
            db.execute("INSERT INTO collaboration_snapshots(workspace,revision,snapshot,sha256,presentation,updated) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(workspace) DO UPDATE SET revision=excluded.revision,"
                "snapshot=excluded.snapshot,sha256=excluded.sha256,presentation=excluded.presentation,updated=excluded.updated",
                (row["workspace"], revision, data, digest,
                 json.dumps(presentation, sort_keys=True, ensure_ascii=False, allow_nan=False), self._now()))
        return {"revision":revision, "sha256":digest, "committed":True}
