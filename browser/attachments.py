"""Attachment descriptors for observed Web turns.

The Edge composer path already pastes images before the prompt text. This
module adds the *descriptive* layer the shell/viewers need: typed attachment
descriptors (image/pdf/text/code), per-turn quotas, data-URL validation and
evidence metadata (sha256/size) WITHOUT carrying raw bytes into the ledger.
Raw bytes stay in the page/relay payload; here only fingerprints travel, so
logs and exports never leak document content.
"""
from __future__ import annotations

import binascii

import base64
import hashlib
import json
import re

ATTACHMENT_KINDS = frozenset({"image", "pdf", "text", "code"})
MAX_ATTACHMENTS_PER_TURN = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
# Chunked upload bounds for attachments above the shell body budget.
# The shell bridge caps POST bodies at 800k: raw chunks are 512KiB so the
# base64 data URL (~699k) plus JSON envelope stays under the limit.
CHUNK_BYTES = 512 * 1024
MAX_CHUNKS_PER_UPLOAD = 40
UPLOAD_TTL_S = 1800

# Final shell action schemas for chunked attachment upload (Brisa contract
# for Prisma/Codex; the bridge allowlist registration itself is Codex-owned).
# Every mutating call carries its own request_key; status accepts upload_id
# or any request_key for dedupe queries after an ambiguous reply. The UI
# keeps local progress by (upload_id, index, sha) and retries a chunk with
# the SAME request_key — never a new key for the same index, never automatic
# resend after an ambiguous reply (status first, then resume).
ATTACHMENT_UPLOAD_SCHEMAS: dict = {
    "attachment_upload_begin": {
        "payload": {"project_id": "str", "space_id": "optional str",
                    "conversation_id": "optional ID", "kind": "image|pdf|text|code",
                    "name": "1..256", "total_bytes": "1..budget",
                    "total_sha256": "hex sha256"},
        "returns": {"upload_id": "upl-<hex>", "chunk_bytes": 524288,
                    "chunks_expected": "int", "state": "open"},
    },
    "attachment_upload_chunk": {
        "payload": {"upload_id": "str", "index": "0-based int",
                    "data_url": "base64 data URL <=~700k chars",
                    "chunk_sha256": "optional hex sha256"},
        "returns": {"upload_id": "str", "received_chunks": "int",
                    "received_bytes": "int", "complete": "bool",
                    "idempotent_replay": "bool"},
    },
    "attachment_upload_complete": {
        "payload": {"upload_id": "str"},
        "returns": {"attachments": "[receipt]", "evidence": "summary",
                    "idempotent_replay": "bool"},
    },
    "attachment_upload_abort": {
        "payload": {"upload_id": "str"},
        "returns": {"upload_id": "str", "state": "aborted",
                    "idempotent_replay": "bool"},
    },
    "attachment_upload_status": {
        "payload": {"upload_id": "optional",
                    "request_key": "optional chunk/register key"},
        "returns": {"upload_id": "str", "state": "open|complete|aborted",
                    "received_chunks": "int", "received_bytes": "int",
                    "complete": "bool", "expired": "bool"},
    },
}
_DATA_URL = re.compile(r"^data:([A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)$")


