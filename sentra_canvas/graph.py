"""Persistent native desktop canvas graph with workspace-scoped operations.

Separate versioned SQLite database prevents touching the existing SENTRA/OMA
data stores or interfering with concurrent installer work.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from sentra_remote.secrets import protect_secret, unprotect_secret

KIND = frozenset({"terminal", "agent", "team", "note"})

class GraphStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA journal_mode=WAL")
        with self._lock, self.db:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version > 5:
                raise RuntimeError("newer Canvas graph database; update SENTRA")
            if version == 0:
                self.db.executescript("""
                    CREATE TABLE nodes (
                        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                        kind TEXT NOT NULL, resource_id TEXT,
                        title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
                        x REAL NOT NULL, y REAL NOT NULL,
                        width INTEGER NOT NULL, height INTEGER NOT NULL,
                        created REAL NOT NULL,
                        UNIQUE(workspace_id,kind,resource_id)
                    );
                    CREATE INDEX nodes_workspace ON nodes(workspace_id);
                    CREATE TABLE links (
                        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                        source TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                        target TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                        created REAL NOT NULL, UNIQUE(workspace_id,source,target)
                    );
                    CREATE INDEX links_workspace ON links(workspace_id);
                    PRAGMA user_version=1;
                """)
        with self._lock, self.db:
            if self.db.execute("PRAGMA user_version").fetchone()[0] < 2:
                self.db.executescript("""
                    CREATE TABLE handoffs (
                        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                        source TEXT NOT NULL, target TEXT NOT NULL,
                        content TEXT NOT NULL, status TEXT NOT NULL,
                        created REAL NOT NULL,
                        FOREIGN KEY(source) REFERENCES nodes(id),
                        FOREIGN KEY(target) REFERENCES nodes(id)
                    );
                    CREATE INDEX handoffs_workspace ON handoffs(workspace_id,created);
                    PRAGMA user_version=2;
                """)
        self.db.execute("PRAGMA foreign_keys=ON")
        with self._lock, self.db:
            if self.db.execute("PRAGMA user_version").fetchone()[0] < 3:
                self.db.execute("ALTER TABLE handoffs ADD COLUMN protected_content TEXT NOT NULL DEFAULT ''")
                self.db.execute("ALTER TABLE handoffs ADD COLUMN request_key TEXT")
                self.db.execute("ALTER TABLE handoffs ADD COLUMN updated REAL NOT NULL DEFAULT 0")
                self.db.execute("CREATE UNIQUE INDEX handoff_requests ON handoffs(workspace_id,request_key)")
                self.db.execute("PRAGMA user_version=3")
        with self._lock, self.db:
            if self.db.execute("PRAGMA user_version").fetchone()[0] < 4:
                self.db.execute("ALTER TABLE handoffs ADD COLUMN receipt_status TEXT NOT NULL DEFAULT 'pending'")
                self.db.execute("ALTER TABLE handoffs ADD COLUMN receipt_updated REAL NOT NULL DEFAULT 0")
                self.db.execute("PRAGMA user_version=4")
        self.db.execute("PRAGMA synchronous=FULL")
        with self._lock, self.db:
            if self.db.execute("PRAGMA user_version").fetchone()[0] < 5:
                self.db.execute("CREATE TABLE collaboration_projection("
                                "workspace TEXT PRIMARY KEY, revision INTEGER NOT NULL)")
                self.db.execute("PRAGMA user_version=5")

    def apply_presentation(self, ws: str, revision: int, presentation: dict) -> bool:
        """Recover a committed CRDT projection in one idempotent transaction.

        Only existing workspace geometry and note text may change. Stale CRDT
        IDs cannot create resources, recreate removed notes, or alter topology.
        The authoritative snapshot remains in the ControlPlane store; this
        revision is an acknowledgement of its local presentation projection.
        """
        from sentra_collab.authority import validate_presentation
        if type(revision) is not int or revision < 0:
            raise ValueError("invalid collaboration projection revision")
        validate_presentation(presentation)
        with self._lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT revision FROM collaboration_projection WHERE workspace=?",
                                  (ws,)).fetchone()
            if revision <= (row["revision"] if row else 0):
                return False
            for ident, node in presentation["nodes"].items():
                self.db.execute("UPDATE nodes SET x=?,y=?,width=?,height=? "
                                "WHERE id=? AND workspace_id=?",
                                (node["x"], node["y"], node["width"], node["height"], ident, ws))
            for ident, text in presentation["notes"].items():
                self.db.execute("UPDATE nodes SET body=? WHERE id=? AND workspace_id=? AND kind='note'",
                                (text, ident, ws))
            self.db.execute("INSERT INTO collaboration_projection(workspace,revision) VALUES(?,?) "
                            "ON CONFLICT(workspace) DO UPDATE SET revision=excluded.revision", (ws, revision))
            return True

    def _read(self, ws: str, ident: str) -> dict:
        row = self.db.execute(
            "SELECT * FROM nodes WHERE id=? AND workspace_id=?", (ident, ws)
        ).fetchone()
        if not row:
            raise PermissionError("canvas node is not accessible")
        return dict(row)

    def _validate_pos(self, x, y):
        a,b = float(x), float(y)
        if not all(math.isfinite(v) and abs(v) < 100000 for v in (a,b)):
            raise ValueError("invalid canvas coordinates")
        return a,b

    def sync(self, ws: str, terminals: list[dict],
             agents: list[dict], teams: list[dict]) -> dict:
        with self._lock, self.db:
            existing = list(self.db.execute("SELECT id,kind,resource_id FROM nodes WHERE workspace_id=?", (ws,)))
            known = {(r["kind"],r["resource_id"]) for r in existing}
            count = len(existing)
            for kind, rows in (("terminal",terminals),("agent",agents),("team",teams)):
                for row in rows:
                    if (kind,row["id"]) in known:
                        self.db.execute(
                            "UPDATE nodes SET title=? WHERE workspace_id=? AND kind=? AND resource_id=?",
                            (row["name"],ws,kind,row["id"]))
                        continue
                    x = 280 + (count % 3) * 530
                    y = 150 + (count // 3) * 365
                    w,h = ((462,300) if kind=="terminal" else
                           (358,250) if kind=="agent" else (365,220))
                    self.db.execute(
                        """INSERT OR IGNORE INTO nodes
                        (id,workspace_id,kind,resource_id,title,body,x,y,width,height,created)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (uuid.uuid4().hex,ws,kind,row["id"],row["name"],"",
                         x,y,w,h,time.time()))
                    count+=1
            return self.snapshot(ws)

    def snapshot(self, ws: str) -> dict:
        with self._lock:
            nodes = [dict(row) for row in self.db.execute(
                "SELECT * FROM nodes WHERE workspace_id=? ORDER BY created",(ws,))]
            links = [dict(row) for row in self.db.execute(
                "SELECT * FROM links WHERE workspace_id=? ORDER BY created",(ws,))]
            return {"nodes":nodes, "links":links}

    def move(self, ws: str, ident: str, x, y) -> dict:
        x,y = self._validate_pos(x,y)
        with self._lock,self.db:
            self._read(ws,ident)
            self.db.execute("UPDATE nodes SET x=?,y=? WHERE id=? AND workspace_id=?",
                            (x,y,ident,ws))
            return self._read(ws,ident)

    def resize(self, ws: str, ident: str, width, height) -> dict:
        w,h = int(width),int(height)
        if not 250<=w<=1100 or not 150<=h<=850:
            raise ValueError("invalid node dimensions")
        with self._lock,self.db:
            self._read(ws,ident)
            self.db.execute("UPDATE nodes SET width=?,height=? WHERE id=? AND workspace_id=?",
                            (w,h,ident,ws))
            return self._read(ws,ident)

    def note(self, ws: str, title: str, body: str, x=440, y=220) -> dict:
        if not isinstance(title,str) or not 1<=len(title.strip())<=64:
            raise ValueError("note title must be 1 to 64 characters")
        if not isinstance(body,str) or len(body)>8000:
            raise ValueError("note text exceeds 8000 characters")
        x,y=self._validate_pos(x,y)
        ident=uuid.uuid4().hex
        with self._lock,self.db:
            self.db.execute(
                """INSERT INTO nodes
                (id,workspace_id,kind,resource_id,title,body,x,y,width,height,created)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (ident,ws,"note",None,title.strip(),body,x,y,335,220,time.time()))
            return self._read(ws,ident)

    def update_note(self, ws: str, ident: str, body: str) -> dict:
        if not isinstance(body,str) or len(body)>8000:
            raise ValueError("invalid note")
        with self._lock,self.db:
            node=self._read(ws,ident)
            if node["kind"]!="note":raise ValueError("only notes are editable here")
            self.db.execute("UPDATE nodes SET body=? WHERE id=? AND workspace_id=?",
                            (body,ident,ws))
            return self._read(ws,ident)

    def remove_note(self, ws: str, ident: str) -> None:
        with self._lock,self.db:
            node=self._read(ws,ident)
            if node["kind"]!="note":
                raise ValueError("only notes can be removed from this endpoint")
            self.db.execute("DELETE FROM handoffs WHERE workspace_id=? AND (source=? OR target=?)",
                            (ws,ident,ident))
            self.db.execute("DELETE FROM links WHERE workspace_id=? AND (source=? OR target=?)",
                            (ws,ident,ident))
            self.db.execute("DELETE FROM nodes WHERE id=? AND workspace_id=?", (ident,ws))

    def link(self, ws: str, source: str, target: str) -> dict:
        if source==target:raise ValueError("cannot link a node to itself")
        with self._lock,self.db:
            self._read(ws,source)
            self._read(ws,target)
            existing=self.db.execute("SELECT * FROM links WHERE workspace_id=? AND source=? AND target=?",
                                     (ws,source,target)).fetchone()
            if existing:return dict(existing)
            row=dict(id=uuid.uuid4().hex,workspace_id=ws,
                     source=source,target=target,created=time.time())
            self.db.execute("INSERT INTO links VALUES(:id,:workspace_id,:source,:target,:created)",row)
            return row

    def unlink(self, ws: str, ident: str) -> None:
        with self._lock,self.db:
            row=self.db.execute("SELECT 1 FROM links WHERE id=? AND workspace_id=?",
                                (ident,ws)).fetchone()
            if not row:raise PermissionError("link is not accessible")
            self.db.execute("DELETE FROM links WHERE id=? AND workspace_id=?",(ident,ws))

    def linked_target(self,ws,source,target):
        with self._lock:
            first=self._read(ws,source)
            second=self._read(ws,target)
            connected=self.db.execute(
                "SELECT 1 FROM links WHERE workspace_id=? AND source=? AND target=?",
                (ws,source,target)).fetchone()
            if not connected:raise PermissionError("directed canvas link required")
            return first,second

    def record_handoff(self,ws,source,target,content,status="sent"):
        row, _ = self.prepare_handoff(ws,source,target,content,uuid.uuid4().hex)
        self.handoff_state(ws,row["id"],"sending")
        return self.handoff_state(ws,row["id"],status)

    @staticmethod
    def _protected(content):
        value=protect_secret(content)
        if not value.startswith(("dpapi:","keyring:")):
            raise RuntimeError("handoff persistence requires OS protected storage")
        return value

    @staticmethod
    def _handoff_row(row):
        result=dict(row)
        protected=result.pop("protected_content")
        if protected:
            if not protected.startswith(("dpapi:","keyring:")):
                raise RuntimeError("unprotected handoff data rejected")
            result["content"]=unprotect_secret(protected)
        return result

    def prepare_handoff(self,ws,source,target,content,request_key):
        if not isinstance(content,str) or not 1<=len(content.strip())<=4000:
            raise ValueError("handoff must contain 1-4000 characters")
        if not isinstance(request_key,str) or not 1<=len(request_key)<=128:
            raise ValueError("handoff request key must contain 1-128 characters")
        with self._lock,self.db:
            existing=self.handoff_request(ws,source,target,content,request_key)
            if existing:return existing,False
            self.linked_target(ws,source,target)
            now=time.time()
            ident=uuid.uuid4().hex
            self.db.execute("""INSERT INTO handoffs(id,workspace_id,source,target,content,status,
                created,protected_content,request_key,updated) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (ident,ws,source,target,"","prepared",now,self._protected(content),request_key,now))
            row=self.db.execute("SELECT * FROM handoffs WHERE id=?",(ident,)).fetchone()
            return self._handoff_row(row),True

    def handoff_request(self,ws,source,target,content,request_key):
        with self._lock:
            stored=self.db.execute("SELECT * FROM handoffs WHERE workspace_id=? AND request_key=?",
                                   (ws,request_key)).fetchone()
            if stored is None:return None
            row=self._handoff_row(stored)
            if (row["source"],row["target"],row["content"])!=(source,target,content):
                raise ValueError("handoff idempotency collision")
            return row

    def handoff_state(self,ws,ident,status):
        allowed={"prepared":{"sending","not_sent"},"sending":{"sent","uncertain","failed"}}
        with self._lock,self.db:
            row=self.db.execute("SELECT * FROM handoffs WHERE workspace_id=? AND id=?",(ws,ident)).fetchone()
            if row is None:raise PermissionError("handoff is not accessible")
            if status==row["status"]:return self._handoff_row(row)
            if status not in allowed.get(row["status"],set()):raise ValueError("invalid handoff transition")
            self.db.execute("UPDATE handoffs SET status=?,updated=? WHERE id=?",(status,time.time(),ident))
            return self._handoff_row(self.db.execute("SELECT * FROM handoffs WHERE id=?",(ident,)).fetchone())

    def claim_handoff(self, ws, targets, content):
        """Claim one exact terminal message; it does NOT claim provider success."""
        if not isinstance(content, str) or not isinstance(targets, set):
            raise ValueError("invalid handoff claim")
        with self._lock, self.db:
            for row in self.db.execute(
                "SELECT * FROM handoffs WHERE workspace_id=? AND status IN ('sending','sent') "
                "AND receipt_status='pending' ORDER BY created ASC", (ws,)
            ):
                if row["target"] not in targets:
                    continue
                if self._handoff_row(row)["content"] != content:
                    continue
                updated = self.db.execute(
                    "UPDATE handoffs SET receipt_status='running',receipt_updated=? "
                    "WHERE id=? AND workspace_id=? AND receipt_status='pending'",
                    (time.time(), row["id"], ws)
                )
                if updated.rowcount == 1:
                    return {"id": row["id"], "receipt_status": "running"}
            return None

    def complete_handoff(self, ws, ident, targets, receipt):
        """Only a destination terminal's bound capability may record the receipt."""
        if receipt not in {"answered", "tool_completed", "failed", "uncertain"}:
            raise ValueError("invalid handoff receipt")
        with self._lock, self.db:
            row = self.db.execute(
                "SELECT * FROM handoffs WHERE id=? AND workspace_id=?", (ident,ws)
            ).fetchone()
            if row is None or row["target"] not in targets:
                raise PermissionError("handoff receipt is inaccessible")
            if row["receipt_status"] == receipt:
                return {"id": ident, "receipt_status": receipt, "idempotent_replay": True}
            if row["receipt_status"] != "running":
                raise ValueError("handoff was not claimed by its destination")
            self.db.execute(
                "UPDATE handoffs SET receipt_status=?,receipt_updated=? "
                "WHERE id=? AND workspace_id=?", (receipt,time.time(),ident,ws)
            )
            return {"id": ident, "receipt_status": receipt, "idempotent_replay": False}

    def interrupt_handoffs(self, ws, targets):
        """An exited destination cannot silently leave in-flight work pending."""
        if not targets:
            return 0
        with self._lock, self.db:
            changed=0
            for target in targets:
                result=self.db.execute(
                    "UPDATE handoffs SET receipt_status='uncertain',receipt_updated=? "
                    "WHERE workspace_id=? AND target=? "
                    "AND status IN ('sending','sent') "
                    "AND receipt_status IN ('pending','running')",
                    (time.time(),ws,target))
                changed+=result.rowcount
            return changed

    def recover_handoffs(self,workspaces):
        # Called only for workspaces owned by the current Canvas principal.
        with self._lock,self.db:
            for ws in workspaces:
                for row in self.db.execute("SELECT id,content FROM handoffs WHERE workspace_id=? AND content<>'' AND protected_content=''",(ws,)).fetchall():
                    self.db.execute("UPDATE handoffs SET protected_content=?,content='' WHERE id=?",
                                    (self._protected(row["content"]),row["id"]))
                self.db.execute("UPDATE handoffs SET receipt_status='uncertain',receipt_updated=? "
                                "WHERE workspace_id=? AND status IN ('sending','sent') "
                                "AND receipt_status IN ('pending','running')",(time.time(),ws))
                self.db.execute("UPDATE handoffs SET status='uncertain',updated=? WHERE workspace_id=? AND status='sending'",
                                (time.time(),ws))
                self.db.execute("UPDATE handoffs SET status='not_sent',updated=? WHERE workspace_id=? AND status='prepared'",
                                (time.time(),ws))

    def handoffs(self,ws,limit=40):
        with self._lock:
            return [self._handoff_row(r) for r in self.db.execute(
                "SELECT * FROM handoffs WHERE workspace_id=? ORDER BY created DESC LIMIT ?",
                (ws,min(100,max(1,int(limit)))))]

    def close(self):
        with self._lock:self.db.close()
