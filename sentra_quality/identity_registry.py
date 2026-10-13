"""Selo: stable identity registry (projection only, never a grant source).

Derives stable principal ids:
- OIDC: ``oidc-<sha256(issuer + chr(0) + subject)>``
- SPIFFE: ``spiffe-<sha256(trust_domain + chr(0) + spiffe_id)>``

Stores only session/policy/cursor projections owner-scoped in SQLite with
digest + CAS. Secrets (tokens, private keys) are never persisted here; only
public metadata (fingerprints, expiry, availability) is kept. Authentication
outcomes never create grants or capabilities.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def oidc_principal_id(issuer: str, subject: str) -> str:
    issuer = str(issuer or "").strip()
    subject = str(subject or "").strip()
    if not issuer or not subject or len(issuer) > 2048 or len(subject) > 1024:
        raise ValueError("issuer and subject are required")
    digest = hashlib.sha256((issuer + "\0" + subject).encode("utf-8")).hexdigest()
    return "oidc-" + digest


def spiffe_principal_id(trust_domain: str, spiffe_id: str) -> str:
    trust_domain = str(trust_domain or "").strip().lower()
    spiffe_id = str(spiffe_id or "").strip()
    if not trust_domain or not spiffe_id:
        raise ValueError("trust_domain and spiffe_id are required")
    if not spiffe_id.startswith("spiffe://"):
        raise ValueError("spiffe_id must use spiffe:// scheme")
    digest = hashlib.sha256((trust_domain + "\0" + spiffe_id).encode("utf-8")).hexdigest()
    return "spiffe-" + digest


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class IdentityRegistry:
    """Owner-scoped projection of authenticated principals and sessions."""

    def __init__(self, state_root: Path | str, *, clock=time.time) -> None:
        root = Path(state_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "identity_registry.sqlite3"
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS identity_principals(
                    owner TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    issuer TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY(owner, principal_id)
                );
                CREATE TABLE IF NOT EXISTS identity_sessions(
                    owner TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL,
                    public_metadata_json TEXT NOT NULL,
                    PRIMARY KEY(owner, session_id)
                );
                CREATE TABLE IF NOT EXISTS identity_events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    session_id TEXT,
                    principal_id TEXT,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA busy_timeout=5000")
            with db:
                yield db
        finally:
            db.close()

    def _event(self, db, owner, action, outcome, reason, session_id=None, principal_id=None):
        db.execute(
            "INSERT INTO identity_events(owner,session_id,principal_id,action,outcome,reason,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (owner, session_id, principal_id, action, outcome, str(reason)[:1000], self.clock()),
        )

    def register_oidc(self, owner: str, *, issuer: str, subject: str,
                      metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("owner is required")
        principal_id = oidc_principal_id(issuer, subject)
        public = {k: str(v)[:256] for k, v in dict(metadata or {}).items()
                  if k in {"display_name", "session_kind", "audience", "auth_time"}}
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM identity_principals WHERE owner=? AND principal_id=?",
                (owner, principal_id),
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO identity_principals VALUES(?,?,?,?,?,?,?,?)",
                    (owner, principal_id, "oidc", str(issuer)[:2048],
                     str(subject)[:1024], now, now, _canonical(public)),
                )
            else:
                db.execute(
                    "UPDATE identity_principals SET last_seen=?,metadata_json=? "
                    "WHERE owner=? AND principal_id=?",
                    (now, _canonical(public), owner, principal_id),
                )
            self._event(db, owner, "register", "ok", "principal registered",
                        principal_id=principal_id)
        return {"principal_id": principal_id, "kind": "oidc",
                "issuer": str(issuer)[:2048], "creates_grants": False}

    def register_spiffe(self, owner: str, *, trust_domain: str, spiffe_id: str,
                        metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("owner is required")
        principal_id = spiffe_principal_id(trust_domain, spiffe_id)
        public = {k: str(v)[:256] for k, v in dict(metadata or {}).items()
                  if k in {"availability", "expiry", "cert_fingerprint", "bundle_fingerprint"}}
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM identity_principals WHERE owner=? AND principal_id=?",
                (owner, principal_id),
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO identity_principals VALUES(?,?,?,?,?,?,?,?)",
                    (owner, principal_id, "spiffe", str(trust_domain)[:512],
                     str(spiffe_id)[:2048], now, now, _canonical(public)),
                )
            else:
                db.execute(
                    "UPDATE identity_principals SET last_seen=?,metadata_json=? "
                    "WHERE owner=? AND principal_id=?",
                    (now, _canonical(public), owner, principal_id),
                )
            self._event(db, owner, "register", "ok", "workload principal registered",
                        principal_id=principal_id)
        return {"principal_id": principal_id, "kind": "spiffe",
                "trust_domain": str(trust_domain)[:512], "creates_grants": False}

    def session_begin(self, owner: str, *, session_id: str, principal_id: str,
                      ttl_s: float | None = None,
                      public_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        owner = str(owner or "").strip()
        session_id = str(session_id or "").strip()
        principal_id = str(principal_id or "").strip()
        if not owner or not session_id or not principal_id:
            raise ValueError("owner, session_id and principal_id are required")
        if len(session_id) > 256:
            raise ValueError("session_id too long")
        expires_at = None
        if ttl_s is not None:
            if not isinstance(ttl_s, (int, float)) or not 1 <= float(ttl_s) <= 31_536_000:
                raise ValueError("ttl_s must be 1..31536000")
            expires_at = self.clock() + float(ttl_s)
        public = {str(k)[:64]: str(v)[:256] for k, v in dict(public_metadata or {}).items()}
        # Never persist tokens/keys even if the caller passes them by mistake.
        for banned in ("access_token", "refresh_token", "id_token", "private_key",
                       "token", "secret", "client_secret", "password"):
            public.pop(banned, None)
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            known = db.execute(
                "SELECT 1 FROM identity_principals WHERE owner=? AND principal_id=?",
                (owner, principal_id),
            ).fetchone()
            if known is None:
                raise FileNotFoundError("unknown principal for this owner")
            db.execute(
                "INSERT OR REPLACE INTO identity_sessions VALUES(?,?,?,?,?,?,?,?)",
                (owner, session_id, principal_id, "ACTIVE", now, now,
                 expires_at, _canonical(public)),
            )
            self._event(db, owner, "session_begin", "ok", "session projected",
                        session_id=session_id, principal_id=principal_id)
        return {"session_id": session_id, "principal_id": principal_id,
                "status": "ACTIVE", "creates_grants": False}

    def session_invalidate(self, owner: str, session_id: str, *, reason: str = "revoked") -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM identity_sessions WHERE owner=? AND session_id=?",
                (owner, session_id),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("session not found")
            db.execute(
                "UPDATE identity_sessions SET status='REVOKED',updated_at=? "
                "WHERE owner=? AND session_id=?",
                (self.clock(), owner, session_id),
            )
            self._event(db, owner, "session_invalidate", "ok", reason,
                        session_id=session_id, principal_id=row["principal_id"])
        return {"session_id": session_id, "status": "REVOKED"}

    def session_status(self, owner: str, session_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM identity_sessions WHERE owner=? AND session_id=?",
                (owner, session_id),
            ).fetchone()
        if row is None:
            return {"known": False, "locally_active": False}
        now = self.clock()
        active = row["status"] == "ACTIVE" and (
            row["expires_at"] is None or float(row["expires_at"]) > now)
        return {
            "known": True,
            "locally_active": bool(active),
            "status": row["status"] if active else "EXPIRED_OR_REVOKED",
            "principal_id": row["principal_id"],
            # Local eligibility only; never an Operation permission.
            "authorizes_effects": False,
        }

    def principal(self, owner: str, principal_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM identity_principals WHERE owner=? AND principal_id=?",
                (owner, principal_id),
            ).fetchone()
            sessions = db.execute(
                "SELECT session_id,status,updated_at FROM identity_sessions "
                "WHERE owner=? AND principal_id=? ORDER BY updated_at DESC LIMIT 20",
                (owner, principal_id),
            ).fetchall()
        if row is None:
            raise FileNotFoundError("principal not found")
        return {
            "principal_id": row["principal_id"],
            "kind": row["kind"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "metadata": json.loads(row["metadata_json"]),
            "recent_sessions": [dict(s) for s in sessions],
            "creates_grants": False,
        }
