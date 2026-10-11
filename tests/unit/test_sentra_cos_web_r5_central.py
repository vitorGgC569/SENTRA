"""R5: owner/Run/WorkItem/grant + real relay HTTP/SQLite V2, crash fencing.

The browser identity epoch is obtained from Chat2's production MV3 JS fixture,
not a claim of a verified external ChatGPT account or actual remote send.
"""
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from native_bridge.continuation_web import WebContinuation, WebContinuationConflict
from native_bridge.relay import RelayServer
from test_governance_coordination import _services
from test_sentra_cos_web_relay_authenticated_routes import configure, cleanup, grant, post
from test_sentra_cos_web_v2_transport import enroll_v2, REQ, EXT


def _v2_collector_trace(tmp_path):
    """Run the current Chat2 production MV3 *prepare* (no logout/poison).

    The old round-3 fixture attempts to republish after global logout; the
    current producer correctly forbids that until operator repair. Never
    weaken production's deny-only profile poisoning for this test.
    """
    node=shutil.which("node")
    if not node:
        pytest.skip("Node test runner not installed")
    script=Path(__file__).with_name("sentra_cos_web_v2_http_producer.cjs")
    env={**os.environ, "SENTRA_TEST_SOURCE_HASH":"f"*64,
         "SENTRA_TEST_HTTP_URL":"http://127.0.0.1:8765",
         "SENTRA_TEST_HTTP_TOKEN":secrets.token_urlsafe(32)}
    proc=subprocess.run([node,str(script),"prepare",str(tmp_path/"mv3-r5.json")],
                        text=True,capture_output=True,env=env,timeout=10)
    assert proc.returncode==0,proc.stderr
    notice=json.loads(proc.stdout)
    assert set(notice)=={"source_sha256","worker","document_id","identity_epoch"}
    return {"notice":notice}


def _stage_and_receipt(control, server, adapter, params, trace):
    grant_info=grant(control,params)
    staged=adapter.stage(**params)
    worker=trace["notice"]["worker"]
    job=server.state.poll(worker)
    assert job["kind"]=="CHAT_SEND" and job["task_id"]==staged["continuation_id"]
    assert post(server,"/jobs/progress",{
        "job_id":job["job_id"],"worker":worker,
        "lease_token":job["lease_token"],"phase":"sending"})[0]==200
    receipt={"conversation_id":"target-chat-123","message_id":"message-r5-12345",
             "prompt_sha256":hashlib.sha256(job["prompt"].encode()).hexdigest(),
             "images_attached":0}
    enroll_v2(server,control,trace,message_id=receipt["message_id"])
    body={"job_id":job["job_id"],"worker":worker,
          "lease_token":job["lease_token"],"evidence":receipt,
          "request_id":REQ,"source_sha256":trace["notice"]["source_sha256"],
          "document_id":trace["notice"]["document_id"],
          "identity_epoch":trace["notice"]["identity_epoch"]}
    return grant_info,staged,job,receipt,body


def test_r5_http_v2_duplicate_ack_concurrency_then_restart_cas_same_run(tmp_path):
    trace=_v2_collector_trace(tmp_path)
    durable,context,control,server,adapter,p=configure(tmp_path)
    try:
        approved,staged,job,receipt,body=_stage_and_receipt(
            control,server,adapter,p,trace)
        work_before=control.work_item_info(p["work_item_id"],p["owner"])
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies=list(pool.map(lambda _:post(server,"/jobs/delivery-receipt",body),range(4)))
        assert all(code==200 and result["state"]=="attested" for code,result in replies),replies
        assert sum(not result["replayed"] for _,result in replies)==1
        assert server.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
        with sqlite3.connect(tmp_path/"web-relay.sqlite3") as db:
            row=db.execute("SELECT payload,result FROM jobs WHERE id=?",(job["job_id"],)).fetchone()
            assert row[0].startswith(("dpapi:","keyring:")) and row[1] is None
        assert job["prompt"].encode() not in (tmp_path/"web-relay.sqlite3").read_bytes()
        with control.store.connect("session_checkpoint") as db:
            rows=db.execute("SELECT job_id,identity_epoch FROM authenticated_web_receipts "
                            "WHERE job_id=?",(job["job_id"],)).fetchall()
            assert len(rows)==1 and rows[0]["identity_epoch"]==trace["notice"]["identity_epoch"]
        assert adapter.status(p["owner"],staged["continuation_id"])["core_state"]=="PREPARED"
        assert adapter.status(p["owner"],staged["continuation_id"])["account_identity_attested"] is False
    finally:
        cleanup(server,context,durable)

    d2,c2,control2=_services(tmp_path)
    server2=RelayServer(port=0,db_path=tmp_path/"web-relay.sqlite3",
                        authenticated_control=control2).start()
    server2.state.extension_version=lambda:{"source_hash":trace["notice"]["source_sha256"]}
    try:
        recovered=WebContinuation(control2,server2.state)
        assert recovered.reconcile(p["owner"],staged["continuation_id"])["collector_message_attested"]
        assert recovered.commit(p["owner"],staged["continuation_id"],
                                operator_approved=True)["stage"]=="PUBLISHED"
        assert recovered.commit(p["owner"],staged["continuation_id"],
                                operator_approved=True)["core_state"]=="COMMITTED"
        chat=next(c for c in d2.run_status(p["run_id"],p["owner"])["chats"]
                  if c["chat_id"]==p["chat_id"])
        assert chat["conversation_id"]=="target-chat-123"
        assert control2.work_item_info(p["work_item_id"],p["owner"])==work_before
        assert server2.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
        assert server2.state.poll("TAB-991") is None
        assert recovered.status(p["owner"],staged["continuation_id"])["automatic_retry"] is False
    finally:
        cleanup(server2,c2,d2)


