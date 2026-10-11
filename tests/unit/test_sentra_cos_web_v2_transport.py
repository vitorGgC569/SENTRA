"""Actual Chat2 MV3 JS-generated identity_epoch -> authenticated loopback HTTP relay.

The MV3 block executes via Node only as a hermetic fixture; HTTP and central
SQLite/DPAPI, grants, workers, Web receipts are real. Not a remote ChatGPT E2E.
"""
import hashlib
import sqlite3

import pytest

from native_bridge.continuation_web import WebContinuation
from native_bridge.relay import RelayServer
from test_sentra_cos_chat2_round3_mv3 import mv3_trace
from test_sentra_cos_web_relay_authenticated_routes import (
    configure, post, start_delivery, cleanup, EXT, ORIGIN, REQ,
)
from test_governance_coordination import _services


def enroll_v2(server,control,trace, *, conversation="target-chat-123",
              message_id="message-33777", request_id=REQ):
    notice=trace["notice"]
    sha=notice["source_sha256"]
    server.state.extension_version=lambda:{"source_hash":sha,"version":"fixture-from-MV3"}
    control.browser_evidence.configure(
        extension_id=EXT,principal="local-operator",workspace="web-lab",
        source_sha256=sha,enabled=True,expected_revision=0)
    challenge={k:notice[k] for k in (
        "source_sha256","worker","document_id","identity_epoch")}
    code,data=post(server,"/browser-evidence/challenge",challenge)
    assert code==200,data
    obs={"nonce":data["nonce"],"document_id":notice["document_id"],
         "conversation_id":conversation,"route_conversation_id":conversation,
         "identity_epoch":notice["identity_epoch"],"state":"idle",
         "requests":[{"request_id":request_id,"message_id":message_id}]}
    code,response=post(server,"/browser-evidence/observe",
                       {"source_sha256":sha,"worker":notice["worker"],"evidence":obs})
    assert code==200,response
    return obs


def test_actual_js_v2_to_relay_http_receipt_fence_ciphertext_and_grant(tmp_path):
    trace=mv3_trace()
    durable,ctx,control,server,adapter,p=configure(tmp_path)
    try:
        notice=trace["notice"]
        from test_sentra_cos_web_relay_authenticated_routes import grant
        grant(control,p)
        staged=adapter.stage(**p)
        job=server.state.poll(notice["worker"])
        assert job is not None
        code,_=post(server,"/jobs/progress",
                    {"job_id":job["job_id"],"worker":notice["worker"],
                     "lease_token":job["lease_token"],"phase":"sending"})
        assert code==200
        receipt={"conversation_id":"target-chat-123","message_id":"message-33777",
                 "prompt_sha256":hashlib.sha256(job["prompt"].encode()).hexdigest(),
                 "images_attached":0}
        observation=enroll_v2(server,control,trace)
        base={"job_id":job["job_id"],"worker":notice["worker"],
              "lease_token":job["lease_token"],"evidence":receipt,
              "request_id":REQ,"source_sha256":notice["source_sha256"],
              "document_id":notice["document_id"]}
        for malformed in (
            {**base},
            {**base,"identity_epoch":"forged-epoch-4567"},
            {**base,"identity_epoch":notice["identity_epoch"],"worker":"TAB-99"},
            {**base,"identity_epoch":notice["identity_epoch"],"document_id":"other-doc-12345"},
            {**base,"identity_epoch":notice["identity_epoch"],"lease_token":"bad-lease"},
            {**base,"identity_epoch":notice["identity_epoch"],"model":"gpt-6-high"},
        ):
            code,_=post(server,"/jobs/delivery-receipt",malformed)
            assert code in (400,403),malformed
        assert server.state.delivery_status(job["job_id"])["state"]=="pending"
        verified={**base,"identity_epoch":notice["identity_epoch"]}
        code,result=post(server,"/jobs/delivery-receipt",verified)
        assert code==200,result
        assert result["state"]=="attested"
        assert adapter.status(p["owner"],staged["continuation_id"])["collector_message_attested"]
        assert adapter.commit(p["owner"],staged["continuation_id"],
                              operator_approved=True)["stage"]=="PUBLISHED"
        assert server.state.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]==1
        with sqlite3.connect(tmp_path/"web-relay.sqlite3") as db:
            stored=db.execute("SELECT payload FROM jobs WHERE id=?",(job["job_id"],)).fetchone()[0]
        assert stored.startswith(("dpapi:","keyring:"))
        assert job["prompt"] not in stored
        assert job["prompt"].encode() not in (tmp_path/"web-relay.sqlite3").read_bytes()
        with control.session_checkpoints.store.connect("session_checkpoint") as db:
            assert db.execute("SELECT identity_epoch FROM authenticated_web_receipts "
                              "WHERE job_id=?",(job["job_id"],)).fetchone()[0]==notice["identity_epoch"]
    finally:
        cleanup(server,ctx,durable)


