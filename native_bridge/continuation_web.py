"""Web A->B continuation with a single durable browser delivery and exact receipt.

The Control Plane remains authoritative for Run/chat binding and grant decisions.
This adapter never dispatches a second browser send while a prior effect is uncertain.
A target conversation must already be identified; it is never fabricated from a URL.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any

from sentra_core.conversation import ConversationIdentity
from sentra_mcp.services.session_checkpoint import SessionCheckpointConflict
from .protocol import ChatJob
from .web_evidence_ingress import AuthenticatedWebReceiptBroker


class WebContinuationConflict(SessionCheckpointConflict):
    """Conflicting intent, stale authority, or uncertain browser effect."""


class WebContinuation:
    """Compose central checkpoints/Run/grants with the relay's durable outbox.

    All entry points are host-only. The browser posts its own message receipt
    through JobStore.delivery_receipt under a valid worker lease.
    """

    def __init__(self, control: Any, relay: Any, *, clock=time.time):
        self.control, self.relay, self.clock = control, relay, clock
        self.authenticated_receipts = AuthenticatedWebReceiptBroker(control, relay)
        self.store = control.session_checkpoints.store
        with self.store.connect("session_checkpoint") as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS web_continuation_transfers(
                    continuation_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    work_item_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    grant_id TEXT NOT NULL,
                    target_url TEXT NOT NULL,
                    job_id TEXT NOT NULL UNIQUE,
                    prompt_sha256 TEXT NOT NULL,
                    checkpoint_sha256 TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    created REAL NOT NULL,
                    updated REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS web_continuations_by_owner
                    ON web_continuation_transfers(owner,run_id,chat_id);
                CREATE TABLE IF NOT EXISTS web_target_allocations(
                    allocation_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    run_id TEXT NOT NULL, chat_id TEXT NOT NULL,
                    work_item_id TEXT NOT NULL, principal_id TEXT NOT NULL,
                    grant_id TEXT NOT NULL, checkpoint_id TEXT NOT NULL,
                    checkpoint_sha256 TEXT NOT NULL,
                    request_key TEXT NOT NULL, job_id TEXT UNIQUE NOT NULL,
                    prompt_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL, created REAL NOT NULL,
                    UNIQUE(owner,chat_id,request_key));
                CREATE UNIQUE INDEX IF NOT EXISTS web_target_allocation_open
                    ON web_target_allocations(owner,chat_id)
                    WHERE state IN ('ALLOCATING','CLAIMED','UNCERTAIN');
            """)

    def _row(self, owner: str, continuation_id: str) -> dict[str, Any]:
        with self.store.connect("session_checkpoint") as db:
            row = db.execute(
                "SELECT * FROM web_continuation_transfers "
                "WHERE owner=? AND continuation_id=?",
                (owner, continuation_id),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("web continuation not found")
        return dict(row)

    def _authority(self, owner: str, run_id: str, work_item_id: str,
                   principal_id: str) -> dict[str, Any]:
        run = self.control._run(run_id, owner)
        self.control._agent_from_run(run, principal_id)
        item = self.control.work_item_info(work_item_id, owner)
        if item["run_id"] != run_id:
            raise WebContinuationConflict("WorkItem does not belong to Run")
        if run["state"] not in {"CREATED", "RUNNING"} or item["state"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise PermissionError("Web continuation authority is inactive")
        if item.get("assignee_agent_id") and item["assignee_agent_id"] != principal_id:
            raise PermissionError("Web continuation agent differs from WorkItem assignee")
        grant = self.control.authorization.require(
            owner, principal_type="agent", principal_id=principal_id,
            capability="web:send", scope_type="work_item",
            scope_id=work_item_id, context={"provider": "chatgpt"},
            local_owner=False,
        )
        if not grant.get("grant_id"):
            raise PermissionError("explicit work item grant required")
        return grant

    def stage(self, owner: str, *, run_id: str, chat_id: str, work_item_id: str,
              principal_id: str, target_url: str, request_key: str,
              summary: str, operator_approved: bool = False) -> dict[str, Any]:
        """Pin summary and queue exactly one authorized SEND to existing chat B.

        The summary must match the immutable checkpoint's own summary, rather
        than accepting a new unreviewed transcript. A staged job is a real
        relay job, not a claim that ChatGPT has received its message.
        """
        if operator_approved is not True:
            raise PermissionError("human approval required for Web context transfer")
        if not isinstance(summary, str) or not 1 <= len(summary) <= 16000:
            raise ValueError("bounded summary required")
        identity = ConversationIdentity.parse(target_url)
        if identity.provider != "chatgpt":
            raise ValueError("ChatGPT destination required")
        checkpoint = self.control.latest_session_checkpoint(
            owner, run_id=run_id, chat_id=chat_id)
        if (checkpoint.get("checkpoint") or {}).get("summary") != summary:
            raise WebContinuationConflict("summary does not match pinned checkpoint")
        grant = self._authority(owner, run_id, work_item_id, principal_id)
        continuation = self.control.prepare_chat_continuation(
            owner, run_id=run_id, chat_id=chat_id,
            target_conversation_id=identity.conversation_id,
            request_key=request_key, checkpoint_id=checkpoint["checkpoint_id"])
        if continuation["state"] not in ("PREPARED",):
            raise WebContinuationConflict("continuation already moved beyond staging")
        prompt = "SENTRA continuation context (read-only):\n\n" + summary
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        job_id = "job_" + hashlib.sha256(continuation["continuation_id"].encode()).hexdigest()[:32]
        values = (continuation["continuation_id"], owner, run_id, chat_id,
                  work_item_id, principal_id, grant["grant_id"],
                  identity.canonical_url, job_id, digest,
                  checkpoint["payload_sha256"])
        with self.store.connect("session_checkpoint") as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT * FROM web_continuation_transfers WHERE continuation_id=?",
                (values[0],)).fetchone()
            if old and tuple(old[k] for k in (
                "continuation_id", "owner", "run_id", "chat_id", "work_item_id",
                "principal_id", "grant_id", "target_url", "job_id",
                "prompt_sha256", "checkpoint_sha256")) != values:
                raise WebContinuationConflict("continuation intent changed")
            if not old:
                now = self.clock()
                db.execute(
                    "INSERT INTO web_continuation_transfers "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,'STAGED',?,?)",
                    (*values, now, now))
        # Unconfirmed means the browser may have applied an effect already.
        # A new stage call must not mask the outstanding reconciliation.
        previous = self.relay.delivery_status(job_id)
        if previous and previous["state"] == "unconfirmed":
            raise WebContinuationConflict("uncertain Web delivery requires reconciliation")
        # This insert is idempotent by delivery_key and fingerprint across
        # process restarts. A crash after submit cannot generate a second job.
        job = ChatJob(job_id=job_id, task_id=continuation["continuation_id"],
                      provider="chatgpt", kind="CHAT_SEND", prompt=prompt,
                      new_chat=False, conversation_url=identity.canonical_url,
                      delivery_key="continuation:" + continuation["continuation_id"])
        existing = self.relay.submit(job)
        if existing != job_id:
            raise WebContinuationConflict("relay delivery key claimed by foreign job")
        return self.status(owner, continuation["continuation_id"])

    def status(self, owner: str, continuation_id: str) -> dict[str, Any]:
        item = self._row(owner, continuation_id)
        continuation = self.control.reconcile_chat_continuation(owner, continuation_id)
        delivery = self.relay.delivery_status(item["job_id"])
        evidence = delivery.get("receipt") if delivery else None
        exact = bool(delivery and delivery["state"] == "sent" and evidence
                     and evidence.get("conversation_id") ==
                     continuation["target_conversation_id"]
                     and evidence.get("prompt_sha256") == item["prompt_sha256"])
        browser_attested = False
        if exact:
            try:
                self.authenticated_receipts.require_attested(
                    owner, run_id=item["run_id"], job_id=item["job_id"],
                    evidence=evidence)
                browser_attested = True
            except PermissionError:
                pass  # A valid relay receipt alone is not trusted browser proof.
        return {"continuation_id": continuation_id, "run_id": item["run_id"],
                "chat_id": item["chat_id"], "work_item_id": item["work_item_id"],
                "stage": item["stage"], "core_state": continuation["state"],
                "delivery": delivery, "target_receipt_exact": exact,
                "collector_message_attested": browser_attested,
                "account_identity_attested": False,
                "message_id": evidence.get("message_id") if exact and isinstance(evidence, dict) else None,
                "automatic_retry": False,
                "requires_operator_reconciliation": bool(
                    continuation["requires_operator_reconciliation"] or
                    (delivery and delivery["state"] == "unconfirmed"))}

    def commit(self, owner: str, continuation_id: str, *,
               operator_approved: bool = False) -> dict[str, Any]:
        """Rebind A->B only AFTER the genuine exact Web message receipt."""
        if operator_approved is not True:
            raise PermissionError("human approval required for Web commit")
        item = self._row(owner, continuation_id)
        # A prior send grant might have been revoked while the Web worker ran.
        grant = self._authority(owner, item["run_id"], item["work_item_id"],
                                item["principal_id"])
        if grant["grant_id"] != item["grant_id"]:
            raise PermissionError("original Web send grant changed; refusing commit")
        status = self.status(owner, continuation_id)
        if not status["target_receipt_exact"]:
            raise WebContinuationConflict("no exact Web receipt; never re-send automatically")
        self.authenticated_receipts.require_attested(
            owner, run_id=item["run_id"], job_id=item["job_id"],
            evidence=status["delivery"]["receipt"])
        if status["core_state"] == "PREPARED":
            self.control.commit_chat_continuation(
                owner, continuation_id, operator_approved=True)
        elif status["core_state"] != "COMMITTED":
            raise WebContinuationConflict("binding uncertain; reconcile before commit")
        # Keep SAME logical Run/Chat/WorkItem; only the provider conversation is rebound.
        with self.store.connect("session_checkpoint") as db:
            db.execute("UPDATE web_continuation_transfers SET stage='PUBLISHED',updated=? "
                       "WHERE continuation_id=? AND owner=?",
                       (self.clock(), continuation_id, owner))
            db.execute("UPDATE web_target_allocations SET state='PUBLISHED' "
                       "WHERE owner=? AND job_id=? AND state='CLAIMED'",
                       (owner, item["job_id"]))
        return self.status(owner, continuation_id)

    def reconcile(self, owner: str, continuation_id: str) -> dict[str, Any]:
        """Crash recovery is observation only; never retries or commits a send."""
        return self.status(owner, continuation_id)

    def allocate_new_target(self, owner: str, *, run_id: str, chat_id: str,
                            work_item_id: str, principal_id: str,
                            request_key: str, summary: str,
                            operator_approved: bool = False) -> dict[str, Any]:
        """Queue ONE CHAT_START. No local rebind or fabricated target identity."""
        if operator_approved is not True:
            raise PermissionError("human approval required to open new Web target")
        if not isinstance(summary, str) or not 1 <= len(summary) <= 16000:
            raise ValueError("bounded checkpoint summary required")
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128:
            raise ValueError("bounded request key required")
        checkpoint = self.control.latest_session_checkpoint(
            owner, run_id=run_id, chat_id=chat_id)
        source = self.control._continuation_chat(
            owner, {"run_id": run_id, "chat_id": chat_id})
        if (checkpoint.get("checkpoint") or {}).get("summary") != summary or (
                checkpoint.get("conversation_id") != source.get("conversation_id")):
            raise WebContinuationConflict("source checkpoint changed")
        grant = self._authority(owner, run_id, work_item_id, principal_id)
        allocation_id = "web-target-" + hashlib.sha256(
            (owner + "|" + run_id + "|" + chat_id + "|" + request_key).encode()
        ).hexdigest()[:32]
        job_id = "job_" + hashlib.sha256(allocation_id.encode()).hexdigest()[:32]
        prompt = "SENTRA continuation context (read-only):\n\n" + summary
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        values = (allocation_id, owner, run_id, chat_id, work_item_id,
                  principal_id, grant["grant_id"], checkpoint["checkpoint_id"],
                  checkpoint["payload_sha256"], request_key, job_id, digest)
        with self.store.connect("session_checkpoint") as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM web_target_allocations "
                             "WHERE allocation_id=?", (allocation_id,)).fetchone()
            if old and tuple(old[k] for k in (
                    "allocation_id","owner","run_id","chat_id","work_item_id",
                    "principal_id","grant_id","checkpoint_id","checkpoint_sha256",
                    "request_key","job_id","prompt_sha256")) != values:
                raise WebContinuationConflict("new target intent collision")
            if not old:
                db.execute("INSERT INTO web_target_allocations "
                           "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'ALLOCATING',?)",
                           (*values, self.clock()))
            elif old["state"] != "ALLOCATING":
                raise WebContinuationConflict("target requires claim/reconciliation")
        previous = self.relay.delivery_status(job_id)
        if previous and previous["state"] == "unconfirmed":
            raise WebContinuationConflict("uncertain target creation: no retry")
        job = ChatJob(job_id=job_id, task_id=allocation_id,
                      provider="chatgpt", kind="CHAT_START",
                      new_chat=True, prompt=prompt,
                      delivery_key="web-create:" + allocation_id)
        if self.relay.submit(job) != job_id:
            raise WebContinuationConflict("new target job identity collision")
        return self.target_status(owner, allocation_id)

    def target_status(self, owner: str, allocation_id: str) -> dict[str, Any]:
        with self.store.connect("session_checkpoint") as db:
            row = db.execute("SELECT * FROM web_target_allocations "
                             "WHERE owner=? AND allocation_id=?",
                             (owner, allocation_id)).fetchone()
        if row is None:
            raise FileNotFoundError("target allocation not found")
        item = dict(row)
        delivery = self.relay.delivery_status(item["job_id"])
        evidence = (delivery or {}).get("receipt")
        exact = bool(delivery and delivery["state"] == "sent" and evidence
                     and evidence.get("prompt_sha256") == item["prompt_sha256"]
                     and evidence.get("conversation_id"))
        browser_attested = False
        if exact:
            try:
                self.authenticated_receipts.require_attested(
                    owner, run_id=item["run_id"], job_id=item["job_id"],
                    evidence=evidence)
                browser_attested = True
            except PermissionError:
                pass
        return {"allocation_id": allocation_id, "job_id": item["job_id"],
                "state": item["state"], "run_id": item["run_id"],
                "work_item_id": item["work_item_id"],
                "receipt_exact": exact, "receipt": evidence if exact else None,
                "collector_message_attested": browser_attested,
                "account_identity_attested": False,
                "delivery_state": delivery["state"] if delivery else "not_submitted",
                "automatic_retry": False}

    def claim_new_target(self, owner: str, allocation_id: str) -> dict[str, Any]:
        """Prepare the central continuation AFTER the browser proves B exists.

        Replaying claim across crashes is idempotent; no second Web message.
        """
        with self.store.connect("session_checkpoint") as db:
            row = db.execute("SELECT * FROM web_target_allocations "
                             "WHERE owner=? AND allocation_id=?",
                             (owner, allocation_id)).fetchone()
        if row is None:
            raise FileNotFoundError("target allocation not found")
        item = dict(row)
        grant = self._authority(owner,item["run_id"],item["work_item_id"],
                                item["principal_id"])
        if grant["grant_id"] != item["grant_id"]:
            raise PermissionError("original Web target grant changed; refusing claim")
        checkpoint = self.control.latest_session_checkpoint(
            owner,run_id=item["run_id"],chat_id=item["chat_id"])
        if checkpoint["checkpoint_id"] != item["checkpoint_id"]:
            raise WebContinuationConflict("source checkpoint changed; abort target claim")
        status = self.target_status(owner, allocation_id)
        if not status["receipt_exact"]:
            raise WebContinuationConflict("new chat has no exact Web receipt")
        self.authenticated_receipts.require_attested(
            owner, run_id=item["run_id"], job_id=item["job_id"],
            evidence=status["receipt"])
        target_id = status["receipt"]["conversation_id"]
        continuation = self.control.prepare_chat_continuation(
            owner,run_id=item["run_id"],chat_id=item["chat_id"],
            target_conversation_id=target_id,
            request_key=item["request_key"],checkpoint_id=item["checkpoint_id"])
        now = self.clock()
        with self.store.connect("session_checkpoint") as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT job_id FROM web_continuation_transfers "
                             "WHERE continuation_id=?",
                             (continuation["continuation_id"],)).fetchone()
            if old and old["job_id"] != item["job_id"]:
                raise WebContinuationConflict("continuation already has another delivery")
            if not old:
                db.execute(
                    "INSERT INTO web_continuation_transfers "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,'STAGED',?,?)",
                    (continuation["continuation_id"],owner,item["run_id"],
                     item["chat_id"],item["work_item_id"],item["principal_id"],
                     item["grant_id"],"https://chatgpt.com/c/"+target_id,
                     item["job_id"],item["prompt_sha256"],
                     item["checkpoint_sha256"],now,now))
            db.execute("UPDATE web_target_allocations SET state='CLAIMED' "
                       "WHERE allocation_id=? AND owner=?",
                       (allocation_id,owner))
        return self.status(owner, continuation["continuation_id"])
