"""Production MV3 receipt callback -> REAL RelayServer HTTP V2 -> central SQLite.

The JS runs in a hermetic Node/Chrome fixture, but uses the actual MV3 code
and HTTP requests. Does not send a prompt to ChatGPT or attest a real account.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_sentra_cos_web_relay_authenticated_routes import configure, grant, cleanup
from native_bridge.continuation_web import WebContinuation

ROOT = Path(__file__).resolve().parents[2]
EXT="a"*32
REQ="request-metadata-12345"
MSG="message-33777"
DOC_PREFIX="document-"


def _scenario(tmp_path, scenario):
    node=shutil.which("node")
    if not node:
        pytest.skip("Node fixture harness unavailable")
    durable,ctx,control,server,adapter,p=configure(tmp_path)
    try:
        sha=json.loads((ROOT/"edge_extension/manifest.json").read_text(
            encoding="utf-8"))["sentra_source_hash"]
        server.state.extension_version=lambda:{"source_hash":sha,"version":"test-current-MV3"}
        control.browser_evidence.configure(
            extension_id=EXT,principal="local-operator",workspace="web-lab",
            source_sha256=sha,enabled=True,expected_revision=0)
        grant(control,p)
        staged=adapter.stage(**p)
        job=server.state.poll("TAB-337")
        assert job is not None
        payload={
            "scenario":scenario,
            "url":f"http://127.0.0.1:{server.server.server_port}",
            "token":server.token,  # disposable relay fixture only
            "job":{"job_id":job["job_id"],"lease_token":job["lease_token"],
                   "prompt_sha256":hashlib.sha256(job["prompt"].encode()).hexdigest()},
        }
        fixture=Path(__file__).with_name("sentra_cos_chat2_receipt_v2_pipeline.cjs")
        result=subprocess.run([node,str(fixture),json.dumps(payload)],
             capture_output=True,text=True,cwd=ROOT,timeout=18)
        assert result.returncode==0,(scenario,result.stdout,result.stderr)
        record=json.loads(next(line.partition("=")[2] for line in
            result.stdout.splitlines() if line.startswith("SENTRA_RECEIPT_V2=")))
        delivery=server.state.delivery_status(job["job_id"])
        with control.session_checkpoints.store.connect("session_checkpoint") as db:
            attested=db.execute(
                "SELECT request_id,message_id,identity_epoch FROM authenticated_web_receipts "
                "WHERE job_id=?",(job["job_id"],)).fetchone()
            identity=tuple(attested) if attested else None
        with control.session_checkpoints.store.connect("chat_access") as db:
            poison=db.execute(
                "SELECT reason FROM browser_profile_uncertainty "
                "WHERE principal=? LIMIT 1",("local-operator",)).fetchone()
        if scenario=="valid":
            assert record["error"] is None
            assert record["receiptState"]=="attested"
            assert record["v2Count"]==1 and record["preliminaryCount"]==0
            assert record["observedCount"]==1 and record["phaseCount"]==1
            assert identity is not None and identity[0:2]==(REQ,MSG)
            assert identity[2] and identity[2].startswith("identity-")
            assert delivery["state"]=="sent"
            assert record["duplicateState"]=="uncertain"
            assert adapter.commit(p["owner"],staged["continuation_id"],
                                  operator_approved=True)["stage"]=="PUBLISHED"
        elif scenario in ("approval","missing_metadata","wrong_message",
                          "no_sending","wrong_worker","bad_phase_ack"):
            assert record["v2Count"]==0 and record["preliminaryCount"]==1
            assert identity is None
            assert delivery["state"] in ("sent","pending","unconfirmed","not_sent")
            assert not adapter.status(p["owner"],staged["continuation_id"])[
                "collector_message_attested"]
            if scenario=="approval":
                assert record["observedCount"]==1
                assert control.browser_evidence.dispatch_state(
                    "local-operator","target-chat-123")["send_blocked"]
        elif scenario=="uncertain_ack":
            assert record["error"]=="NETWORK_AFTER_POST"
            assert record["duplicateState"]=="uncertain"
            assert record["v2Count"]==1 and record["preliminaryCount"]==0
            # Host may have durably attested although MV3 lost the ACK.
            # No second HTTP attempt, no automatic Web retransmission.
            assert identity is not None and delivery["state"]=="sent"
            assert server.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
        elif scenario in ("wrong_epoch","downgrade","wrong_document","wrong_source_sha"):
            assert record["v2Count"]==int(scenario!="downgrade")
            assert record["preliminaryCount"]==int(scenario=="downgrade")
            assert record["error"]=="HTTP_403"
            assert identity is None
            assert delivery["state"]=="pending"
        elif scenario in ("unknown_profile","multi_tab_logout","untracked_logout"):
            assert record["profilePoison"] is True
            if scenario=="multi_tab_logout":
                with control.session_checkpoints.store.connect("chat_access") as db:
                    assert db.execute("SELECT COUNT(*) FROM browser_revoked_documents "
                        "WHERE extension_id=?",(EXT,)).fetchone()[0]>=2
            assert record["v2Count"]==0 and record["preliminaryCount"]==1
            assert identity is None and poison is not None
            assert control.browser_evidence.dispatch_state(
                "local-operator","target-chat-123")["send_blocked"]
        elif scenario=="reload":
            assert record["v2Count"]==0 and record["preliminaryCount"]==1
            assert identity is None
        assert server.state.db.execute("SELECT count(*) FROM jobs").fetchone()[0]==1
        return record
    finally:
        cleanup(server,ctx,durable)


@pytest.mark.parametrize("scenario",[
    "valid","approval","missing_metadata","wrong_message","wrong_epoch",
    "downgrade","wrong_document","unknown_profile","no_sending","wrong_worker",
    "uncertain_ack","bad_phase_ack","multi_tab_logout","reload"
])
def test_actual_mv3_callback_relay_v2_receipt_contract(tmp_path,scenario):
    record=_scenario(tmp_path,scenario)
    # The production callback and test trace never assert account/model/effort.
    assert all(route["route"] in {
        "/jobs/progress","/browser-evidence/challenge",
        "/browser-evidence/observe","/browser-evidence/invalidate",
        "/jobs/delivery-receipt"} for route in record["routes"])
    assert len([x for x in record["routes"]
                if x["route"]=="/jobs/delivery-receipt"])==1