def _decode_data_url(value: str) -> tuple[str, bytes]:
    if not isinstance(value, str) or len(value) > (MAX_DOCUMENT_BYTES * 4 // 3 + 256):
        raise ValueError("attachment data URL exceeds budget")
    match = _DATA_URL.fullmatch(value.strip())
    if match is None:
        raise ValueError("attachment must be a base64 data URL")
    mime, payload = match.group(1).lower(), match.group(2)
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("attachment payload is not valid base64") from exc
    return mime, raw


def describe_attachments(items: list[dict]) -> list[dict]:
    """Validate caller-supplied attachments and return viewer-safe descriptors.

    Each item: {"kind": "image|pdf|text|code", "data_url": ..., "name": ...}.
    Returns descriptors with sha256/byte size and viewer hints. Raises
    ValueError fail-closed on any quota or type violation.
    """
    if not isinstance(items, list) or len(items) > MAX_ATTACHMENTS_PER_TURN:
        raise ValueError(f"attachments must be a list of 0..{MAX_ATTACHMENTS_PER_TURN}")
    descriptors: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("attachment must be an object")
        kind = item.get("kind")
        if kind not in ATTACHMENT_KINDS:
            raise ValueError("unsupported attachment kind")
        name = item.get("name")
        if name is not None and (not isinstance(name, str) or not 1 <= len(name) <= 256):
            raise ValueError("attachment name must be 1..256 characters")
        mime, raw = _decode_data_url(item.get("data_url", ""))
        budget = MAX_IMAGE_BYTES if kind == "image" else MAX_DOCUMENT_BYTES
        if kind == "image" and mime not in {"image/png", "image/jpeg"}:
            raise ValueError("image attachments must be PNG or JPEG")
        if kind == "pdf" and mime != "application/pdf":
            raise ValueError("pdf attachments must use application/pdf")
        if kind in {"text", "code"} and mime != "text/plain":
            raise ValueError("text/code attachments must use text/plain")
        if len(raw) > budget or not raw:
            raise ValueError("attachment byte budget exceeded or empty")
        descriptors.append({
            "kind": kind,
            "name": name or ("attachment-%d" % (len(descriptors) + 1)),
            "mime": mime,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "viewer": "image" if kind == "image" else ("pdf" if kind == "pdf" else "code"),
        })
    return descriptors


def evidence_summary(descriptors: list[dict]) -> dict:
    """Compact evidence block stored alongside a send receipt (no raw bytes)."""
    return {
        "attachments": len(descriptors),
        "kinds": sorted({d["kind"] for d in descriptors}),
        "total_bytes": sum(int(d["bytes"]) for d in descriptors),
        "sha256": [d["sha256"] for d in descriptors],
    }


class AttachmentStore:
    """Real content-addressed attachment storage under the server state root.

    `attachment_register` (shell) persists bytes and returns receipts;
    `validate_attachments` resolves message_send refs to evidence without
    leaking bytes into logs. Bytes live in files, the ledger (chat_access
    DB) holds only fingerprints. Removal is explicit; no TTL deletes user
    data silently.
    """

    def __init__(self, state_root, *, store=None) -> None:
        from pathlib import Path as _Path

        from sentra_mcp.services.chat_access import _PRINCIPAL as _P
        from sentra_mcp.services.chat_access import _validate as _v

        self.state_root = _Path(state_root)
        self._principal = _P
        self._validate = _v
        if store is None:
            from sentra_mcp.services.control_store import create_control_plane_store
            store = create_control_plane_store(self.state_root)
        self.store = store
        db = self.store.connect("chat_access")
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS browser_attachment_blobs(
                    attachment_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    kind TEXT NOT NULL, name TEXT NOT NULL,
                    mime TEXT NOT NULL, bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS browser_attachment_blobs_owner
                    ON browser_attachment_blobs(owner,sha256);
                CREATE TABLE IF NOT EXISTS browser_attachment_requests(
                    owner TEXT NOT NULL, project_id TEXT NOT NULL,
                    request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    result TEXT,
                    PRIMARY KEY(owner,project_id,request_key));
                CREATE TABLE IF NOT EXISTS browser_attachment_uploads(
                    upload_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    project_id TEXT NOT NULL, kind TEXT NOT NULL,
                    name TEXT NOT NULL, total_bytes INTEGER NOT NULL,
                    total_sha256 TEXT NOT NULL, received_bytes INTEGER NOT NULL,
                    received_chunks INTEGER NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS browser_attachment_chunk_requests(
                    upload_id TEXT NOT NULL, chunk_index INTEGER NOT NULL,
                    request_key TEXT NOT NULL, chunk_sha256 TEXT NOT NULL,
                    ack TEXT,
                    PRIMARY KEY(upload_id,chunk_index),
                    UNIQUE(request_key));
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(browser_attachment_blobs)")}
            for column in ("project_id", "space_id", "conversation_id",
                           "request_key", "operation_id", "work_item_id"):
                if column not in columns:
                    db.execute(f"ALTER TABLE browser_attachment_blobs ADD COLUMN {column} TEXT")
            upload_columns = {row[1] for row in db.execute("PRAGMA table_info(browser_attachment_uploads)")}
            if "state" not in upload_columns:
                db.execute("ALTER TABLE browser_attachment_uploads ADD COLUMN state TEXT NOT NULL DEFAULT 'open'")
            for column in ("space_id", "conversation_id", "request_key"):
                if column not in upload_columns:
                    db.execute(f"ALTER TABLE browser_attachment_uploads ADD COLUMN {column} TEXT")
            db.execute("CREATE TABLE IF NOT EXISTS browser_attachment_upload_intents("
                       "owner TEXT NOT NULL,project_id TEXT NOT NULL,request_key TEXT NOT NULL,"
                       "fingerprint TEXT NOT NULL,upload_id TEXT NOT NULL,"
                       "PRIMARY KEY(owner,project_id,request_key))")
            db.commit()
        finally:
            db.close()

    def attachment_availability(self) -> dict:
        """Composition data for home.attachments (Codex): bounds, no secrets."""
        return {"available": True,
                "max_attachments_per_turn": MAX_ATTACHMENTS_PER_TURN,
                "max_image_bytes": MAX_IMAGE_BYTES,
                "max_document_bytes": MAX_DOCUMENT_BYTES,
                "kinds": sorted(ATTACHMENT_KINDS),
                "chunk_bytes": CHUNK_BYTES,
                "max_chunks_per_upload": MAX_CHUNKS_PER_UPLOAD,
                # Honest availability: local storage receipt only. Stored bytes
                # do NOT prove delivery to the model; that requires the
                # composer send plus the exact provider receipt.
                "proves_model_delivery": False}

    def _blob_path(self, digest: str):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("canonical attachment digest required")
        return (self.state_root / "attachments" / digest[:2] /
                digest[2:])

    def _upload_dir(self, upload_id: str):
        if not isinstance(upload_id, str) or not re.fullmatch(r"upl-[0-9a-f]{32}", upload_id):
            raise ValueError("canonical upload identity required")
        return (self.state_root / "attachments" / "uploads" / upload_id)

    def _store_bytes(self, digest: str, raw: bytes) -> None:
        """Atomic OS-encrypted write bound to digest; admission at each effect."""
        from .protected_assets import write_asset
        path = self._blob_path(digest)
        if path.is_file():
            if self._check_bytes(digest, len(raw)) != raw:
                raise PermissionError("attachment content collision")
            return
        write_asset(self.state_root, path, raw, binding="attachment:" + digest)

    def _check_bytes(self, digest: str, size: int) -> bytes:
        """Read + verify SHA-256 and size. Any mismatch fails closed."""
        from .protected_assets import read_asset
        raw = read_asset(self.state_root, self._blob_path(digest),
                         binding="attachment:" + digest, max_bytes=max(1, size))
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise PermissionError("attachment bytes are missing or changed")
        return raw

    def attachment_dispatch(self, project_id: str, owner: str, action: str,
                              payload: dict, request_key: str | None) -> dict:
        """Shell-composed entry for all attachment actions (Codex wires the
        runtime to this dispatcher). Single-shot `attachment_register` keeps
        its direct method below and delegates here."""
        if action == "attachment_register":
            return self.attachment_register(project_id, owner, action, payload,
                                            request_key)
        if action == "attachment_upload_begin":
            return self.shell_upload_begin(project_id, owner, payload, request_key)
        if action == "attachment_upload_chunk":
            return self.shell_upload_chunk(project_id, owner, payload, request_key)
        if action == "attachment_upload_complete":
            return self.shell_upload_complete(project_id, owner, payload, request_key)
        if action == "attachment_upload_abort":
            return self.upload_abort(project_id, owner, payload, request_key)
        if action == "attachment_upload_status":
            return self.upload_status(project_id, owner, payload)
        raise ValueError("unsupported attachment action")

    def attachment_register(self, project_id: str, owner: str, action: str,
                            payload: dict, request_key: str | None) -> dict:
        """Shell-composed `attachment_register` with CAS idempotency + scope.

        Blobs bind (owner, project_id, space_id, conversation_id) plus the
        originating operation_id/work_item_id when the server supplies them;
        cross-scope refs are rejected at validate time. The same request_key
        replays the stored result; a key reused for another fingerprint is a
        conflict. Reply loss therefore never duplicates storage.
        """
        import time as _time
        import uuid as _uuid

        self._validate("principal", owner, self._principal)
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 200:
            raise ValueError("attachment_register requires request_key 1..200")
        if not isinstance(project_id, str) or not project_id:
            raise ValueError("attachment_register requires project_id")
        space_id = payload.get("space_id")
        conversation = payload.get("conversation") or {}
        conversation_id = payload.get("conversation_id") or conversation.get("conversation_id")
        for label, value in (("space_id", space_id), ("conversation_id", conversation_id)):
            if value is not None and (not isinstance(value, str) or not value or len(value) > 200):
                raise ValueError(f"attachment {label} must be a non-empty string ≤200")
        operation_id = conversation.get("operation_id")
        work_item_id = conversation.get("work_item_id")
        for label, value in (("operation_id", operation_id), ("work_item_id", work_item_id)):
            if value is not None and (not isinstance(value, str) or not value or len(value) > 200):
                raise ValueError(f"attachment {label} must be a non-empty string ≤200")
        items = payload.get("attachments")
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_ATTACHMENTS_PER_TURN:
            raise ValueError(
                f"attachment_register requires 1..{MAX_ATTACHMENTS_PER_TURN} attachments")
        descriptors = describe_attachments(items)
        fingerprint = hashlib.sha256(json.dumps(
            {"project_id": project_id, "space_id": space_id,
             "conversation_id": conversation_id, "descriptors": descriptors},
            sort_keys=True).encode()).hexdigest()
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM browser_attachment_requests WHERE owner=? AND project_id=? AND request_key=?",
                                  (owner, project_id, request_key)).fetchone()
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise ValueError("request_key already used for another attachment intent")
                if existing["result"]:
                    return {**json.loads(existing["result"]),
                            "idempotent_replay": True}
                row = db.execute("SELECT attachment_id,kind,name,mime,bytes,sha256,project_id,space_id,conversation_id,operation_id,work_item_id,created FROM "
                                 "browser_attachment_blobs WHERE request_key=? AND owner=?",
                                 (request_key, owner)).fetchall()
                if row:
                    receipts = [dict(r) for r in row]
                    result = {"attachments": receipts,
                              "evidence": evidence_summary(receipts),
                              "idempotent_replay": True}
                    db.execute("UPDATE browser_attachment_requests SET result=? WHERE owner=? AND project_id=? AND request_key=?",
                               (json.dumps(result), owner, project_id, request_key))
                    db.commit()
                    return result
            import base64 as _b64

            receipts = []
            for item, descriptor in zip(items, descriptors):
                match = _DATA_URL.fullmatch(str(item["data_url"]).strip())
                if match is None:
                    raise ValueError("invalid attachment data URL")
                raw = _b64.b64decode(match.group(2), validate=True)
                if hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
                    raise ValueError("attachment bytes do not match descriptor")
                attachment_id = "att-" + _uuid.uuid4().hex
                self._store_bytes(descriptor["sha256"], raw)
                created = _time.time()
                db.execute("INSERT INTO browser_attachment_blobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (attachment_id, owner, descriptor["kind"],
                            descriptor["name"], descriptor["mime"],
                            descriptor["bytes"], descriptor["sha256"],
                            created, project_id, space_id, conversation_id,
                            request_key, operation_id, work_item_id))
                receipts.append({"attachment_id": attachment_id,
                                 **descriptor, "project_id": project_id,
                                 "space_id": space_id,
                                 "conversation_id": conversation_id,
                                 "operation_id": operation_id,
                                 "work_item_id": work_item_id,
                                 "stored": True, "stored_at": created})
            result = {"attachments": receipts,
                      "evidence": evidence_summary(receipts),
                      "idempotent_replay": False}
            db.execute("INSERT INTO browser_attachment_requests VALUES(?,?,?,?,?) "
                       "ON CONFLICT(owner,project_id,request_key) DO UPDATE SET "
                       "fingerprint=excluded.fingerprint,result=excluded.result",
                       (owner, project_id, request_key, fingerprint, json.dumps(result)))
            db.commit()
            return result
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def upload_begin(self, owner: str, *, project_id: str, kind: str,
                     name: str, total_bytes: int, total_sha256: str,
                     request_key: str | None = None, space_id=None, conversation_id=None) -> dict:
        """Start a chunked upload for attachments above the shell body budget."""
        import re as _re
        import time as _time
        import uuid as _uuid

        self._validate("principal", owner, self._principal)
        if not isinstance(project_id, str) or not project_id:
            raise ValueError("upload_begin requires project_id")
        if kind not in ATTACHMENT_KINDS:
            raise ValueError("unsupported attachment kind")
        if not isinstance(name, str) or not 1 <= len(name) <= 256:
            raise ValueError("upload name must be 1..256 characters")
        budget = MAX_IMAGE_BYTES if kind == "image" else MAX_DOCUMENT_BYTES
        if type(total_bytes) is not int or not 1 <= total_bytes <= budget:
            raise ValueError("upload total_bytes exceeds budget")
        if not isinstance(total_sha256, str) or _re.fullmatch(r"[a-f0-9]{64}", total_sha256) is None:
            raise ValueError("upload total_sha256 must be hex SHA-256")
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 200:
            raise ValueError("upload_begin requires a durable request_key")
        for value in (space_id, conversation_id):
            if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 200):
                raise ValueError("bounded upload scope required")
        fingerprint = hashlib.sha256(json.dumps([kind, name, total_bytes, total_sha256,
            space_id, conversation_id], separators=(",", ":")).encode()).hexdigest()
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM browser_attachment_upload_intents "
                "WHERE owner=? AND project_id=? AND request_key=?",
                (owner, project_id, request_key)).fetchone()
            if prior is not None:
                if prior["fingerprint"] != fingerprint:
                    raise ValueError("upload request_key conflicts with recorded scope/content")
                return {"upload_id": prior["upload_id"], "chunk_bytes": CHUNK_BYTES,
                        "chunks_expected": (total_bytes + CHUNK_BYTES - 1) // CHUNK_BYTES,
                        "idempotent_replay": True}
            upload_id = "upl-" + _uuid.uuid4().hex
            db.execute("INSERT INTO browser_attachment_uploads "
                       "(upload_id,owner,project_id,kind,name,total_bytes,total_sha256,"
                       "received_bytes,received_chunks,created,state,space_id,conversation_id,request_key) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,'open',?,?,?)",
                       (upload_id, owner, project_id, kind, name, total_bytes,
                        total_sha256, 0, 0, _time.time(), space_id, conversation_id, request_key))
            db.execute("INSERT INTO browser_attachment_upload_intents VALUES(?,?,?,?,?)",
                       (owner, project_id, request_key, fingerprint, upload_id))
            db.commit()
            return {"upload_id": upload_id, "chunk_bytes": CHUNK_BYTES,
                    "chunks_expected": (total_bytes + CHUNK_BYTES - 1) // CHUNK_BYTES}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def shell_upload_begin(self, project_id: str, owner: str, payload: dict,
                             request_key: str | None) -> dict:
        """Shell wrapper: begin is idempotent by its own request_key."""
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 200:
            raise ValueError("attachment_upload_begin requires request_key 1..200")
        kind, name = payload.get("kind"), payload.get("name")
        total_bytes, total_sha256 = payload.get("total_bytes"), payload.get("total_sha256")
        if (not isinstance(kind, str) or not isinstance(name, str)
                or not isinstance(total_bytes, int) or not isinstance(total_sha256, str)):
            raise ValueError("invalid attachment upload metadata")
        return self.upload_begin(owner, project_id=project_id,
                                 kind=kind, name=name, total_bytes=total_bytes,
                                 total_sha256=total_sha256, request_key=request_key,
                                 space_id=payload.get("space_id"),
                                 conversation_id=payload.get("conversation_id") or
                                 (payload.get("conversation") or {}).get("conversation_id"))

    def upload_chunk(self, owner: str, *, upload_id: str, index: int,
                     data_url: str, request_key: str,
                     chunk_sha256: str | None = None) -> dict:
        """Append one base64 chunk with per-chunk request_key idempotency.

        The same (upload_id, index, request_key) replays the stored ack, so
        an ambiguous reply is resolved by retrying with the SAME key — never
        a new key for the same index. A key reused for another
        (upload, index, bytes) intent is a conflict.
        """
        import base64 as _b64
        import re as _re
        import time as _time

        self._validate("principal", owner, self._principal)
        if not isinstance(upload_id, str) or not upload_id.startswith("upl-"):
            raise ValueError("invalid upload_id")
        if type(index) is not int or index < 0:
            raise ValueError("chunk index must be a non-negative integer")
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 200:
            raise ValueError("attachment_upload_chunk requires request_key 1..200")
        if chunk_sha256 is not None and (
                not isinstance(chunk_sha256, str)
                or _re.fullmatch(r"[a-f0-9]{64}", chunk_sha256) is None):
            raise ValueError("chunk_sha256 must be hex SHA-256")
        match = _DATA_URL.fullmatch(str(data_url or "").strip())
        if match is None:
            raise ValueError("chunk must be a base64 data URL")
        raw = _b64.b64decode(match.group(2), validate=True)
        if len(raw) > CHUNK_BYTES or not raw:
            raise ValueError("chunk exceeds chunk budget or is empty")
        digest = hashlib.sha256(raw).hexdigest()
        if chunk_sha256 is not None and chunk_sha256 != digest:
            raise ValueError("chunk bytes do not match chunk_sha256")
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM browser_attachment_uploads WHERE upload_id=? AND owner=?",
                             (upload_id, owner)).fetchone()
            if row is None:
                raise PermissionError("upload belongs to another owner or is unknown")
            if row["state"] != "open":
                raise ValueError("upload is already %s" % row["state"])
            if _time.time() - float(row["created"]) > UPLOAD_TTL_S:
                raise ValueError("upload expired; begin again")
            prior = db.execute("SELECT * FROM browser_attachment_chunk_requests WHERE upload_id=? AND chunk_index=?",
                               (upload_id, index)).fetchone()
            if prior is not None:
                if prior["request_key"] != request_key or prior["chunk_sha256"] != digest:
                    raise ValueError("request_key already used for another chunk intent")
                if prior["ack"]:
                    return {**json.loads(prior["ack"]), "idempotent_replay": True}
            clash = db.execute("SELECT upload_id,chunk_index FROM browser_attachment_chunk_requests WHERE request_key=?",
                               (request_key,)).fetchone()
            if clash is not None and (clash["upload_id"], clash["chunk_index"]) != (upload_id, index):
                raise ValueError("request_key already used for another chunk")
            if index != int(row["received_chunks"]):
                raise ValueError("chunk index out of order")
            if int(row["received_bytes"]) + len(raw) > int(row["total_bytes"]):
                raise ValueError("upload would exceed declared total")
            part = self._upload_dir(upload_id) / ("%08d.part" % index)
            from .protected_assets import write_asset
            write_asset(self.state_root, part, raw, binding="chunk:%s:%d" % (upload_id, index))
            received_chunks = index + 1
            received_bytes = int(row["received_bytes"]) + len(raw)
            db.execute("UPDATE browser_attachment_uploads SET received_bytes=?,received_chunks=? WHERE upload_id=?",
                       (received_bytes, received_chunks, upload_id))
            ack = {"upload_id": upload_id, "received_chunks": received_chunks,
                   "received_bytes": received_bytes,
                   "complete": received_bytes >= int(row["total_bytes"]),
                   "idempotent_replay": False}
            db.execute("INSERT INTO browser_attachment_chunk_requests VALUES(?,?,?,?,?) "
                       "ON CONFLICT(upload_id,chunk_index) DO UPDATE SET "
                       "request_key=excluded.request_key,chunk_sha256=excluded.chunk_sha256,ack=excluded.ack",
                       (upload_id, index, request_key, digest, json.dumps(ack)))
            db.commit()
            return ack
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def shell_upload_chunk(self, project_id: str, owner: str, payload: dict,
                           request_key: str | None) -> dict:
        """Shell wrapper: per-chunk request_key comes from the envelope."""
        upload_id = payload.get("upload_id")
        index, data_url = payload.get("index"), payload.get("data_url")
        if (not isinstance(upload_id, str) or not isinstance(index, int)
                or not isinstance(data_url, str) or not isinstance(request_key, str)):
            raise ValueError("invalid attachment upload chunk")
        db = self.store.connect("chat_access")
        try:
            row = db.execute("SELECT project_id FROM browser_attachment_uploads WHERE upload_id=?",
                             (upload_id,)).fetchone()
        finally:
            db.close()
        if row is None or row["project_id"] != project_id:
            raise PermissionError("upload belongs to another project or is unknown")
        return self.upload_chunk(owner, upload_id=upload_id,
                                 index=index, data_url=data_url,
                                 request_key=request_key,
                                 chunk_sha256=payload.get("chunk_sha256"))

    def shell_upload_complete(self, project_id: str, owner: str, payload: dict,
                                request_key: str | None) -> dict:
        """Shell wrapper: complete is idempotent by its own request_key."""
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 200:
            raise ValueError("attachment_upload_complete requires request_key 1..200")
        conversation = payload.get("conversation") or {}
        upload_id = payload.get("upload_id")
        if not isinstance(upload_id, str):
            raise ValueError("invalid attachment upload ID")
        return self.upload_complete(owner, upload_id=upload_id,
                                    project_id=project_id, request_key=request_key,
                                    space_id=payload.get("space_id"),
                                    conversation_id=payload.get("conversation_id") or conversation.get("conversation_id"),
                                    operation_id=conversation.get("operation_id"),
                                    work_item_id=conversation.get("work_item_id"))

    def upload_abort(self, project_id: str, owner: str, payload: dict,
                     request_key: str | None) -> dict:
        """Idempotent abort: staging removed, state -> aborted. Replay safe."""
        import shutil as _shutil

        self._validate("principal", owner, self._principal)
        upload_id = payload.get("upload_id")
        if not isinstance(upload_id, str) or not upload_id.startswith("upl-"):
            raise ValueError("invalid upload_id")
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM browser_attachment_uploads WHERE upload_id=? AND owner=?",
                             (upload_id, owner)).fetchone()
            if row is None or row["project_id"] != project_id:
                raise PermissionError("upload belongs to another owner/project or is unknown")
            if row["state"] == "aborted":
                db.rollback()
                return {"upload_id": upload_id, "state": "aborted",
                        "idempotent_replay": True}
            if row["state"] == "complete":
                raise ValueError("completed upload cannot be aborted; delete the blob explicitly")
            db.execute("UPDATE browser_attachment_uploads SET state='aborted' WHERE upload_id=?",
                       (upload_id,))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        from .protected_assets import safe_path, checkpoint
        checkpoint(required=True)
        directory = safe_path(self.state_root, self._upload_dir(upload_id))
        if directory.exists():
            if any(path.is_symlink() for path in directory.rglob("*")):
                raise PermissionError("unsafe upload staging cleanup")
            checkpoint(required=True)
            _shutil.rmtree(directory)
        return {"upload_id": upload_id, "state": "aborted",
                "idempotent_replay": False}

    def upload_status(self, project_id: str, owner: str, payload: dict) -> dict:
        """Dedupe query after an ambiguous reply: resolve by upload_id or by
        any chunk/register request_key. Read-only; never resends or mutates."""
        self._validate("principal", owner, self._principal)
        upload_id = payload.get("upload_id")
        request_key = payload.get("request_key")
        db = self.store.connect("chat_access")
        try:
            if isinstance(upload_id, str) and upload_id:
                row = db.execute("SELECT * FROM browser_attachment_uploads WHERE upload_id=? AND owner=?",
                                 (upload_id, owner)).fetchone()
                if row is None or (project_id is not None and row["project_id"] != project_id):
                    raise PermissionError("upload belongs to another owner/project or is unknown")
            elif isinstance(request_key, str) and request_key:
                begin = db.execute("SELECT upload_id FROM browser_attachment_upload_intents "
                    "WHERE owner=? AND project_id=? AND request_key=?",
                    (owner, project_id, request_key)).fetchone()
                if begin is not None:
                    row = db.execute("SELECT * FROM browser_attachment_uploads WHERE upload_id=? AND owner=? AND project_id=?",
                                     (begin["upload_id"], owner, project_id)).fetchone()
                    if row is None:
                        return {"state": "uncertain", "requires_reconciliation": True}
                    return self._upload_view(row)
                chunk = db.execute("SELECT * FROM browser_attachment_chunk_requests WHERE request_key=?",
                                   (request_key,)).fetchone()
                if chunk is not None:
                    row = db.execute("SELECT * FROM browser_attachment_uploads WHERE upload_id=? AND owner=?",
                                     (chunk["upload_id"], owner)).fetchone()
                    if row is None or row["project_id"] != project_id:
                        raise PermissionError("upload belongs to another owner or is unknown")
                    if chunk["ack"]:
                        return {**json.loads(chunk["ack"]),
                                "upload_id": chunk["upload_id"], "state": row["state"]}
                    return self._upload_view(row)
                reg = db.execute("SELECT * FROM browser_attachment_requests WHERE request_key=? AND owner=? AND project_id=?",
                                 (request_key, owner, project_id)).fetchone()
                if reg is None:
                    raise PermissionError("request_key is unknown")
                if reg["result"]:
                    return {**json.loads(reg["result"]), "state": "complete"}
                return {"state": "uncertain",
                        "reason": "interrupted request requires reconciliation"}
            else:
                raise ValueError("upload_status requires upload_id or request_key")
            return self._upload_view(row)
        finally:
            db.close()

    @staticmethod
    def _upload_view(row) -> dict:
        import time as _time

        total = int(row["total_bytes"])
        received = int(row["received_bytes"])
        return {"upload_id": row["upload_id"], "state": row["state"],
                "received_chunks": int(row["received_chunks"]),
                "received_bytes": received,
                "complete": received >= total,
                "expired": (_time.time() - float(row["created"])) > UPLOAD_TTL_S}

    def upload_complete(self, owner: str, *, upload_id: str, project_id: str,
                        request_key: str, space_id: str | None = None,
                        conversation_id: str | None = None,
                        operation_id: str | None = None,
                        work_item_id: str | None = None) -> dict:
        """Verify total SHA-256 and register the assembled bytes as one blob."""
        import time as _time
        import uuid as _uuid

        self._validate("principal", owner, self._principal)
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM browser_attachment_uploads WHERE upload_id=? AND owner=?",
                             (upload_id, owner)).fetchone()
            if row is None or row["project_id"] != project_id:
                raise PermissionError("upload belongs to another owner or project")
            for field, wanted in (("space_id", space_id), ("conversation_id", conversation_id)):
                if row[field] != wanted:
                    raise PermissionError("completed attachment must preserve its original upload scope")
            if row["state"] == "aborted":
                raise ValueError("aborted upload cannot be completed")
            fingerprint = hashlib.sha256(json.dumps(
                {"upload_id": upload_id, "sha256": row["total_sha256"],
                 "operation_id": operation_id, "work_item_id": work_item_id},
                sort_keys=True).encode()).hexdigest()
            reg = db.execute("SELECT fingerprint,result FROM browser_attachment_requests WHERE owner=? AND project_id=? AND request_key=?",
                             (owner, project_id, request_key)).fetchone()
            if reg is not None:
                if reg["fingerprint"] != fingerprint:
                    raise PermissionError("attachment completion request_key has another immutable intent")
                if reg["result"] and row["state"] == "complete":
                    return {**json.loads(reg["result"]), "idempotent_replay": True}
                raise ValueError("attachment completion requires original receipt reconciliation")
            if row["state"] == "complete":
                raise ValueError("completed upload requires its original completion request_key")
            if int(row["received_bytes"]) != int(row["total_bytes"]):
                raise ValueError("upload is incomplete")
            directory = self._upload_dir(upload_id)
            from .protected_assets import read_asset, checkpoint
            parts = [directory / ("%08d.part" % i) for i in range(int(row["received_chunks"]))]
            assembled = b"".join(read_asset(self.state_root, part,
                binding="chunk:%s:%d" % (upload_id, i), max_bytes=CHUNK_BYTES)
                for i, part in enumerate(parts))
            if (len(assembled) != row["total_bytes"]
                    or hashlib.sha256(assembled).hexdigest() != row["total_sha256"]):
                raise PermissionError("assembled upload SHA-256 mismatch")
            # Image MIME follows the actual bytes, not the generic upload kind.
            mime = {"image": "image/png", "pdf": "application/pdf"}.get(
                row["kind"], "text/plain")
            if row["kind"] == "image":
                if assembled.startswith(b"\xff\xd8\xff"):
                    mime = "image/jpeg"
                elif not assembled.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("image bytes are not PNG/JPEG")
            if row["kind"] == "pdf" and not assembled.startswith(b"%PDF-"):
                raise ValueError("PDF bytes lack a PDF header")
            descriptor = {"kind": row["kind"], "name": row["name"],
                          "mime": mime, "bytes": len(assembled),
                          "sha256": row["total_sha256"],
                          "viewer": "image" if row["kind"] == "image" else (
                              "pdf" if row["kind"] == "pdf" else "code")}
            budget = MAX_IMAGE_BYTES if row["kind"] == "image" else MAX_DOCUMENT_BYTES
            if len(assembled) > budget:
                raise ValueError("assembled upload exceeds budget")
            self._store_bytes(row["total_sha256"], assembled)
            attachment_id = "att-" + _uuid.uuid4().hex
            created = _time.time()
            db.execute("INSERT INTO browser_attachment_blobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (attachment_id, owner, row["kind"], row["name"], mime,
                        len(assembled), row["total_sha256"], created,
                        project_id, space_id, conversation_id, request_key,
                        operation_id, work_item_id))
            receipt = {"attachment_id": attachment_id, **descriptor,
                       "project_id": project_id, "space_id": space_id,
                       "conversation_id": conversation_id,
                       "operation_id": operation_id,
                       "work_item_id": work_item_id,
                       "stored": True, "stored_at": created}
            db.execute("INSERT INTO browser_attachment_requests VALUES(?,?,?,?,?)",
                       (owner, project_id, request_key, fingerprint,
                        json.dumps({"attachments": [receipt],
                                    "evidence": evidence_summary([receipt]),
                                    "idempotent_replay": False})))
            db.execute("UPDATE browser_attachment_uploads SET state='complete' WHERE upload_id=?",
                       (upload_id,))
            db.commit()
            # Cleanup follows the durable receipt; a crash can leave encrypted
            # staging, but can never remove the only input before commit.
            for part in parts:
                try:
                    checkpoint(required=True)
                    part.unlink()
                except OSError:
                    pass
            try:
                checkpoint(required=True)
                directory.rmdir()
            except OSError:
                pass
            return {"attachments": [receipt],
                    "evidence": evidence_summary([receipt]),
                    "idempotent_replay": False}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def validate_attachments(self, owner: str, refs: list,
                             *, project_id: str | None = None,
                             space_id: str | None = None,
                             conversation_id: str | None = None) -> dict:
        """Resolve message_send attachment refs to evidence. Fail-closed.

        Checks owner + project/space/conversation scope binding (root passes
        the canonical conversation) and re-verifies content SHA-256 on every
        call; stale or foreign refs are denied, never degraded.
        """
        self._validate("principal", owner, self._principal)
        if not isinstance(refs, list) or len(refs) > MAX_ATTACHMENTS_PER_TURN:
            raise ValueError("attachment refs must be a list within quota")
        db = self.store.connect("chat_access")
        try:
            resolved = []
            for ref in refs:
                if not isinstance(ref, str) or not ref.startswith("att-"):
                    raise ValueError("invalid attachment ref")
                row = db.execute("SELECT kind,name,mime,bytes,sha256,project_id,space_id,conversation_id,operation_id,work_item_id FROM "
                                 "browser_attachment_blobs WHERE attachment_id=? AND owner=?",
                                 (ref, owner)).fetchone()
                if row is None:
                    raise PermissionError("attachment ref is unknown or belongs to another owner")
                if project_id is not None and row["project_id"] != project_id:
                    raise PermissionError("attachment ref belongs to another project")
                for key, wanted in (("space_id", space_id),
                                    ("conversation_id", conversation_id)):
                    if isinstance(wanted, str) and wanted and row[key] != wanted:
                        raise PermissionError(
                            "attachment ref belongs to another %s" % key)
                self._check_bytes(row["sha256"], int(row["bytes"]))
                resolved.append({"attachment_id": ref, **dict(row)})
        finally:
            db.close()
        return {"attachments": resolved,
                "evidence": evidence_summary(resolved)}

    def read_bytes(self, owner: str, attachment_id: str) -> tuple[dict, bytes]:
        """Server-side byte access for the composer upload path (Rastro/relay)."""
        self._validate("principal", owner, self._principal)
        db = self.store.connect("chat_access")
        try:
            row = db.execute("SELECT kind,name,mime,bytes,sha256,project_id,space_id,conversation_id,operation_id,work_item_id FROM "
                             "browser_attachment_blobs WHERE attachment_id=? AND owner=?",
                             (attachment_id, owner)).fetchone()
        finally:
            db.close()
        if row is None:
            raise PermissionError("attachment is unknown or belongs to another owner")
        raw = self._check_bytes(row["sha256"], int(row["bytes"]))
        return dict(row), raw

    def protect_legacy_blob(self, owner: str, attachment_id: str, *, operator_approved=False):
        """Explicit host migration; ordinary readers never fall back to plaintext."""
        if operator_approved is not True:
            raise PermissionError("operator-approved legacy asset migration required")
        from .protected_assets import safe_path, write_asset, checkpoint
        self._validate("principal", owner, self._principal)
        db = self.store.connect("chat_access")
        try:
            row = db.execute("SELECT sha256,bytes FROM browser_attachment_blobs WHERE owner=? AND attachment_id=?",
                             (owner, attachment_id)).fetchone()
        finally:
            db.close()
        if row is None:
            raise PermissionError("legacy asset is not scoped to this owner")
        path = safe_path(self.state_root, self._blob_path(row["sha256"]))
        checkpoint(required=True)
        with path.open("rb") as source:
            prefix = source.read(8)
        if prefix.startswith((b"dpapi:", b"keyring:")):
            self._check_bytes(row["sha256"], row["bytes"])
            return {"protected": True, "idempotent_replay": True, "forensic_erasure": False}
        if path.stat().st_size != row["bytes"] or row["bytes"] > MAX_DOCUMENT_BYTES:
            raise PermissionError("legacy asset byte bounds changed")
        checkpoint(required=True)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise PermissionError("legacy asset digest changed")
        write_asset(self.state_root, path, raw, binding="attachment:" + row["sha256"])
        # Replacing a file never proves scrubbing OS snapshots/free pages or
        # portability of the existing DPAPI/keyring identity.
        return {"protected": True, "idempotent_replay": False, "forensic_erasure": False}
