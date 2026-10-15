"""Protected native ChatGPT Web binaries, scoped to a verified original Web send.

The extension transfers only canonical ChatGPT file IDs: never arbitrary URLs,
DOM image nodes, data URLs supplied by the page or SENTRA code output.
Chunks are individually OS-protected. A finalized asset is visible only after
an independently attested ANSWERED frame for its exact assistant message.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from contextlib import closing

from native_bridge.job_store import JobStore
from sentra_core.generated_media import TRANSPORT, validate_asset

_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_FILE = re.compile(r"^file-[A-Za-z0-9_-]{8,160}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_MIMES = {"image/png": ".png", "image/jpeg": ".jpg"}
_CHUNK = 65536
_MAX = 8 * 1024 * 1024
ADMITTED = "ADMITTED"
UNCERTAIN_NO_RESEND = "UNCERTAIN_NO_RESEND"
VERIFIED = "VERIFIED"
_FENCE_REASONS = {"transfer_failed", "integrity_mismatch", "observation_timeout"}


def _asset_id(job_id, message_id, file_id):
    material = "\0".join((job_id, message_id, file_id)).encode()
    return "web-native-" + hashlib.sha256(material).hexdigest()[:40]


class WebGeneratedAssets:
    def __init__(self, control, relay=None):
        self.control, self.relay, self.store = control, relay, control.session_checkpoints.store
        with closing(self.store.connect("session_checkpoint")) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS web_native_generated_assets(
                asset_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, owner TEXT NOT NULL,
                run_id TEXT NOT NULL, work_item_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                remote_conversation_id TEXT NOT NULL, remote_message_id TEXT NOT NULL,
                protected_manifest TEXT NOT NULL, finalized INTEGER NOT NULL DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS web_native_generated_chunks(
                asset_id TEXT NOT NULL REFERENCES web_native_generated_assets(asset_id),
                part INTEGER NOT NULL, sha256 TEXT NOT NULL, protected_bytes TEXT NOT NULL,
                PRIMARY KEY(asset_id,part))""")
            db.execute("""CREATE TABLE IF NOT EXISTS web_native_generated_expected(
                job_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                conversation_id TEXT NOT NULL, message_id TEXT NOT NULL,
                protected_file_ids TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS web_native_generated_uncertain(
                owner TEXT NOT NULL, job_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                reason TEXT NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(owner, job_id))""")

    def declare(self, *, owner, job_id, conversation_id, message_id, file_ids):
        if (not isinstance(file_ids,list) or len(file_ids)>4
            or len(set(map(str,file_ids))) != len(file_ids)
            or any(not isinstance(v,str) or not _FILE.fullmatch(v) for v in file_ids)):
            raise ValueError("native image requires unique canonical committed pointers")
        with closing(self.store.connect("session_checkpoint")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM web_native_generated_expected WHERE job_id=?",
                                  (job_id,)).fetchone()
            if existing:
                if ((existing["owner"],existing["conversation_id"],existing["message_id"]) !=
                    (owner,conversation_id,message_id) or
                    JobStore._unseal(existing["protected_file_ids"],job_id,"native_expected")["file_ids"] != file_ids):
                    raise PermissionError("native image expectation replay changed")
            else:
                db.execute("INSERT INTO web_native_generated_expected VALUES(?,?,?,?,?)",
                    (job_id,owner,conversation_id,message_id,
                     JobStore._seal({"file_ids":file_ids},job_id,"native_expected")))

    def ready_for_job(self, *, owner, job_id, conversation_id, message_id):
        with closing(self.store.connect("session_checkpoint")) as db:
            row = db.execute("SELECT * FROM web_native_generated_expected WHERE job_id=?",
                             (job_id,)).fetchone()
            if row is None:
                return True  # pre-upgrade text-only final, no declaration
            if (row["owner"],row["conversation_id"],row["message_id"]) != (owner,conversation_id,message_id):
                raise PermissionError("native image expectation scope changed")
            expected = JobStore._unseal(row["protected_file_ids"],job_id,"native_expected")["file_ids"]
            for file_id in expected:
                ident = _asset_id(job_id,message_id,file_id)
                asset = db.execute("SELECT finalized FROM web_native_generated_assets WHERE asset_id=? "
                    "AND job_id=? AND owner=? AND remote_conversation_id=? AND remote_message_id=?",
                    (ident,job_id,owner,conversation_id,message_id)).fetchone()
                if asset is None or asset["finalized"] != 1:
                    return False
        return True

    def _scope(self, *, job_id, worker, lease_token, extension_id, source_sha256,
               request_id, document_id, identity_epoch, conversation_id, message_id):
        if self.relay is None or self.relay.web_send is None:
            raise PermissionError("native Web asset requires live authenticated relay")
        if any(not isinstance(v, str) or not _ID.fullmatch(v) for v in
               (request_id, document_id, identity_epoch, conversation_id, message_id)):
            raise ValueError("exact Web message/document/epoch required")
        self.relay._original_worker(job_id, worker, lease_token)
        bound = self.relay.web_send.binding(job_id)
        if not bound or bound["worker"] != worker or not bound["send_fence"]:
            raise PermissionError("native Web asset lacks original send fence")
        self.relay.web_send._authority(bound, effect=False)
        principal = self.relay.web_send._collector(extension_id, source_sha256)
        delivery = self.relay.delivery_status(job_id)
        receipt = (delivery or {}).get("receipt")
        if not receipt or delivery["state"] != "sent" or receipt["conversation_id"] != conversation_id:
            raise PermissionError("native Web asset differs from exact sent conversation")
        proof = self.relay.web_send.receipts.require_attested(
            bound["owner"], run_id=bound["run_id"], job_id=job_id, evidence=receipt)
        if proof["request_id"] != request_id:
            raise PermissionError("native Web asset request does not match attested parent")
        self.relay.web_send.receipts.prove_message(
            owner=bound["owner"], run_id=bound["run_id"], browser_principal=principal,
            request_id=request_id, worker=worker, conversation_id=conversation_id,
            message_id=receipt["message_id"], extension_id=extension_id,
            document_id=document_id, identity_epoch=identity_epoch)
        status = self.relay.web_send.status(bound["owner"], job_id)
        if status["state"] != "ANSWERED" or status["answer_message_id"] != message_id:
            raise PermissionError("native Web asset requires independently attested final assistant")
        return bound

    def chunk(self, *, extension_id, source_sha256, job_id, worker, lease_token,
              request_id, document_id, identity_epoch, conversation_id, message_id,
              file_id, mime_type, filename, byte_length, sha256, part,
              chunk_sha256, data_base64):
        bound = self._scope(job_id=job_id, worker=worker, lease_token=lease_token,
            extension_id=extension_id, source_sha256=source_sha256, request_id=request_id,
            document_id=document_id, identity_epoch=identity_epoch,
            conversation_id=conversation_id, message_id=message_id)
        if self._fence(bound["owner"], job_id) is not None:
            raise PermissionError("UNCERTAIN_NO_RESEND")
        if (not _FILE.fullmatch(str(file_id)) or mime_type not in _MIMES
            or filename != "chatgpt-native-" + hashlib.sha256(file_id.encode()).hexdigest()[:16] + _MIMES[mime_type]
            or type(byte_length) is not int or not 1 <= byte_length <= _MAX
            or not _SHA.fullmatch(str(sha256))
            or type(part) is not int or not 0 <= part < (byte_length + _CHUNK - 1) // _CHUNK
            or not _SHA.fullmatch(str(chunk_sha256))
            or not isinstance(data_base64, str) or len(data_base64) > ((_CHUNK + 2) // 3) * 4):
            raise ValueError("invalid canonical native image descriptor")
        raw = base64.b64decode(data_base64, validate=True)
        expected = min(_CHUNK, byte_length - part * _CHUNK)
        if (len(raw) != expected or base64.b64encode(raw).decode() != data_base64
            or hashlib.sha256(raw).hexdigest() != chunk_sha256):
            raise ValueError("native image chunk integrity mismatch")
        with closing(self.store.connect("session_checkpoint")) as db:
            expected = db.execute("SELECT * FROM web_native_generated_expected WHERE job_id=?",
                                  (job_id,)).fetchone()
        if (expected is None or expected["owner"] != bound["owner"] or
            (expected["conversation_id"],expected["message_id"]) != (conversation_id,message_id) or
            file_id not in JobStore._unseal(expected["protected_file_ids"],job_id,"native_expected")["file_ids"]):
            raise PermissionError("native image was not declared by the committed assistant frame")
        aid = _asset_id(job_id, message_id, file_id)
        manifest = dict(transport=TRANSPORT, request_id=request_id,
            conversation_id=conversation_id, message_id=message_id, file_id=file_id,
            filename=filename, mime_type=mime_type, byte_length=byte_length, sha256=sha256)
        with closing(self.store.connect("session_checkpoint")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM web_native_generated_assets WHERE asset_id=?", (aid,)).fetchone()
            if old is None:
                count = db.execute("SELECT COUNT(*) FROM web_native_generated_assets WHERE job_id=?",
                                   (job_id,)).fetchone()[0]
                if count >= 4:
                    raise ValueError("native Web image quota exceeded")
                db.execute("INSERT INTO web_native_generated_assets VALUES(?,?,?,?,?,?,?,?,?,0)",
                    (aid, job_id, bound["owner"], bound["run_id"], bound["work_item_id"],
                     bound["operation_id"], conversation_id, message_id,
                     JobStore._seal(manifest, aid, "native_manifest")))
            elif (tuple(old[k] for k in ("job_id","owner","run_id","work_item_id","operation_id",
                                          "remote_conversation_id","remote_message_id"))
                  != (job_id,bound["owner"],bound["run_id"],bound["work_item_id"],
                      bound["operation_id"],conversation_id,message_id)
                  or JobStore._unseal(old["protected_manifest"],aid,"native_manifest") != manifest):
                raise PermissionError("native Web image identity changed")
            existing = db.execute("SELECT sha256,protected_bytes FROM web_native_generated_chunks "
                                  "WHERE asset_id=? AND part=?", (aid,part)).fetchone()
            if existing:
                if existing["sha256"] != chunk_sha256 or JobStore._unseal(
                        existing["protected_bytes"],aid,"native_chunk:" + str(part))["base64"] != data_base64:
                    raise ValueError("native image replay changed existing bytes")
                return {"asset_id":aid,"part":part,"replayed":True,"automatic_resend":False}
            if old and old["finalized"]:
                raise ValueError("finalized native image cannot acquire new chunks")
            db.execute("INSERT INTO web_native_generated_chunks VALUES(?,?,?,?)",
                (aid, part, chunk_sha256, JobStore._seal({"base64":data_base64},aid,"native_chunk:" + str(part))))
        return {"asset_id":aid,"part":part,"replayed":False,"automatic_resend":False}

    def _bytes(self, db, asset_id, manifest):
        rows = db.execute("SELECT * FROM web_native_generated_chunks WHERE asset_id=? ORDER BY part",
                          (asset_id,)).fetchall()
        total = (manifest["byte_length"] + _CHUNK - 1) // _CHUNK
        if len(rows) != total or [row["part"] for row in rows] != list(range(total)):
            raise ValueError("native image is missing protected chunks")
        pieces = []
        for row in rows:
            data = JobStore._unseal(row["protected_bytes"],asset_id,"native_chunk:" + str(row["part"]))["base64"]
            raw = base64.b64decode(data,validate=True)
            if (len(raw) != min(_CHUNK, manifest["byte_length"] - row["part"] * _CHUNK)
                    or hashlib.sha256(raw).hexdigest() != row["sha256"]):
                raise ValueError("native image protected chunk changed")
            pieces.append(raw)
        raw = b"".join(pieces)
        payload = {key:manifest[key] for key in (
            "transport","request_id","conversation_id","message_id","filename",
            "mime_type","byte_length","sha256")}
        validate_asset({"type":"sentra.generated_asset",**payload,
                        "data_base64":base64.b64encode(raw).decode()},manifest["request_id"])
        return raw

    def finalize(self, **scope):
        file_id = scope.pop("file_id")
        bound = self._scope(**scope)
        if self._fence(bound["owner"], scope["job_id"]) is not None:
            raise PermissionError("UNCERTAIN_NO_RESEND")
        aid = _asset_id(scope["job_id"],scope["message_id"],file_id)
        with closing(self.store.connect("session_checkpoint")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM web_native_generated_assets WHERE asset_id=?",
                             (aid,)).fetchone()
            if not row or row["owner"] != bound["owner"] or row["operation_id"] != bound["operation_id"]:
                raise PermissionError("native image has no original scoped upload")
            manifest = JobStore._unseal(row["protected_manifest"],aid,"native_manifest")
            raw = self._bytes(db, aid, manifest)
            if not row["finalized"]:
                db.execute("UPDATE web_native_generated_assets SET finalized=1 WHERE asset_id=?", (aid,))
        return {"type":"sentra.generated_asset","transport":TRANSPORT,"asset_id":aid,
                "request_id":manifest["request_id"],"conversation_id":manifest["conversation_id"],
                "message_id":manifest["message_id"],"operation_id":row["operation_id"],
                "mime_type":manifest["mime_type"],"filename":manifest["filename"],
                "byte_length":len(raw),"sha256":manifest["sha256"],
                "replayed":bool(row["finalized"]),"automatic_resend":False}

    def for_job(self, *, owner, run_id, work_item_id, operation_id, job_id,
                conversation_id, message_id):
        if self._fence(owner, job_id) is not None:
            return []
        with closing(self.store.connect("session_checkpoint")) as db:
            rows = db.execute("SELECT asset_id,protected_manifest FROM web_native_generated_assets "
                "WHERE owner=? AND run_id=? AND work_item_id=? AND operation_id=? AND job_id=? "
                "AND remote_conversation_id=? AND remote_message_id=? AND finalized=1",
                (owner,run_id,work_item_id,operation_id,job_id,conversation_id,message_id)).fetchall()
        return [{"asset_id":r["asset_id"], **{k:JobStore._unseal(
            r["protected_manifest"],r["asset_id"],"native_manifest")[k]
            for k in ("filename","mime_type","byte_length","sha256")}} for r in rows]

    def read(self, *, owner, operation_id, asset_id):
        with closing(self.store.connect("session_checkpoint")) as db:
            row = db.execute("SELECT * FROM web_native_generated_assets WHERE owner=? "
                "AND operation_id=? AND asset_id=? AND finalized=1",(owner,operation_id,asset_id)).fetchone()
            if not row:
                raise PermissionError("native image is not finalized for this operation")
            fence = db.execute(
                "SELECT operation_id FROM web_native_generated_uncertain WHERE owner=? AND job_id=?",
                (owner, row["job_id"])).fetchone()
            if fence is not None:
                raise PermissionError("UNCERTAIN_NO_RESEND")
            manifest = JobStore._unseal(row["protected_manifest"],asset_id,"native_manifest")
            raw = self._bytes(db,asset_id,manifest)
        return manifest,raw

    def fenced_asset_ids(self, owner, asset_ids):
        """Asset ids whose job is fenced. Those bytes must not be offered."""
        chosen = [asset_id for asset_id in asset_ids
                  if isinstance(asset_id, str) and asset_id.startswith("web-native-")]
        if not chosen:
            return set()
        placeholders = ",".join("?" for _ in chosen)
        with closing(self.store.connect("session_checkpoint")) as db:
            rows = db.execute(
                "SELECT a.asset_id FROM web_native_generated_assets a "
                "JOIN web_native_generated_uncertain u ON u.owner=a.owner AND u.job_id=a.job_id "
                "WHERE a.owner=? AND a.asset_id IN (" + placeholders + ")",
                (owner, *chosen)).fetchall()
        return {row["asset_id"] for row in rows}

    def _fence(self, owner, job_id):
        with closing(self.store.connect("session_checkpoint")) as db:
            return db.execute("SELECT * FROM web_native_generated_uncertain WHERE owner=? AND job_id=?",
                              (owner, job_id)).fetchone()

    def _write_fence(self, *, owner, job_id, operation_id, reason, allow_finalized):
        if reason not in _FENCE_REASONS:
            raise ValueError("bounded uncertain reason required")
        if self.relay is None or self.relay.web_send is None:
            raise PermissionError("uncertain fence requires the original relay binding")
        bound = self.relay.web_send.binding(job_id)
        if not bound or bound.get("owner") != owner or bound.get("operation_id") != operation_id:
            raise PermissionError("uncertain fence outside original operation")
        with closing(self.store.connect("session_checkpoint")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            finalized = db.execute("SELECT COUNT(*) FROM web_native_generated_assets "
                                   "WHERE owner=? AND job_id=? AND finalized=1", (owner, job_id)).fetchone()[0]
            if finalized and not allow_finalized:
                raise PermissionError("verified native image cannot be reclassified uncertain")
            prior = db.execute("SELECT * FROM web_native_generated_uncertain WHERE owner=? AND job_id=?",
                               (owner, job_id)).fetchone()
            if prior is not None:
                if prior["operation_id"] != operation_id or prior["reason"] != reason:
                    raise ValueError("uncertain native image fence changed")
                return {"status": UNCERTAIN_NO_RESEND, "reason": reason,
                        "operation_id": operation_id, "automatic_resend": False, "already_fenced": True}
            db.execute("INSERT INTO web_native_generated_uncertain VALUES(?,?,?,?,?)",
                       (owner, job_id, operation_id, reason, time.time()))
        return {"status": UNCERTAIN_NO_RESEND, "reason": reason, "operation_id": operation_id,
                "automatic_resend": False, "already_fenced": False}

    def mark_uncertain(self, *, owner, job_id, operation_id, reason):
        """Remember a failed native transfer. Does not fetch or resend bytes."""
        return self._write_fence(owner=owner, job_id=job_id, operation_id=operation_id,
                                 reason=reason, allow_finalized=False)

    def verdict(self, *, owner, run_id, work_item_id, operation_id, job_id,
                conversation_id, message_id):
        """ADMITTED without bytes is not success. UNCERTAIN_NO_RESEND stays put."""
        fence = self._fence(owner, job_id)
        if fence is not None:
            if fence["operation_id"] != operation_id:
                raise PermissionError("uncertain native image belongs to another operation")
            return {"status": UNCERTAIN_NO_RESEND, "generated_asset_verified": False,
                    "automatic_resend": False, "success": False, "reason": fence["reason"],
                    "run_id": run_id, "work_item_id": work_item_id, "operation_id": operation_id,
                    "job_id": job_id, "assets": []}
        rows = self.for_job(owner=owner, run_id=run_id, work_item_id=work_item_id,
                            operation_id=operation_id, job_id=job_id,
                            conversation_id=conversation_id, message_id=message_id)
        if not rows:
            return {"status": ADMITTED, "generated_asset_verified": False,
                    "automatic_resend": False, "success": False,
                    "run_id": run_id, "work_item_id": work_item_id, "operation_id": operation_id,
                    "job_id": job_id, "assets": []}
        assets = []
        for row in rows:
            try:
                manifest, raw = self.read(owner=owner, operation_id=operation_id, asset_id=row["asset_id"])
            except (ValueError, PermissionError):
                self._write_fence(owner=owner, job_id=job_id, operation_id=operation_id,
                                  reason="integrity_mismatch", allow_finalized=True)
                return {"status": UNCERTAIN_NO_RESEND, "generated_asset_verified": False,
                        "automatic_resend": False, "success": False, "reason": "integrity_mismatch",
                        "run_id": run_id, "work_item_id": work_item_id, "operation_id": operation_id,
                        "job_id": job_id, "assets": []}
            digest = hashlib.sha256(raw).hexdigest()
            if (manifest.get("mime_type") != row["mime_type"] or manifest.get("byte_length") != len(raw)
                    or manifest.get("sha256") != digest or row["byte_length"] != len(raw)
                    or row["sha256"] != digest or manifest.get("mime_type") not in _MIMES):
                self._write_fence(owner=owner, job_id=job_id, operation_id=operation_id,
                                  reason="integrity_mismatch", allow_finalized=True)
                return {"status": UNCERTAIN_NO_RESEND, "generated_asset_verified": False,
                        "automatic_resend": False, "success": False, "reason": "integrity_mismatch",
                        "run_id": run_id, "work_item_id": work_item_id, "operation_id": operation_id,
                        "job_id": job_id, "assets": []}
            assets.append({"asset_id": row["asset_id"], "mime_type": manifest["mime_type"],
                           "byte_length": len(raw), "sha256": digest})
        return {"status": VERIFIED, "generated_asset_verified": True, "automatic_resend": False,
                "success": True, "run_id": run_id, "work_item_id": work_item_id,
                "operation_id": operation_id, "job_id": job_id, "assets": assets}
