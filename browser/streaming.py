"""Message-ID-keyed streaming history for observed Web conversations.

Page streaming frames are *data*, never delivery proof, grants or authority.
Each frame binds (principal, conversation_id, message_id) to a monotonically
increasing revision with a bounded text prefix. Full bodies are never stored
here: oversized turns keep an overflow reference the viewer resolves through
the existing read-only extract path. Rastro's outbox/receipts remain the only
delivery authority; this ledger only answers "what partial text was observed".
"""
from __future__ import annotations

import hashlib
import time

from sentra_mcp.services.chat_access import _ID, _PRINCIPAL, _validate

MAX_PREFIX_CHARS = 32_000
MAX_FRAMES_PER_MESSAGE = 512


class StreamingLedger:
    """SQLite-backed partial-text ledger in the shared chat_access database."""

    def __init__(self, store) -> None:
        self.store = store
        db = self.store.connect("chat_access")
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS browser_stream_frames(
                    principal TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    prefix_sha256 TEXT NOT NULL, prefix_chars INTEGER NOT NULL,
                    truncated INTEGER NOT NULL, overflow_ref TEXT,
                    observed REAL NOT NULL,
                    PRIMARY KEY(principal,conversation_id,message_id,revision));
                CREATE INDEX IF NOT EXISTS browser_stream_frames_lookup
                    ON browser_stream_frames(principal,conversation_id,message_id,revision);
            """)
            db.execute("CREATE TABLE IF NOT EXISTS browser_stream_content("
                       "principal TEXT NOT NULL,conversation_id TEXT NOT NULL,message_id TEXT NOT NULL,"
                       "revision INTEGER NOT NULL,protected_text TEXT NOT NULL,sha256 TEXT NOT NULL,"
                       "PRIMARY KEY(principal,conversation_id,message_id,revision))")
            db.commit()
        finally:
            db.close()

    def record_frame(self, *, principal: str, conversation_id: str,
                     message_id: str, revision: int, text: str) -> dict:
        """Store one partial snapshot. Revisions must increase per message."""
        _validate("principal", principal, _PRINCIPAL)
        _validate("conversation identity", conversation_id, _ID)
        _validate("message identity", message_id, _ID)
        if type(revision) is not int or revision < 0:
            raise ValueError("stream revision must be a non-negative integer")
        if not isinstance(text, str):
            raise ValueError("stream text must be a string")
        if len(text.encode()) > 1_500_000:
            raise ValueError("stream body exceeds recoverable content budget")
        truncated = len(text) > MAX_PREFIX_CHARS
        prefix = text[:MAX_PREFIX_CHARS]
        digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
        overflow = None
        if truncated:
            overflow = "overflow:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            latest = db.execute(
                "SELECT MAX(revision) AS rev, COUNT(*) AS n FROM browser_stream_frames "
                "WHERE principal=? AND conversation_id=? AND message_id=?",
                (principal, conversation_id, message_id)).fetchone()
            if latest["rev"] == revision:
                prior = db.execute("SELECT sha256 FROM browser_stream_content WHERE principal=? "
                    "AND conversation_id=? AND message_id=? AND revision=?",
                    (principal, conversation_id, message_id, revision)).fetchone()
                if prior is None or prior["sha256"] != hashlib.sha256(text.encode()).hexdigest():
                    raise ValueError("same stream revision conflicts with full protected body")
                return {"revision": revision, "prefix_chars": len(prefix), "prefix_sha256": digest,
                        "truncated": truncated, "overflow_ref": overflow, "idempotent_replay": True,
                        "grants_created": False}
            if latest["rev"] is not None and revision < int(latest["rev"]):
                raise ValueError("stream revision must increase per message")
            if int(latest["n"]) >= MAX_FRAMES_PER_MESSAGE:
                raise ValueError("stream frame budget exceeded for message")
            now = time.time()
            db.execute("INSERT INTO browser_stream_frames VALUES(?,?,?,?,?,?,?,?,?)",
                       (principal, conversation_id, message_id, revision, digest,
                        len(prefix), int(truncated), overflow, now))
            from sentra_core.conversations import _encode
            db.execute("INSERT INTO browser_stream_content VALUES(?,?,?,?,?,?)",
                       (principal, conversation_id, message_id, revision, _encode(text),
                        hashlib.sha256(text.encode()).hexdigest()))
            db.commit()
            return {"revision": revision, "prefix_chars": len(prefix),
                    "prefix_sha256": digest, "truncated": truncated,
                    "overflow_ref": overflow, "grants_created": False}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def latest(self, principal: str, conversation_id: str, message_id: str) -> dict:
        _validate("principal", principal, _PRINCIPAL)
        _validate("conversation identity", conversation_id, _ID)
        _validate("message identity", message_id, _ID)
        db = self.store.connect("chat_access")
        try:
            row = db.execute(
                "SELECT revision,prefix_sha256,prefix_chars,truncated,overflow_ref,observed "
                "FROM browser_stream_frames WHERE principal=? AND conversation_id=? "
                "AND message_id=? ORDER BY revision DESC LIMIT 1",
                (principal, conversation_id, message_id)).fetchone()
        finally:
            db.close()
        if row is None:
            return {"present": False}
        return {"present": True, **dict(row)}

    def history(self, principal: str, conversation_id: str, message_id: str,
                *, limit: int = 50) -> dict:
        _validate("principal", principal, _PRINCIPAL)
        _validate("conversation identity", conversation_id, _ID)
        _validate("message identity", message_id, _ID)
        limit = max(1, min(int(limit), MAX_FRAMES_PER_MESSAGE))
        db = self.store.connect("chat_access")
        try:
            rows = db.execute(
                "SELECT revision,prefix_sha256,prefix_chars,truncated,overflow_ref,observed "
                "FROM browser_stream_frames WHERE principal=? AND conversation_id=? "
                "AND message_id=? ORDER BY revision DESC LIMIT ?",
                (principal, conversation_id, message_id, limit)).fetchall()
        finally:
            db.close()
        return {"frames": [dict(r) for r in rows], "grants_created": False}

    def record_extension_snapshot(self, *, principal: str, conversation_id: str,
                                  message_index: int, revision: int,
                                  text: str, request_id: str | None = None,
                                  document_id: str | None = None,
                                  identity_epoch: str | None = None) -> dict:
        """Bind an extension stream snapshot (DOM message index + revision) to
        the durable logical message_id.

        The content script reports snapshots by assistant-message index because
        the page virtualizes/reorders the DOM. The index alone never becomes
        identity: it resolves against the ordered, evidence-bound message_ids
        of the conversation (chat_request_owners + browser_request_messages).
        Out-of-range or unbound indexes fail closed instead of fabricating a
        message. This closes contracts.md lacuna 3 Brisa-side; Rastro/history
        consumers read by the resolved logical message_id.
        """
        _validate("principal", principal, _PRINCIPAL)
        _validate("conversation identity", conversation_id, _ID)
        if type(message_index) is not int or message_index < 1:
            raise ValueError("extension message index must be a positive integer")
        db = self.store.connect("chat_access")
        try:
            if request_id is None or document_id is None or identity_epoch is None:
                raise PermissionError("DOM index alone never identifies a durable message; exact request/document/epoch required")
            row = db.execute(
                "SELECT m.message_id,e.identity_epoch FROM browser_request_messages m "
                "JOIN chat_request_owners o ON o.principal=m.principal "
                "AND o.request_id=m.request_id "
                "JOIN browser_document_epochs e ON e.extension_id=m.extension_id "
                "AND e.worker=m.worker AND e.document_id=m.document_id "
                "WHERE m.principal=? AND o.conversation_id=? AND m.request_id=? AND m.document_id=?",
                (principal, conversation_id, request_id, document_id)).fetchone()
        finally:
            db.close()
        if row is None or row["identity_epoch"] != identity_epoch:
            raise PermissionError("stream snapshot has no exact request/document/epoch binding")
        message_id = row["message_id"]
        stored = self.record_frame(principal=principal,
                                   conversation_id=conversation_id,
                                   message_id=message_id, revision=revision,
                                   text=text)
        return {**stored, "message_id": message_id,
                "message_index": message_index}

    def read_content(self, principal, conversation_id, message_id, revision):
        """Recover overflow by exact scoped frame, never an unowned digest."""
        for label, value in (("principal", principal), ("conversation", conversation_id), ("message", message_id)):
            _validate(label, value, _PRINCIPAL if label == "principal" else _ID)
        if type(revision) is not int or revision < 0:
            raise ValueError("exact stream revision required")
        db = self.store.connect("chat_access")
        try:
            row = db.execute("SELECT protected_text,sha256 FROM browser_stream_content "
                "WHERE principal=? AND conversation_id=? AND message_id=? AND revision=?",
                (principal, conversation_id, message_id, revision)).fetchone()
        finally:
            db.close()
        if row is None:
            raise FileNotFoundError("stream content not recoverable for this scoped frame")
        from sentra_core.conversations import _decode
        text = _decode(row["protected_text"])
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != row["sha256"]:
            raise PermissionError("protected stream content digest mismatch")
        return {"content": text, "revision": revision, "sha256": row["sha256"], "grants_created": False}