def test_r5_attested_receipt_cannot_commit_with_replacement_grant(tmp_path):
    trace=_v2_collector_trace(tmp_path)
    d,c,control,server,adapter,p=configure(tmp_path)
    try:
        approved,stage,job,receipt,body=_stage_and_receipt(control,server,adapter,p,trace)
        assert post(server,"/jobs/delivery-receipt",body)[1]["state"]=="attested"
        control.authorization.revoke(approved["grant_id"],p["owner"])
        newer=grant(control,p)
        assert newer["grant_id"]!=approved["grant_id"]
        with pytest.raises(PermissionError,match="original Web send grant"):
            adapter.commit(p["owner"],stage["continuation_id"],operator_approved=True)
        original=next(x for x in d.run_status(p["run_id"],p["owner"])["chats"]
                      if x["chat_id"]==p["chat_id"])
        assert original["conversation_id"]=="source-chat-123"
        assert server.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
    finally:
        cleanup(server,c,d)


def test_r5_approval_pending_blocks_send_until_new_idle_evidence(tmp_path):
    trace=_v2_collector_trace(tmp_path)
    d,c,control,server,adapter,p=configure(tmp_path)
    notice=trace["notice"]
    try:
        grant(control,p)
        enroll_v2(server,control,trace,message_id="message-r5-12345")
        base={k:notice[k] for k in (
            "source_sha256","worker","document_id","identity_epoch")}
        def update_page(state):
            code,ch=post(server,"/browser-evidence/challenge",base)
            assert code==200,ch
            code,answer=post(server,"/browser-evidence/observe",{
                "source_sha256":notice["source_sha256"],"worker":notice["worker"],
                "evidence":{"nonce":ch["nonce"],"document_id":notice["document_id"],
                            "identity_epoch":notice["identity_epoch"],
                            "conversation_id":"target-chat-123",
                            "route_conversation_id":"target-chat-123",
                            "state":state,"requests":[{"request_id":REQ,
                                                       "message_id":"message-r5-12345"}]}})
            assert code==200,answer
        update_page("awaiting_approval")
        with pytest.raises(PermissionError,match="human approval"):
            adapter.stage(**p)
        assert server.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==0
        update_page("idle")
        staged=adapter.stage(**p)
        assert staged["delivery"]["state"]=="not_sent"
        assert server.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
    finally:
        cleanup(server,c,d)


def test_r5_uncertain_after_sending_restart_blocks_every_new_dispatch(tmp_path):
    trace=_v2_collector_trace(tmp_path)
    d,c,control,server,adapter,p=configure(tmp_path)
    notice=trace["notice"]
    try:
        grant(control,p)
        stage=adapter.stage(**p)
        job=server.state.poll(notice["worker"])
        assert job
        assert post(server,"/jobs/progress",{
            "job_id":job["job_id"],"worker":notice["worker"],
            "lease_token":job["lease_token"],"phase":"sending"})[0]==200
        server.state.clock=lambda:time.time()+100000
        assert server.state.poll("TAB-999") is None
        assert server.state.delivery_status(job["job_id"])["state"]=="unconfirmed"
        assert server.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
    finally:
        cleanup(server,c,d)
    d2,c2,control2=_services(tmp_path)
    server2=RelayServer(port=0,db_path=tmp_path/"web-relay.sqlite3",
                        authenticated_control=control2).start()
    server2.state.extension_version=lambda:{"source_hash":notice["source_sha256"]}
    try:
        recovered=WebContinuation(control2,server2.state)
        result=recovered.reconcile(p["owner"],stage["continuation_id"])
        assert result["delivery"]["state"]=="unconfirmed"
        assert result["automatic_retry"] is False
        assert result["requires_operator_reconciliation"]
        with pytest.raises(WebContinuationConflict,match="uncertain"):
            recovered.stage(**p)
        with pytest.raises((PermissionError,WebContinuationConflict)):
            recovered.commit(p["owner"],stage["continuation_id"],operator_approved=True)
        assert server2.state.poll("TAB-998") is None
        assert server2.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
    finally:
        cleanup(server2,c2,d2)


def test_r5_target_claim_rejects_reissued_grant_without_new_send(tmp_path):
    d,c,control,server,adapter,p=configure(tmp_path)
    try:
        initial=grant(control,p)
        allocation=adapter.allocate_new_target(**{
            k:p[k] for k in ("owner","run_id","chat_id","work_item_id",
                             "principal_id","request_key","summary","operator_approved")})
        control.authorization.revoke(initial["grant_id"],p["owner"])
        replacement=grant(control,p)
        assert replacement["grant_id"]!=initial["grant_id"]
        with pytest.raises(PermissionError,match="original Web target grant"):
            adapter.claim_new_target(p["owner"],allocation["allocation_id"])
        assert adapter.target_status(p["owner"],allocation["allocation_id"])["state"]=="ALLOCATING"
        assert server.state.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]==1
        source=next(row for row in d.run_status(p["run_id"],p["owner"])["chats"]
                    if row["chat_id"]==p["chat_id"])
        assert source["conversation_id"]=="source-chat-123"
    finally:
        cleanup(server,c,d)
