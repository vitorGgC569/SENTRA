"""Owner/workspace protected ChatGPT Web observations: revisioned, opt-in index.

Host-side persistence only. Browser origin/identity must be verified by the
Chat 2 collector BEFORE calling record_frame; this module grants no authority.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from typing import Any

from sentra_remote.secrets import protect_secret, unprotect_secret
from .control_store import ControlPlaneStore, create_control_plane_store


_IDENT = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_TOKENS = re.compile(r"[^\W_]{2,40}", re.UNICODE)
_SECRET_LIKE = re.compile(
    r"(?:[A-Za-z0-9_-]*[0-9][A-Za-z0-9_-]*){8,}|sk-[A-Za-z0-9]+|"
    r"dpapi:[A-Za-z0-9]+|keyring:[A-Za-z0-9]+|bearer[A-Za-z0-9]+|"
    r"xox[bap]-[A-Za-z0-9-]+|gh[pous]_[A-Za-z0-9]+")
_SECRET_WORDS = frozenset({
    "password", "passwd", "secret", "token", "api-key", "apikey",
    "cookie", "session-token", "authorization", "private-key", "privatekey"})
_MAX_MESSAGE = 800000  # full 200000-character ChatResult even at 4-byte UTF-8
_MAX_WORKSPACE = 8 * 1024 * 1024


class WebHistoryConflict(RuntimeError):
    pass


def _bounded(name: str, value: str, pattern=_IDENT) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{name} requires a stable bounded identifier")
    return value


def _protected(text: str) -> str:
    cipher = protect_secret(text)
    if not cipher.startswith(("dpapi:", "keyring:")):
        raise RuntimeError("OS-protected Web history storage is mandatory")
    return cipher


def _plain(cipher: str) -> str:
    if not isinstance(cipher, str) or not cipher.startswith(("dpapi:", "keyring:")):
        raise RuntimeError("plaintext Web history rejected")
    return unprotect_secret(cipher)


def _terms(text: str) -> set[str]:
    found = set(token.casefold() for token in _TOKENS.findall(text or "")[:1024])
    # Never index secret-looking material by default (A11): tokens with a
    # high digit/symbol ratio or known secret prefixes stay searchable only
    # via exact message reads, never via the Geraldton index.
    return {token for token in found
            if not _SECRET_LIKE.fullmatch(token) and token not in _SECRET_WORDS}


def _hashed(key: bytes, terms: set[str]) -> set[str]:
    return {hmac.new(key, token.encode("utf-8"), hashlib.sha256).hexdigest()
            for token in terms}


class WebHistoryStore:
    """Works inside the central provider_content SQLite namespace, never JSONL."""

    def __init__(self, state_root: str, *, store: ControlPlaneStore | None = None,
                 clock=time.time):
        self.store = store or create_control_plane_store(state_root)
        self.clock = clock
        with self.store.connect("provider_content") as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS web_history_prefs(
                    owner TEXT NOT NULL, workspace TEXT NOT NULL,
                    index_enabled INTEGER NOT NULL DEFAULT 0,
                    index_key TEXT,
                    PRIMARY KEY(owner,workspace));
                CREATE TABLE IF NOT EXISTS web_history_messages(
                    owner TEXT NOT NULL, workspace TEXT NOT NULL,
                    conversation_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, role TEXT NOT NULL,
                    state TEXT NOT NULL, protected_body TEXT NOT NULL,
                    body_sha256 TEXT NOT NULL, byte_length INTEGER NOT NULL,
                    observed_at REAL NOT NULL,
                    PRIMARY KEY(owner,workspace,conversation_id,message_id));
                CREATE INDEX IF NOT EXISTS web_history_by_chat
                    ON web_history_messages(owner,workspace,conversation_id,observed_at);
                CREATE TABLE IF NOT EXISTS web_history_terms(
                    owner TEXT NOT NULL, workspace TEXT NOT NULL,
                    digest TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    PRIMARY KEY(owner,workspace,digest,conversation_id,message_id));
                CREATE TABLE IF NOT EXISTS web_history_host_observations(
                    owner TEXT NOT NULL, workspace TEXT NOT NULL,
                    conversation_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, body_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL, collector_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL, document_id TEXT NOT NULL,
                    identity_epoch TEXT NOT NULL,
                    PRIMARY KEY(owner,workspace,conversation_id,message_id));
            """)

    @staticmethod
    def _scope(owner: str, workspace: str) -> tuple[str, str]:
        return (_bounded("owner", owner, re.compile(r"^[^\x00-\x1f]{1,128}$")),
                _bounded("workspace", workspace,
                         re.compile(r"^[^\x00-\x1f]{1,256}$")))

    def _key(self, db, owner: str, workspace: str) -> bytes | None:
        row = db.execute(
            "SELECT index_enabled,index_key FROM web_history_prefs "
            "WHERE owner=? AND workspace=?", (owner, workspace)).fetchone()
        if not row or not row["index_enabled"]:
            return None
        key = bytes.fromhex(_plain(row["index_key"]))
        if len(key) != 32:
            raise RuntimeError("invalid protected Web history index key")
        return key

    def set_index(self, owner: str, workspace: str, *, enabled: bool,
                  operator_approved: bool = False) -> dict[str, Any]:
        """Opt-in with a local human decision; disable erases all search tokens."""
        owner, workspace = self._scope(owner, workspace)
        if operator_approved is not True or type(enabled) is not bool:
            raise PermissionError("explicit index consent required")
        with self.store.connect("provider_content") as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT index_enabled FROM web_history_prefs "
                             "WHERE owner=? AND workspace=?",
                             (owner, workspace)).fetchone()
            if not enabled:
                db.execute("DELETE FROM web_history_terms WHERE owner=? AND workspace=?",
                           (owner, workspace))
                db.execute("INSERT INTO web_history_prefs(owner,workspace,index_enabled,index_key) "
                           "VALUES(?,?,0,NULL) ON CONFLICT(owner,workspace) DO UPDATE SET "
                           "index_enabled=0,index_key=NULL", (owner, workspace))
                return {"enabled": False, "indexed_messages": 0}
            if row and row["index_enabled"]:
                count = db.execute("SELECT COUNT(DISTINCT conversation_id||':'||message_id) "
                                   "FROM web_history_terms WHERE owner=? AND workspace=?",
                                   (owner, workspace)).fetchone()[0]
                return {"enabled": True, "indexed_messages": count}
            key = secrets.token_bytes(32)
            db.execute("DELETE FROM web_history_terms WHERE owner=? AND workspace=?",
                       (owner, workspace))
            db.execute("INSERT INTO web_history_prefs(owner,workspace,index_enabled,index_key) "
                       "VALUES(?,?,1,?) ON CONFLICT(owner,workspace) DO UPDATE SET "
                       "index_enabled=1,index_key=excluded.index_key",
                       (owner, workspace, _protected(key.hex())))
            rows = db.execute("SELECT conversation_id,message_id,protected_body "
                              "FROM web_history_messages WHERE owner=? AND workspace=?",
                              (owner, workspace)).fetchall()
            for r in rows:
                self._index(db, owner, workspace, r["conversation_id"],
                            r["message_id"], _plain(r["protected_body"]), key)
            return {"enabled": True, "indexed_messages": len(rows)}

    def _index(self, db, owner, workspace, conversation_id, message_id, body, key):
        db.execute("DELETE FROM web_history_terms WHERE owner=? AND workspace=? "
                   "AND conversation_id=? AND message_id=?",
                   (owner, workspace, conversation_id, message_id))
        if key is None:
            return
        for digest in list(sorted(_hashed(key, _terms(body))))[:256]:
            db.execute("INSERT INTO web_history_terms VALUES(?,?,?,?,?)",
                       (owner, workspace, digest, conversation_id, message_id))

    def record_frame(self, owner: str, workspace: str, *, conversation_id: str,
                     message_id: str, revision: int, role: str, state: str,
                     body: str, host_observation: dict | None = None) -> dict[str, Any]:
        """Overwrite one message revision, never store one row per streaming frame."""
        owner, workspace = self._scope(owner, workspace)
        conversation_id = _bounded("conversation_id", conversation_id)
        message_id = _bounded("message_id", message_id)
        if type(revision) is not int or not 0 <= revision <= 1_000_000:
            raise ValueError("bounded revision required")
        if role not in ("user", "assistant", "tool") or state not in ("partial", "complete"):
            raise ValueError("invalid Web message role/state")
        if not isinstance(body, str):
            raise ValueError("Web message text required")
        length = len(body.encode("utf-8"))
        if length > _MAX_MESSAGE:
            raise ValueError("Web message exceeds size quota")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        with self.store.connect("provider_content") as db:
            db.execute("BEGIN IMMEDIATE")
            scope = (owner, workspace, conversation_id, message_id)
            host = self._check_host(db, scope, host_observation, digest=digest, state=state)
            previous = db.execute(
                "SELECT * FROM web_history_messages WHERE owner=? AND workspace=? "
                "AND conversation_id=? AND message_id=?",
                (owner, workspace, conversation_id, message_id)).fetchone()
            if previous:
                if previous["role"] != role:
                    raise WebHistoryConflict("message role changed")
                if revision < previous["revision"]:
                    raise WebHistoryConflict("message revision moved backwards")
                if revision == previous["revision"]:
                    if previous["body_sha256"] != digest or previous["state"] != state:
                        raise WebHistoryConflict("same revision contains conflicting frame")
                    if host is not None:
                        self._save_host(db, scope, host)
                    return {"message_id": message_id, "revision": revision,
                            "idempotent_replay": True}
                if previous["state"] == "complete":
                    raise WebHistoryConflict("finalized message cannot reopen")
            used = db.execute(
                "SELECT COALESCE(SUM(byte_length),0) FROM web_history_messages "
                "WHERE owner=? AND workspace=?", (owner, workspace)).fetchone()[0]
            if used - (previous["byte_length"] if previous else 0) + length > _MAX_WORKSPACE:
                raise ValueError("Web workspace history quota exceeded")
            protected = _protected(body)
            now = self.clock()
            db.execute(
                "INSERT INTO web_history_messages VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(owner,workspace,conversation_id,message_id) DO UPDATE SET "
                "revision=excluded.revision,role=excluded.role,state=excluded.state,"
                "protected_body=excluded.protected_body,body_sha256=excluded.body_sha256,"
                "byte_length=excluded.byte_length,observed_at=excluded.observed_at",
                (owner,workspace,conversation_id,message_id,revision,role,state,
                 protected,digest,length,now))
            key = self._key(db, owner, workspace)
            if key is not None:
                self._index(db,owner,workspace,conversation_id,message_id,body,key)
            if host is not None:
                self._save_host(db, scope, host)
            return {"message_id": message_id, "revision": revision,
                    "idempotent_replay": False}

    def _check_host(self, db, scope, observation, *, digest, state):
        previous = db.execute("SELECT * FROM web_history_host_observations WHERE owner=? AND workspace=? "
                              "AND conversation_id=? AND message_id=?", scope).fetchone()
        if observation is None:
            if previous is not None:
                raise WebHistoryConflict("pinned Host observation cannot be omitted")
            return None  # Existing explicitly trusted synthetic/legacy callback.
        fields = {"revision", "body_sha256", "state", "collector_id", "source_sha256", "document_id", "identity_epoch"}
        if not isinstance(observation, dict) or set(observation) != fields:
            raise ValueError("exact Host observation fields required")
        host = dict(observation)
        if type(host["revision"]) is not int or not 1 <= host["revision"] <= 2**53:
            raise ValueError("positive bounded Host revision required")
        if host["body_sha256"] != digest or host["state"] != state:
            raise WebHistoryConflict("Host observation body/state differs from central frame")
        if not isinstance(host["source_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", host["source_sha256"]):
            raise ValueError("Host collector source SHA256 required")
        for key in ("collector_id", "document_id", "identity_epoch"):
            _bounded("Host " + key, host[key], re.compile(r"^[^\x00-\x1f]{1,256}$"))
        if previous is not None:
            if any(host[key] != previous[key] for key in ("collector_id", "source_sha256", "document_id", "identity_epoch")):
                raise WebHistoryConflict("pinned Host collector/document/epoch changed")
            if host["revision"] < previous["revision"]:
                raise WebHistoryConflict("Host revision moved backwards")
            if host["revision"] == previous["revision"] and any(
                    host[key] != previous[key] for key in ("body_sha256", "state")):
                raise WebHistoryConflict("same Host revision contains conflicting observation")
        return host

    @staticmethod
    def _save_host(db, scope, host):
        db.execute("INSERT INTO web_history_host_observations VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                   "ON CONFLICT(owner,workspace,conversation_id,message_id) DO UPDATE SET "
                   "revision=excluded.revision,body_sha256=excluded.body_sha256,state=excluded.state",
                   (*scope, host["revision"], host["body_sha256"], host["state"], host["collector_id"],
                    host["source_sha256"], host["document_id"], host["identity_epoch"]))

    def list_observed_conversations(self, owner: str, workspace: str, *,
                                    limit: int = 50) -> list[dict[str, Any]]:
        """Read-only Home/recents projection over observed Web messages (no authority)."""
        owner, workspace = self._scope(owner, workspace)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be 1..200")
        with self.store.connect("provider_content") as db:
            rows = db.execute(
                "SELECT conversation_id,COUNT(*) AS messages,"
                "MAX(observed_at) AS last_observed FROM web_history_messages "
                "WHERE owner=? AND workspace=? GROUP BY conversation_id "
                "ORDER BY last_observed DESC LIMIT ?",
                (owner, workspace, limit)).fetchall()
        return [{"conversation_id": row["conversation_id"],
                 "messages": int(row["messages"]),
                 "last_observed": row["last_observed"]} for row in rows]

    def messages(self, owner: str, workspace: str, conversation_id: str,
                 *, limit: int = 100) -> list[dict[str, Any]]:
        owner, workspace = self._scope(owner, workspace)
        conversation_id = _bounded("conversation_id", conversation_id)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit must be 1..500")
        with self.store.connect("provider_content") as db:
            rows = db.execute(
                "SELECT * FROM web_history_messages WHERE owner=? AND workspace=? "
                "AND conversation_id=? ORDER BY observed_at,message_id LIMIT ?",
                (owner,workspace,conversation_id,limit)).fetchall()
        return [{**{k:r[k] for k in ("conversation_id","message_id","revision",
                                      "role","state","observed_at")},
                 "body":_plain(r["protected_body"])} for r in rows]

    def search(self, owner: str, workspace: str, query: str, *,
               limit: int = 20) -> list[dict[str, Any]]:
        owner, workspace = self._scope(owner, workspace)
        if not isinstance(query, str) or not 1 <= len(query) <= 200:
            raise ValueError("bounded search query required")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("search limit must be 1..50")
        terms = _terms(query)
        if not terms or len(terms) > 12:
            raise ValueError("1..12 searchable terms required")
        with self.store.connect("provider_content") as db:
            key = self._key(db, owner, workspace)
            if key is None:
                raise PermissionError("Web history index is not enabled")
            hashes = sorted(_hashed(key, terms))
            placeholders = ",".join("?" for _ in hashes)
            rows = db.execute(
                "SELECT m.conversation_id,m.message_id,m.revision,m.role,"
                "m.protected_body FROM web_history_messages m JOIN "
                "(SELECT conversation_id,message_id FROM web_history_terms "
                "WHERE owner=? AND workspace=? AND digest IN (" + placeholders + ") "
                "GROUP BY conversation_id,message_id HAVING COUNT(*)=?) t "
                "ON m.conversation_id=t.conversation_id AND m.message_id=t.message_id "
                "WHERE m.owner=? AND m.workspace=? ORDER BY m.observed_at DESC LIMIT ?",
                (owner,workspace,*hashes,len(hashes),owner,workspace,limit)).fetchall()
        return [{"conversation_id":r["conversation_id"],"message_id":r["message_id"],
                 "revision":r["revision"],"role":r["role"],
                 "snippet":_plain(r["protected_body"])[:240]} for r in rows]

    def export_markdown(self, owner: str, workspace: str, conversation_id: str,
                        *, redact_body: bool = False) -> str:
        if type(redact_body) is not bool:
            raise ValueError("redact_body must be a boolean")
        items = self.messages(owner, workspace, conversation_id, limit=500)
        output = ["# ChatGPT Web conversation", "",
                  f"Conversation: \\u0060{conversation_id}\\u0060", "",
                  "Source: host-side Web observations, not proof of account ownership.", ""]
        for item in items:
            output.extend([f"## {item['role']} — {item['message_id']} (rev {item['revision']}, {item['state']})",
                           ""])
            body = "[CONTENT REDACTED]" if redact_body else item["body"]
            output.extend("> " + line for line in body.splitlines() or [""])
            output.append("")
        result = "\n".join(output)
        if len(result.encode("utf-8")) > 2_000_000:
            raise ValueError("Web Markdown export exceeds 2 MB")
        return result

    def export_message(self, owner: str, workspace: str, conversation_id: str,
                       message_id: str, *, redact_body: bool = False) -> str:
        """Export a single response/message with provenance (OD-CF06/A20)."""
        if type(redact_body) is not bool:
            raise ValueError("redact_body must be a boolean")
        owner, workspace = self._scope(owner, workspace)
        conversation_id = _bounded("conversation_id", conversation_id)
        message_id = _bounded("message_id", message_id)
        with self.store.connect("provider_content") as db:
            row = db.execute(
                "SELECT * FROM web_history_messages WHERE owner=? AND workspace=? "
                "AND conversation_id=? AND message_id=?",
                (owner, workspace, conversation_id, message_id)).fetchone()
        if row is None:
            raise FileNotFoundError("Web message not found for owner/workspace")
        body = "[CONTENT REDACTED]" if redact_body else _plain(row["protected_body"])
        output = ["# ChatGPT Web response", "",
                  f"Conversation: `{conversation_id}`", f"Message: `{message_id}`",
                  f"Role: {row['role']}, revision {row['revision']}, {row['state']}", "",
                  "Source: host-side Web observations, not proof of account ownership.", ""]
        output.extend("> " + line for line in body.splitlines() or [""])
        output.append("")
        result = "\n".join(output)
        if len(result.encode("utf-8")) > 2_000_000:
            raise ValueError("Web Markdown export exceeds 2 MB")
        return result

    def delete_workspace(self, owner: str, workspace: str, *,
                         operator_approved: bool = False) -> dict[str, int]:
        """Erase a whole workspace history WITH its search index (A11).

        Disabling the index (`set_index(enabled=False)`) erases terms but
        keeps messages; deleting the session erases messages, host
        observations AND terms together.
        """
        if operator_approved is not True:
            raise PermissionError("explicit workspace erase approval required")
        owner, workspace = self._scope(owner, workspace)
        with self.store.connect("provider_content") as db:
            db.execute("BEGIN IMMEDIATE")
            hosts = db.execute("DELETE FROM web_history_host_observations "
                               "WHERE owner=? AND workspace=?",
                               (owner, workspace)).rowcount
            terms = db.execute("DELETE FROM web_history_terms "
                               "WHERE owner=? AND workspace=?",
                               (owner, workspace)).rowcount
            messages = db.execute("DELETE FROM web_history_messages "
                                  "WHERE owner=? AND workspace=?",
                                  (owner, workspace)).rowcount
            db.execute("DELETE FROM web_history_prefs WHERE owner=? AND workspace=?",
                       (owner, workspace))
        return {"messages": messages, "terms": terms, "host_observations": hosts}

    def purge(self, owner: str, workspace: str, conversation_id: str, *,
              operator_approved: bool = False) -> int:
        if operator_approved is not True:
            raise PermissionError("explicit purge approval required")
        owner,workspace = self._scope(owner,workspace)
        conversation_id = _bounded("conversation_id",conversation_id)
        with self.store.connect("provider_content") as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM web_history_host_observations WHERE owner=? AND workspace=? AND conversation_id=?",
                       (owner,workspace,conversation_id))
            db.execute("DELETE FROM web_history_terms WHERE owner=? AND workspace=? "
                       "AND conversation_id=?", (owner,workspace,conversation_id))
            count = db.execute("DELETE FROM web_history_messages WHERE owner=? "
                               "AND workspace=? AND conversation_id=?",
                               (owner,workspace,conversation_id)).rowcount
        return count
