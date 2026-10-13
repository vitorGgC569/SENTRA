"""Responses composition over the existing Web outbox and central authority.

This module routes authenticated host facts. It owns no sender, Run, Grant or
message queue. Missing account attestation and rollout proof fail closed.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from native_bridge.job_store import JobStore
from native_bridge.web_send import WebSendAuthority
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService


class DurableWebTransport:
    def __init__(self, authority, *, control=None, jobs=None,
                 account_attestor=None, assistant_attestor=None, message_attestor=None, activation_validator=None):
        self.authority = authority
        self._owns_context = control is None
        self._owns_jobs = jobs is None
        if control is not None and control.durable.state_root.resolve() != authority.state_root:
            raise ValueError("Web transport requires the same central state root")
        self.control = control or ControlPlaneService(
            authority.durable, ContextBusService(authority.state_root))
        if jobs is None:
            outbox = authority.state_root / "browser" / "relay.sqlite3"
            try:
                outbox.parent.mkdir(parents=True, exist_ok=True)
                jobs = JobStore(outbox)
            except Exception:
                if self._owns_context:
                    self.control.context.close()
                raise
        self.jobs = jobs
        self.account_attestor = account_attestor
        self.activation_validator = activation_validator
        self.message_attestor = message_attestor or self._host_observation
        try:
            self.web = WebSendAuthority(self.control, self.jobs, assistant_attestor=assistant_attestor or self._host_observation)
            self._initialize()
        except Exception:
            self.close()
            raise

    def _initialize(self):
        with self.control.store.connect("session_checkpoint") as db:
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS gateway_web_transport_mode(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    mode TEXT NOT NULL, revision INTEGER NOT NULL);
                INSERT OR IGNORE INTO gateway_web_transport_mode VALUES(1,'legacy',0);
                CREATE TABLE IF NOT EXISTS gateway_web_bindings(
                    conversation_uri TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    run_id TEXT NOT NULL, work_item_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL, grant_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS gateway_web_submissions(
                    token_hash TEXT NOT NULL, operation_id TEXT NOT NULL, submission_index INTEGER NOT NULL,
                    job_id TEXT NOT NULL UNIQUE, worker TEXT NOT NULL,
                    document_id TEXT NOT NULL, identity_epoch TEXT NOT NULL,
                    prompt_sha256 TEXT NOT NULL,
                    PRIMARY KEY(token_hash,operation_id,submission_index));
                CREATE TABLE IF NOT EXISTS gateway_web_attachment_links(
                    token_hash TEXT NOT NULL, operation_id TEXT NOT NULL,
                    submission_index INTEGER NOT NULL,
                    asset_id TEXT NOT NULL, sha256 TEXT NOT NULL,
                    PRIMARY KEY(token_hash,operation_id,submission_index,asset_id));
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(gateway_web_submissions)")}
            if "operation_id" not in columns:
                db.execute("ALTER TABLE gateway_web_submissions RENAME TO gateway_web_submissions_v1")
                db.execute("CREATE TABLE gateway_web_submissions (token_hash TEXT NOT NULL, operation_id TEXT NOT NULL, "
                    "submission_index INTEGER NOT NULL, job_id TEXT NOT NULL UNIQUE, worker TEXT NOT NULL, "
                    "document_id TEXT NOT NULL, identity_epoch TEXT NOT NULL, prompt_sha256 TEXT NOT NULL, "
                    "PRIMARY KEY(token_hash,operation_id,submission_index))")
                db.execute("INSERT INTO gateway_web_submissions SELECT old.token_hash, i.operation_id, old.submission_index, "
                    "old.job_id,old.worker,old.document_id,old.identity_epoch,old.prompt_sha256 "
                    "FROM gateway_web_submissions_v1 old JOIN web_send_intents i ON i.job_id=old.job_id")
                old_count = db.execute("SELECT COUNT(*) FROM gateway_web_submissions_v1").fetchone()[0]
                if db.execute("SELECT COUNT(*) FROM gateway_web_submissions").fetchone()[0] != old_count:
                    raise RuntimeError("Web phase migration requires reconciliation of missing intents")
                db.execute("DROP TABLE gateway_web_submissions_v1")

    def status(self):
        with self.control.store.connect("session_checkpoint") as db:
            row = db.execute("SELECT mode,revision FROM gateway_web_transport_mode WHERE singleton=1").fetchone()
        return {**dict(row), "production_enabled": row["mode"] == "durable_v2",
                "account_attestor_available": callable(self.account_attestor),
                "activation_validator_available": callable(self.activation_validator),
                "automatic_resend": False}

    def set_mode(self, mode: str, *, expected_revision: int):
        if mode not in {"legacy", "candidate_v2", "durable_v2"}:
            raise ValueError("invalid Web transport mode")
        # Only the trusted host validator can approve current build, real Web
        # E2E and identity gates. HTTP/model booleans are never rollout evidence.
        if mode != "legacy" and (not callable(self.activation_validator) or
                                  self.activation_validator(mode) is not True):
            raise PermissionError("Web transport activation lacks verified build/E2E/identity gates")
        with self.control.store.connect("session_checkpoint") as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE gateway_web_transport_mode SET mode=?,revision=revision+1 "
                                 "WHERE singleton=1 AND revision=?", (mode, expected_revision)).rowcount
            if changed != 1:
                raise RuntimeError("Web transport revision changed")
        # Rollback changes routing for NEW requests only; outbox states are untouched.
        return self.status()

    def bind(self, conversation_uri: str, *, owner: str, run_id: str,
             work_item_id: str, principal_id: str, grant_id: str):
        if not isinstance(conversation_uri, str) or not conversation_uri.startswith("conversation://"):
            raise ValueError("logical conversation URI required")
        work = self.control.work_item_info(work_item_id, owner)
        if work["run_id"] != run_id:
            raise PermissionError("WorkItem/Run binding mismatch")
        grant = self.control.authorization.require(
            owner, principal_type="agent", principal_id=principal_id, capability="web:send",
            scope_type="work_item", scope_id=work_item_id, local_owner=False)
        if grant["grant_id"] != grant_id:
            raise PermissionError("original Web send grant required")
        with self.control.store.connect("session_checkpoint") as db:
            db.execute("INSERT INTO gateway_web_bindings VALUES(?,?,?,?,?,?) "
                       "ON CONFLICT(conversation_uri) DO UPDATE SET owner=excluded.owner,run_id=excluded.run_id,"
                       "work_item_id=excluded.work_item_id,principal_id=excluded.principal_id,grant_id=excluded.grant_id",
                       (conversation_uri, owner, run_id, work_item_id, principal_id, grant_id))
        return {"conversation_uri": conversation_uri, "run_id": run_id,
                "work_item_id": work_item_id, "grants_created": False}

    def binding(self, conversation_uri):
        with self.control.store.connect("session_checkpoint") as db:
            row = db.execute("SELECT * FROM gateway_web_bindings WHERE conversation_uri=?",
                             (conversation_uri,)).fetchone()
        if row is None:
            raise PermissionError("conversation has no host-authorized Web WorkItem binding")
        return dict(row)

    def admit_responses(self, *, conversation_uri, request_identity, payload):
        binding = self.binding(conversation_uri)
        token = self.authority.issue_bound(control=self.control, request_identity=request_identity,
            **binding)
        cap = self.authority._capability(token)
        # The original Responses intent is protected before upstream/browser I/O.
        try:
            self.web.stage_request(binding["owner"], request_identity=request_identity,
                run_id=cap.run_id, operation_id=cap.operation_id,
                payload={"responses": payload, "request_identity": request_identity})
        except Exception:
            self.authority.retire(token, failed=True)
            raise
        return token

    def _request(self, cap):
        # Recover only the original protected host intent; page/model fields
        # cannot substitute the stable Responses request identity.
        with self.control.store.connect("session_checkpoint") as db:
            row = db.execute("SELECT r.request_id FROM web_response_requests r "
                "JOIN gateway_bound_web_turns b ON r.owner=b.owner AND r.request_identity_sha256=b.request_hash "
                "WHERE b.token_hash=?", (cap.token_hash,)).fetchone()
        if row is None:
            raise PermissionError("Web turn has no protected Responses intent")
        intent = self.web.request_payload(cap.owner, row["request_id"])
        identity = intent["request_identity"]
        with self.control.store.connect("session_checkpoint") as db:
            root = db.execute("SELECT operation_id FROM web_response_requests WHERE request_id=?", (row["request_id"],)).fetchone()
        if root["operation_id"] != cap.operation_id:
            identity += ":phase:" + cap.operation_id
            self.web.stage_request(cap.owner, request_identity=identity, run_id=cap.run_id,
                                   operation_id=cap.operation_id, payload=intent)
        return identity, intent["responses"]

    def _proof(self, cap, payload, responses):
        descriptor, tab = self.authority._physical_tab(payload["traceId"])
        if not callable(self.account_attestor):
            from .browser_host_identity import read_host_identity
            read_host_identity(descriptor, tab, trace_id=payload["traceId"])
            # Reading committed account/menu properties has no calibrated
            # account schema yet. Neither account_id nor account_verified from
            # an HTTP payload can substitute operator-enrolled host proof.
            raise PermissionError("current Browser Host snapshot lacks calibrated account/profile attestation")
        proof = self.account_attestor(cap, descriptor, tab)
        if not isinstance(proof, dict) or proof.get("account_verified") is not True:
            raise PermissionError("current browser account/profile identity is unverified by host")
        for field in ("extension_id", "source_sha256", "worker", "browser_principal", "document_id", "identity_epoch"):
            if not isinstance(proof.get(field), str) or not proof[field]:
                raise PermissionError("browser host attestation is incomplete")
        if proof.get("approval_state") not in {"idle", "pending"}:
            raise PermissionError("current approval state is not attested by host")
        if proof.get("collector_kind") == "electron":
            revision = proof.get("authentication_revision")
            if type(revision) is not int or revision < 0:
                raise PermissionError("current browser account authentication revision is unverified")
            cap.browser_account_revision = revision
        requested_effort = (responses.get("reasoning") or {}).get("effort")
        if (proof.get("selection_verified") is not True or
                proof.get("requested_model") != responses.get("model") or
                proof.get("requested_effort") != requested_effort or
                proof.get("model") != payload.get("model") or proof.get("effort") != payload.get("effort")):
            raise PermissionError("current physical model/effort is not attested for the original request")
        for field in ("document_id", "identity_epoch"):
            if proof.get(field) != payload.get(field):
                raise PermissionError("browser document/epoch differs from host attestation")
        if payload.get("surface_id") != tab.get("surfaceId"):
            raise PermissionError("browser surface differs from authenticated descriptor")
        return proof

    def _staged_images(self, binding, refs) -> tuple[list, list[tuple[str, str]]]:
        """Resolve gateway preflight attachment refs to outbox images.

        `refs` (from the browser-event payload, host-authenticated) is a list
        of {asset_id, sha256} pointing at READY_LOCAL staged bytes in
        `WebAssetDrafts`. Each ref must belong to the SAME bound WorkItem
        with a live `web:attach` grant and an exact digest; bytes are
        materialized host-side within the relay image caps. Returns
        (data-URLs, [(asset_id, sha256)]). Empty refs admit a text-only turn
        exactly as before. Anything else fails closed: the browser never
        supplies bytes and a replay with different attachments is rejected
        by `_attachment_links`, never substituted.
        """
        import re as _re
        if refs is None:
            refs = []
        if not isinstance(refs, list) or len(refs) > 2:
            raise ValueError("preflight attachments hold at most 2 staged refs "
                             "per send (composer quota until the Brisa composer "
                             "path expands); larger sets are refused, never split")
        if not refs:
            return [], []
        from sentra_mcp.services.web_history_assets import WebAssetDrafts
        from native_bridge.attachment_upload import AttachmentUploads
        drafts = WebAssetDrafts(self.control)
        uploads = AttachmentUploads(self.control, self.jobs, drafts)
        images: list = []
        links: list[tuple[str, str]] = []
        for ref in refs:
            if not isinstance(ref, dict):
                raise ValueError("staged attachment ref must be an object")
            asset_id = ref.get("asset_id")
            sha256 = ref.get("sha256")
            if (not isinstance(asset_id, str)
                    or not _re.fullmatch(r"[A-Za-z0-9_-]{8,160}", asset_id)
                    or not isinstance(sha256, str)
                    or not _re.fullmatch(r"[0-9a-f]{64}", sha256)):
                raise ValueError("staged attachment ref requires asset_id and sha256")
            status = None
            try:
                status = drafts.status(binding["owner"], asset_id)
            except FileNotFoundError:
                raise PermissionError("staged attachment unknown for owner")
            if status["state"] != "READY_LOCAL":
                raise PermissionError("staged attachment is not finalized")
            if status["work_item_id"] != binding["work_item_id"] or status["sha256"] != sha256:
                raise PermissionError("staged attachment binding changed")
            images.append(uploads.bound_image(binding["owner"], asset_id))
            links.append((asset_id, sha256))
        return images, sorted(links)

    def _attachment_links(self, cap, index: int) -> list[tuple[str, str]]:
        with self.control.store.connect("session_checkpoint") as db:
            try:
                rows = db.execute(
                    "SELECT asset_id,sha256 FROM gateway_web_attachment_links "
                    "WHERE token_hash=? AND operation_id=? AND submission_index=?",
                    (cap.token_hash, cap.operation_id, index)).fetchall()
            except Exception as exc:
                message = str(exc)
                if ("does not exist" in message or "undefined" in message.lower()
                        or "no such table" in message):
                    return []
                raise
        return sorted((row["asset_id"], row["sha256"]) for row in rows)

    def _host_observation(self, **expected):
        from .browser_host_identity import read_host_message
        with self.control.store.connect("session_checkpoint") as db:
            row = db.execute("SELECT s.*,b.owner,b.run_id FROM gateway_web_submissions s "
                "JOIN gateway_bound_web_turns b ON b.token_hash=s.token_hash WHERE s.job_id=?",
                (expected["job_id"],)).fetchone()
            receipt = db.execute("SELECT request_id FROM authenticated_web_receipts WHERE job_id=? AND owner=? AND run_id=?",
                (expected["job_id"], expected["owner"], expected["run_id"])).fetchone()
        if row is None or (row["owner"], row["run_id"], row["worker"], row["identity_epoch"]) != (
                expected["owner"], expected["run_id"], expected["worker"], expected["identity_epoch"]):
            raise PermissionError("Browser Host observation has no original submission binding")
        with self.authority.lock:
            cap = self.authority.capabilities.get(row["token_hash"]) or self.authority._rehydrate(row["token_hash"])
        if cap is None or cap.operation_id != row["operation_id"] or cap.browser_account_revision is None:
            raise PermissionError("Browser Host observation has no current account-bound phase")
        descriptor, tab = self.authority._physical_tab(cap.trace_id)
        if (tab.get("documentId"), tab.get("identityEpoch")) != (row["document_id"], row["identity_epoch"]):
            raise PermissionError("Browser Host document/epoch differs from original submission")
        query = dict(expected)
        if expected["role"] == "assistant":
            if receipt is None:
                raise PermissionError("Browser Host assistant has no original user receipt")
            query.update(request_id=receipt["request_id"], complete=expected["state"] == "complete")
        observed = read_host_message(descriptor, tab, trace_id=cap.trace_id, expected=query)
        if (observed.get("document_id"), observed.get("identity_epoch")) != (row["document_id"], row["identity_epoch"]):
            raise PermissionError("Browser Host document/epoch changed during message observation")
        if (type(observed.get("authentication_revision")) is not int
                or observed["authentication_revision"] != cap.browser_account_revision):
            raise PermissionError("Browser Host account changed during message observation")
        return {**expected, "authenticated": True, "host_observation": {
            "revision": observed["host_revision"], "body_sha256": observed["body_sha256"],
            "state": "complete" if observed.get("complete") is True else "partial",
            "collector_id": observed["collector_id"], "source_sha256": observed["collector_sha256"],
            "document_id": observed["document_id"], "identity_epoch": observed["identity_epoch"]}}

    def browser_event(self, action: str, payload: dict[str, Any]):
        cap = self.authority._capability(payload.get("capability"))
        if not cap.shared_run:
            raise PermissionError("Web outbox requires a bound central WorkItem")
        trace = payload.get("traceId")
        if trace != cap.trace_id or not trace:
            raise PermissionError("Web event belongs to another browser phase")
        index = payload.get("submission_index")
        if type(index) is not int or not 0 <= index <= 128:
            raise ValueError("invalid physical submission index")
        with self.control.store.connect("session_checkpoint") as db:
            row = db.execute("SELECT * FROM gateway_web_submissions WHERE token_hash=? AND operation_id=? AND submission_index=?",
                             (cap.token_hash, cap.operation_id, index)).fetchone()
        if action == "failure":
            # Losing the page/account must not prevent a conservative stop of
            # the ORIGINAL intent. This path can only fail/cancel or preserve
            # uncertainty; it cannot establish not-run, receive or resend.
            if row is None or payload.get("request_id") != row["job_id"]:
                raise PermissionError("Web failure has no matching original intent")
            for field in ("document_id", "identity_epoch", "prompt_sha256"):
                if row[field] != payload.get(field):
                    raise PermissionError("Web failure belongs to another submission")
            return self.web.failure(cap.owner, row["job_id"], reason="browser_delivery_failed")
        self.authority.authorize("browser-heartbeat", {"capability": payload["capability"], "traceId": trace})
        binding = self.binding(cap.conversation_uri)
        if (binding["owner"], binding["run_id"], binding["work_item_id"], binding["principal_id"], binding["grant_id"]) != (
                cap.owner, cap.run_id, cap.work_item_id, cap.agent_id, cap.web_grant_id):
            raise PermissionError("Web authority binding changed during execution")
        request_identity, responses = self._request(cap)
        proof = self._proof(cap, payload, responses)
        if action == "preflight":
            prompt = payload.get("prompt")
            if not isinstance(prompt, str) or hashlib.sha256(prompt.encode()).hexdigest() != payload.get("prompt_sha256"):
                raise ValueError("physical prompt fingerprint mismatch")
            images, links = self._staged_images(binding, payload.get("attachments"))
            if row is not None:
                if row["worker"] != proof["worker"] or any(row[field] != payload.get(field)
                    for field in ("document_id", "identity_epoch", "prompt_sha256")):
                    raise PermissionError("Web preflight replay changed its physical identity")
                if links != self._attachment_links(cap, index):
                    raise PermissionError("Web preflight replay changed its attachments")
                self.web._authority(self.web._row(cap.owner, row["job_id"]))
                previous = self.web.status(cap.owner, row["job_id"])
                if previous["state"] != "READY" or previous["send_fence"]:
                    raise PermissionError("Web intent already advanced; reconcile instead of resending")
                return {"ok": True, "state": "READY", "request_id": row["job_id"], "account_verified": True,
                    "document_id": row["document_id"], "identity_epoch": row["identity_epoch"],
                    "prompt_sha256": row["prompt_sha256"], "submission_index": index, "idempotent_replay": True,
                    "attachments": len(links)}
            admitted = self.web.admit(cap.owner,
                request_identity=request_identity, submission_index=index, run_id=cap.run_id,
                operation_id=cap.operation_id, work_item_id=cap.work_item_id,
                principal_id=binding["principal_id"], grant_id=binding["grant_id"],
                workspace=self.control._run(cap.run_id, cap.owner)["workspace"],
                conversation_key=cap.conversation_uri, prompt=prompt,
                conversation_url=proof.get("conversation_url"), requested_model=payload.get("model"),
                requested_effort=payload.get("effort"), target_worker=proof["worker"], dispatch_mode="external",
                images=images)
            claimed = self.web.claim(cap.owner, admitted["job_id"], worker=proof["worker"])
            self.jobs.progress(admitted["job_id"], proof["worker"], claimed["lease_token"], "ready")
            with self.control.store.connect("session_checkpoint") as db:
                db.execute("INSERT OR IGNORE INTO gateway_web_submissions VALUES(?,?,?,?,?,?,?,?)",
                    (cap.token_hash, cap.operation_id, index, admitted["job_id"], proof["worker"],
                     payload["document_id"], payload["identity_epoch"], payload["prompt_sha256"]))
                for asset_id, sha256 in links:
                    db.execute("INSERT OR IGNORE INTO gateway_web_attachment_links VALUES(?,?,?,?,?)",
                        (cap.token_hash, cap.operation_id, index, asset_id, sha256))
            return {"ok": True, "state": "READY", "request_id": admitted["job_id"],
                    "account_verified": True, "document_id": payload["document_id"],
                    "identity_epoch": payload["identity_epoch"], "prompt_sha256": payload["prompt_sha256"],
                    "submission_index": index, "attachments": len(links)}
        if row is None or payload.get("request_id") != row["job_id"]:
            raise PermissionError("Web submission has no matching durable preflight")
        for field in ("document_id", "identity_epoch", "prompt_sha256"):
            if row[field] != payload.get(field):
                raise PermissionError("Web submission identity changed")
        # Lease tokens never travel to the model or Responses client.
        with self.jobs.lock:
            job = self.jobs.db.execute("SELECT lease FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
        if action == "sending":
            self.web.pre_send(cap.owner, row["job_id"], worker=row["worker"], lease_token=job[0],
                              resource_key=cap.physical_key, fencing_token=cap.physical_fence)
            return {"ok": True, "state": "SENDING", "request_id": row["job_id"],
                    "document_id": row["document_id"], "identity_epoch": row["identity_epoch"],
                    "prompt_sha256": row["prompt_sha256"], "submission_index": index}
        if action == "receipt":
            request_id = payload.get("observed_request_id")
            message_id = payload.get("message_id")
            if not isinstance(request_id, str) or not isinstance(message_id, str):
                raise PermissionError("receipt requires observed provider request/message identity")
            if proof.get("collector_kind") == "electron":
                expected = {"owner": cap.owner, "run_id": cap.run_id, "job_id": row["job_id"],
                    "worker": row["worker"], "identity_epoch": row["identity_epoch"], "role": "user",
                    "conversation_id": payload["conversation_id"], "message_id": message_id,
                    "request_id": request_id, "body_sha256": row["prompt_sha256"]}
                observed = self.message_attestor(**expected)
                if (not isinstance(observed, dict) or observed.get("authenticated") is not True
                        or any(observed.get(key) != value for key, value in expected.items())):
                    raise PermissionError("Web user message has no independent host observation")
            collector = {"extension_id": proof["extension_id"], "source_sha256": proof["source_sha256"],
                         "worker": row["worker"], "document_id": row["document_id"],
                         "identity_epoch": row["identity_epoch"]}
            evidence_service = self.control.browser_evidence
            host_collector = proof.get("collector_kind") == "electron"
            if host_collector:
                nonce = evidence_service.challenge_host(collector_id=collector["extension_id"],
                    source_sha256=collector["source_sha256"], surface_id=payload["surface_id"], worker=row["worker"],
                    document_id=row["document_id"], identity_epoch=row["identity_epoch"])["nonce"]
            else:
                nonce = evidence_service.challenge(**collector)["nonce"]
            observation = {"nonce": nonce, "document_id": row["document_id"], "identity_epoch": row["identity_epoch"],
                          "conversation_id": payload["conversation_id"], "route_conversation_id": payload["conversation_id"],
                          "state": "awaiting_approval" if proof["approval_state"] == "pending" else "idle",
                          "requests": [{"request_id": request_id, "message_id": message_id}]}
            if host_collector:
                evidence_service.observe_host(collector_id=collector["extension_id"],
                    source_sha256=collector["source_sha256"], surface_id=payload["surface_id"],
                    worker=row["worker"], evidence=observation)
            else:
                evidence_service.observe(extension_id=collector["extension_id"],
                    source_sha256=collector["source_sha256"], worker=row["worker"], evidence=observation)
            self.web.receipt(cap.owner, row["job_id"], worker=row["worker"], lease_token=job[0],
                evidence={"conversation_id": payload["conversation_id"], "message_id": message_id,
                          "prompt_sha256": row["prompt_sha256"], "images_attached": payload.get("images_attached", 0)},
                request_id=request_id, extension_id=collector["extension_id"],
                source_sha256=collector["source_sha256"], document_id=row["document_id"], identity_epoch=row["identity_epoch"])
            return {"ok": True, "state": "SENT", "request_id": row["job_id"], "message_id": message_id}
        if action == "answer":
            result = self.web.answer(cap.owner, row["job_id"], request_id=payload["observed_request_id"],
                worker=row["worker"], browser_principal=proof["browser_principal"],
                identity_epoch=row["identity_epoch"],
                conversation_id=payload["conversation_id"], message_id=payload["message_id"],
                revision=payload["revision"], body=payload["body"], complete=payload.get("complete") is True,
                parent_user_message_id=payload.get("parent_user_message_id"))
            from browser.streaming import StreamingLedger
            # The proven observation feeds the same snapshot ledger as the
            # binary relay. It remains presentation data, never a final receipt.
            try:
                StreamingLedger(self.control.store).record_frame(
                    principal=proof['browser_principal'], conversation_id=payload['conversation_id'],
                    message_id=payload['message_id'], revision=payload['revision'], text=payload['body'])
            except ValueError:
                pass  # Preview quota must not invalidate an already proved answer.
            return {**result, "ok": True}
        raise ValueError("unsupported Web browser event")

    def require_receipts(self, token):
        cap = self.authority._capability(token)
        if not cap.shared_run:
            return
        with self.control.store.connect("session_checkpoint") as db:
            rows = db.execute("SELECT job_id FROM gateway_web_submissions WHERE token_hash=?", (cap.token_hash,)).fetchall()
        if not rows:
            raise PermissionError("Web completion has no observed message receipt")
        for row in rows:
            if self.web.status(cap.owner, row["job_id"])["state"] != "ANSWERED":
                raise PermissionError("Web message remains unconfirmed; automatic resend prohibited")

    def delivery_view(self, token):
        cap = self.authority._capability(token)
        with self.control.store.connect("session_checkpoint") as db:
            rows = db.execute("SELECT job_id FROM gateway_web_submissions WHERE token_hash=? ORDER BY submission_index",
                              (cap.token_hash,)).fetchall()
        return {"transport": "durable_v2", "run_id": cap.run_id, "operation_id": cap.operation_id,
                "messages": [self.web.status(cap.owner, row["job_id"]) for row in rows],
                "automatic_resend": False}

    def close(self):
        if self._owns_jobs:
            self.jobs.close()
        if self._owns_context:
            self.control.context.close()
