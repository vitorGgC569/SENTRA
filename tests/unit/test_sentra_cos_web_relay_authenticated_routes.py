"""Real HTTP loopback ingress, durable SQLite and centrally enrolled browser proof.

Browser observations are deliberate controlled fixtures. Not a real account E2E.
"""
import hashlib
import json
import sqlite3
import time
import urllib.error
import urllib.request

import pytest

from native_bridge.continuation_web import WebContinuation
from native_bridge.relay import RelayServer
from test_sentra_cos_web_continuation_receipts import setup, grant
from test_governance_coordination import _services


EXT="a"*32
HASH="1"*64
ORIGIN="chrome-extension://"+EXT
DOC="document-web-12345"
REQ="request-metadata-12345"


def post(server, route, data, *, origin=ORIGIN, token=None):
    base=f"http://127.0.0.1:{server.server.server_port}"
    body=json.dumps(data).encode()
    headers={"Content-Type":"application/json","Origin":origin,
             "Authorization":"Bearer "+(token if token is not None else server.token)}
    request=urllib.request.Request(base+route,data=body,headers=headers)
    try:
        with urllib.request.urlopen(request,timeout=6) as response:
            return response.status,json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code,json.loads(exc.read())


def configure(tmp_path):
    durable,context,control,old,preset,params=setup(tmp_path)
    old.close()
    server=RelayServer(port=0,db_path=tmp_path/"web-relay.sqlite3",
                       authenticated_control=control).start()
    # A synthetic extension identity is injected solely for this transport
    # test; production _browser_collector checks the actual stamped manifest.
    server.state.extension_version=lambda:{"source_hash":HASH,"version":"test"}
    adapter=WebContinuation(control,server.state)
    return durable,context,control,server,adapter,params


def enroll_http(server,control,*,worker,conversation,message,request=REQ):
    control.browser_evidence.configure(
        extension_id=EXT,principal="local-operator",workspace="web-lab",
        source_sha256=HASH,enabled=True,expected_revision=0)
    code,challenge=post(server,"/browser-evidence/challenge",
                        {"source_sha256":HASH,"worker":worker,"document_id":DOC})
    assert code==200,challenge
    evidence={"nonce":challenge["nonce"],"document_id":DOC,
              "conversation_id":conversation,"route_conversation_id":conversation,
              "state":"idle",
              "requests":[{"request_id":request,"message_id":message}]}
    code,observed=post(server,"/browser-evidence/observe",
                       {"source_sha256":HASH,"worker":worker,"evidence":evidence})
    assert code==200,observed
    return request


def start_delivery(adapter,control,server,params,worker="TAB-337"):
    grant(control,params)
    staged=adapter.stage(**params)
    job=server.state.poll(worker)
    assert job["kind"]=="CHAT_SEND"
    code,result=post(server,"/jobs/progress",
                     {"job_id":job["job_id"],"worker":worker,
                      "lease_token":job["lease_token"],"phase":"sending"})
    assert code==200,result
    receipt={"conversation_id":"target-chat-123","message_id":"message-33777",
             "prompt_sha256":hashlib.sha256(job["prompt"].encode()).hexdigest(),
             "images_attached":0}
    return staged,job,receipt


def envelope(job,receipt,*,request=REQ,worker="TAB-337",document=DOC):
    return {"job_id":job["job_id"],"worker":worker,
            "lease_token":job["lease_token"],"evidence":receipt,
            "request_id":request,"source_sha256":HASH,"document_id":document}


def cleanup(server,context,durable):
    server.stop()
    context.close()
    durable.close()


