"""Real SQLite Run/WorkItem/grant + browser outbox, including crash recovery."""
import hashlib

import pytest

from native_bridge.continuation_web import WebContinuation, WebContinuationConflict
from native_bridge.job_store import JobStore
from native_bridge.web_evidence_ingress import AuthenticatedWebReceiptBroker
from test_governance_coordination import _services


def setup(tmp_path):
    durable, context, control = _services(tmp_path)
    owner = "web-owner"
    run = durable.create_run(owner, workspace="web-lab")["run_id"]
    control.ensure_agent(run, owner, agent_id="web-agent", role="builder")
    durable.bind_chat(run, owner, agent_id="web-agent", provider="chatgpt",
                      conversation_id="source-chat-123", chat_id="logical-web-chat")
    work = control.create_work_item(run, owner, objective="Continue the same Run")
    checkpoint = control.write_session_checkpoint(
        owner, run_id=run, chat_id="logical-web-chat",
        source_instance_id="web-observer", source_epoch="epoch-1", source_seq=1,
        checkpoint={"summary": "Completed task A; continue task B."},
        cursor={"last_message_id": "msg-old-123"})
    relay = JobStore(tmp_path / "web-relay.sqlite3")
    adapter = WebContinuation(control, relay)
    params = dict(owner=owner, run_id=run, chat_id="logical-web-chat",
                  work_item_id=work["work_item_id"], principal_id="web-agent",
                  target_url="https://chatgpt.com/c/target-chat-123",
                  request_key="web-handoff-one",
                  summary="Completed task A; continue task B.",
                  operator_approved=True)
    return durable, context, control, relay, adapter, params


def grant(control, params):
    return control.authorization.grant(
        params["owner"], principal_type="agent", principal_id="web-agent",
        capability="web:send", scope_type="work_item",
        scope_id=params["work_item_id"], conditions={"provider": "chatgpt"})


def attest_collector(control, relay, params, *, worker, job_id, receipt, request_id):
    """Fixture registers and observes a nonce-bound collector; not an E2E Web claim."""
    extension_id = "a" * 32
    build = "1" * 64
    browser_principal = "local-operator"
    control.browser_evidence.configure(
        extension_id=extension_id,principal=browser_principal,
        workspace="web-lab",source_sha256=build,
        enabled=True,expected_revision=0)
    document_id="browser-doc-12345"
    nonce=control.browser_evidence.challenge(
        extension_id=extension_id,source_sha256=build,
        worker=worker,document_id=document_id)["nonce"]
    conversation=receipt["conversation_id"]
    control.browser_evidence.observe(
        extension_id=extension_id,source_sha256=build,worker=worker,
        evidence={"nonce":nonce,"document_id":document_id,
                  "conversation_id":conversation,
                  "route_conversation_id":conversation,"state":"idle",
                  "requests":[{"request_id":request_id,
                               "message_id":receipt["message_id"]}]})
    return AuthenticatedWebReceiptBroker(control,relay).attest_existing(
        params["owner"],run_id=params["run_id"],job_id=job_id,
        browser_principal=browser_principal,request_id=request_id,
        worker=worker,evidence=receipt)


