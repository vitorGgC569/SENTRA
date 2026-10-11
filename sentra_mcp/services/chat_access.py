"""Durable, additive ChatGPT conversation access policy for SENTRA MCP.

Browser evidence establishes request -> conversation ownership; it NEVER
authenticates a principal and NEVER grants capabilities. The central executor,
authorization and durable gates remain unchanged. No model-facing operation
can forge a request owner through this service.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from .control_store import ControlPlaneStore, SQLiteControlPlaneStore


_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_PRINCIPAL = re.compile(r"^[A-Za-z0-9_.:@/-]{1,200}$")


def _validate(label, value, pattern):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


class ChatAccessService:
    """Supplementary deny/allowlist, never an authorization provider.

    Trust can be changed by the authenticated local operator only; request
    correlation may ONLY be inserted by an independently authenticated browser
    evidence collector, not through the MCP tool surface.
    """

    def __init__(self, state_root: Path | str, *, store: ControlPlaneStore | None = None):
        self.store = store or SQLiteControlPlaneStore(state_root)
        db=self._db()
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chat_access_policy (
                    principal TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    trusted INTEGER NOT NULL DEFAULT 0,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 1,
                    updated REAL NOT NULL,
                    PRIMARY KEY(principal,conversation_id)
                );
                CREATE TABLE IF NOT EXISTS chat_access_strict (
                    principal TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS chat_request_owners (
                    principal TEXT NOT NULL, request_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    created REAL NOT NULL,
                    PRIMARY KEY(principal,request_id)
                );
                CREATE TABLE IF NOT EXISTS browser_request_conflicts (
                    principal TEXT NOT NULL, request_id TEXT NOT NULL,
                    detected REAL NOT NULL, PRIMARY KEY(principal,request_id)
                );
                CREATE TABLE IF NOT EXISTS browser_request_messages (
                    principal TEXT NOT NULL, request_id TEXT NOT NULL,
                    message_id TEXT NOT NULL, extension_id TEXT NOT NULL,
                    worker TEXT NOT NULL, document_id TEXT NOT NULL,
                    collector_revision INTEGER NOT NULL,
                    PRIMARY KEY(principal,request_id),
                    UNIQUE(principal,message_id)
                );
                CREATE TABLE IF NOT EXISTS browser_chat_gates (
                    principal TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    state TEXT NOT NULL, observed REAL NOT NULL,
                    PRIMARY KEY(principal,conversation_id)
                );
                CREATE INDEX IF NOT EXISTS chat_request_by_conversation
                    ON chat_request_owners(principal,conversation_id);
            """)
        finally:
            db.close()

    def _db(self):
        return self.store.connect("chat_access")

    def set_strict(self, principal: str, enabled: bool, *, expected_revision: int):
        _validate("principal", principal, _PRINCIPAL)
        if type(enabled) is not bool or type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("strict mode requires a boolean and expected revision")
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision FROM chat_access_strict WHERE principal=?", (principal,)
            ).fetchone()
            old = row["revision"] if row else 0
            if old != expected_revision:
                raise ValueError("chat strict policy revision changed")
            db.execute(
                "INSERT INTO chat_access_strict VALUES(?,?,?) "
                "ON CONFLICT(principal) DO UPDATE SET enabled=excluded.enabled,revision=excluded.revision",
                (principal, int(enabled), old + 1)
            )
            db.commit()
            return {"strict":enabled,"revision":old+1}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def set_chat(self, principal: str, conversation_id: str, *,
                 trusted: bool, blocked: bool, expected_revision: int):
        _validate("principal", principal, _PRINCIPAL)
        _validate("conversation ID", conversation_id, _ID)
        if (type(trusted) is not bool or type(blocked) is not bool or
                type(expected_revision) is not int or expected_revision < 0):
            raise ValueError("chat policy requires booleans and revision")
        if trusted and blocked:
            raise ValueError("a blocked chat cannot simultaneously be trusted")
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute(
                "SELECT revision FROM chat_access_policy WHERE principal=? AND conversation_id=?",
                (principal,conversation_id)
            ).fetchone()
            old=row["revision"] if row else 0
            if old != expected_revision:
                raise ValueError("chat policy revision changed")
            db.execute(
                "INSERT INTO chat_access_policy VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(principal,conversation_id) DO UPDATE SET "
                "trusted=excluded.trusted,blocked=excluded.blocked,revision=excluded.revision,updated=excluded.updated",
                (principal,conversation_id,int(trusted),int(blocked),old+1,time.time())
            )
            db.commit()
            return self.chat_status(principal,conversation_id)
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def chat_status(self, principal: str, conversation_id: str):
        _validate("principal", principal, _PRINCIPAL)
        _validate("conversation ID", conversation_id, _ID)
        db=self._db()
        try:
            row=db.execute(
                "SELECT trusted,blocked,revision FROM chat_access_policy WHERE principal=? AND conversation_id=?",
                (principal,conversation_id)
            ).fetchone()
            proof_count=db.execute(
                "SELECT COUNT(*) FROM chat_request_owners WHERE principal=? AND conversation_id=?",
                (principal,conversation_id)
            ).fetchone()[0]
            return {"conversation_id":conversation_id,"trusted":bool(row["trusted"]) if row else False,
                    "blocked":bool(row["blocked"]) if row else False,"revision":row["revision"] if row else 0,
                    "proven_request_count":proof_count,"verified_origin_available":bool(proof_count)}
        finally:
            db.close()

    def strict_status(self, principal: str):
        _validate("principal", principal, _PRINCIPAL)
        db=self._db()
        try:
            row=db.execute("SELECT enabled,revision FROM chat_access_strict WHERE principal=?",
                           (principal,)).fetchone()
            return {"strict":bool(row["enabled"]) if row else False,"revision":row["revision"] if row else 0}
        finally:
            db.close()

    def bind_verified_request(self, principal: str, request_id: str, conversation_id: str,
                              *, evidence_sha256: str):
        """Trust-boundary ingress ONLY; never exposed as an MCP/agent tool.

        Caller must independently authenticate the extension AND verify that
        the browser/page request ID matches the transport request. The method
        validates immutable ownership, not the truth of arbitrary client input.
        """
        _validate("principal",principal,_PRINCIPAL)
        _validate("request ID",request_id,_ID)
        _validate("conversation ID",conversation_id,_ID)
        if not isinstance(evidence_sha256,str) or not re.fullmatch(r"[a-f0-9]{64}",evidence_sha256):
            raise ValueError("authenticated evidence SHA256 required")
        db=self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute(
                "SELECT conversation_id,evidence_sha256 FROM chat_request_owners WHERE principal=? AND request_id=?",
                (principal,request_id)
            ).fetchone()
            if row and row["conversation_id"] != conversation_id:
                raise PermissionError("request is already owned by a different chat")
            if not row:
                db.execute("INSERT INTO chat_request_owners VALUES(?,?,?,?,?)",
                           (principal,request_id,conversation_id,evidence_sha256,time.time()))
            db.commit()
            return {"conversation_id":conversation_id,"state":"proven" if not row else "unchanged"}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def require_allowed(self, principal: str, request_id: str | None, *, _db=None):
        """Fail-closed when strict and origin unproven; blocked chats always deny.

        Private _db allows the exact message check and consent claim to use
        ONE SQLite transaction, without a gap for a tab/grant revocation.
        """
        _validate("principal",principal,_PRINCIPAL)
        if request_id is not None:
            _validate("request ID",request_id,_ID)
        db=_db if _db is not None else self._db()
        try:
            conflict=db.execute(
                "SELECT 1 FROM browser_request_conflicts WHERE principal=? AND request_id=?",
                (principal,request_id)
            ).fetchone() if request_id else None
            if conflict:
                raise PermissionError("conflicting browser request identity quarantined")
            strict=db.execute(
                "SELECT enabled FROM chat_access_strict WHERE principal=?", (principal,)
            ).fetchone()
            row=db.execute(
                "SELECT conversation_id FROM chat_request_owners WHERE principal=? AND request_id=?",
                (principal,request_id)
            ).fetchone() if request_id is not None else None
            if row is None:
                if strict and strict["enabled"]:
                    raise PermissionError("unproven ChatGPT conversation refused by strict policy")
                return {"allowed":True,"source":"unattributed","strict":bool(strict and strict["enabled"])}
            # A browser request remains valid only in its originally enrolled
            # extension build, tab and document. Navigation, account changes
            # (when the document is replaced) and revocation invalidate proof.
            proof=db.execute(
                "SELECT extension_id,worker,document_id,collector_revision,message_id "
                "FROM browser_request_messages WHERE principal=? AND request_id=?",
                (principal,request_id)
            ).fetchone()
            if proof:
                poisoned=db.execute(
                    "SELECT reason FROM browser_profile_uncertainty "
                    "WHERE principal=? AND extension_id=?",
                    (principal,proof["extension_id"])).fetchone()
                if poisoned:
                    raise PermissionError("browser profile or account identity remains unverified")
                live=db.execute(
                    "SELECT d.document_id,c.revision FROM browser_documents d "
                    "JOIN browser_collectors c ON c.extension_id=d.extension_id "
                    "WHERE d.extension_id=? AND d.worker=? AND c.principal=? "
                    "AND c.enabled=1 AND d.conversation_id=?",
                    (proof["extension_id"],proof["worker"],principal,row["conversation_id"])
                ).fetchone()
                if (live is None or live["document_id"] != proof["document_id"]
                        or live["revision"] != proof["collector_revision"]):
                    raise PermissionError("browser request lost document or collector identity")
            page=db.execute(
                "SELECT state FROM browser_chat_gates WHERE principal=? AND conversation_id=?",
                (principal,row["conversation_id"])
            ).fetchone()
            if page and page["state"] in {"awaiting_approval","signed_out","unknown"}:
                raise PermissionError("browser conversation awaits human approval or identity repair")
            chat=db.execute(
                "SELECT trusted,blocked FROM chat_access_policy WHERE principal=? AND conversation_id=?",
                (principal,row["conversation_id"])
            ).fetchone()
            if chat and chat["blocked"]:
                raise PermissionError("this ChatGPT conversation was blocked by the operator")
            if strict and strict["enabled"] and not (chat and chat["trusted"]):
                raise PermissionError("chat not explicitly trusted under strict mode")
            return {"allowed":True,"source":"proven","conversation_id":row["conversation_id"],
                    "strict":bool(strict and strict["enabled"])}
        finally:
            if _db is None:
                db.close()

    def require_exact_message(self, principal: str, request_id: str, message_id: str,
                              *, _db=None):
        """Atomically bind metadata.request_id -> message.id -> chat policy.

        Host-only action claims may supply the *same* central SQLite connection
        (_db) already in BEGIN IMMEDIATE. Direct callers take their own write
        lock, preventing page revocation between checking trust and pairing.
        """
        _validate("message identity", message_id, _ID)
        db = _db if _db is not None else self._db()
        try:
            if _db is None:
                db.execute("BEGIN IMMEDIATE")
            allowed = self.require_allowed(principal, request_id, _db=db)
            row = db.execute(
                "SELECT message_id FROM browser_request_messages WHERE principal=? AND request_id=?",
                (principal, request_id)
            ).fetchone()
            if row is None or row["message_id"] != message_id:
                raise PermissionError("unverified MCP request and Web message pairing")
            result={**allowed, "message_id": message_id, "pairing": "observed_metadata_request_id"}
            if _db is None:
                db.commit()
            return result
        except BaseException:
            if _db is None:
                db.rollback()
            raise
        finally:
            if _db is None:
                db.close()
