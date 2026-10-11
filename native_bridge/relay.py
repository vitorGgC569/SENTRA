"""Loopback HTTP relay: bearer authentication, durable leases, bounded requests."""
from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .bootstrap import bootstrap_proof, extension_identity, write_extension_bootstrap
from .protocol import ChatJob, ChatResult
from .job_store import JobStore
from .web_send import WebSendConflict


class RelayState(JobStore):
    WORKER_ONLINE_WINDOW_S = 45.0
    EXTENSION_ONLINE_WINDOW_S = 90.0
    POOL_LEASE_WINDOW_S = 45.0

    def __init__(self, extension_dir=None, db_path=":memory:", *, browser_evidence=None,
                 authenticated_control=None):
        super().__init__(db_path)
        self.extension_dir = extension_dir
        self.browser_evidence = browser_evidence or (
            authenticated_control.browser_evidence if authenticated_control is not None else None)
        self.authenticated_control = authenticated_control
        self.authenticated_receipt_broker = None
        self.web_send = None
        if authenticated_control is not None:
            from .continuation_web import WebContinuation
            self.authenticated_receipt_broker = WebContinuation(
                authenticated_control, self).authenticated_receipts
            from .web_send import WebSendAuthority
            self.web_send = WebSendAuthority(authenticated_control, self)
        self._last_poll = {}
        self._worker_status = {}
        self._extension_seen = 0.0
        self._extension_status = {}
        self._pool_owner = None
        self._pool_seen = 0.0
        self._bootstrap_successes = 0
        self._bootstrap_failures = 0
        self._bootstrap_last_seen = None
        self.started_at = time.time()

    def submit(self, job):
        """Refuse a new Web effect when a known ChatGPT tab awaits approval.

        Inert for unevidenced/unenrolled chats, preserving legacy transport.
        It is not a substitute for a fresh DOM check at the actual send point.
        """
        if (self.browser_evidence is not None and
                str(job.provider or "").lower() == "chatgpt" and
                job.kind in {"CHAT_TASK", "CHAT_START", "CHAT_SEND"} and
                not job.new_chat and job.conversation_url):
            from sentra_core.conversation import ConversationIdentity
            identity = ConversationIdentity.parse(job.conversation_url)
            if identity.provider != "chatgpt":
                raise PermissionError("provider/chat URL mismatch")
            self.browser_evidence.require_dispatch_ready(
                "local-operator", identity.conversation_id)
        return super().submit(job)


    def attested_web_receipt(self, *, job_id, worker, lease_token, evidence,
                             extension_id, source_sha256, document_id,
                             request_id, identity_epoch=None):
        """Authenticated MV3 callback. IDs of owner/Run/WorkItem come from SQLite.

        The extension supplies only Web observation metadata, NEVER authority.
        Both the browser enrollment and worker lease must still be valid.
        Receipt commit and central attestation are two durable databases:
        a crash between them is recoverable only by attest_existing, NOT resend.
        """
        import hashlib
        import re
        if self.authenticated_receipt_broker is None:
            raise PermissionError("host has not enabled authenticated Web receipts")
        if (not isinstance(worker, str) or not re.fullmatch(r"TAB-[0-9]{1,12}",worker)
                or not isinstance(request_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{8,160}",request_id)):
            raise PermissionError("invalid worker or Web request ID")
        control = self.authenticated_control
        send = self.web_send.binding(job_id) if self.web_send is not None else None
        if send is not None:
            self.web_send.receipt(
                send["owner"], job_id, worker=worker, lease_token=lease_token,
                evidence=evidence, request_id=request_id, extension_id=extension_id,
                source_sha256=source_sha256, document_id=document_id, identity_epoch=identity_epoch)
            return {"job_id": job_id, "state": "attested", "message_id": evidence["message_id"],
                    "relay_delivery_state": "sent", "automatic_resend": False}
        with control.session_checkpoints.store.connect("session_checkpoint") as db:
            records = db.execute(
                "SELECT owner,run_id,work_item_id,principal_id,grant_id,prompt_sha256 "
                "FROM web_continuation_transfers WHERE job_id=? UNION "
                "SELECT owner,run_id,work_item_id,principal_id,grant_id,prompt_sha256 "
                "FROM web_target_allocations WHERE job_id=?",(job_id,job_id)
            ).fetchall()
        if len(records) != 1:
            raise PermissionError("Web receipt has no unique authorized continuation")
        bound = dict(records[0])
        if not isinstance(evidence,dict) or evidence.get("prompt_sha256") != bound["prompt_sha256"]:
            raise PermissionError("receipt does not match stored continuation digest")
        with control.session_checkpoints.store.connect("chat_access") as db:
            enrollment = db.execute(
                "SELECT principal,workspace FROM browser_collectors "
                "WHERE extension_id=? AND source_sha256=? AND enabled=1",
                (extension_id,source_sha256)
            ).fetchone()
        if enrollment is None:
            raise PermissionError("Web receipt collector not enrolled")
        item=control.work_item_info(bound["work_item_id"],bound["owner"])
        if item["run_id"] != bound["run_id"]:
            raise PermissionError("Web receipt WorkItem/Run binding changed")
        grant=control.authorization.require(
            bound["owner"],principal_type="agent",principal_id=bound["principal_id"],
            capability="web:send",scope_type="work_item",
            scope_id=bound["work_item_id"],context={"provider":"chatgpt"},
            local_owner=False)
        if grant.get("grant_id") != bound["grant_id"]:
            raise PermissionError("Web receipt original grant revoked or replaced")
        broker=self.authenticated_receipt_broker
        with self.lock:
            self._expire()
            lease=self.db.execute(
                "SELECT state,worker,lease,lease_until,deadline,phase "
                "FROM jobs WHERE id=?",(job_id,)).fetchone()
            now=self.clock()
            if (not lease or lease[0]!="LEASED" or lease[1]!=worker
                    or not isinstance(lease_token,str)
                    or not secrets.compare_digest(lease[2] or "",lease_token)
                    or not lease[3] or lease[3] < now
                    or not lease[4] or lease[4] < now
                    or lease[5]!="sending"):
                raise PermissionError("Web receipt requires live exact sending lease")
            return broker.accept(
                bound["owner"],run_id=bound["run_id"],job_id=job_id,
                browser_principal=enrollment["principal"],request_id=request_id,
                worker=worker,lease_token=lease_token,evidence=evidence,
                extension_id=extension_id,document_id=document_id,
                identity_epoch=identity_epoch)

    def reconcile_web_receipt(self, *, job_id, worker, request_id,
                              extension_id, source_sha256, document_id,
                              identity_epoch=None):
        """Host-only restart reconciliation: never asks browser to send again.

        Caller authenticates the local operator. Only a *previously sent*
        exact relay receipt can be attested against still-live browser evidence.
        """
        if self.authenticated_receipt_broker is None:
            raise PermissionError("authenticated Web receipts are unavailable")
        control=self.authenticated_control
        send = self.web_send.binding(job_id) if self.web_send is not None else None
        if send is not None:
            self.web_send.reconcile(
                send["owner"], job_id, worker=worker, request_id=request_id,
                extension_id=extension_id, source_sha256=source_sha256,
                document_id=document_id, identity_epoch=identity_epoch)
            return {"job_id": job_id, "state": "attested", "automatic_resend": False}
        with control.session_checkpoints.store.connect("session_checkpoint") as db:
            records=db.execute(
                "SELECT owner,run_id,work_item_id,principal_id,grant_id,prompt_sha256 "
                "FROM web_continuation_transfers WHERE job_id=? UNION "
                "SELECT owner,run_id,work_item_id,principal_id,grant_id,prompt_sha256 "
                "FROM web_target_allocations WHERE job_id=?",(job_id,job_id)
            ).fetchall()
        if len(records)!=1:
            raise PermissionError("unknown continuation receipt")
        bound=dict(records[0])
        item=control.work_item_info(bound["work_item_id"],bound["owner"])
        if item["run_id"]!=bound["run_id"]:
            raise PermissionError("Web continuation WorkItem changed")
        grant=control.authorization.require(
            bound["owner"],principal_type="agent",principal_id=bound["principal_id"],
            capability="web:send",scope_type="work_item",
            scope_id=bound["work_item_id"],context={"provider":"chatgpt"},
            local_owner=False)
        if grant.get("grant_id")!=bound["grant_id"]:
            raise PermissionError("reconciliation requires original active grant")
        status=self.delivery_status(job_id)
        if not status or status["state"]!="sent" or not status.get("receipt"):
            raise PermissionError("Web result uncertain, no authenticated receipt to reconcile")
        with control.session_checkpoints.store.connect("chat_access") as db:
            enrollment=db.execute(
                "SELECT principal FROM browser_collectors WHERE extension_id=? "
                "AND source_sha256=? AND enabled=1",(extension_id,source_sha256)
            ).fetchone()
        if enrollment is None:
            raise PermissionError("collector not enrolled")
        broker=self.authenticated_receipt_broker
        broker._prove_browser(
            owner=bound["owner"],run_id=bound["run_id"],
            browser_principal=enrollment["principal"],request_id=request_id,
            worker=worker,evidence=status["receipt"],extension_id=extension_id,
            document_id=document_id,identity_epoch=identity_epoch)
        return broker.attest_existing(
            bound["owner"],run_id=bound["run_id"],job_id=job_id,
            browser_principal=enrollment["principal"],request_id=request_id,
            worker=worker,evidence=status["receipt"],
            identity_epoch=identity_epoch)

    def extension_version(self):
        root = Path(self.extension_dir) if self.extension_dir else None
        if not root:
            return {"version": None}
        try:
            return extension_identity(root)
        except (OSError, ValueError, KeyError):
            return {"version": None, "error": "extension manifest unavailable or stale"}

    def note_bootstrap(self, success: bool) -> None:
        with self.lock:
            self._bootstrap_last_seen = time.time()
            if success:
                self._bootstrap_successes += 1
            else:
                self._bootstrap_failures += 1

    def bootstrap_status(self) -> dict:
        with self.lock:
            return {
                "successes": self._bootstrap_successes,
                "failures": self._bootstrap_failures,
                "last_seen": self._bootstrap_last_seen,
            }

    def mark_extension(self, status=None):
        if status is not None and not isinstance(status, dict):
            raise ValueError("extension status must be an object")
        with self.lock:
            self._extension_seen = time.time()
            if isinstance(status, dict):
                self._extension_status = dict(status)

    def extension_status(self):
        with self.lock:
            last_seen = float(self._extension_seen or 0.0)
            status = dict(self._extension_status or {})
        age_s = (time.time() - last_seen) if last_seen else None
        return {
            "online": bool(last_seen and age_s is not None and age_s <= self.EXTENSION_ONLINE_WINDOW_S),
            "last_seen": last_seen or None,
            "age_s": round(age_s, 3) if age_s is not None else None,
            "status": status,
        }

    def mark_worker(self, worker="", status=None):
        if not isinstance(worker, str) or not worker.startswith("TAB-"):
            raise ValueError("invalid worker identity")
        if status is not None and not isinstance(status, dict):
            raise ValueError("worker status must be an object")
        with self.lock:
            self._last_poll[worker] = time.time()
            if isinstance(status, dict):
                self._worker_status[worker] = status

    def worker_status(self, worker):
        if not isinstance(worker, str) or not worker.startswith("TAB-"):
            raise ValueError("invalid worker identity")
        with self.lock:
            last_seen = self._last_poll.get(worker)
            status = dict(self._worker_status.get(worker) or {})
        online = bool(
            last_seen is not None
            and time.time() - last_seen <= self.WORKER_ONLINE_WINDOW_S
        )
        return {
            "worker": worker,
            "online": online,
            "last_seen": last_seen,
            "status": status,
        }

    def _continuation_send_authority(self, jid):
        if self.authenticated_control is None:
            return None
        control = self.authenticated_control
        with control.session_checkpoints.store.connect("session_checkpoint") as db:
            rows = db.execute("SELECT owner,run_id,work_item_id,principal_id,grant_id FROM web_continuation_transfers "
                              "WHERE job_id=? UNION SELECT owner,run_id,work_item_id,principal_id,grant_id "
                              "FROM web_target_allocations WHERE job_id=?", (jid, jid)).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise PermissionError("continuation job has conflicting authority")
        row = dict(rows[0])
        run = control._run(row["run_id"], row["owner"])
        control._agent_from_run(run, row["principal_id"])
        item = control.work_item_info(row["work_item_id"], row["owner"])
        if (item["run_id"] != row["run_id"] or run["state"] not in {"CREATED", "RUNNING"} or
                item["state"] in {"COMPLETED", "FAILED", "CANCELLED"} or
                (item.get("assignee_agent_id") and item["assignee_agent_id"] != row["principal_id"])):
            raise PermissionError("continuation send authority is inactive or changed")
        grant = control.authorization.require(row["owner"], principal_type="agent", principal_id=row["principal_id"],
            capability="web:send", scope_type="work_item", scope_id=row["work_item_id"],
            context={"provider": "chatgpt"}, local_owner=False)
        if grant.get("grant_id") != row["grant_id"]:
            raise PermissionError("original continuation grant revoked or replaced")
        return row

    def _browser_job_admitted(self, payload):
        if isinstance(payload, dict):
            try:
                self._continuation_send_authority(payload.get("job_id", ""))
            except (PermissionError, FileNotFoundError):
                return False
        if self.web_send is not None and isinstance(payload, dict):
            bound = self.web_send.binding(payload.get("job_id", ""))
            if bound is not None:
                if bound["send_fence"] or bound["stage"] != "QUEUED":
                    return False
                try:
                    self.web_send._authority(bound)
                except (PermissionError, FileNotFoundError):
                    return False
        if self.browser_evidence is None or not isinstance(payload, dict):
            return True
        if (payload.get("provider") != "chatgpt" or
                payload.get("kind") not in {"CHAT_TASK", "CHAT_START", "CHAT_SEND"} or
                payload.get("new_chat") or not payload.get("conversation_url")):
            return True
        from sentra_core.conversation import ConversationIdentity
        try:
            identity = ConversationIdentity.parse(payload["conversation_url"])
            if identity.provider != "chatgpt":
                return False
            self.browser_evidence.require_dispatch_ready(
                "local-operator", identity.conversation_id)
        except (ValueError, PermissionError):
            return False
        return True

    def progress(self, jid, worker, token, phase):
        bound = self.web_send.binding(jid) if self.web_send is not None else None
        if bound is not None and phase == "sending":
            # The browser cannot invent central fencing facts. Derive them
            # exclusively from the already-authorized Operation's live lease.
            run = self.authenticated_control.durable.run_status(bound["run_id"], bound["owner"])
            leases = [lease for lease in run.get("leases", [])
                      if lease.get("operation_id") == bound["operation_id"] and
                      lease.get("lease_until", 0) > self.authenticated_control.durable.clock()]
            if len(leases) != 1:
                raise PermissionError("pre-Send requires an unambiguous existing central lease")
            lease = leases[0]
            return self.web_send.pre_send(bound["owner"], jid, worker=worker, lease_token=token,
                                          resource_key=lease["resource_key"], fencing_token=lease["fencing_token"])
        if phase == "sending":
            with self.lock:
                legacy = self._continuation_send_authority(jid)
                if legacy is not None:
                    if (self.delivery_status(jid) or {}).get("state") != "not_sent":
                        raise WebSendConflict("continuation pre-Send ACK already consumed; reconcile without resend")
                    return super().progress(jid, worker, token, phase, single_use_send=True)
        return super().progress(jid, worker, token, phase)

    def poll(self, worker=""):
        job = super().poll(worker, candidate_check=self._browser_job_admitted)
        if worker:
            self.mark_worker(worker)
        return job

    def workers_online(self):
        with self.lock:
            return [
                w for w, t in self._last_poll.items()
                if time.time() - t <= self.WORKER_ONLINE_WINDOW_S
            ]

    def release_worker(self, worker=""):
        if not isinstance(worker, str) or not worker.startswith("TAB-"):
            raise ValueError("invalid worker identity")
        with self.lock:
            # Keep the key so workers_ever_seen remains monotonic for diagnostics,
            # but make the worker immediately offline and clear cached UI status.
            self._last_poll[worker] = 0.0
            self._worker_status.pop(worker, None)

    def workers_ever_seen(self):
        with self.lock:
            return len(self._last_poll)

    def claim_pool(self, instance_id: str) -> dict:
        if not isinstance(instance_id, str) or not instance_id.startswith("POOL-") or len(instance_id) > 120:
            raise ValueError("invalid pool instance identity")
        now = time.time()
        with self.lock:
            expired = (
                self._pool_owner is None
                or now - self._pool_seen > self.POOL_LEASE_WINDOW_S
            )
            if expired or self._pool_owner == instance_id:
                self._pool_owner = instance_id
                self._pool_seen = now
                leader = True
            else:
                leader = False
            return {
                "leader": leader,
                "owner": self._pool_owner,
                "lease_window_s": self.POOL_LEASE_WINDOW_S,
            }

    def pool_status(self) -> dict:
        now = time.time()
        with self.lock:
            active = (
                self._pool_owner is not None
                and now - self._pool_seen <= self.POOL_LEASE_WINDOW_S
            )
            return {
                "active": active,
                "owner": self._pool_owner if active else None,
                "lease_window_s": self.POOL_LEASE_WINDOW_S,
            }

    def wait(self, job_id, timeout_s):
        deadline = time.monotonic() + max(0, min(timeout_s, 25))
        while True:
            result = self.result(job_id)
            if result is not None or time.monotonic() >= deadline:
                return result
            time.sleep(.1)


def make_handler(state, token):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def _send(self, payload, code=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (OSError, TimeoutError):
                pass

        def log_message(self, *args):
            pass

        def _authorized(self):
            origin = self.headers.get("Origin", "")
            # A website, including chatgpt.com content scripts, cannot call the relay.
            if origin and not origin.startswith("chrome-extension://"):
                self._send({"error": "forbidden origin"}, 403)
                return False
            if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}",
                                                 f"localhost:{self.server.server_port}"}:
                self._send({"error": "invalid host"}, 403)
                return False
            if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self._send({"error": "pairing token required"}, 401)
                return False
            return True

        def _read_json(self, maximum=1048576):
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= int(maximum):
                self._send({"error": f"body must be 1..{int(maximum)} bytes"}, 413)
                return None
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("JSON object required")
            return data

        def _bootstrap(self, data):
            origin = self.headers.get("Origin", "")
            extension_id = (
                origin.removeprefix("chrome-extension://")
                if origin.startswith("chrome-extension://")
                else ""
            )
            if (
                len(extension_id) != 32
                or any(ch < "a" or ch > "p" for ch in extension_id)
            ):
                state.note_bootstrap(False)
                return self._send({"error": "forbidden extension origin"}, 403)
            if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}",
                                                 f"localhost:{self.server.server_port}"}:
                state.note_bootstrap(False)
                return self._send({"error": "invalid host"}, 403)
            identity = state.extension_version()
            if not identity.get("version"):
                state.note_bootstrap(False)
                return self._send({"error": "extension identity unavailable"}, 503)
            supplied = {
                "schema_version": data.get("schema_version"),
                "extension_version": data.get("extension_version"),
                "build_id": data.get("build_id"),
                "source_hash": data.get("source_hash"),
            }
            expected_identity = {
                "schema_version": 1,
                "extension_version": identity.get("version"),
                "build_id": identity.get("build_id"),
                "source_hash": identity.get("source_hash"),
            }
            if supplied != expected_identity:
                state.note_bootstrap(False)
                return self._send({"error": "extension identity mismatch",
                                   "expected": expected_identity}, 409)
            proof = str(data.get("proof") or "")
            expected_proof = bootstrap_proof(token, identity)
            if not proof or not secrets.compare_digest(proof, expected_proof):
                state.note_bootstrap(False)
                return self._send({"error": "extension bootstrap proof required"}, 401)
            state.note_bootstrap(True)
            return self._send({"ok": True, "token": token, **expected_identity})

        def _browser_collector(self, data):
            if state.browser_evidence is None:
                raise PermissionError("browser evidence collector unavailable")
            origin = self.headers.get("Origin", "")
            if not origin.startswith("chrome-extension://"):
                raise PermissionError("evidence requires the enrolled extension origin")
            extension_id = origin.removeprefix("chrome-extension://")
            identity = state.extension_version()
            if not identity.get("source_hash") or data.get("source_sha256") != identity["source_hash"]:
                raise PermissionError("browser evidence extension build changed")
            return {"extension_id": extension_id, "source_sha256": identity["source_hash"],
                    "worker": data["worker"]}

        def do_POST(self):
            try:
                if self.path == "/auth/bootstrap":
                    data = self._read_json(8192)
                    if data is None:
                        return
                    return self._bootstrap(data)
                if not self._authorized():
                    return
                data = self._read_json()
                if data is None:
                    return
                if self.path == "/browser-evidence/challenge":
                    v1 = {"source_sha256", "worker", "document_id"}
                    v2 = v1 | {"identity_epoch"}
                    if set(data) not in (v1, v2):
                        raise ValueError("exact V1/V2 evidence challenge schema required")
                    collector = self._browser_collector(data)
                    return self._send(state.browser_evidence.challenge(
                        **collector, document_id=data["document_id"],
                        identity_epoch=data.get("identity_epoch")))
                if self.path == "/browser-evidence/observe":
                    if set(data) != {"source_sha256", "worker", "evidence"}:
                        raise ValueError("exact browser observe transport schema required")
                    # BrowserEvidenceService enforces V2 identity_epoch inside evidence,
                    # nonce, collector revision and document binding in central SQLite.
                    collector = self._browser_collector(data)
                    return self._send(state.browser_evidence.observe(
                        **collector, evidence=data["evidence"]))
                if self.path == "/browser-evidence/invalidate":
                    v1 = {"source_sha256", "worker", "document_id", "reason"}
                    v2 = v1 | {"identity_epoch"}
                    if set(data) not in (v1, v2):
                        raise ValueError("exact V1/V2 browser invalidation schema required")
                    collector = self._browser_collector(data)
                    outcome=state.browser_evidence.invalidate_document(
                        **collector, document_id=data["document_id"], reason=data["reason"],
                        identity_epoch=data.get("identity_epoch"))
                    if outcome["state"]=="invalidated":
                        # Mark only that observed worker offline, never kill or
                        # requeue a lease whose Web send may already have happened.
                        state.release_worker(collector["worker"])
                    return self._send(outcome)
                if self.path == "/extension/heartbeat":
                    state.mark_extension(data.get("status"))
                    return self._send({"ok": True, "extension": state.extension_status()})
                if self.path == "/workers/heartbeat":
                    worker = str(data.get("worker") or "")
                    status = data.get("status")
                    state.mark_worker(worker, status)
                    return self._send({"ok": True})
                if self.path == "/workers/pool-claim":
                    instance_id = str(data.get("instance_id") or "")
                    return self._send({"ok": True, **state.claim_pool(instance_id)})
                if self.path == "/workers/release":
                    worker = str(data.get("worker") or "")
                    state.release_worker(worker)
                    return self._send({"ok": True, "released": True})
                if self.path == "/jobs/submit":
                    allowed = {
                        "task_id", "prompt", "timeout_s", "new_chat",
                        "conversation_url", "kind", "images", "target_worker",
                        "browser_action", "browser_args", "project_id",
                        "project_url", "chat_title", "provider", "model",
                        "delivery_key",
                    }
                    if set(data) - allowed:
                        raise ValueError("unknown job fields")
                    return self._send({"job_id": state.submit(ChatJob(**data))})
                if self.path == "/jobs/result":
                    lease_token = data.pop("lease_token", "")
                    state.store_result(ChatResult(**data), lease_token)
                elif self.path == "/jobs/delivery-receipt":
                    legacy={"job_id","worker","lease_token","evidence"}
                    verified=legacy | {"request_id","source_sha256","document_id"}
                    verified_v2=verified | {"identity_epoch"}
                    if set(data) in (verified,verified_v2):
                        collector=self._browser_collector(data)
                        result=state.attested_web_receipt(
                            job_id=data["job_id"],worker=collector["worker"],
                            lease_token=data["lease_token"],evidence=data["evidence"],
                            request_id=data["request_id"],document_id=data["document_id"],
                            extension_id=collector["extension_id"],
                            source_sha256=collector["source_sha256"],
                            identity_epoch=data.get("identity_epoch"))
                        return self._send({**result,"relay_delivery_state":"sent",
                                           "automatic_resend":False})
                    if set(data)!=legacy:
                        raise ValueError("exact preliminary or authenticated receipt schema required")
                    # Legacy receipt stays preliminary: NEVER permits Web A->B commit.
                    return self._send(state.delivery_receipt(data["job_id"],data["worker"],
                        data["lease_token"],data["evidence"]))
                elif self.path == "/jobs/progress":
                    info = state.progress(data["job_id"], data["worker"], data["lease_token"], data["phase"])
                    return self._send({"ok": True, **info})
                elif self.path == "/jobs/lease":
                    state.lease(data["job_id"], data["worker"], data["lease_token"])
                elif self.path == "/jobs/ack":
                    state.acknowledge(data["job_id"])
                elif self.path == "/jobs/cancel":
                    state.cancel(data["job_id"])
                else:
                    return self._send({"error": "not found"}, 404)
                return self._send({"ok": True})
            except PermissionError:
                return self._send({"error": "browser collector denied; enroll or repair in SENTRA"}, 403)
            except WebSendConflict as exc:
                return self._send({"error": str(exc), "automatic_resend": False}, 409)
            except (ValueError, TypeError, KeyError) as exc:
                return self._send({"error": str(exc)}, 400)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                return self._send({"ok": True, "authentication": "bearer",
                                   **state.counts(), "workers_online": state.workers_online(),
                                   "workers_ever_seen": state.workers_ever_seen(),
                                   "extension": state.extension_status(),
                                   "pool": state.pool_status(),
                                   "bootstrap": state.bootstrap_status(),
                                   "uptime_s": round(time.time()-state.started_at, 1)})
            if parsed.path == "/extension/version":
                identity = state.extension_version()
                bootstrap_refreshed = None
                if state.extension_dir:
                    try:
                        write_extension_bootstrap(Path(state.extension_dir), token)
                        bootstrap_refreshed = True
                    except (OSError, ValueError, KeyError):
                        bootstrap_refreshed = False
                return self._send({
                    **identity,
                    "bootstrap_refreshed": bootstrap_refreshed,
                })
            if not self._authorized():
                return
            qs = parse_qs(parsed.query)
            try:
                if parsed.path == "/auth/check":
                    return self._send({"ok": True})
                if parsed.path == "/workers/status":
                    worker = (qs.get("worker") or [""])[0]
                    return self._send(state.worker_status(worker))
                if parsed.path == "/jobs/delivery":
                    return self._send(state.delivery_status((qs.get("job_id") or [""])[0]))
                if parsed.path == "/jobs/poll":
                    return self._send({"job": state.poll((qs.get("worker") or [""])[0])})
                if parsed.path == "/jobs/wait":
                    jid = (qs.get("job_id") or [""])[0]
                    timeout = float((qs.get("timeout_s") or ["20"])[0])
                    result = state.wait(jid, timeout)
                    if result is not None:
                        return self._send(result)
                    status = state.pending_status(jid)
                    return self._send({"pending": True, **status})
                return self._send({"error": "not found"}, 404)
            except ValueError as exc:
                return self._send({"error": str(exc)}, 400)

    return Handler


class BoundedHTTPServer(ThreadingHTTPServer):
    """Bound concurrent HTTP handler threads; slow local clients cannot spawn unbounded workers."""
    daemon_threads = False

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class RelayServer:
    def __init__(self, host="127.0.0.1", port=8765, extension_dir=None, token=None, db_path=":memory:",
                 browser_evidence=None, authenticated_control=None):
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("relay must bind loopback only")
        self.token = token or secrets.token_urlsafe(32)
        if len(self.token) < 32:
            raise ValueError("relay token must contain at least 32 characters")
        if extension_dir is not None:
            write_extension_bootstrap(Path(extension_dir), self.token)
        self.state = RelayState(extension_dir, db_path, browser_evidence=browser_evidence,
                                authenticated_control=authenticated_control)
        try:
            self.server = BoundedHTTPServer((host, port), make_handler(self.state, self.token))
        except OSError:
            self.state.close()
            raise
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)
        self.state.close()
