"""Durable, conservative evidence of MCP tool invocations.

A tool call proves an MCP client reached SENTRA. It does NOT, by itself,
establish a ChatGPT account has installed or authorized the app.
Observations are tied to the exact configured Tunnel ID fingerprint.
"""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path


_VALID_ID=re.compile(r"^tunnel_[A-Za-z0-9_-]{8,128}$")
_SURFACE=re.compile(r"^[a-z][a-z0-9_-]{0,48}$")


class ConnectorProof:
    def __init__(self,state_root):
        self.root=Path(state_root).resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/"connector-proof.sqlite3"
        db=self._db()
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS connector_observations(
                tunnel_hash TEXT NOT NULL,
                surface TEXT NOT NULL,
                first_at REAL NOT NULL,
                last_at REAL NOT NULL,
                count INTEGER NOT NULL,
                authenticated INTEGER NOT NULL,
                last_transport TEXT NOT NULL,
                PRIMARY KEY(tunnel_hash,surface)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS connector_schemas(
                tunnel_hash TEXT NOT NULL, surface TEXT NOT NULL,
                schema_sha256 TEXT NOT NULL, method_count INTEGER NOT NULL,
                published_at REAL NOT NULL, PRIMARY KEY(tunnel_hash,surface)
            )""")
            columns={r[1] for r in db.execute("PRAGMA table_info(connector_observations)")}
            if "last_local_schema_sha256" not in columns:
                db.execute("ALTER TABLE connector_observations ADD COLUMN last_local_schema_sha256 TEXT NOT NULL DEFAULT ''")
        finally:
            db.close()

    def _db(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @staticmethod
    def _fingerprint(tunnel_id):
        if not isinstance(tunnel_id,str) or not _VALID_ID.fullmatch(tunnel_id):
            return None
        return hashlib.sha256(tunnel_id.encode("ascii")).hexdigest()

    def configured_tunnel_id(self):
        config=self.root/"tunnel.json"
        try:
            value=json.loads(config.read_text(encoding="utf-8"))
        except (OSError,ValueError,UnicodeError):
            return None
        identifier=value.get("tunnel_id") if isinstance(value,dict) else None
        return identifier if self._fingerprint(identifier) else None

    def record_local_schema(self,*,schema_sha256,method_count,surface="core"):
        """Local MCP registry fingerprint only, never a ChatGPT cache proof."""
        if not isinstance(schema_sha256,str) or not re.fullmatch(r"[a-f0-9]{64}",schema_sha256):
            raise ValueError("invalid schema SHA256")
        if type(method_count) is not int or not 0<=method_count<=4096:
            raise ValueError("invalid schema method count")
        if not isinstance(surface,str) or not _SURFACE.fullmatch(surface):
            raise ValueError("invalid MCP surface")
        tunnel=self._fingerprint(self.configured_tunnel_id()) or "unconfigured"
        with self._db() as db:
            db.execute("""INSERT INTO connector_schemas VALUES(?,?,?,?,?)
                ON CONFLICT(tunnel_hash,surface) DO UPDATE SET
                schema_sha256=excluded.schema_sha256,
                method_count=excluded.method_count,
                published_at=excluded.published_at""",
                (tunnel,surface,schema_sha256,method_count,time.time()))

    def record_tool(self,*,surface="core",transport="unknown",authenticated=False):
        """Accept only SDK-observed invocations, not browser-declared plugin state."""
        if not isinstance(surface,str) or not _SURFACE.fullmatch(surface):
            raise ValueError("invalid MCP surface")
        if type(authenticated) is not bool:
            raise ValueError("authenticated must be an SDK-observed boolean")
        tunnel=self._fingerprint(self.configured_tunnel_id()) or "unconfigured"
        kind=transport if transport in {"streamable-http","sse","stdio"} else "unknown"
        now=time.time()
        db=self._db()
        try:
            with db:
                row=db.execute("SELECT schema_sha256 FROM connector_schemas WHERE tunnel_hash=? AND surface=?",
                               (tunnel,surface)).fetchone()
                local_sha=row["schema_sha256"] if row else ""
                db.execute("""INSERT INTO connector_observations
                    (tunnel_hash,surface,first_at,last_at,count,authenticated,last_transport,last_local_schema_sha256)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(tunnel_hash,surface) DO UPDATE SET
                    last_at=excluded.last_at,count=count+1,
                    authenticated=MAX(authenticated,excluded.authenticated),
                    last_transport=excluded.last_transport,
                    last_local_schema_sha256=CASE WHEN excluded.authenticated=1
                        THEN excluded.last_local_schema_sha256
                        ELSE connector_observations.last_local_schema_sha256 END""",
                    (tunnel,surface,now,now,1,int(authenticated),kind,
                     local_sha if authenticated else ""))
        finally:
            db.close()

    def status(self,tunnel_id=None):
        """Never returns raw tunnel, token, account or browser identifiers."""
        active=self._fingerprint(tunnel_id or self.configured_tunnel_id())
        if active is None:
            return {"tunnel_configured":False,"mcp_tool_observed":False,
                    "authenticated_tool_observed":False,
                    "plugin_installed_in_chatgpt":"unverified","schema_current_in_chatgpt":"unverified"}
        db=self._db()
        try:
            rows=db.execute("SELECT surface,last_at,count,authenticated,last_transport,last_local_schema_sha256 "
                            "FROM connector_observations WHERE tunnel_hash=?",(active,)).fetchall()
            schemas=db.execute("SELECT surface,schema_sha256,method_count,published_at FROM connector_schemas "
                               "WHERE tunnel_hash=?",(active,)).fetchall()
        finally:
            db.close()
        local={r["surface"]:dict(r) for r in schemas}
        changed=any(r["authenticated"] and r["last_local_schema_sha256"] and
                    r["surface"] in local and
                    r["last_local_schema_sha256"]!=local[r["surface"]]["schema_sha256"]
                    for r in rows)
        return {"tunnel_configured":True,"mcp_tool_observed":bool(rows),
                "authenticated_tool_observed":any(bool(r["authenticated"]) for r in rows),
                "plugin_installed_in_chatgpt":"unverified",
                "schema_current_in_chatgpt":"unverified",
                "local_schema_changed_since_authenticated_call":changed,
                "local_schemas":[{"surface":s,"schema_sha256":r["schema_sha256"],
                                  "method_count":r["method_count"],
                                  "published_at":r["published_at"]}
                                 for s,r in sorted(local.items())],
                "surfaces":[{"name":r["surface"],"last_at":r["last_at"],"calls":r["count"],
                             "transport":r["last_transport"]} for r in rows]}