def test_web_handoff_requires_real_grant_and_exact_message_receipt(tmp_path):
    durable, context, control, relay, adapter, p = setup(tmp_path)
    try:
        with pytest.raises(PermissionError):
            adapter.stage(**p)
        g = grant(control, p)
        with pytest.raises(PermissionError):
            adapter.stage(**{**p, "operator_approved": False})
        stage = adapter.stage(**p)
        assert stage["delivery"]["state"] == "not_sent"
        assert stage["core_state"] == "PREPARED"
        assert stage["target_receipt_exact"] is False
        assert stage["collector_message_attested"] is False
        assert adapter.stage(**p)["continuation_id"] == stage["continuation_id"]
        assert relay.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        with pytest.raises(WebContinuationConflict, match="receipt"):
            adapter.commit(p["owner"], stage["continuation_id"], operator_approved=True)
        work_before = control.work_item_info(p["work_item_id"], p["owner"])
        claimed = relay.poll("TAB-123")
        assert claimed and claimed["kind"] == "CHAT_SEND"
        relay.progress(claimed["job_id"], "TAB-123", claimed["lease_token"], "sending")
        receipt = {"conversation_id": "target-chat-123", "message_id": "message-12345",
                   "prompt_sha256": hashlib.sha256(claimed["prompt"].encode()).hexdigest(),
                   "images_attached": 0}
        with pytest.raises(ValueError, match="mismatch"):
            relay.delivery_receipt(claimed["job_id"], "TAB-123",
                                   claimed["lease_token"],
                                   {**receipt, "conversation_id": "other-chat-123"})
        relay.delivery_receipt(claimed["job_id"], "TAB-123",
                               claimed["lease_token"], receipt)
        assert adapter.status(p["owner"], stage["continuation_id"])["target_receipt_exact"]
        with pytest.raises(PermissionError,match="proof missing"):
            adapter.commit(p["owner"],stage["continuation_id"],operator_approved=True)
        attest_collector(control,relay,p,worker="TAB-123",job_id=claimed["job_id"],
                         receipt=receipt,request_id="request-12345")
        assert adapter.status(p["owner"], stage["continuation_id"])["collector_message_attested"]
        assert adapter.status(p["owner"], stage["continuation_id"])["account_identity_attested"] is False
        done = adapter.commit(p["owner"], stage["continuation_id"],
                              operator_approved=True)
        assert done["stage"] == "PUBLISHED" and done["core_state"] == "COMMITTED"
        assert done["message_id"] == "message-12345"
        assert adapter.commit(p["owner"], stage["continuation_id"],
                              operator_approved=True)["stage"] == "PUBLISHED"
        chat = next(c for c in durable.run_status(p["run_id"], p["owner"])["chats"]
                    if c["chat_id"] == p["chat_id"])
        assert chat["conversation_id"] == "target-chat-123"
        assert chat["agent_id"] == "web-agent"
        assert control.work_item_info(p["work_item_id"], p["owner"]) == work_before
        assert control.authorization.info(g["grant_id"], p["owner"])["revoked"] is False
        assert relay.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    finally:
        relay.db.close()
        context.close()
        durable.close()


def test_web_handoff_crash_restart_and_uncertain_no_second_send(tmp_path):
    durable, context, control, relay, adapter, p = setup(tmp_path)
    grant(control, p)
    stage = adapter.stage(**p)
    job = relay.poll("web-worker-321")
    relay.progress(job["job_id"], "web-worker-321", job["lease_token"], "sending")
    ident = stage["continuation_id"]
    relay.db.close()
    context.close()
    durable.close()
    restarted_durable, restarted_context, restarted = _services(tmp_path)
    reopened_relay = JobStore(tmp_path / "web-relay.sqlite3")
    recovered = WebContinuation(restarted, reopened_relay)
    try:
        assert recovered.reconcile(p["owner"], ident)["automatic_retry"] is False
        assert recovered.reconcile(p["owner"], ident)["delivery"]["state"] == "pending"
        assert recovered.stage(**p)["continuation_id"] == ident
        assert reopened_relay.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        with pytest.raises(WebContinuationConflict, match="receipt"):
            recovered.commit(p["owner"], ident, operator_approved=True)
        reopened_relay.delivery.uncertain(job["job_id"])
        reopened_relay.db.commit()
        uncertain = recovered.reconcile(p["owner"], ident)
        assert uncertain["delivery"]["state"] == "unconfirmed"
        assert uncertain["requires_operator_reconciliation"] is True
        assert uncertain["automatic_retry"] is False
        with pytest.raises(WebContinuationConflict, match="reconciliation"):
            recovered.stage(**p)
        assert reopened_relay.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert next(c for c in restarted_durable.run_status(
            p["run_id"], p["owner"])["chats"] if c["chat_id"] == p["chat_id"]
        )["conversation_id"] == "source-chat-123"
    finally:
        reopened_relay.db.close()
        restarted_context.close()
        restarted_durable.close()


def test_web_handoff_stale_checkpoint_revoke_and_foreign_work_item(tmp_path):
    durable, context, control, relay, adapter, p = setup(tmp_path)
    try:
        g = grant(control, p)
        stage = adapter.stage(**p)
        control.authorization.revoke(g["grant_id"], p["owner"])
        with pytest.raises(PermissionError):
            adapter.commit(p["owner"], stage["continuation_id"],
                           operator_approved=True)
        control.write_session_checkpoint(
            p["owner"], run_id=p["run_id"], chat_id=p["chat_id"],
            source_instance_id="web-observer", source_epoch="epoch-1", source_seq=2,
            checkpoint={"summary": "Newer state"}, cursor={})
        with pytest.raises(WebContinuationConflict):
            adapter.stage(**p)
        with pytest.raises(FileNotFoundError):
            adapter.status("foreign-owner", stage["continuation_id"])
    finally:
        relay.db.close()
        context.close()
        durable.close()


