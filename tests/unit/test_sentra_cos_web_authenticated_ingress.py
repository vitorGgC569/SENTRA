"""SQLite-backed browser document/worker binding, no implied account E2E."""
import hashlib

import pytest

from native_bridge.job_store import JobStore
from native_bridge.web_evidence_ingress import (
    AuthenticatedWebReceiptBroker, AuthenticatedWebFrameIngress,
    WebReceiptAttestationError)
from sentra_mcp.services.web_history_store import WebHistoryStore, WebHistoryConflict
from test_sentra_cos_web_continuation_receipts import setup, grant
from test_governance_coordination import _services


def enroll(control, *, worker, conversation, message_id,
           request_id="metadata-request-1234", state="idle"):
    args=dict(extension_id="a"*32,source_sha256="1"*64,worker=worker)
    control.browser_evidence.configure(
        extension_id=args["extension_id"], principal="local-operator",
        workspace="web-lab",source_sha256=args["source_sha256"],
        enabled=True,expected_revision=0)
    document_id="browser-doc-12345"
    nonce=control.browser_evidence.challenge(
        **args,document_id=document_id)["nonce"]
    control.browser_evidence.observe(
        **args,evidence={
            "nonce":nonce,"document_id":document_id,
            "conversation_id":conversation,"route_conversation_id":conversation,
            "state":state,
            "requests":[{"request_id":request_id,"message_id":message_id}]})
    return request_id


def test_authenticated_ingress_rejects_wrong_worker_message_and_revocation(tmp_path):
    durable,context,control,relay,adapter,p=setup(tmp_path)
    try:
        grant(control,p)
        staged=adapter.stage(**p)
        leased=relay.poll("TAB-125")
        relay.progress(leased["job_id"],"TAB-125",leased["lease_token"],"sending")
        receipt={"conversation_id":"target-chat-123","message_id":"message-12567",
                 "prompt_sha256":hashlib.sha256(leased["prompt"].encode()).hexdigest(),
                 "images_attached":0}
        req=enroll(control,worker="TAB-125",conversation=receipt["conversation_id"],
                   message_id=receipt["message_id"])
        broker=AuthenticatedWebReceiptBroker(control,relay)
        params=dict(owner=p["owner"],run_id=p["run_id"],job_id=leased["job_id"],
                    browser_principal="local-operator",request_id=req,
                    worker="TAB-125",lease_token=leased["lease_token"],evidence=receipt)
        with pytest.raises(PermissionError):
            broker.accept(**{**params,"worker":"TAB-999"})
        with pytest.raises(PermissionError):
            broker.accept(**{**params,"evidence":{**receipt,"message_id":"other-message"}})
        assert relay.delivery_status(leased["job_id"])["state"]=="pending"
        authenticated=broker.accept(**params)
        assert authenticated["state"]=="attested" and not authenticated["replayed"]
        assert broker.accept(**params)["replayed"] is True
        assert adapter.commit(p["owner"],staged["continuation_id"],operator_approved=True)["stage"]=="PUBLISHED"
        # Reconfiguring collector invalidates the browser proof. No new send occurs.
        control.browser_evidence.configure(
            extension_id="a"*32,principal="local-operator",workspace="web-lab",
            source_sha256="1"*64,enabled=False,expected_revision=1)
        with pytest.raises(PermissionError):
            broker.require_attested(p["owner"],run_id=p["run_id"],
                                    job_id=leased["job_id"],evidence=receipt)
        assert relay.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]==1
    finally:
        relay.close();context.close();durable.close()


def test_web_frame_ingress_fails_closed_revisions_and_bounded_acl(tmp_path):
    durable,context,control,relay,adapter,p=setup(tmp_path)
    try:
        req=enroll(control,worker="TAB-126",conversation="target-chat-123",
                   message_id="message-12678")
        history=WebHistoryStore(tmp_path,store=control.store)
        ingress=AuthenticatedWebFrameIngress(control,history)
        values=dict(owner=p["owner"],run_id=p["run_id"],
                    browser_principal="local-operator",request_id=req,
                    worker="TAB-126",conversation_id="target-chat-123",
                    message_id="message-12678",role="assistant")
        with pytest.raises(PermissionError):
            ingress.record(**{**values,"worker":"TAB-127"},revision=0,
                           state="partial",body="should not persist")
        first=ingress.record(**values,revision=0,state="partial",body="streaming alpha")
        assert first["revision"]==0
        assert ingress.record(**values,revision=0,state="partial",
                              body="streaming alpha")["idempotent_replay"]
        with pytest.raises(WebHistoryConflict):
            ingress.record(**values,revision=0,state="partial",body="tamper")
        assert ingress.record(**values,revision=1,state="complete",
                              body="final beta")["revision"]==1
        assert history.messages(p["owner"],"web-lab","target-chat-123")[0]["body"]=="final beta"
        assert history.messages("another-owner","web-lab","target-chat-123")==[]
        control.browser_evidence.configure(
            extension_id="a"*32,principal="local-operator",workspace="web-lab",
            source_sha256="1"*64,enabled=False,expected_revision=1)
        with pytest.raises(PermissionError):
            ingress.record(**values,revision=2,state="complete",body="cannot persist")
    finally:
        relay.close();context.close();durable.close()


def test_authenticated_receipt_persists_across_crash_without_new_submission(tmp_path):
    durable,context,control,relay,adapter,p=setup(tmp_path)
    grant(control,p)
    staged=adapter.stage(**p)
    leased=relay.poll("TAB-135")
    relay.progress(leased["job_id"],"TAB-135",leased["lease_token"],"sending")
    receipt={"conversation_id":"target-chat-123","message_id":"message-13579",
             "prompt_sha256":hashlib.sha256(leased["prompt"].encode()).hexdigest(),
             "images_attached":0}
    req=enroll(control,worker="TAB-135",conversation=receipt["conversation_id"],
               message_id=receipt["message_id"])
    relay.delivery_receipt(leased["job_id"],"TAB-135",leased["lease_token"],receipt)
    relay.close();context.close();durable.close()
    recovered_durable,recovered_context,recovered=_services(tmp_path)
    jobs=JobStore(tmp_path/"web-relay.sqlite3")
    try:
        broker=AuthenticatedWebReceiptBroker(recovered,jobs)
        assert broker.attest_existing(
            p["owner"],run_id=p["run_id"],job_id=leased["job_id"],
            browser_principal="local-operator",request_id=req,
            worker="TAB-135",evidence=receipt)["state"]=="attested"
        from native_bridge.continuation_web import WebContinuation
        outcome=WebContinuation(recovered,jobs).commit(
            p["owner"],staged["continuation_id"],operator_approved=True)
        assert outcome["stage"]=="PUBLISHED"
        assert jobs.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
    finally:
        jobs.close();recovered_context.close();recovered_durable.close()
