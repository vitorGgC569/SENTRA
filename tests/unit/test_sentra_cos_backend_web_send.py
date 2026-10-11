"""Existing authority + SQLite/OS crypto. Browser observations are fixtures."""
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from native_bridge.job_store import JobStore
from native_bridge.protocol import ChatJob
from native_bridge.web_send import WebSendAuthority, WebSendConflict
from native_bridge.web_evidence_ingress import WebReceiptAttestationError
from test_governance_coordination import _services


OWNER = "backend-test-owner"
WORKER = "TAB-713"
EXT = "a" * 32
SOURCE = "b" * 64
DOC = "document-backend-713"
EPOCH = "epoch-backend-713"
REQUEST = "provider-request-713"
USER = "provider-user-msg-713"
CHAT = "backend-chat-713"


@pytest.fixture
def backend(tmp_path):
    d, c, control = _services(tmp_path)
    now = [1000.0]
    d.clock = lambda: now[0]
    run = d.create_run(OWNER, workspace=str(tmp_path))["run_id"]
    control.ensure_agent(run, OWNER, agent_id="backend-agent", role="builder")
    item = control.create_work_item(run, OWNER, objective="Web test", assignee_agent_id="backend-agent")
    operation = d.create_operation(run, OWNER, kind="chatgpt-web-turn", initial_state="RUNNING", idempotency_key="web-turn-713")
    grant = control.authorization.grant(OWNER, principal_type="agent", principal_id="backend-agent",
                                        capability="web:send", scope_type="work_item", scope_id=item["work_item_id"])
    jobs = JobStore(tmp_path / "relay.sqlite3", clock=lambda: now[0])
    api = WebSendAuthority(control, jobs)
    params = dict(request_identity='{"thread_id":"backend","turn_id":"713"}', run_id=run,
                  operation_id=operation["operation_id"], work_item_id=item["work_item_id"],
                  principal_id="backend-agent", grant_id=grant["grant_id"], workspace=str(tmp_path),
                  conversation_key="conversation://backend", prompt="physical backend prompt",
                  conversation_url="https://chatgpt.com/c/" + CHAT, target_worker=WORKER,
                  requested_model="gpt-6", requested_effort="high")
    yield d, c, control, jobs, api, params, now
    jobs.close()
    c.close()
    d.close()


def lease(d, params, worker=WORKER):
    return d.acquire_lease(params["run_id"], OWNER, "browser-tab:" + worker,
                           operation_id=params["operation_id"], ttl_s=120)


def start(backend):
    d, _, _, jobs, api, p, _ = backend
    admitted = api.admit(OWNER, **p)
    claim = api.claim(OWNER, admitted["job_id"], worker=WORKER)
    authority = lease(d, p)
    args = dict(worker=WORKER, lease_token=claim["lease_token"], resource_key=authority["resource_key"],
                fencing_token=authority["fencing_token"])
    api.pre_send(OWNER, admitted["job_id"], **args)
    return admitted["job_id"], claim, args


def observe(control, *, message=USER, request=REQUEST, state="idle"):
    with control.store.connect("chat_access") as db:
        registered = db.execute("SELECT 1 FROM browser_collectors WHERE extension_id=?", (EXT,)).fetchone()
    if not registered:
        control.browser_evidence.configure(extension_id=EXT, principal="local-operator",
            workspace=control.durable.run_status(
                control.durable.list_runs(OWNER)["items"][0]["run_id"], OWNER)["workspace"],
            source_sha256=SOURCE, enabled=True, expected_revision=0)
    challenge = control.browser_evidence.challenge(extension_id=EXT, source_sha256=SOURCE,
        worker=WORKER, document_id=DOC, identity_epoch=EPOCH)
    control.browser_evidence.observe(extension_id=EXT, source_sha256=SOURCE, worker=WORKER,
        evidence={"nonce": challenge["nonce"], "document_id": DOC, "identity_epoch": EPOCH,
                  "conversation_id": CHAT, "route_conversation_id": CHAT, "state": state,
                  "requests": [{"request_id": request, "message_id": message}]})


