"""Recoverable Web attachments with real upload receipts (Rastro).

`WebAssetDrafts` (Rastro, `web_history_assets.py`) stages chunked,
OS-protected bytes as READY_LOCAL. READY_LOCAL is explicitly NOT an
upload: bytes never leave the host here. A real upload happens only when
the staged asset is bound to a durable relay delivery (`ChatJob.images`)
and the browser returns the exact Web receipt (prompt digest + attachment
count match in `WebDeliveryJournal.receipt`).

This module provides that binding plus recoverable reads:

- `bind_asset_to_job`: attach a READY_LOCAL asset's bytes to a new or
  existing relay job as data-URL images (within the relay 2-image/size
  caps), recording the asset->job binding durably. Replays are idempotent;
  a changed asset digest fails closed.
- `upload_status`: READY_LOCAL vs UPLOADED (exact receipt) vs UNCERTAIN.
- `read_asset`: recoverable bounded read of the staged bytes (same grant).
"""
from __future__ import annotations

import base64
import hashlib
import time
from typing import Any

from native_bridge.protocol import MAX_IMAGE_CHARS


def _data_url(mime: str, raw: bytes) -> str:
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))


_MIME_BY_TYPE = {"image/png": "image/png", "image/jpeg": "image/jpeg",
                 "application/pdf": "application/pdf", "text/plain": "text/plain"}


