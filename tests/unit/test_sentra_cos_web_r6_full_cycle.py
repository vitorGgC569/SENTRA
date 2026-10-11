"""R6: real loopback HTTP/SQLite V2 relay, CHAT_START->A/B CAS, crash and worker identity.

No remote ChatGPT account; metadata is from the actual production MV3 prepare
block executed in a hermetic Node environment. Never perform a Web click.
"""
import hashlib

import pytest

from native_bridge.continuation_web import WebContinuation, WebContinuationConflict
from native_bridge.job_store import _workers_match
from native_bridge.relay import RelayServer
from test_governance_coordination import _services
from test_sentra_cos_web_r5_central import _v2_collector_trace
from test_sentra_cos_web_relay_authenticated_routes import configure, cleanup, grant, post
from test_sentra_cos_web_v2_transport import enroll_v2, REQ


def _new_destination(tmp_path):
    trace=_v2_collector_trace(tmp_path)
    d,c,control,relay,adapter,p=configure(tmp_path)
    grant(control,p)
    allocation=adapter.allocate_new_target(**{
        k:p[k] for k in ("owner","run_id","chat_id","work_item_id",
                         "principal_id","request_key","summary","operator_approved")})
    job=relay.state.poll(trace["notice"]["worker"])
    assert job and job["kind"]=="CHAT_START" and job["new_chat"] is True
    return trace,d,c,control,relay,adapter,p,allocation,job


def test_r6_new_chat_v2_receipt_claim_commit_across_two_restarts(tmp_path):
    trace,d,c,control,server,adapter,p,allocation,job=_new_destination(tmp_path)
    worker=trace["notice"]["worker"]
    try:
        assert post(server,"/jobs/progress",{
            "job_id":job["job_id"],"worker":worker,
            "lease_token":job["lease_token"],"phase":"sending"})[0]==200
        receipt={"conversation_id":"fresh-target-r6-12345",
                 "message_id":"message-fresh-r6-12345",
                 "prompt_sha256":hashlib.sha256(job["prompt"].encode()).hexdigest(),
                 "images_attached":0}
        enroll_v2(server,control,trace,conversation=receipt["conversation_id"],
                  message_id=receipt["message_id"])
        callback={"job_id":job["job_id"],"worker":worker,
                  "lease_token":job["lease_token"],"evidence":receipt,
                  "request_id":REQ,"source_sha256":trace["notice"]["source_sha256"],
                  "document_id":trace["notice"]["document_id"],
                  "identity_epoch":trace["notice"]["identity_epoch"]}
        for changed in ({**callback,"worker":"TAB-777"},
                        {**callback,"identity_epoch":"wrong-epoch-123456"},
                        {**callback,"evidence":{**receipt,"message_id":"wrong-message-12345"}}):
            assert post(server,"/jobs/delivery-receipt",changed)[0] in (400,403)
        code,accepted=post(server,"/jobs/delivery-receipt",callback)
        assert code==200 and accepted["state"]=="attested"
        code,repeat=post(server,"/jobs/delivery-receipt",callback)
        assert code==200 and repeat["replayed"] is True
        assert adapter.target_status(p["owner"],allocation["allocation_id"])["collector_message_attested"]
        assert adapter.target_status(p["owner"],allocation["allocation_id"])["account_identity_attested"] is False
        assert server.state.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]==1
        assert job["prompt"].encode() not in (tmp_path/"web-relay.sqlite3").read_bytes()
    finally:
        cleanup(server,c,d)

    d2,c2,control2=_services(tmp_path)
    server2=RelayServer(port=0,db_path=tmp_path/"web-relay.sqlite3",
                        authenticated_control=control2).start()
    server2.state.extension_version=lambda:{"source_hash":trace["notice"]["source_sha256"]}
    try:
        next_adapter=WebContinuation(control2,server2.state)
        claimed=next_adapter.claim_new_target(p["owner"],allocation["allocation_id"])
        assert claimed["collector_message_attested"] and claimed["core_state"]=="PREPARED"
        assert next_adapter.claim_new_target(p["owner"],allocation["allocation_id"])["continuation_id"]==claimed["continuation_id"]
        assert server2.state.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]==1
    finally:
        cleanup(server2,c2,d2)

    d3,c3,control3=_services(tmp_path)
    server3=RelayServer(port=0,db_path=tmp_path/"web-relay.sqlite3",
                        authenticated_control=control3).start()
    try:
        final=WebContinuation(control3,server3.state)
        done=final.commit(p["owner"],claimed["continuation_id"],operator_approved=True)
        assert done["stage"]=="PUBLISHED" and done["core_state"]=="COMMITTED"
        chat=next(x for x in d3.run_status(p["run_id"],p["owner"])["chats"]
                  if x["chat_id"]==p["chat_id"])
        assert chat["conversation_id"]=="fresh-target-r6-12345"
        assert final.target_status(p["owner"],allocation["allocation_id"])["state"]=="PUBLISHED"
        assert server3.state.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]==1
        assert server3.state.poll("TAB-778") is None
    finally:
        cleanup(server3,c3,d3)