def test_http_attested_receipt_preserves_run_and_ciphertext(tmp_path):
    durable,context,control,server,adapter,p=configure(tmp_path)
    try:
        staged,job,receipt=start_delivery(adapter,control,server,p)
        enroll_http(server,control,worker="TAB-337",
                    conversation=receipt["conversation_id"],
                    message=receipt["message_id"])
        body=envelope(job,receipt)
        for altered in (
            {**body,"worker":"TAB-33"},
            {**body,"lease_token":"invalid-worker-lease"},
            {**body,"document_id":"other-doc-12345"},
            {**body,"evidence":{**receipt,"message_id":"other-message"}},
            {**body,"model":"gpt-6-high"},
        ):
            status,_=post(server,"/jobs/delivery-receipt",altered)
            assert status in (400,403),altered
        assert server.state.delivery_status(job["job_id"])["state"]=="pending"
        status,answer=post(server,"/jobs/delivery-receipt",body)
        assert status==200,answer
        assert answer["state"]=="attested" and answer["relay_delivery_state"]=="sent"
        status,replayed=post(server,"/jobs/delivery-receipt",body)
        assert status==200 and replayed["replayed"] is True
        assert adapter.status(p["owner"],staged["continuation_id"])["collector_message_attested"]
        finished=adapter.commit(p["owner"],staged["continuation_id"],operator_approved=True)
        assert finished["stage"]=="PUBLISHED" and finished["core_state"]=="COMMITTED"
        assert server.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
        with sqlite3.connect(tmp_path/"web-relay.sqlite3") as db:
            columns=db.execute("SELECT payload,result FROM jobs WHERE id=?",
                               (job["job_id"],)).fetchone()
        assert columns[0].startswith(("dpapi:","keyring:"))
        assert job["prompt"] not in columns[0]
        assert (tmp_path/"web-relay.sqlite3").read_bytes().find(
            job["prompt"].encode())<0
    finally:
        cleanup(server,context,durable)


def test_http_invalidate_fences_active_receipt_and_other_worker_untouched(tmp_path):
    durable,context,control,server,adapter,p=configure(tmp_path)
    try:
        staged,job,receipt=start_delivery(adapter,control,server,p)
        enroll_http(server,control,worker="TAB-337",
                    conversation=receipt["conversation_id"],
                    message=receipt["message_id"])
        invalid={"source_sha256":HASH,"worker":"TAB-337",
                 "document_id":DOC,"reason":"account_changed"}
        for origin,token,invalid_data in (
            ("https://chatgpt.com",None,invalid),
            (ORIGIN,"wrong-token",invalid),
            (ORIGIN,None,{**invalid,"source_sha256":"0"*64}),
            (ORIGIN,None,{**invalid,"reason":"erase_database"}),
            (ORIGIN,None,{**invalid,"document_id":"other-doc-12345"}),
            (ORIGIN,None,{**invalid,"worker":"TAB-338"}),
        ):
            status,_=post(server,"/browser-evidence/invalidate",
                          invalid_data,origin=origin,token=token)
            if invalid_data["worker"]=="TAB-338":
                assert status==200  # absent documents cannot revoke another worker
            else:
                assert status in (400,401,403)
        status,result=post(server,"/browser-evidence/invalidate",invalid)
        assert status==200 and result["state"]=="invalidated"
        assert server.state.worker_status("TAB-337")["online"] is False
        status,result=post(server,"/browser-evidence/invalidate",invalid)
        assert status==200 and result["state"]=="invalidated"  # idempotent deny-only
        status,result=post(server,"/jobs/delivery-receipt",envelope(job,receipt))
        assert status==403,result
        assert server.state.delivery_status(job["job_id"])["state"]=="pending"
        assert server.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
        assert adapter.status(p["owner"],staged["continuation_id"])["collector_message_attested"] is False
    finally:
        cleanup(server,context,durable)