def test_actual_js_v2_deny_only_http_no_downgrade_and_restart(tmp_path):
    trace=mv3_trace()
    durable,ctx,control,server,adapter,p=configure(tmp_path)
    notice=trace["notice"]
    try:
        observation=enroll_v2(server,control,trace)
        challenge={k:notice[k] for k in ("source_sha256","worker","document_id","identity_epoch")}
        # Existing V2 document cannot be challenged again without the epoch.
        for invalid in ({k:v for k,v in challenge.items() if k!="identity_epoch"},
                        {**challenge,"identity_epoch":"wrong-epoch-99999"}):
            code,_=post(server,"/browser-evidence/challenge",invalid)
            assert code==403
        # V1 observe is also a downgrade; same nonce from enrolled V2 page.
        code,_=post(server,"/browser-evidence/observe",
                     {"source_sha256":notice["source_sha256"],
                      "worker":notice["worker"],
                      "evidence":{k:v for k,v in observation.items() if k!="identity_epoch"}})
        assert code==403
        for invalid in ({k:v for k,v in notice.items() if k!="identity_epoch"},
                        {**notice,"identity_epoch":"wrong-epoch-99999"},
                        {**notice,"worker":"TAB-991"},
                        {**notice,"document_id":"wrong-document-1234"}):
            code,_=post(server,"/browser-evidence/invalidate",invalid)
            assert code==403  # unknown worker cannot reuse another worker's bound V2 epoch
        assert control.chat_access.require_exact_message(
            "local-operator",REQ,"message-33777")["allowed"]
        code,revoked=post(server,"/browser-evidence/invalidate",notice)
        assert code==200,revoked
        assert revoked["state"]=="invalidated"
        with pytest.raises(PermissionError):
            control.chat_access.require_exact_message("local-operator",REQ,"message-33777")
        code,again=post(server,"/browser-evidence/invalidate",notice)
        assert code==200 and again["state"]=="invalidated"
        assert server.state.worker_status(notice["worker"])["online"] is False
    finally:
        cleanup(server,ctx,durable)
    durable2,ctx2,control2=_services(tmp_path)
    server2=RelayServer(port=0,db_path=tmp_path/"web-relay.sqlite3",
                        authenticated_control=control2).start()
    server2.state.extension_version=lambda:{"source_hash":notice["source_sha256"]}
    try:
        code,response=post(server2,"/browser-evidence/invalidate",notice)
        assert code==200 and response["state"]=="invalidated"
        code,response=post(server2,"/browser-evidence/challenge",
                           {k:notice[k] for k in (
                               "source_sha256","worker","document_id","identity_epoch")})
        assert code==403
    finally:
        cleanup(server2,ctx2,durable2)


def test_v2_preliminary_sent_restart_reconcile_only_same_epoch(tmp_path):
    trace=mv3_trace()
    durable,ctx,control,server,adapter,p=configure(tmp_path)
    notice=trace["notice"]
    from test_sentra_cos_web_relay_authenticated_routes import grant
    grant(control,p)
    staged=adapter.stage(**p)
    job=server.state.poll(notice["worker"])
    assert job
    assert post(server,"/jobs/progress",{
        "job_id":job["job_id"],"worker":notice["worker"],
        "lease_token":job["lease_token"],"phase":"sending"})[0]==200
    receipt={"conversation_id":"target-chat-123","message_id":"message-33777",
             "prompt_sha256":hashlib.sha256(job["prompt"].encode()).hexdigest(),
             "images_attached":0}
    enroll_v2(server,control,trace)
    preliminary={k:v for k,v in {
        "job_id":job["job_id"],"worker":notice["worker"],
        "lease_token":job["lease_token"],"evidence":receipt}.items()}
    assert post(server,"/jobs/delivery-receipt",preliminary)[1]["state"]=="sent"
    with pytest.raises(PermissionError):
        adapter.commit(p["owner"],staged["continuation_id"],operator_approved=True)
    cleanup(server,ctx,durable)
    d2,c2,control2=_services(tmp_path)
    server2=RelayServer(port=0,db_path=tmp_path/"web-relay.sqlite3",
                        authenticated_control=control2).start()
    server2.state.extension_version=lambda:{"source_hash":notice["source_sha256"]}
    try:
        props=dict(job_id=job["job_id"],worker=notice["worker"],request_id=REQ,
                   extension_id=EXT,source_sha256=notice["source_sha256"],
                   document_id=notice["document_id"])
        for wrong in (None,"wrong-epoch-99999"):
            with pytest.raises(PermissionError):
                server2.state.reconcile_web_receipt(**props,identity_epoch=wrong)
        assert server2.state.reconcile_web_receipt(
            **props,identity_epoch=notice["identity_epoch"])["state"]=="attested"
        assert WebContinuation(control2,server2.state).commit(
            p["owner"],staged["continuation_id"],operator_approved=True)["stage"]=="PUBLISHED"
        assert server2.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
    finally:
        cleanup(server2,c2,d2)


