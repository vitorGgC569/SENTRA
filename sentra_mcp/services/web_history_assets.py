"""Chunked OS-protected Web attachment drafts scoped to central WorkItems.

READY_LOCAL is NOT remote upload. Browser upload receipts remain a separate
Chat2 handshake; this catalog never forwards bytes to an external provider.
"""
from __future__ import annotations

import base64
import hashlib
import re
import time
import uuid
from typing import Any

from sentra_remote.secrets import protect_secret, unprotect_secret
from .control_store import SQLiteControlPlaneStore

_ALLOWED = {"image/png", "image/jpeg", "application/pdf", "text/plain"}
_MAX_BYTES = 4 * 1024 * 1024
_MAX_TOTAL = 16 * 1024 * 1024
_CHUNK = 64 * 1024
_IDENT = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class WebAssetConflict(RuntimeError):
    pass


class WebAssetDrafts:
    def __init__(self, control: Any, *, clock=time.time):
        self.control, self.clock = control, clock
        self.store = getattr(control, "store", None) or SQLiteControlPlaneStore(
            control.durable.state_root)
        with self.store.connect("provider_content") as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS web_asset_drafts(
                    asset_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL, workspace TEXT NOT NULL,
                    run_id TEXT NOT NULL, work_item_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    content_type TEXT NOT NULL, expected_bytes INTEGER NOT NULL,
                    expected_sha256 TEXT NOT NULL, state TEXT NOT NULL,
                    created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS web_asset_owner_workspace
                    ON web_asset_drafts(owner,workspace,state);
                CREATE TABLE IF NOT EXISTS web_asset_chunks(
                    asset_id TEXT NOT NULL, part INTEGER NOT NULL,
                    sha256 TEXT NOT NULL, bytes_count INTEGER NOT NULL,
                    protected_base64 TEXT NOT NULL,
                    PRIMARY KEY(asset_id,part));
            """)

    def _row(self, owner: str, asset_id: str) -> dict[str, Any]:
        with self.store.connect("provider_content") as db:
            row = db.execute("SELECT * FROM web_asset_drafts "
                             "WHERE owner=? AND asset_id=?",
                             (owner,asset_id)).fetchone()
        if row is None:
            raise FileNotFoundError("Web attachment not found")
        return dict(row)

    def _check(self, item):
        work = self.control.work_item_info(item["work_item_id"],item["owner"])
        if work["run_id"] != item["run_id"]:
            raise WebAssetConflict("attachment WorkItem binding changed")
        grant = self.control.authorization.require(
            item["owner"], principal_type="agent",
            principal_id=item["principal_id"], capability="web:attach",
            scope_type="work_item", scope_id=item["work_item_id"],
            context={"provider":"chatgpt"}, local_owner=False)
        if not grant.get("grant_id"):
            raise PermissionError("explicit Web attachment grant required")
        return work

    def begin(self, owner: str, *, run_id: str, work_item_id: str,
              principal_id: str, conversation_id: str, message_id: str,
              content_type: str, expected_bytes: int, expected_sha256: str,
              operator_approved: bool = False) -> dict[str, Any]:
        if operator_approved is not True:
            raise PermissionError("human consent required to stage attachment")
        if (not isinstance(conversation_id,str) or not _IDENT.fullmatch(conversation_id)
                or not isinstance(message_id,str) or not _IDENT.fullmatch(message_id)):
            raise ValueError("exact bounded Web message identity required")
        if content_type not in _ALLOWED:
            raise ValueError("unsupported Web attachment format")
        if type(expected_bytes) is not int or not 1 <= expected_bytes <= _MAX_BYTES:
            raise ValueError("Web attachment exceeds maximum bytes")
        if not isinstance(expected_sha256,str) or not _SHA.fullmatch(expected_sha256):
            raise ValueError("expected SHA-256 is mandatory")
        item = dict(owner=owner,run_id=run_id,work_item_id=work_item_id,
                    principal_id=principal_id)
        work = self._check(item)
        run = self.control._run(run_id,owner)
        workspace = run.get("workspace")
        if not workspace:
            raise WebAssetConflict("Run lacks bound workspace")
        with self.store.connect("provider_content") as db:
            db.execute("BEGIN IMMEDIATE")
            used = db.execute(
                "SELECT COALESCE(SUM(expected_bytes),0) FROM web_asset_drafts "
                "WHERE owner=? AND workspace=? AND state!='DELETED'",
                (owner,workspace)).fetchone()[0]
            if used + expected_bytes > _MAX_TOTAL:
                raise WebAssetConflict("Web attachment workspace quota exceeded")
            ident = "web-asset-" + uuid.uuid4().hex
            db.execute("INSERT INTO web_asset_drafts "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?,'RECEIVING',?)",
                       (ident,owner,workspace,run_id,work_item_id,principal_id,
                        conversation_id,message_id,content_type,expected_bytes,
                        expected_sha256,self.clock()))
        return self.status(owner,ident)

    def put_chunk(self, owner: str, asset_id: str, *, part: int,
                  content: bytes) -> dict[str, Any]:
        item = self._row(owner,asset_id)
        self._check(item)
        if item["state"] != "RECEIVING":
            raise WebAssetConflict("attachment is not receiving chunks")
        if type(part) is not int or not 0 <= part < 64:
            raise ValueError("bounded part index required")
        if not isinstance(content,bytes) or not 1 <= len(content) <= _CHUNK:
            raise ValueError("bounded binary chunk required")
        digest = hashlib.sha256(content).hexdigest()
        with self.store.connect("provider_content") as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT sha256 FROM web_asset_chunks "
                             "WHERE asset_id=? AND part=?",(asset_id,part)).fetchone()
            if old:
                if old["sha256"] != digest:
                    raise WebAssetConflict("chunk index collision")
                return self.status(owner,asset_id)
            total = db.execute("SELECT COALESCE(SUM(bytes_count),0) FROM web_asset_chunks "
                               "WHERE asset_id=?", (asset_id,)).fetchone()[0]
            if total + len(content) > item["expected_bytes"]:
                raise WebAssetConflict("attachment byte quota exceeded")
            wrapped = protect_secret(base64.b64encode(content).decode("ascii"))
            if not wrapped.startswith(("dpapi:","keyring:")):
                raise RuntimeError("OS protection required for Web attachment bytes")
            db.execute("INSERT INTO web_asset_chunks VALUES(?,?,?,?,?)",
                       (asset_id,part,digest,len(content),wrapped))
        return self.status(owner,asset_id)

    def _bytes(self, db, asset_id):
        chunks = db.execute("SELECT * FROM web_asset_chunks WHERE asset_id=? ORDER BY part",
                            (asset_id,)).fetchall()
        if [r["part"] for r in chunks] != list(range(len(chunks))):
            raise WebAssetConflict("missing contiguous Web attachment chunk")
        parts = []
        for chunk in chunks:
            cipher = chunk["protected_base64"]
            if not cipher.startswith(("dpapi:","keyring:")):
                raise WebAssetConflict("plaintext Web attachment rejected")
            raw = base64.b64decode(unprotect_secret(cipher),validate=True)
            if hashlib.sha256(raw).hexdigest() != chunk["sha256"] or len(raw) != chunk["bytes_count"]:
                raise WebAssetConflict("Web attachment chunk integrity failure")
            parts.append(raw)
        return b"".join(parts)

    def finish(self, owner: str, asset_id: str) -> dict[str, Any]:
        item = self._row(owner,asset_id)
        self._check(item)
        if item["state"] == "READY_LOCAL":
            return self.status(owner,asset_id)
        if item["state"] != "RECEIVING":
            raise WebAssetConflict("attachment cannot finalize")
        with self.store.connect("provider_content") as db:
            db.execute("BEGIN IMMEDIATE")
            raw = self._bytes(db,asset_id)
            if len(raw) != item["expected_bytes"] or (
                hashlib.sha256(raw).hexdigest() != item["expected_sha256"]):
                raise WebAssetConflict("incomplete or altered Web attachment")
            db.execute("UPDATE web_asset_drafts SET state='READY_LOCAL' "
                       "WHERE asset_id=? AND owner=?", (asset_id,owner))
        return self.status(owner,asset_id)

    def read(self, owner: str, asset_id: str) -> bytes:
        item = self._row(owner,asset_id)
        self._check(item)
        if item["state"] != "READY_LOCAL":
            raise WebAssetConflict("attachment not finalized")
        with self.store.connect("provider_content") as db:
            raw = self._bytes(db,asset_id)
        if len(raw) != item["expected_bytes"] or hashlib.sha256(raw).hexdigest() != item["expected_sha256"]:
            raise WebAssetConflict("attachment digest changed")
        return raw

    def status(self, owner: str, asset_id: str) -> dict[str, Any]:
        item = self._row(owner,asset_id)
        return {"asset_id":asset_id,"state":item["state"],
                "expected_bytes":item["expected_bytes"],
                "sha256":item["expected_sha256"],
                "conversation_id":item["conversation_id"],
                "message_id":item["message_id"],"work_item_id":item["work_item_id"],
                "web_uploaded":False,"automatic_forward":False}

    def discard(self, owner: str, asset_id: str, *,
                operator_approved: bool = False) -> None:
        if operator_approved is not True:
            raise PermissionError("explicit cleanup approval required")
        item = self._row(owner,asset_id)
        self._check(item)
        with self.store.connect("provider_content") as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM web_asset_chunks WHERE asset_id=?", (asset_id,))
            db.execute("UPDATE web_asset_drafts SET state='DELETED' "
                       "WHERE owner=? AND asset_id=?", (owner,asset_id))