def receipt_args(claim):
    return dict(worker=WORKER, lease_token=claim["lease_token"],
                evidence={"conversation_id": CHAT, "message_id": USER,
                          "prompt_sha256": hashlib.sha256(claim["prompt"].encode()).hexdigest(), "images_attached": 0},
                request_id=REQUEST, extension_id=EXT, source_sha256=SOURCE, document_id=DOC, identity_epoch=EPOCH)


def test_stage_responses_encrypted_and_no_new_authority(backend):
    d, _, control, jobs, api, p, _ = backend
    payload = {"input": "PRIVATE_RESPONSES_SENTINEL", "model": "gpt-6"}
    args = {key: p[key] for key in ("request_identity", "run_id", "operation_id")}
    result = api.stage_request(OWNER, payload=payload, **args)
    assert api.request_payload(OWNER, result["request_id"]) == payload
    assert api.stage_request(OWNER, payload=payload, **args)["replayed"]
    with control.store.connect("session_checkpoint") as db:
        protected = db.execute("SELECT protected_payload FROM web_response_requests").fetchone()[0]
        assert protected.startswith(("dpapi:", "keyring:"))
    assert b"PRIVATE_RESPONSES_SENTINEL" not in control.store.path_for("session_checkpoint").read_bytes()
    assert jobs.counts()["submitted"] == 0
    assert len(d.list_runs(OWNER)["items"]) == 1
    assert len(d.list_operations(p["run_id"], OWNER)["items"]) == 1
    with pytest.raises(WebSendConflict):
        api.stage_request(OWNER, payload={"input": "changed"}, **args)
    with pytest.raises(FileNotFoundError):
        api.request_payload("another-owner", result["request_id"])


def test_admission_crash_gap_and_fingerprint_conflict(backend, monkeypatch):
    _, _, control, jobs, api, p, _ = backend
    submit = jobs.submit
    monkeypatch.setattr(jobs, "submit", lambda job: (_ for _ in ()).throw(SystemExit("crash before insert")))
    with pytest.raises(SystemExit):
        api.admit(OWNER, **p)
    with control.store.connect("session_checkpoint") as db:
        job_id = db.execute("SELECT job_id FROM web_send_intents").fetchone()[0]
    assert api.status(OWNER, job_id)["admission_recovery_required"]
    monkeypatch.setattr(jobs, "submit", submit)
    assert WebSendAuthority(control, jobs).admit(OWNER, **p)["job_id"] == job_id
    assert jobs.counts()["submitted"] == 1
    with pytest.raises(WebSendConflict):
        api.admit(OWNER, **{**p, "requested_effort": "medium"})
    assert jobs.poll("TAB-999") is None  # external mode cannot be consumed by MV3


def test_concurrent_admission_two_sqlite_instances_one_job(backend):
    d, _, control, jobs, api, p, now = backend
    jobs2 = JobStore(jobs.db.execute("PRAGMA database_list").fetchone()[2], clock=lambda: now[0])
    api2 = WebSendAuthority(control, jobs2)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda n: (api if n % 2 else api2).admit(OWNER, **p), range(16)))
        assert len({r["job_id"] for r in results}) == 1
        assert jobs.counts()["submitted"] == 1
        assert len(d.list_operations(p["run_id"], OWNER)["items"]) == 1
        with control.store.connect("session_checkpoint") as db:
            assert db.execute("SELECT count(*) FROM web_send_intents").fetchone()[0] == 1
    finally:
        jobs2.close()


def test_two_sqlite_connections_poll_cannot_claim_same_queued_job(tmp_path):
    first, second = JobStore(tmp_path / "relay.sqlite3"), JobStore(tmp_path / "relay.sqlite3")
    try:
        first.submit(ChatJob(task_id="race-job", prompt="relay message"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda args: args[0].poll(args[1]), [(first, "TAB-1"), (second, "TAB-2")]))
        assert sum(claim is not None for claim in claims) == 1
    finally:
        first.close(); second.close()