def test_new_web_target_allocation_claim_commit_and_no_second_browser_send(tmp_path):
    durable,context,control,relay,adapter,p = setup(tmp_path)
    try:
        grant(control,p)
        allocate = {k:p[k] for k in ("owner","run_id","chat_id","work_item_id",
                                      "principal_id","request_key","summary",
                                      "operator_approved")}
        started = adapter.allocate_new_target(**allocate)
        assert started["delivery_state"]=="not_sent"
        assert adapter.allocate_new_target(**allocate)["allocation_id"] == started["allocation_id"]
        assert relay.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        with pytest.raises(WebContinuationConflict,match="receipt"):
            adapter.claim_new_target(p["owner"],started["allocation_id"])
        job=relay.poll("TAB-456")
        assert job["kind"]=="CHAT_START" and job["new_chat"] is True
        relay.progress(job["job_id"],"TAB-456",job["lease_token"],"sending")
        receipt={"conversation_id":"created-chat-45678","message_id":"created-message-56789",
                 "prompt_sha256":hashlib.sha256(job["prompt"].encode()).hexdigest(),
                 "images_attached":0}
        relay.delivery_receipt(job["job_id"],"TAB-456",job["lease_token"],receipt)
        with pytest.raises(PermissionError,match="proof missing"):
            adapter.claim_new_target(p["owner"],started["allocation_id"])
        attest_collector(control,relay,p,worker="TAB-456",job_id=job["job_id"],
                         receipt=receipt,request_id="request-45678")
        assert adapter.target_status(p["owner"],started["allocation_id"])["collector_message_attested"]
        preflight=adapter.claim_new_target(p["owner"],started["allocation_id"])
        assert preflight["target_receipt_exact"] is True
        assert preflight["message_id"]=="created-message-56789"
        claimed_again=adapter.claim_new_target(p["owner"],started["allocation_id"])
        assert claimed_again["continuation_id"]==preflight["continuation_id"]
        committed=adapter.commit(p["owner"],preflight["continuation_id"],
                                 operator_approved=True)
        assert committed["stage"]=="PUBLISHED"
        assert adapter.target_status(p["owner"],started["allocation_id"])["state"]=="PUBLISHED"
        assert next(c for c in durable.run_status(p["run_id"],p["owner"])["chats"]
                    if c["chat_id"]==p["chat_id"])["conversation_id"]=="created-chat-45678"
        assert relay.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    finally:
        relay.db.close();context.close();durable.close()


def test_created_web_target_crash_uncertain_without_replay(tmp_path):
    durable,context,control,relay,adapter,p=setup(tmp_path)
    grant(control,p)
    alloc={k:p[k] for k in ("owner","run_id","chat_id","work_item_id",
                            "principal_id","request_key","summary",
                            "operator_approved")}
    first=adapter.allocate_new_target(**alloc)
    leased=relay.poll("new-chat-worker-777")
    relay.progress(leased["job_id"],"new-chat-worker-777",
                   leased["lease_token"],"sending")
    relay.db.close();context.close();durable.close()
    reopened_durable,reopened_context,reopened=_services(tmp_path)
    jobs=JobStore(tmp_path/"web-relay.sqlite3")
    recovered=WebContinuation(reopened,jobs)
    try:
        assert recovered.target_status(p["owner"],first["allocation_id"])["delivery_state"]=="pending"
        jobs.delivery.uncertain(leased["job_id"])
        jobs.db.commit()
        assert recovered.target_status(p["owner"],first["allocation_id"])["delivery_state"]=="unconfirmed"
        with pytest.raises(WebContinuationConflict,match="no retry"):
            recovered.allocate_new_target(**alloc)
        with pytest.raises(WebContinuationConflict,match="receipt"):
            recovered.claim_new_target(p["owner"],first["allocation_id"])
        assert jobs.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]==1
        assert next(c for c in reopened_durable.run_status(p["run_id"],p["owner"])["chats"]
                    if c["chat_id"]==p["chat_id"])["conversation_id"]=="source-chat-123"
    finally:
        jobs.db.close();reopened_context.close();reopened_durable.close()