def test_r6_worker_tab_id_must_match_exactly_even_with_shared_prefix_or_digits(tmp_path):
    assert _workers_match("TAB-12","TAB-12")
    for wrong in ("TAB-123","TAB-1","TAB-120","OTHER-12","tab-12"):
        assert not _workers_match("TAB-12",wrong)
        assert not _workers_match(wrong,"TAB-12")
    d,c,control,server,adapter,p=configure(tmp_path)
    try:
        grant(control,p)
        stage=adapter.stage(**p)
        # Earlier alias logic could match TAB-77 against TAB-777.
        with server.state.lock:
            server.state.db.execute("UPDATE jobs SET payload=payload WHERE id=(SELECT id FROM jobs LIMIT 1)")
        job=server.state.poll("TAB-77")
        assert job
        code,_=post(server,"/jobs/progress",{
            "job_id":job["job_id"],"worker":"TAB-777",
            "lease_token":job["lease_token"],"phase":"sending"})
        assert code==400
        assert server.state.db.execute("SELECT phase FROM jobs WHERE id=?",(job["job_id"],)).fetchone()[0]!="sending"
    finally:
        cleanup(server,c,d)


@pytest.mark.parametrize("phase",["queued","leased","sending"])
def test_r6_crash_at_each_phase_preserves_exactly_one_delivery_intent(tmp_path,phase):
    d,c,control,server,adapter,p=configure(tmp_path)
    grant(control,p)
    stage=adapter.stage(**p)
    jid=stage["continuation_id"]
    if phase!="queued":
        job=server.state.poll("TAB-77")
        assert job
        if phase=="sending":
            assert post(server,"/jobs/progress",{
                "job_id":job["job_id"],"worker":"TAB-77",
                "lease_token":job["lease_token"],"phase":"sending"})[0]==200
    cleanup(server,c,d)

    d2,c2,control2=_services(tmp_path)
    server2=RelayServer(port=0,db_path=tmp_path/"web-relay.sqlite3",
                        authenticated_control=control2).start()
    try:
        continuation=WebContinuation(control2,server2.state)
        assert continuation.reconcile(p["owner"],jid)["automatic_retry"] is False
        assert continuation.stage(**p)["continuation_id"]==jid
        assert server2.state.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]==1
        if phase=="sending":
            # A sending phase is never automatically re-queued to a fresh worker.
            assert server2.state.poll("TAB-999") is None
        if phase=="queued":
            assert server2.state.poll("TAB-77") is not None
        with pytest.raises((PermissionError,WebContinuationConflict)):
            continuation.commit(p["owner"],jid,operator_approved=True)
    finally:
        cleanup(server2,c2,d2)