def test_pre_send_single_use_fence_and_same_conversation_busy(backend):
    d, _, _, jobs, api, p, _ = backend
    job_id, claim, args = start(backend)
    with pytest.raises(WebSendConflict, match="already consumed"):
        api.pre_send(OWNER, job_id, **args)
    second = api.admit(OWNER, **{**p, "request_identity": "second-physical-request", "target_worker": "TAB-714"})
    other = api.claim(OWNER, second["job_id"], worker="TAB-714")
    with pytest.raises(WebSendConflict, match="active send"):
        api.pre_send(OWNER, second["job_id"], **{**args, "worker": "TAB-714", "lease_token": other["lease_token"]})
    assert api.status(OWNER, second["job_id"])["send_fence"] == 0
    assert jobs.delivery_status(job_id)["state"] == "pending"
    assert d.operation_status(p["operation_id"], OWNER)["progress"]["web_send_fence"] == 1


def test_crash_after_central_fence_before_job_progress_never_replays(backend, monkeypatch):
    d, _, control, jobs, api, p, _ = backend
    job_id = api.admit(OWNER, **p)["job_id"]
    claim = api.claim(OWNER, job_id, worker=WORKER)
    central = lease(d, p)
    monkeypatch.setattr(JobStore, "progress", lambda *args, **kw: (_ for _ in ()).throw(SystemExit("power cut")))
    with pytest.raises(SystemExit):
        api.pre_send(OWNER, job_id, worker=WORKER, lease_token=claim["lease_token"],
                     resource_key=central["resource_key"], fencing_token=central["fencing_token"])
    recovered = WebSendAuthority(control, jobs)
    assert recovered.status(OWNER, job_id)["state"] == "UNCONFIRMED"
    assert recovered.admit(OWNER, **p)["job_id"] == job_id
    with pytest.raises(WebSendConflict):
        recovered.claim(OWNER, job_id, worker=WORKER)
    assert jobs.counts()["submitted"] == 1


def test_original_grant_and_foreign_fence_rejected_before_send(backend):
    d, _, control, jobs, api, p, _ = backend
    job_id = api.admit(OWNER, **p)["job_id"]
    claim = api.claim(OWNER, job_id, worker=WORKER)
    another = d.create_operation(p["run_id"], OWNER, kind="other", initial_state="RUNNING", idempotency_key="foreign-op")
    foreign = d.acquire_lease(p["run_id"], OWNER, "other-resource", operation_id=another["operation_id"], ttl_s=120)
    with pytest.raises(PermissionError, match="does not belong"):
        api.pre_send(OWNER, job_id, worker=WORKER, lease_token=claim["lease_token"],
                     resource_key="other-resource", fencing_token=foreign["fencing_token"])
    control.authorization.revoke(p["grant_id"], OWNER)
    control.authorization.grant(OWNER, principal_type="agent", principal_id=p["principal_id"], capability="web:send",
                                 scope_type="work_item", scope_id=p["work_item_id"])
    with pytest.raises(PermissionError, match="revoked or replaced"):
        api.claim(OWNER, job_id, worker=WORKER)
    assert jobs.delivery_status(job_id)["state"] == "not_sent"


def test_late_receipt_after_expiry_restart_no_resend_and_partial_not_final(backend):
    _, _, control, jobs, api, p, now = backend
    job_id, claim, _ = start(backend)
    now[0] += 181
    assert api.status(OWNER, job_id)["state"] == "UNCONFIRMED"
    observe(control)
    repaired = WebSendAuthority(control, jobs)
    assert repaired.receipt(OWNER, job_id, **receipt_args(claim))["state"] == "SENT"
    assert jobs.poll(WORKER) is None
    args = dict(request_id=REQUEST, worker=WORKER, browser_principal="local-operator", conversation_id=CHAT,
                message_id="assistant-message-713", parent_user_message_id=USER, revision=1,
                body="partial answer", identity_epoch=EPOCH)
    with pytest.raises(WebReceiptAttestationError, match="unavailable"):
        repaired.answer(OWNER, job_id, **args)
    # Trusted callback is explicitly a hermetic fixture, not proof of a real account.
    repaired.assistant_attestor = lambda **expected: {**expected, "authenticated": True}
    assert repaired.answer(OWNER, job_id, **args)["state"] == "ANSWERING"
    reconcile = {k: v for k, v in receipt_args(claim).items() if k not in {"evidence", "lease_token"}}
    assert repaired.reconcile(OWNER, job_id, **reconcile)["state"] == "ANSWERING"
    assert repaired.answer(OWNER, job_id, **{**args, "revision": 2, "body": "final answer", "complete": True})["state"] == "ANSWERED"
    assert repaired.receipt(OWNER, job_id, **receipt_args(claim))["state"] == "ANSWERED"
    assert jobs.counts()["submitted"] == 1
    with pytest.raises(WebSendConflict):
        repaired.answer(OWNER, job_id, **{**args, "revision": 3})
    with control.store.connect("chat_access") as db:
        assert db.execute("SELECT count(*) FROM browser_request_messages WHERE request_id=?", (REQUEST,)).fetchone()[0] == 1