def test_http_old_receipt_preliminary_restart_host_reconciliation_no_resend(tmp_path):
    durable,context,control,server,adapter,p=configure(tmp_path)
    grant(control,p)
    staged=adapter.stage(**p)
    job=server.state.poll("TAB-337")
    code,_=post(server,"/jobs/progress",{"job_id":job["job_id"],
                "worker":"TAB-337","lease_token":job["lease_token"],"phase":"sending"})
    assert code==200
    receipt={"conversation_id":"target-chat-123","message_id":"message-33777",
             "prompt_sha256":hashlib.sha256(job["prompt"].encode()).hexdigest(),
             "images_attached":0}
    enroll_http(server,control,worker="TAB-337",conversation=receipt["conversation_id"],
                message=receipt["message_id"])
    old_payload={k:envelope(job,receipt)[k] for k in ("job_id","worker","lease_token","evidence")}
    code,preliminary=post(server,"/jobs/delivery-receipt",old_payload)
    assert code==200 and preliminary["state"]=="sent"
    with pytest.raises(PermissionError,match="proof missing"):
        adapter.commit(p["owner"],staged["continuation_id"],operator_approved=True)
    server.stop();context.close();durable.close()
    durable2,context2,control2=_services(tmp_path)
    server2=RelayServer(port=0,db_path=tmp_path/"web-relay.sqlite3",
                        authenticated_control=control2).start()
    server2.state.extension_version=lambda:{"source_hash":HASH}
    try:
        reconciled=server2.state.reconcile_web_receipt(
            job_id=job["job_id"],worker="TAB-337",request_id=REQ,
            extension_id=EXT,source_sha256=HASH,document_id=DOC)
        assert reconciled["state"]=="attested"
        adapter2=WebContinuation(control2,server2.state)
        assert adapter2.commit(p["owner"],staged["continuation_id"],
                               operator_approved=True)["stage"]=="PUBLISHED"
        assert server2.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
    finally:
        cleanup(server2,context2,durable2)


def test_http_expired_lease_does_not_attest_or_resend(tmp_path):
    durable,context,control,server,adapter,p=configure(tmp_path)
    try:
        staged,job,receipt=start_delivery(adapter,control,server,p)
        enroll_http(server,control,worker="TAB-337",
                    conversation=receipt["conversation_id"],
                    message=receipt["message_id"])
        server.state.clock=lambda:time.time()+100000
        code,result=post(server,"/jobs/delivery-receipt",envelope(job,receipt))
        assert code==403,result
        delivery=server.state.delivery_status(job["job_id"])
        assert delivery["state"] in {"pending","unconfirmed"}
        assert adapter.reconcile(p["owner"],staged["continuation_id"])["automatic_retry"] is False
        assert server.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
    finally:
        cleanup(server,context,durable)


def test_http_grant_revocation_prevents_receipt_despite_browser_proof(tmp_path):
    durable,context,control,server,adapter,p=configure(tmp_path)
    try:
        staged,job,receipt=start_delivery(adapter,control,server,p)
        enroll_http(server,control,worker="TAB-337",
                    conversation=receipt["conversation_id"],
                    message=receipt["message_id"])
        with control.session_checkpoints.store.connect("session_checkpoint") as db:
            old=db.execute("SELECT grant_id FROM web_continuation_transfers "
                           "WHERE job_id=?",(job["job_id"],)).fetchone()[0]
        control.authorization.revoke(old,p["owner"])
        code,body=post(server,"/jobs/delivery-receipt",envelope(job,receipt))
        assert code==403,body
        assert server.state.delivery_status(job["job_id"])["state"]=="pending"
        assert server.state.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]==1
    finally:
        cleanup(server,context,durable)


def test_http_wrong_extension_origin_and_id_cannot_attest(tmp_path):
    durable,context,control,server,adapter,p=configure(tmp_path)
    try:
        staged,job,receipt=start_delivery(adapter,control,server,p)
        enroll_http(server,control,worker="TAB-337",
                    conversation=receipt["conversation_id"],
                    message=receipt["message_id"])
        for origin in (
            "chrome-extension://"+"b"*32,
            "https://chatgpt.com",
            "null",
        ):
            code,_=post(server,"/jobs/delivery-receipt",
                        envelope(job,receipt),origin=origin)
            assert code==403
        assert server.state.delivery_status(job["job_id"])["state"]=="pending"
    finally:
        cleanup(server,context,durable)