def test_v2_streaming_frames_require_same_epoch_and_protect_sqlite(tmp_path):
    from native_bridge.web_evidence_ingress import AuthenticatedWebFrameIngress
    from sentra_mcp.services.web_history_store import WebHistoryStore
    trace=mv3_trace()
    durable,ctx,control,server,adapter,p=configure(tmp_path)
    notice=trace["notice"]
    secret="SENTRA_V2_FRAME_PRIVATE_97466"
    try:
        enroll_v2(server,control,trace)
        history=WebHistoryStore(tmp_path,store=control.store)
        frames=AuthenticatedWebFrameIngress(control,history)
        args=dict(owner=p["owner"],run_id=p["run_id"],
                  browser_principal="local-operator",request_id=REQ,
                  worker=notice["worker"],conversation_id="target-chat-123",
                  message_id="message-33777",role="assistant")
        for epoch in (None,"wrong-epoch-99999"):
            with pytest.raises(PermissionError):
                frames.record(**args,revision=0,state="partial",body=secret,
                              identity_epoch=epoch)
        observed=frames.record(**args,revision=0,state="partial",body=secret,
                               identity_epoch=notice["identity_epoch"])
        assert observed["revision"]==0
        final=frames.record(**args,revision=1,state="complete",
                            body=secret+" FINAL",identity_epoch=notice["identity_epoch"])
        assert final["revision"]==1
        assert history.messages(p["owner"],"web-lab","target-chat-123")[0]["body"]==secret+" FINAL"
        db_path=control.store.path_for("provider_content")
        assert secret.encode() not in db_path.read_bytes()
        status,result=post(server,"/browser-evidence/invalidate",notice)
        assert status==200
        with pytest.raises(PermissionError):
            frames.record(**args,revision=2,state="complete",body="stale proof",
                          identity_epoch=notice["identity_epoch"])
    finally:
        cleanup(server,ctx,durable)


def test_v2_uncertain_expired_send_never_auto_retries(tmp_path):
    import time
    trace=mv3_trace()
    durable,ctx,control,server,adapter,p=configure(tmp_path)
    notice=trace["notice"]
    from test_sentra_cos_web_relay_authenticated_routes import grant
    try:
        grant(control,p)
        staged=adapter.stage(**p)
        job=server.state.poll(notice["worker"])
        assert job
        assert post(server,"/jobs/progress",{
            "job_id":job["job_id"],"worker":notice["worker"],
            "lease_token":job["lease_token"],"phase":"sending"})[0]==200
        enroll_v2(server,control,trace)
        receipt={"conversation_id":"target-chat-123","message_id":"message-33777",
                 "prompt_sha256":hashlib.sha256(job["prompt"].encode()).hexdigest(),
                 "images_attached":0}
        # Simulates a lost worker / relay restart after potential Web click.
        server.state.clock=lambda:time.time()+100000
        code,_=post(server,"/jobs/delivery-receipt",{
            "job_id":job["job_id"],"worker":notice["worker"],
            "lease_token":job["lease_token"],"evidence":receipt,
            "request_id":REQ,"source_sha256":notice["source_sha256"],
            "document_id":notice["document_id"],"identity_epoch":notice["identity_epoch"]})
        assert code==403
        info=adapter.reconcile(p["owner"],staged["continuation_id"])
        assert info["automatic_retry"] is False
        assert info["collector_message_attested"] is False
        assert server.state.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]==1
        assert server.state.poll("TAB-88") is None
        with pytest.raises((PermissionError,RuntimeError)):
            adapter.commit(p["owner"],staged["continuation_id"],operator_approved=True)
    finally:
        cleanup(server,ctx,durable)