def test_receipt_attestation_crash_gap_reconciles_without_submit(backend, monkeypatch):
    _, _, control, jobs, api, _, _ = backend
    job_id, claim, _ = start(backend)
    observe(control)
    original = api.receipts.attest_existing
    monkeypatch.setattr(api.receipts, "attest_existing", lambda *a, **kw: (_ for _ in ()).throw(SystemExit("central receipt gap")))
    with pytest.raises(SystemExit):
        api.receipt(OWNER, job_id, **receipt_args(claim))
    assert jobs.delivery_status(job_id)["state"] == "sent"
    monkeypatch.setattr(api.receipts, "attest_existing", original)
    args = {k: v for k, v in receipt_args(claim).items() if k not in {"evidence", "lease_token"}}
    assert api.reconcile(OWNER, job_id, **args)["state"] == "SENT"
    assert jobs.counts()["submitted"] == 1


@pytest.mark.parametrize("fenced", [False, True])
def test_failure_is_durable_and_never_requeues(backend, fenced):
    _, _, control, jobs, api, p, _ = backend
    job_id = start(backend)[0] if fenced else api.admit(OWNER, **p)["job_id"]
    result = api.failure(OWNER, job_id, reason="browser disconnected")
    assert result["state"] == ("UNCONFIRMED" if fenced else "FAILED")
    assert WebSendAuthority(control, jobs).status(OWNER, job_id)["state"] == result["state"]
    assert jobs.poll(WORKER) is None
    with pytest.raises(WebSendConflict):
        api.claim(OWNER, job_id, worker=WORKER)


def test_two_physical_indices_same_responses_operation(backend):
    _, _, control, jobs, api, p, _ = backend
    one = api.admit(OWNER, **p)
    two = api.admit(OWNER, **{**p, "submission_index": 1, "prompt": "multipart second physical text"})
    assert one["job_id"] != two["job_id"] and one["operation_id"] == two["operation_id"]
    assert api.admit(OWNER, **p)["job_id"] == one["job_id"]
    assert jobs.counts()["submitted"] == 2


def test_full_store_restart_preserves_send_fence_and_receipt(backend, tmp_path):
    d, c, control, jobs, api, params, now = backend
    staged = api.stage_request(OWNER, **{k: params[k] for k in ("request_identity", "run_id", "operation_id")},
                               payload={"input": "restart-protected-payload"})
    job_id, claim, _ = start(backend)
    now[0] += 181
    assert api.status(OWNER, job_id)["state"] == "UNCONFIRMED"
    jobs.close(); c.close(); d.close()
    d2, c2, control2 = _services(tmp_path)
    d2.clock = lambda: now[0]
    jobs2 = JobStore(tmp_path / "relay.sqlite3", clock=lambda: now[0])
    try:
        recovered = WebSendAuthority(control2, jobs2)
        assert recovered.request_payload(OWNER, staged["request_id"])["input"] == "restart-protected-payload"
        assert recovered.status(OWNER, job_id)["state"] == "UNCONFIRMED"
        assert recovered.admit(OWNER, **params)["job_id"] == job_id
        with pytest.raises(WebSendConflict):
            recovered.claim(OWNER, job_id, worker=WORKER)
        observe(control2)
        assert recovered.receipt(OWNER, job_id, **receipt_args(claim))["state"] == "SENT"
        assert jobs2.poll(WORKER) is None and jobs2.counts()["submitted"] == 1
        assert len(d2.list_runs(OWNER)["items"]) == 1
        assert len(d2.list_operations(params["run_id"], OWNER)["items"]) == 1
    finally:
        jobs2.close(); c2.close(); d2.close()