class AttachmentUploads:
    def __init__(self, control: Any, jobs: Any, drafts: Any, *, clock=time.time) -> None:
        self.control, self.jobs, self.drafts = control, jobs, drafts
        self.clock = clock
        self.store = control.session_checkpoints.store
        with self.store.connect("session_checkpoint") as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS web_asset_uploads(
                    asset_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    job_id TEXT UNIQUE NOT NULL, asset_sha256 TEXT NOT NULL,
                    image_index INTEGER NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS web_asset_send_sets(
                    asset_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    job_id TEXT NOT NULL, asset_sha256 TEXT NOT NULL,
                    position INTEGER NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS web_asset_send_sets_job
                    ON web_asset_send_sets(job_id);
            """)

    def bind_asset_to_job(self, owner: str, asset_id: str, job_id: str) -> dict[str, Any]:
        """Bind staged bytes into a relay job payload. No browser I/O here."""
        status = self.drafts.status(owner, asset_id)
        if status["state"] != "READY_LOCAL":
            raise ValueError("attachment is not finalized (READY_LOCAL required)")
        try:
            self.jobs.pending_status(job_id)
        except ValueError as exc:
            raise ValueError("attachment target job is unknown") from exc
        raw = self.drafts.read(owner, asset_id)
        if hashlib.sha256(raw).hexdigest() != status["sha256"]:
            raise ValueError("attachment digest changed")
        with self.store.connect("session_checkpoint") as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM web_asset_uploads WHERE asset_id=?",
                             (asset_id,)).fetchone()
            if old:
                if (old["owner"], old["job_id"], old["asset_sha256"]) != (
                        owner, job_id, status["sha256"]):
                    raise ValueError("attachment upload identity collision")
                return self.upload_status(owner, asset_id)
            # NOTE: performs no browser send; the caller submits the returned
            # image through the existing authorized relay/WebSend path, whose
            # exact receipt (with attachment count) is the only upload proof.
            db.execute("INSERT INTO web_asset_uploads VALUES(?,?,?,?,?,?)",
                       (asset_id, owner, job_id, status["sha256"], 0, self.clock()))
        return self.upload_status(owner, asset_id)

    def bind_asset_set(self, owner: str, assets: list[tuple[str, str]],
                       job_id: str) -> dict[str, Any]:
        """Bind a whole transmitted set to ONE job (atomic multimodal turn).

        Every asset must be READY_LOCAL with an exact digest; the job must
        exist. One transaction, no partial bindings: any mismatch aborts the
        whole set. The single delivery receipt later covers the set.
        """
        if not isinstance(assets, list) or not 1 <= len(assets) <= 4:
            raise ValueError("asset set must hold 1..4 (asset_id, sha256) pairs")
        try:
            self.jobs.pending_status(job_id)
        except ValueError as exc:
            raise ValueError("attachment target job is unknown") from exc
        with self.store.connect("session_checkpoint") as db:
            db.execute("BEGIN IMMEDIATE")
            for position, (asset_id, sha256) in enumerate(assets):
                status = self.drafts.status(owner, asset_id)
                if status["state"] != "READY_LOCAL":
                    raise ValueError("attachment set member is not finalized")
                raw = self.drafts.read(owner, asset_id)
                if hashlib.sha256(raw).hexdigest() != sha256 or sha256 != status["sha256"]:
                    raise ValueError("attachment set digest changed")
                old = db.execute("SELECT job_id,asset_sha256 FROM web_asset_send_sets "
                                 "WHERE asset_id=?", (asset_id,)).fetchone()
                if old:
                    if (old["job_id"], old["asset_sha256"]) != (job_id, sha256):
                        raise ValueError("attachment set identity collision")
                    continue
                db.execute("INSERT INTO web_asset_send_sets VALUES(?,?,?,?,?,?)",
                           (asset_id, owner, job_id, sha256, position, self.clock()))
        return self.upload_status(owner, assets[0][0])

    def bound_image(self, owner: str, asset_id: str) -> str:
        """Recoverable data-URL for a bound asset (caller enforces relay caps)."""
        item = self.drafts._row(owner, asset_id)
        raw = self.drafts.read(owner, asset_id)
        mime = _MIME_BY_TYPE.get(item["content_type"], "text/plain")
        url = _data_url(mime, raw)
        if len(url) > MAX_IMAGE_CHARS:
            raise ValueError("staged attachment exceeds relay image cap; "
                             "re-stage a smaller file")
        return url

    def upload_status(self, owner: str, asset_id: str) -> dict[str, Any]:
        item = self.drafts.status(owner, asset_id)
        with self.store.connect("session_checkpoint") as db:
            row = db.execute("SELECT job_id FROM web_asset_send_sets "
                             "WHERE asset_id=? AND owner=?",
                             (asset_id, owner)).fetchone()
            if row is None:
                row = db.execute("SELECT job_id FROM web_asset_uploads "
                                 "WHERE asset_id=? AND owner=?",
                                 (asset_id, owner)).fetchone()
        if row is None:
            return {**item, "web_uploaded": False, "delivery": None,
                    "automatic_forward": False}
        delivery = self.jobs.delivery_status(row["job_id"])
        receipt = (delivery or {}).get("receipt")
        uploaded = bool(delivery and delivery["state"] == "sent" and receipt)
        if uploaded:
            try:
                binding = getattr(self.jobs, "web_send", None)
                send = binding.binding(row["job_id"]) if binding is not None else None
                if send is None:
                    with self.store.connect("session_checkpoint") as db:
                        found = db.execute("SELECT run_id FROM web_send_intents WHERE owner=? AND job_id=?",
                                           (owner, row["job_id"])).fetchone()
                    send = dict(found) if found else None
                if send is None:
                    uploaded = False
                else:
                    from .web_evidence_ingress import AuthenticatedWebReceiptBroker
                    AuthenticatedWebReceiptBroker(self.control, self.jobs).require_attested(
                        owner, run_id=send["run_id"], job_id=row["job_id"], evidence=receipt)
            except PermissionError:
                uploaded = False
        return {**item, "job_id": row["job_id"], "web_uploaded": uploaded,
                "delivery": delivery, "delivery_state": (delivery or {}).get("state"),
                "requires_operator_reconciliation":
                    bool(delivery and delivery["state"] == "unconfirmed"),
                "automatic_forward": False}

    def read_asset(self, owner: str, asset_id: str, *, limit: int = 20 * 1024 * 1024) -> bytes:
        raw = self.drafts.read(owner, asset_id)
        if len(raw) > limit:
            raise ValueError("recoverable attachment read exceeds bound")
        return raw
