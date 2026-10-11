"""Chat2's PRODUCTION MV3 JS trace transported via a real loopback HTTP relay.

Uses genuine BrowserEvidenceService/SQLite; does not depend on the temporarily
cyclic ControlPlane import. No external ChatGPT account or DOM proof asserted.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from native_bridge.relay import RelayServer
from sentra_mcp.services.browser_evidence import BrowserEvidenceService
from test_sentra_cos_chat2_round3_mv3 import mv3_trace
import urllib.error
import urllib.request

EXT = "a" * 32
REQ = "request-metadata-12345"

def post(server,route,data,*,origin="chrome-extension://" + EXT,token=None):
    url=f"http://127.0.0.1:{server.server.server_port}{route}"
    headers={"Content-Type":"application/json","Origin":origin,
             "Authorization":"Bearer " + (token if token is not None else server.token)}
    request=urllib.request.Request(url,data=json.dumps(data).encode(),headers=headers)
    try:
        with urllib.request.urlopen(request,timeout=6) as resp:
            return resp.status,json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code,json.loads(exc.read())

CHAT="conversation12345"
MSG="message-33777"


def start(tmp_path, trace):
    be=BrowserEvidenceService(tmp_path)
    sha=trace["notice"]["source_sha256"]
    be.configure(extension_id=EXT,principal="local-operator",workspace=str(tmp_path),
                 source_sha256=sha,enabled=True,expected_revision=0)
    server=RelayServer(port=0,db_path=tmp_path/"relay.db",browser_evidence=be).start()
    server.state.extension_version=lambda:{"version":"MV3-HERMETIC","source_hash":sha}
    return server,be


def enroll(server,notice):
    req={k:notice[k] for k in (
        "source_sha256","worker","document_id","identity_epoch")}
    status,nonce=post(server,"/browser-evidence/challenge",req)
    assert status==200,nonce
    evidence={"nonce":nonce["nonce"],"document_id":notice["document_id"],
              "identity_epoch":notice["identity_epoch"],
              "conversation_id":CHAT,"route_conversation_id":CHAT,
              "state":"idle","requests":[{"request_id":REQ,"message_id":MSG}]}
    status,result=post(server,"/browser-evidence/observe",
                       {"source_sha256":notice["source_sha256"],
                        "worker":notice["worker"],"evidence":evidence})
    assert status==200 and result["state"]=="observed",(status,result)
    return req,evidence


def test_mv3_v2_challenge_observe_invalidate_real_http_no_downgrade(tmp_path):
    trace=mv3_trace()
    notice=trace["notice"]
    server,be=start(tmp_path,trace)
    try:
        challenge,evidence=enroll(server,notice)
        assert be.chat_access.require_exact_message("local-operator",REQ,MSG)["allowed"]
        for wrong in (
            {k:v for k,v in challenge.items() if k!="identity_epoch"},
            {**challenge,"identity_epoch":"forged-epoch-000001"},
        ):
            status,_=post(server,"/browser-evidence/challenge",wrong)
            assert status==403
        for wrong in (
            {**evidence,"identity_epoch":"forged-epoch-000001"},
            {k:v for k,v in evidence.items() if k!="identity_epoch"},
        ):
            status,_=post(server,"/browser-evidence/observe",
                         {"source_sha256":notice["source_sha256"],
                          "worker":notice["worker"],"evidence":wrong})
            assert status==403
        for invalid in (
            {k:v for k,v in notice.items() if k!="identity_epoch"},
            {**notice,"identity_epoch":"forged-epoch-000001"},
            {**notice,"document_id":"changed-doc-123456"},
            {**notice,"reason":"unrecognized"},
        ):
            status,_=post(server,"/browser-evidence/invalidate",invalid)
            assert status in (400,403),invalid
        assert be.chat_access.require_exact_message("local-operator",REQ,MSG)["allowed"]
        status,reply=post(server,"/browser-evidence/invalidate",notice)
        assert status==200 and reply["state"]=="invalidated"
        with pytest.raises(PermissionError):
            be.chat_access.require_exact_message("local-operator",REQ,MSG)
        status,reply=post(server,"/browser-evidence/invalidate",notice)
        assert status==200 and reply["state"]=="invalidated"
        assert server.state.worker_status(notice["worker"])["online"] is False
        assert be.dispatch_state("local-operator",CHAT)["send_blocked"]
        with be.store.connect("chat_access") as db:
            assert db.execute("SELECT identity_epoch FROM browser_document_epochs "
                              "WHERE extension_id=? AND worker=?",
                              (EXT,notice["worker"])).fetchone()[0]==notice["identity_epoch"]
    finally:
        server.stop()


def test_mv3_v2_restart_preserves_revocation_and_wrong_source_token_origin(tmp_path):
    trace=mv3_trace(); notice=trace["notice"]
    server,be=start(tmp_path,trace)
    try:
        enroll(server,notice)
        for origin,token,payload in (
            ("https://chatgpt.com",None,notice),
            ("chrome-extension://"+ "b"*32,None,notice),
            ("chrome-extension://"+ EXT,"invalid-pair-token",notice),
            ("chrome-extension://"+ EXT,None,{**notice,"source_sha256":"0"*64}),
        ):
            status,_=post(server,"/browser-evidence/invalidate",
                          payload,origin=origin,token=token)
            assert status in (401,403)
        assert post(server,"/browser-evidence/invalidate",notice)[0]==200
    finally:
        server.stop()
    be2=BrowserEvidenceService(tmp_path)
    server2=RelayServer(port=0,db_path=tmp_path/"relay.db",
                        browser_evidence=be2).start()
    server2.state.extension_version=lambda:{"source_hash":notice["source_sha256"]}
    try:
        status,response=post(server2,"/browser-evidence/invalidate",notice)
        assert status==200 and response["state"]=="invalidated"
        status,_=post(server2,"/browser-evidence/challenge",
                      {k:notice[k] for k in (
                          "source_sha256","worker","document_id","identity_epoch")})
        assert status==403
        with be2.store.connect("chat_access") as db:
            assert db.execute("SELECT COUNT(*) FROM browser_revoked_documents").fetchone()[0]==1
    finally:
        server2.stop()


def test_production_mv3_js_sends_real_invalidate_http_to_sqlite(tmp_path):
    import os
    import shutil
    import subprocess
    script=Path(__file__).with_name("sentra_cos_web_v2_http_producer.cjs")
    node=shutil.which("node")
    if node is None:
        pytest.skip("Node fixture runner unavailable")
    generated=mv3_trace()
    server,be=start(tmp_path,generated)
    state_file=tmp_path/"mv3-minimal-state.json"
    env={**os.environ,
         "SENTRA_TEST_HTTP_URL":f"http://127.0.0.1:{server.server.server_port}",
         "SENTRA_TEST_HTTP_TOKEN":server.token,
         "SENTRA_TEST_SOURCE_HASH":generated["notice"]["source_sha256"]}
    try:
        prep=subprocess.run([node,str(script),"prepare",str(state_file)],
                            capture_output=True,text=True,timeout=10,env=env)
        assert prep.returncode==0,prep.stderr
        prepared=json.loads(prep.stdout)
        assert set(prepared)=={"source_sha256","worker","document_id","identity_epoch"}
        challenge,evidence=None,None
        code,challenge=post(server,"/browser-evidence/challenge",prepared)
        assert code==200,challenge
        evidence={"nonce":challenge["nonce"],"document_id":prepared["document_id"],
                  "identity_epoch":prepared["identity_epoch"],
                  "conversation_id":CHAT,"route_conversation_id":CHAT,
                  "state":"idle","requests":[{"request_id":REQ,"message_id":MSG}]}
        code,response=post(server,"/browser-evidence/observe",
                           {"source_sha256":prepared["source_sha256"],
                            "worker":prepared["worker"],"evidence":evidence})
        assert code==200,response
        assert be.chat_access.require_exact_message("local-operator",REQ,MSG)["allowed"]
        child=subprocess.run([node,str(script),"revoke",str(state_file)],
                             capture_output=True,text=True,timeout=10,env=env)
        assert child.returncode==0,child.stderr
        receipt=json.loads(child.stdout)
        assert receipt["ok"] is True
        assert receipt["requests"][0]["route"]=="/browser-evidence/invalidate"
        assert receipt["requests"][0]["keys"]==sorted(
            ["source_sha256","worker","document_id","identity_epoch","reason"])
        with pytest.raises(PermissionError):
            be.chat_access.require_exact_message("local-operator",REQ,MSG)
        assert server.state.worker_status(prepared["worker"])["online"] is False
        with be.store.connect("chat_access") as db:
            epoch=db.execute("SELECT identity_epoch FROM browser_document_epochs "
                             "WHERE extension_id=? AND worker=?",
                             (EXT,prepared["worker"])).fetchone()[0]
            assert epoch==prepared["identity_epoch"]
    finally:
        server.stop()