def test_http_relay_routes_admitted_send_with_single_use_pre_send_ack(backend, tmp_path):
    from native_bridge.relay import RelayServer
    from test_sentra_cos_web_relay_authenticated_routes import post
    d, _, control, _, _, params, now = backend
    server = RelayServer(port=0, db_path=tmp_path / "relay.sqlite3", authenticated_control=control).start()
    server.state.clock = lambda: now[0]
    server.state.extension_version = lambda: {"source_hash": SOURCE, "version": "test"}
    api = server.state.web_send
    try:
        observe(control)
        job_id = api.admit(OWNER, **{**params, "dispatch_mode": "relay"})["job_id"]
        claim = server.state.poll(WORKER)
        assert claim["job_id"] == job_id
        lease(d, params)
        progress = {"job_id": job_id, "worker": WORKER, "lease_token": claim["lease_token"], "phase": "sending"}
        code, acknowledged = post(server, "/jobs/progress", progress)
        assert code == 200 and acknowledged["send_fence"] == 1
        code, blocked = post(server, "/jobs/progress", progress)
        assert code == 409 and blocked["automatic_resend"] is False
        body = {"job_id": job_id, **receipt_args(claim)}
        body.pop("extension_id")  # extension identity comes from authenticated Origin
        code, result = post(server, "/jobs/delivery-receipt", body)
        assert code == 200 and result["state"] == "attested"
        assert api.status(OWNER, job_id)["state"] == "SENT"
        assert server.state.counts()["submitted"] == 1
    finally:
        server.stop()


def test_answer_parent_and_host_content_proof_cannot_be_forged(backend):
    _, _, control, jobs, api, _, _ = backend
    job_id, claim, _ = start(backend)
    observe(control)
    api.receipt(OWNER, job_id, **receipt_args(claim))
    args = dict(request_id=REQUEST, worker=WORKER, browser_principal="local-operator", conversation_id=CHAT,
                message_id="assistant-message-713", revision=1, body="host observed body", identity_epoch=EPOCH, complete=True)
    with pytest.raises(WebReceiptAttestationError, match="unavailable"):
        api.answer(OWNER, job_id, **args)  # omitting parent never bypasses host observation
    api.assistant_attestor = lambda **expected: {**expected, "body_sha256": "0" * 64, "authenticated": True}
    with pytest.raises(WebReceiptAttestationError, match="does not match"):
        api.answer(OWNER, job_id, **args)
    api.assistant_attestor = lambda **expected: {**expected, "authenticated": True}
    with pytest.raises(PermissionError, match="parent differs"):
        api.answer(OWNER, job_id, **args, parent_user_message_id="other-user")
    assert api.status(OWNER, job_id)["state"] == "SENT"
    assert api.answer(OWNER, job_id, **args)["state"] == "ANSWERED"


def test_relay_allocation_receipt_replay_after_claim_has_one_binding(tmp_path):
    from test_sentra_cos_web_relay_authenticated_routes import configure, enroll_http, post, envelope, cleanup
    from test_sentra_cos_web_continuation_receipts import grant
    d, c, control, server, continuity, params = configure(tmp_path)
    try:
        grant(control, params)
        allocated = continuity.allocate_new_target(**{k: v for k, v in params.items() if k != "target_url"})
        claim = server.state.poll("TAB-337")
        server.state.progress(claim["job_id"], "TAB-337", claim["lease_token"], "sending")
        receipt = {"conversation_id": "created-chat-33777", "message_id": "created-message-33777",
                   "prompt_sha256": hashlib.sha256(claim["prompt"].encode()).hexdigest(), "images_attached": 0}
        enroll_http(server, control, worker="TAB-337", conversation=receipt["conversation_id"], message=receipt["message_id"])
        body = envelope(claim, receipt)
        assert post(server, "/jobs/delivery-receipt", body)[0] == 200
        prepared = continuity.claim_new_target(params["owner"], allocated["allocation_id"])
        # Transfer and allocation now legitimately reference the SAME job.
        # Their duplicate mapping is one authority, not two conflicting sends.
        assert post(server, "/jobs/delivery-receipt", body)[0] == 200
        assert continuity.status(params["owner"], prepared["continuation_id"])["collector_message_attested"]
        assert server.state.counts()["submitted"] == 1
    finally:
        cleanup(server, c, d)


