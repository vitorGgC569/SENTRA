"""Responses and physical Web sends bound to EXISTING central authority.

The existing JobStore owns delivery, ciphertext and receipts. This service only
adds central admission bindings. Cross-database crash gaps fail closed: the
single-use send fence is persisted before granting permission to touch Send.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from typing import Any

from .job_store import JobStore
from .protocol import ChatJob
from .web_evidence_ingress import AuthenticatedWebReceiptBroker, AuthenticatedWebFrameIngress


class WebSendConflict(RuntimeError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class WebSendAuthority:
    def __init__(self, control: Any, jobs: JobStore, *, assistant_attestor=None):
        self.control, self.jobs = control, jobs
        self.assistant_attestor = assistant_attestor
        self.store = control.session_checkpoints.store
        self.receipts = AuthenticatedWebReceiptBroker(control, jobs)
        with self.store.connect("session_checkpoint") as db:
            db.execute("BEGIN IMMEDIATE")
            # Schema/index migration shares the writer transaction. Another
            # host must never observe a gap without the active-send index.
            schema = """
                CREATE TABLE IF NOT EXISTS web_response_requests(
                    request_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    request_identity_sha256 TEXT NOT NULL,
                    run_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL, protected_payload TEXT NOT NULL,
                    created REAL NOT NULL, UNIQUE(owner,request_identity_sha256));
                CREATE TABLE IF NOT EXISTS web_send_intents(
                    job_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    request_identity_sha256 TEXT NOT NULL, submission_index INTEGER NOT NULL,
                    run_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                    work_item_id TEXT NOT NULL, principal_id TEXT NOT NULL,
                    grant_id TEXT NOT NULL, workspace TEXT NOT NULL,
                    conversation_key TEXT NOT NULL, intent_sha256 TEXT NOT NULL,
                    prompt_sha256 TEXT NOT NULL, stage TEXT NOT NULL,
                    send_fence INTEGER NOT NULL DEFAULT 0,
                    resource_key TEXT, fencing_token INTEGER, worker TEXT,
                    answer_message_id TEXT, answer_revision INTEGER,
                    created REAL NOT NULL, updated REAL NOT NULL,
                    UNIQUE(owner,request_identity_sha256,submission_index));
            """
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
            previous = db.execute("SELECT sql FROM sqlite_master WHERE name='web_send_active_conversation'").fetchone()
            predicate = "WHERESTAGEIN('SENDING','UNCONFIRMED')"
            if previous and predicate not in "".join(previous[0].upper().split()):
                db.execute("DROP INDEX web_send_active_conversation")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS web_send_active_conversation
                    ON web_send_intents(owner,workspace,conversation_key)
                    WHERE stage IN ('SENDING','UNCONFIRMED')""")

    @staticmethod
    def _identity(owner: str, request_identity: str) -> tuple[str, str]:
        if (not isinstance(owner, str) or not owner or len(owner) > 256 or
                not isinstance(request_identity, str) or not 1 <= len(request_identity) <= 8192):
            raise ValueError("bounded owner and stable request_identity required")
        return _sha(request_identity), _sha(_json([owner, request_identity]))

    def stage_request(self, owner: str, *, request_identity: str, run_id: str,
                      operation_id: str, payload: dict) -> dict:
        """Persist one encrypted Responses intent before any upstream request."""
        identity, key = self._identity(owner, request_identity)
        request_id = "webrequest_" + key
        if not isinstance(payload, dict) or len(_json(payload).encode()) > 2_000_000:
            raise ValueError("Responses payload must be an object within 2 MB")
        run = self.control.durable.run_status(run_id, owner, include_details=False)
        operation = self.control.durable.operation_status(operation_id, owner)
        if operation["run_id"] != run_id:
            raise PermissionError("Responses Operation belongs to another Run")
        digest = _sha(_json(payload))
        with self.store.connect("session_checkpoint") as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM web_response_requests WHERE request_id=?", (request_id,)).fetchone()
            if old:
                if (old["owner"], old["run_id"], old["operation_id"], old["payload_sha256"]) != (
                        owner, run_id, operation_id, digest):
                    raise WebSendConflict("Responses request identity changed")
            else:
                if run.get("terminal") or operation["state"] not in {"QUEUED", "STARTING", "RUNNING", "WAITING_EXTERNAL"}:
                    raise PermissionError("Responses authority is inactive")
                db.execute("INSERT INTO web_response_requests VALUES(?,?,?,?,?,?,?,?)",
                           (request_id, owner, identity, run_id, operation_id, digest,
                            JobStore._seal(payload, request_id, "responses_request"), self.jobs.clock()))
        return {"request_id": request_id, "request_identity_sha256": identity,
                "run_id": run_id, "operation_id": operation_id, "state": "STAGED",
                "replayed": old is not None, "automatic_resend": False}

    def request_payload(self, owner: str, request_id: str) -> dict:
        with self.store.connect("session_checkpoint") as db:
            row = db.execute("SELECT protected_payload FROM web_response_requests WHERE owner=? AND request_id=?",
                             (owner, request_id)).fetchone()
        if row is None:
            raise FileNotFoundError("Responses request not found for owner")
        return JobStore._unseal(row[0], request_id, "responses_request")

    def _row(self, owner: str, job_id: str) -> dict:
        with self.store.connect("session_checkpoint") as db:
            row = db.execute("SELECT * FROM web_send_intents WHERE owner=? AND job_id=?", (owner, job_id)).fetchone()
        if row is None:
            raise FileNotFoundError("Web send intent not found for owner")
        return dict(row)

    def binding(self, job_id: str) -> dict | None:
        """Host-only mapping for the already authenticated relay callback."""
        with self.store.connect("session_checkpoint") as db:
            row = db.execute("SELECT * FROM web_send_intents WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def _authority(self, row: dict, *, effect: bool = True) -> dict:
        owner, run_id = row["owner"], row["run_id"]
        run = self.control.durable.run_status(run_id, owner)
        op = self.control.durable.operation_status(row["operation_id"], owner)
        item = self.control.work_item_info(row["work_item_id"], owner)
        if (op["run_id"] != run_id or item["run_id"] != run_id or run.get("workspace") != row["workspace"] or
                (item.get("assignee_agent_id") and item["assignee_agent_id"] != row["principal_id"])):
            raise PermissionError("Web send authority binding changed")
        self.control._agent_from_run(run, row["principal_id"])
        if effect and (run["state"] not in {"CREATED", "RUNNING"} or
                       op["state"] not in {"QUEUED", "STARTING", "RUNNING", "WAITING_EXTERNAL"} or
                       item["state"] in {"COMPLETED", "FAILED", "CANCELLED"}):
            raise PermissionError("Web send authority is inactive")
        grant = self.control.authorization.require(
            owner, principal_type="agent", principal_id=row["principal_id"], capability="web:send",
            scope_type="work_item", scope_id=row["work_item_id"], context={"provider": "chatgpt"}, local_owner=False)
        if grant.get("grant_id") != row["grant_id"]:
            raise PermissionError("original Web send grant revoked or replaced")
        return run

    def admit(self, owner: str, *, request_identity: str, run_id: str, operation_id: str,
              work_item_id: str, principal_id: str, grant_id: str, workspace: str,
              conversation_key: str, prompt: str, conversation_url: str | None = None,
              requested_model: str | None = None, requested_effort: str | None = None,
              target_worker: str = "", timeout_s: int = 180, dispatch_mode: str = "external",
              submission_index: int = 0) -> dict:
        identity, key = self._identity(owner, request_identity)
        if type(submission_index) is not int or not 0 <= submission_index <= 1024:
            raise ValueError("submission_index must be 0..1024")
        if not isinstance(conversation_key, str) or not 1 <= len(conversation_key) <= 512:
            raise ValueError("bounded logical conversation_key required")
        job_id = "websend_" + _sha(_json([key, submission_index]))
        job = ChatJob(job_id=job_id, task_id=operation_id, prompt=prompt, timeout_s=timeout_s,
                      kind="CHAT_SEND" if conversation_url else "CHAT_START", new_chat=not bool(conversation_url),
                      conversation_url=conversation_url, delivery_key="websend:" + job_id,
                      target_worker=target_worker, dispatch_mode=dispatch_mode,
                      requested_model=requested_model, requested_effort=requested_effort)
        job.validate()
        bound = dict(owner=owner, run_id=run_id, operation_id=operation_id, work_item_id=work_item_id,
                     principal_id=principal_id, grant_id=grant_id, workspace=workspace, conversation_key=conversation_key)
        self._authority(bound)
        material = {**bound, "job": {k: v for k, v in job.to_dict().items() if k != "created_at"}}
        intent = _sha(_json(material))
        now = self.jobs.clock()
        with self.store.connect("session_checkpoint") as db:
            db.execute("BEGIN IMMEDIATE")
            request = db.execute("SELECT run_id,operation_id FROM web_response_requests WHERE owner=? AND request_identity_sha256=?",
                                 (owner, identity)).fetchone()
            if request and tuple(request) != (run_id, operation_id):
                raise WebSendConflict("physical submission has another Responses authority")
            old = db.execute("SELECT * FROM web_send_intents WHERE job_id=?", (job_id,)).fetchone()
            if old and old["intent_sha256"] != intent:
                raise WebSendConflict("physical submission identity changed")
            if not old:
                db.execute("""INSERT INTO web_send_intents
                    (job_id,owner,request_identity_sha256,submission_index,run_id,operation_id,
                     work_item_id,principal_id,grant_id,workspace,conversation_key,intent_sha256,
                     prompt_sha256,stage,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'QUEUED',?,?)""",
                           (job_id, owner, identity, submission_index, run_id, operation_id, work_item_id,
                            principal_id, grant_id, workspace, conversation_key, intent, _sha(prompt), now, now))
        # A crash here is recovered by an exact replay. Never recreate an
        # outbox job once physical send permission was persisted.
        if not old or not old["send_fence"]:
            if self.jobs.submit(job) != job_id:
                raise WebSendConflict("foreign outbox delivery key")
        self.control.durable.update_operation(operation_id, owner, progress={
            "web_send_job_id": job_id, "work_item_id": work_item_id, "web_send_principal_id": principal_id})
        return self.status(owner, job_id)

    def claim(self, owner: str, job_id: str, *, worker: str) -> dict:
        row = self._row(owner, job_id)
        self._authority(row)
        if row["send_fence"] or row["stage"] in {"FAILED", "REJECTED", "CANCELLED"}:
            raise WebSendConflict("send fence already consumed; reconciliation required")
        return self.jobs.claim(job_id, worker)

    def failure(self, owner: str, job_id: str, *, reason: str) -> dict:
        """Stop this intent; absence of a receipt never proves not-run.

        A caller cannot supply may_have_sent=False or request a requeue.
        The two durable journals alone determine whether Send was authorized.
        """
        row = self._row(owner, job_id)
        if not isinstance(reason, str) or not 1 <= len(reason) <= 240:
            raise ValueError("bounded failure reason required")
        with self.jobs.lock:
            job = self.jobs.pending_status(job_id)
            delivery = job.get("web_delivery")
            if delivery and delivery["state"] == "sent":
                return self.status(owner, job_id)
            uncertain = bool(row["send_fence"] or job["may_have_sent"] or
                             (delivery and delivery["state"] in {"pending", "unconfirmed"}))
            with self.store.connect("session_checkpoint") as db:
                db.execute("UPDATE web_send_intents SET stage=CASE WHEN send_fence=1 OR ? THEN 'UNCONFIRMED' ELSE 'FAILED' END,"
                           "updated=? WHERE owner=? AND job_id=?", (uncertain, self.jobs.clock(), owner, job_id))
            self.jobs.cancel(job_id)
        return self.status(owner, job_id)

    def pre_send(self, owner: str, job_id: str, *, worker: str, lease_token: str,
                 resource_key: str, fencing_token: int) -> dict:
        row = self._row(owner, job_id)
        durable = self.control.durable
        with durable.lock, self.jobs.lock:
            self._authority(row)
            durable._verify_fence_locked(resource_key, fencing_token)
            lease = durable.db.execute("SELECT run_id,operation_id,owner FROM leases WHERE resource_key=?", (resource_key,)).fetchone()
            if not lease or tuple(lease) != (row["run_id"], row["operation_id"], owner):
                raise PermissionError("central lease does not belong to this Web Operation")
            self.jobs._expire()
            job = self.jobs.db.execute("SELECT state,worker,lease,lease_until,deadline FROM jobs WHERE id=?", (job_id,)).fetchone()
            now = self.jobs.clock()
            if (not job or job[0] != "LEASED" or job[1] != worker or not isinstance(lease_token, str) or
                    not secrets.compare_digest(job[2], lease_token) or min(job[3], job[4]) <= now):
                raise PermissionError("live exact Web job lease required before Send")
            try:
                with self.store.connect("session_checkpoint") as db:
                    db.execute("BEGIN IMMEDIATE")
                    changed = db.execute("UPDATE web_send_intents SET send_fence=1,stage='SENDING',resource_key=?,"
                                         "fencing_token=?,worker=?,updated=? WHERE job_id=? AND send_fence=0",
                                         (resource_key, fencing_token, worker, now, job_id)).rowcount
                    if not changed:
                        raise WebSendConflict("pre-Send ACK already consumed; never click again")
            except sqlite3.IntegrityError as exc:
                raise WebSendConflict("logical conversation already has an active send") from exc
            # Calling the base implementation avoids recursive RelayState
            # dispatch. No ACK is returned until BOTH journals are durable.
            JobStore.progress(self.jobs, job_id, worker, lease_token, "sending")
            durable.update_operation(row["operation_id"], owner, resource_key=resource_key,
                                     fencing_token=fencing_token, progress={"web_send_fence": 1, "web_send_job_id": job_id})
        return {"ok": True, "job_id": job_id, "state": "SENDING", "send_fence": 1, "automatic_resend": False}

    def _collector(self, extension_id: str, source_sha256: str) -> str:
        with self.store.connect("chat_access") as db:
            row = db.execute("SELECT principal FROM browser_collectors WHERE extension_id=? AND source_sha256=? "
                             "AND enabled=1 AND kind IN ('edge','electron')",
                             (extension_id, source_sha256)).fetchone()
        if row is None:
            raise PermissionError("Web collector is not enrolled")
        return row[0]

    def receipt(self, owner: str, job_id: str, *, worker: str, lease_token: str, evidence: dict,
                request_id: str, extension_id: str, source_sha256: str, document_id: str, identity_epoch: str) -> dict:
        row = self._row(owner, job_id)
        self._authority(row, effect=False)
        if not row["send_fence"] or row["worker"] != worker:
            raise PermissionError("receipt requires original pre-Send fence and worker")
        if not identity_epoch:
            raise PermissionError("V2 receipt identity_epoch required")
        # Original job lease token remains available even after timeout. A
        # late exact receipt repairs uncertainty, it NEVER grants a new send.
        self.receipts.accept(owner, run_id=row["run_id"], job_id=job_id,
                             browser_principal=self._collector(extension_id, source_sha256), request_id=request_id,
                             worker=worker, lease_token=lease_token, evidence=evidence, extension_id=extension_id,
                             document_id=document_id, identity_epoch=identity_epoch)
        with self.store.connect("session_checkpoint") as db:
            db.execute("UPDATE web_send_intents SET stage=CASE WHEN stage IN ('ANSWERING','ANSWERED') THEN stage ELSE 'SENT' END,"
                       "updated=? WHERE job_id=?", (self.jobs.clock(), job_id))
        return self.status(owner, job_id)

    def reconcile(self, owner: str, job_id: str, *, worker: str, request_id: str, extension_id: str,
                  source_sha256: str, document_id: str, identity_epoch: str) -> dict:
        row = self._row(owner, job_id)
        self._authority(row, effect=False)
        delivery = self.jobs.delivery_status(job_id)
        if not delivery or delivery["state"] != "sent" or not delivery.get("receipt"):
            raise WebSendConflict("no exact receipt; UNCONFIRMED cannot be resent")
        if row["worker"] != worker or not row["send_fence"] or not identity_epoch:
            raise PermissionError("reconciliation requires original V2 send binding")
        principal = self._collector(extension_id, source_sha256)
        self.receipts._prove_browser(owner=owner, run_id=row["run_id"], browser_principal=principal,
                                     request_id=request_id, worker=worker, evidence=delivery["receipt"],
                                     extension_id=extension_id, document_id=document_id, identity_epoch=identity_epoch)
        self.receipts.attest_existing(owner, run_id=row["run_id"], job_id=job_id, browser_principal=principal,
                                     request_id=request_id, worker=worker, evidence=delivery["receipt"], identity_epoch=identity_epoch)
        with self.store.connect("session_checkpoint") as db:
            db.execute("UPDATE web_send_intents SET stage=CASE WHEN stage IN ('ANSWERING','ANSWERED') THEN stage ELSE 'SENT' END,"
                       "updated=? WHERE job_id=?", (self.jobs.clock(), job_id))
        return self.status(owner, job_id)

    def answer(self, owner: str, job_id: str, *, request_id: str, worker: str, browser_principal: str,
               conversation_id: str, message_id: str, revision: int, body: str, identity_epoch: str,
               complete: bool = False, parent_user_message_id: str | None = None) -> dict:
        """Only an authenticated assistant message can produce ANSWERED."""
        from sentra_mcp.services.web_history_store import WebHistoryStore
        row = self._row(owner, job_id)
        self._authority(row, effect=False)
        delivery = self.jobs.delivery_status(job_id)
        if not delivery or delivery["state"] != "sent" or delivery["receipt"]["conversation_id"] != conversation_id:
            raise PermissionError("assistant response requires exact sent conversation")
        attestation = self.receipts.require_attested(owner, run_id=row["run_id"], job_id=job_id, evidence=delivery["receipt"])
        if worker != row["worker"] or message_id == delivery["receipt"]["message_id"]:
            raise PermissionError("assistant message cannot substitute user receipt")
        if type(complete) is not bool:
            raise ValueError("complete must be boolean")
        if not isinstance(body, str) or len(body) > 200000:
            raise ValueError("answer must fit existing ChatResult text limit (200000 chars)")
        # Serialize identity/revision and history persistence across processes.
        # The send-intent lock is separate from provider_content's history DB.
        history = WebHistoryStore(self.control.durable.state_root, store=self.store)
        ingress = AuthenticatedWebFrameIngress(self.control, history, assistant_attestor=self.assistant_attestor)
        with self.store.connect("session_checkpoint") as db:
            db.execute("BEGIN IMMEDIATE")
            live = db.execute("SELECT answer_message_id,answer_revision,stage FROM web_send_intents WHERE job_id=?", (job_id,)).fetchone()
            if (live[0] and live[0] != message_id) or (live[1] is not None and revision < live[1]):
                raise WebSendConflict("assistant message identity or revision changed")
            if live[2] == "ANSWERED" and not complete:
                raise WebSendConflict("final answer cannot reopen streaming")
            args = dict(run_id=row["run_id"], browser_principal=browser_principal, request_id=request_id,
                        worker=worker, conversation_id=conversation_id, message_id=message_id, revision=revision,
                        state="complete" if complete else "partial", body=body, identity_epoch=identity_epoch)
            parent = parent_user_message_id if parent_user_message_id is not None else delivery["receipt"]["message_id"]
            if parent != delivery["receipt"]["message_id"]:
                raise PermissionError("assistant parent differs from original user receipt")
            if request_id != attestation["request_id"]:
                # A distinct assistant request must itself have witnessed
                # message correlation, AND the host must prove its role/body
                # and parent. Metadata alone never authorizes ANSWERED.
                ingress.proof.prove_message(owner=owner, run_id=row["run_id"], browser_principal=browser_principal,
                    request_id=request_id, worker=worker, conversation_id=conversation_id,
                    message_id=message_id, identity_epoch=identity_epoch)
            args["request_id"] = attestation["request_id"]
            ingress.record_answer(owner, job_id=job_id, parent_user_message_id=parent, **args)
            db.execute("UPDATE web_send_intents SET stage=?,answer_message_id=?,answer_revision=?,updated=? WHERE job_id=?",
                       ("ANSWERED" if complete else "ANSWERING", message_id, revision, self.jobs.clock(), job_id))
        return self.status(owner, job_id)

    def _finish_answer(self, row):
        from sentra_mcp.services.web_history_store import _plain
        delivery = self.jobs.delivery_status(row["job_id"])
        if not delivery or delivery["state"] != "sent":
            raise WebSendConflict("final answer requires original exact durable receipt")
        with self.store.connect("provider_content") as db:
            frame = db.execute("SELECT revision,role,state,protected_body FROM web_history_messages "
                               "WHERE owner=? AND workspace=? AND conversation_id=? AND message_id=?",
                               (row["owner"], row["workspace"], delivery["receipt"]["conversation_id"],
                                row["answer_message_id"])).fetchone()
        if frame is None or tuple(frame)[:3] != (row["answer_revision"], "assistant", "complete"):
            raise WebSendConflict("final history does not match committed assistant identity/revision")
        self.jobs._complete_attested_answer(row["job_id"], worker=row["worker"],
                                           receipt=delivery["receipt"], body=_plain(frame[3]))

    def status(self, owner: str, job_id: str) -> dict:
        row = self._row(owner, job_id)
        if row["stage"] == "ANSWERED":
            # Observation-only repair closes central final -> outbox ACK gap.
            self._finish_answer(row)
        try:
            job = self.jobs.pending_status(job_id)
        except ValueError:
            job = None  # admission committed, process crashed before outbox insert
        delivery = job.get("web_delivery") if job else None
        attested = False
        if delivery and delivery["state"] == "sent":
            try:
                self.receipts.require_attested(owner, run_id=row["run_id"], job_id=job_id, evidence=delivery["receipt"])
                attested = True
            except PermissionError:
                pass
        if attested:
            state = row["stage"] if row["stage"] in {"ANSWERING", "ANSWERED"} else "SENT"
        elif row["send_fence"] or (delivery and delivery["state"] in {"pending", "unconfirmed"}):
            state = "SENDING" if job and job["state"] == "LEASED" and delivery and delivery["state"] == "pending" else "UNCONFIRMED"
        elif row["stage"] in {"FAILED", "REJECTED", "CANCELLED"} or (job and job["state"] == "FAILED"):
            state = row["stage"] if row["stage"] in {"FAILED", "REJECTED", "CANCELLED"} else "FAILED"
        elif job and job["state"] == "LEASED":
            state = "READY" if job["phase"] == "ready" else "PREFLIGHT"
        else:
            state = "QUEUED"
        return {"job_id": job_id, "state": state, "run_id": row["run_id"], "operation_id": row["operation_id"],
                "work_item_id": row["work_item_id"], "submission_index": row["submission_index"],
                "request_identity_sha256": row["request_identity_sha256"], "prompt_sha256": row["prompt_sha256"],
                "answer_message_id": row["answer_message_id"], "answer_revision": row["answer_revision"],
                "delivery": delivery, "collector_message_attested": attested, "account_identity_attested": False,
                "send_fence": row["send_fence"], "admission_recovery_required": job is None,
                "automatic_resend": False, "requires_operator_reconciliation": state == "UNCONFIRMED"}
