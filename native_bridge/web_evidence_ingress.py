"""Host-only relay <-> authenticated browser-evidence receipt join.

The collector must have already passed browser_evidence.challenge/observe via
an enrolled extension origin. Client-provided request IDs alone are NOT proof.
No cookies, account credentials, DOM scraping, grants, or Web retries occur here.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Any


class WebReceiptAttestationError(PermissionError):
    pass


class AuthenticatedWebReceiptBroker:
    """Correlates an already observed Web message and the durable relay receipt."""

    def __init__(self, control: Any, relay: Any):
        self.control, self.relay = control, relay
        self.store = control.session_checkpoints.store
        with self.store.connect("session_checkpoint") as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS authenticated_web_receipts(
                    job_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    browser_principal TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    receipt_sha256 TEXT NOT NULL,
                    attested_at REAL NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS authenticated_web_message
                    ON authenticated_web_receipts(
                       owner,workspace,conversation_id,message_id);
            """)
            columns={row["name"] for row in db.execute("PRAGMA table_info(authenticated_web_receipts)")}
            if "identity_epoch" not in columns:
                db.execute("ALTER TABLE authenticated_web_receipts ADD COLUMN identity_epoch TEXT")

    def _prove_browser(self, *, owner, run_id, browser_principal,
                       request_id, worker, evidence, extension_id=None,
                       document_id=None, identity_epoch=None):
        if (not isinstance(evidence, dict) or
                set(evidence) != {"conversation_id","message_id","prompt_sha256",
                                  "images_attached"}):
            raise WebReceiptAttestationError("exact Web receipt fields required")
        return self.prove_message(owner=owner,run_id=run_id,
                                  browser_principal=browser_principal,
                                  request_id=request_id,worker=worker,
                                  conversation_id=evidence["conversation_id"],
                                  message_id=evidence["message_id"],
                                  extension_id=extension_id, document_id=document_id,
                                  identity_epoch=identity_epoch)

    def prove_message(self, *, owner, run_id, browser_principal,
                      request_id, worker, conversation_id, message_id,
                      extension_id=None, document_id=None, identity_epoch=None):
        """Only a bound, enrolled browser document can persist a Web message."""
        run = self.control.durable.run_status(run_id, owner, include_details=False)
        workspace = run.get("workspace")
        if not workspace:
            raise WebReceiptAttestationError("Run has no workspace binding")
        # This method includes request ID -> Web message metadata -> live document
        # and explicit trust/blocked policy. The proof is NOT a grant.
        verified = self.control.chat_access.require_exact_message(
            browser_principal, request_id, message_id)
        if (verified.get("source") != "proven" or
                verified.get("conversation_id") != conversation_id):
            raise WebReceiptAttestationError("Web request is not tied to target conversation")
        with self.store.connect("chat_access") as db:
            rows = db.execute("""
                SELECT m.extension_id,m.worker,m.document_id,m.collector_revision,
                       c.workspace,c.enabled,c.revision,c.kind,hs.surface_id AS host_surface_id,
                       d.document_id AS active_document,d.conversation_id,
                       ep.identity_epoch AS bound_epoch
                FROM browser_request_messages m
                JOIN browser_collectors c ON c.extension_id=m.extension_id
                JOIN browser_documents d ON d.extension_id=m.extension_id
                                        AND d.worker=m.worker
                LEFT JOIN browser_host_surfaces hs ON hs.collector_id=m.extension_id AND hs.worker=m.worker
                LEFT JOIN browser_document_epochs ep ON ep.extension_id=m.extension_id
                       AND ep.worker=m.worker AND ep.document_id=m.document_id
                WHERE m.principal=? AND m.request_id=?
                  AND c.principal=?
            """, (browser_principal,request_id,browser_principal)).fetchall()
        if len(rows) != 1:
            raise WebReceiptAttestationError("unique enrolled browser source required")
        proof = rows[0]
        if ((extension_id is not None and proof["extension_id"] != extension_id)
                or (document_id is not None and proof["document_id"] != document_id)
                or proof["worker"] != worker or proof["workspace"] != workspace
                or proof["enabled"] != 1
                or proof["kind"] not in {"edge", "electron"}
                or (proof["kind"] == "electron" and proof["host_surface_id"] is None)
                or proof["revision"] != proof["collector_revision"]
                or proof["active_document"] != proof["document_id"]
                or proof["conversation_id"] != conversation_id
                or (proof["bound_epoch"] is not None and
                    proof["bound_epoch"] != identity_epoch)
                or (proof["bound_epoch"] is None and identity_epoch is not None)):
            raise WebReceiptAttestationError("browser tab/workspace/collector changed")
        return workspace

    def attest_existing(self, owner: str, *, run_id: str, job_id: str,
                        browser_principal: str, request_id: str,
                        worker: str, evidence: dict, identity_epoch=None) -> dict:
        """After collector proof, reconcile exact receipt already in relay SQLite.

        Browser can submit the message receipt first and crash before recording
        the central attestation. Reconciliation never submits another Web job.
        """
        workspace = self._prove_browser(
            owner=owner,run_id=run_id,browser_principal=browser_principal,
            request_id=request_id,worker=worker,evidence=evidence,
            identity_epoch=identity_epoch)
        status=self.relay.delivery_status(job_id)
        if (not status or status["state"] != "sent"
                or status.get("receipt") != evidence):
            raise WebReceiptAttestationError("relay has no matching durable exact receipt")
        raw=json.dumps(evidence,sort_keys=True,separators=(",",":"))
        digest=hashlib.sha256(raw.encode("utf-8")).hexdigest()
        with self.store.connect("session_checkpoint") as db:
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("SELECT * FROM authenticated_web_receipts "
                           "WHERE job_id=?", (job_id,)).fetchone()
            if old:
                expected=(owner,run_id,workspace,browser_principal,request_id,
                          worker,evidence["conversation_id"],evidence["message_id"],
                          digest, identity_epoch)
                actual=tuple(old[k] for k in (
                    "owner","run_id","workspace","browser_principal","request_id",
                    "worker","conversation_id","message_id","receipt_sha256","identity_epoch"))
                if actual != expected:
                    raise WebReceiptAttestationError("authenticated receipt identity collision")
                return {"job_id":job_id,"state":"attested",
                        "message_id":evidence["message_id"],"replayed":True}
            db.execute("""
                INSERT INTO authenticated_web_receipts
                (job_id,owner,run_id,workspace,browser_principal,request_id,worker,
                 conversation_id,message_id,receipt_sha256,attested_at,identity_epoch)
                VALUES(?,?,?,?,?,?,?,?,?,?,strftime('%s','now'),?)
            """,(job_id,owner,run_id,workspace,browser_principal,request_id,worker,
                 evidence["conversation_id"],evidence["message_id"],digest,identity_epoch))
        return {"job_id":job_id,"state":"attested",
                "message_id":evidence["message_id"],"replayed":False}

    def accept(self, owner: str, *, run_id: str, job_id: str,
               browser_principal: str, request_id: str, worker: str,
               lease_token: str, evidence: dict, extension_id=None,
               document_id=None, identity_epoch=None) -> dict:
        """Authenticated collector + valid relay worker lease + exact receipt."""
        self._prove_browser(owner=owner,run_id=run_id,
                            browser_principal=browser_principal,
                            request_id=request_id,worker=worker,evidence=evidence,
                            extension_id=extension_id,document_id=document_id,
                            identity_epoch=identity_epoch)
        # JobStore validates sending intent, worker lease and existing
        # conversation/prompt digest, committing receipt to its own DB.
        self.relay.delivery_receipt(job_id,worker,lease_token,evidence)
        return self.attest_existing(owner,run_id=run_id,job_id=job_id,
                                    browser_principal=browser_principal,
                                    request_id=request_id,worker=worker,
                                    evidence=evidence,identity_epoch=identity_epoch)

    def require_attested(self, owner: str, *, run_id: str, job_id: str,
                         evidence: dict) -> dict:
        with self.store.connect("session_checkpoint") as db:
            row=db.execute("SELECT * FROM authenticated_web_receipts "
                           "WHERE owner=? AND run_id=? AND job_id=?",
                           (owner,run_id,job_id)).fetchone()
        if row is None:
            raise WebReceiptAttestationError("browser collector message proof missing")
        self._prove_browser(
            owner=owner,run_id=run_id,
            browser_principal=row["browser_principal"],
            request_id=row["request_id"],worker=row["worker"],evidence=evidence,
            identity_epoch=row["identity_epoch"])
        expected=hashlib.sha256(json.dumps(
            evidence,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if (row["conversation_id"] != evidence["conversation_id"] or
                row["message_id"] != evidence["message_id"] or
                row["receipt_sha256"] != expected or
                self.relay.delivery_status(job_id).get("receipt") != evidence):
            raise WebReceiptAttestationError("authenticated Web receipt changed")
        return {"job_id":job_id,"message_id":row["message_id"],
                "browser_principal":row["browser_principal"],
                "request_id":row["request_id"],"state":"attested"}


class AuthenticatedWebFrameIngress:
    """Chat2 authenticated collector -> central revisioned protected WebHistoryStore.

    The current browser proof schema only pairs messages carrying a witnessed
    metadata.request_id. Unpaired/virtualized text is rejected, not guessed.
    """

    def __init__(self, control: Any, history: Any, *, assistant_attestor=None):
        self.control = control
        self.history = history
        self.assistant_attestor = assistant_attestor
        self.proof = AuthenticatedWebReceiptBroker(control, relay=None)

    def record_answer(self, owner: str, *, run_id: str, job_id: str, browser_principal: str,
                      request_id: str, parent_user_message_id: str, worker: str,
                      conversation_id: str, message_id: str, revision: int, state: str,
                      body: str, identity_epoch: str) -> dict:
        """Observed assistant child of an authenticated user request.

        A provider can reuse request_id for both roles. Never insert the
        assistant into the unique request->user-message correlation table.
        The host callback must independently authenticate the assistant ID,
        parent, document epoch, role and exact revision/content fingerprint.
        Browser/model payload fields alone are not this attestation.
        """
        workspace = self.proof.prove_message(
            owner=owner, run_id=run_id, browser_principal=browser_principal, request_id=request_id,
            worker=worker, conversation_id=conversation_id, message_id=parent_user_message_id,
            identity_epoch=identity_epoch)
        if not callable(self.assistant_attestor):
            raise WebReceiptAttestationError("host-authenticated assistant observation unavailable")
        expected = dict(owner=owner, run_id=run_id, job_id=job_id, worker=worker,
                        conversation_id=conversation_id, message_id=message_id,
                        parent_user_message_id=parent_user_message_id, revision=revision,
                        body_sha256=hashlib.sha256(body.encode()).hexdigest(), identity_epoch=identity_epoch,
                        role="assistant", state=state)
        observed = self.assistant_attestor(**expected)
        if (not isinstance(observed, dict) or observed.get("authenticated") is not True or
                any(observed.get(key) != value for key, value in expected.items())):
            raise WebReceiptAttestationError("assistant observation does not match host proof")
        host = observed.get("host_observation")
        if "host_observation" in observed:
            if not isinstance(host, dict) or host.get("identity_epoch") != identity_epoch:
                raise WebReceiptAttestationError("Host observation differs from assistant epoch")
            self.proof.prove_message(owner=owner, run_id=run_id, browser_principal=browser_principal,
                request_id=request_id, worker=worker, conversation_id=conversation_id,
                message_id=parent_user_message_id, document_id=host.get("document_id"), identity_epoch=identity_epoch)
        return self.history.record_frame(owner, workspace, conversation_id=conversation_id,
                                         message_id=message_id, revision=revision, role="assistant", state=state, body=body,
                                         host_observation=host)

    def record(self, owner: str, *, run_id: str, browser_principal: str,
               request_id: str, worker: str, conversation_id: str,
               message_id: str, revision: int, role: str, state: str,
               body: str, identity_epoch=None) -> dict:
        workspace=self.proof.prove_message(
            owner=owner,run_id=run_id,browser_principal=browser_principal,
            request_id=request_id,worker=worker,conversation_id=conversation_id,
            message_id=message_id,identity_epoch=identity_epoch)
        return self.history.record_frame(
            owner,workspace,conversation_id=conversation_id,
            message_id=message_id,revision=revision,role=role,state=state,
            body=body)