def test_compact_relay_rechecks_original_grant_before_poll_and_pre_send(tmp_path):
    from test_sentra_cos_web_relay_authenticated_routes import configure, cleanup
    from test_sentra_cos_web_continuation_receipts import grant
    d, c, control, server, continuity, params = configure(tmp_path)
    try:
        original = grant(control, params)
        allocated = continuity.allocate_new_target(**{k: v for k, v in params.items() if k != "target_url"})
        claimed = server.state.poll("TAB-337")
        control.authorization.revoke(original["grant_id"], params["owner"])
        grant(control, params)
        with pytest.raises(PermissionError, match="revoked or replaced"):
            server.state.progress(claimed["job_id"], "TAB-337", claimed["lease_token"], "sending")
        assert server.state.delivery_status(allocated["job_id"])["state"] == "not_sent"
        with server.state.lock:
            server.state.db.execute("UPDATE jobs SET state='QUEUED',worker='' WHERE id=?", (claimed["job_id"],))
            server.state.db.commit()
        assert server.state.poll("TAB-338") is None
    finally:
        cleanup(server, c, d)


def test_final_answer_releases_only_original_job_and_recovers_ack_crash(backend, monkeypatch):
    _, _, control, jobs, api, p, _ = backend
    job_id, claim, _ = start(backend)
    observe(control)
    api.receipt(OWNER, job_id, **receipt_args(claim))
    assert jobs.counts()["leased"] == 1
    api.assistant_attestor = lambda **expected: {**expected, "authenticated": True}
    args = dict(request_id=REQUEST, worker=WORKER, browser_principal="local-operator", conversation_id=CHAT,
                message_id="assistant-final-713", revision=1, body="partial real text", identity_epoch=EPOCH)
    api.answer(OWNER, job_id, **args)
    assert jobs.counts()["leased"] == 1 and jobs.result(job_id) is None
    original = jobs._complete_attested_answer
    monkeypatch.setattr(jobs, "_complete_attested_answer", lambda *a, **kw: (_ for _ in ()).throw(SystemExit("final to ACK gap")))
    with pytest.raises(SystemExit):
        api.answer(OWNER, job_id, **{**args, "revision": 2, "body": "PRIVATE_AUTHENTICATED_FINAL", "complete": True})
    with control.store.connect("session_checkpoint") as db:
        assert db.execute("SELECT stage FROM web_send_intents WHERE job_id=?", (job_id,)).fetchone()[0] == "ANSWERED"
    assert jobs.counts()["leased"] == 1
    monkeypatch.setattr(jobs, "_complete_attested_answer", original)
    reconcile = {k: v for k, v in receipt_args(claim).items() if k not in {"evidence", "lease_token"}}
    recovered = api.reconcile(OWNER, job_id, **reconcile)
    assert recovered["state"] == "ANSWERED" and recovered["answer_revision"] == 2
    assert jobs.counts()["leased"] == 0
    assert jobs.result(job_id)["result"] == "PRIVATE_AUTHENTICATED_FINAL"
    raw = jobs.db.execute("SELECT result,ack FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert raw[0].startswith(("dpapi:", "keyring:")) and raw[1] == 1
    assert "PRIVATE_AUTHENTICATED_FINAL" not in raw[0]
    assert api.status(OWNER, job_id)["state"] == "ANSWERED"  # repeat recovery is idempotent
    second = api.admit(OWNER, **{**p, "submission_index": 1, "prompt": "next physical exact prompt"})
    assert api.claim(OWNER, second["job_id"], worker=WORKER)["job_id"] == second["job_id"]


def test_oversized_exact_physical_prompt_denied_without_job_or_send(backend):
    _, _, control, jobs, api, p, _ = backend
    with pytest.raises(ValueError, match="max 20000"):
        api.admit(OWNER, **{**p, "prompt": "X" * 20001})
    assert jobs.counts()["submitted"] == 0
    with control.store.connect("session_checkpoint") as db:
        assert db.execute("SELECT count(*) FROM web_send_intents").fetchone()[0] == 0
