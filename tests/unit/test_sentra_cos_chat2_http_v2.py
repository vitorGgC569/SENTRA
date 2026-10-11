"""Loopback HTTP (TCP) V2 contract: REAL MV3 JavaScript functions -> SQLite.

Native relay remains Chat 3-owned, so this does NOT claim that
native_bridge.relay has integrated the V2 adapter or a real Edge login.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from browser.evidence_http_v2 import (
    CHALLENGE, INVALIDATE, OBSERVE, dispatch_authenticated_v2
)
from sentra_mcp.services.browser_evidence import BrowserEvidenceService

ROOT=Path(__file__).resolve().parents[2]
EXT="a"*32
OWNER="local-operator"
WORKER="TAB-77"
CHAT="conversation12345"
REQ="request-abcdef123"
MSG="message-abcdef123"
TEST_BEARER="Bearer fixture-loopback-only"


@pytest.fixture
def v2_http(tmp_path):
    sha=json.loads((ROOT/"edge_extension/manifest.json").read_text(
        encoding="utf-8"))["sentra_source_hash"]
    evidence=BrowserEvidenceService(tmp_path)
    evidence.configure(extension_id=EXT,principal=OWNER,workspace=str(tmp_path),
                       source_sha256=sha,enabled=True,expected_revision=0)
    posted=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass  # Keep test request and headers out of console/logs.

        def do_POST(self):
            status=200
            response=None
            try:
                if (self.headers.get("Origin") != "chrome-extension://"+EXT
                        or self.headers.get("Authorization") != TEST_BEARER
                        or self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}"):
                    raise PermissionError("non-enrolled extension ingress")
                size=int(self.headers.get("Content-Length","0"))
                if size<1 or size>65536:
                    raise ValueError("bounded HTTP V2 ingress only")
                data=json.loads(self.rfile.read(size))
                response=dispatch_authenticated_v2(
                    service=evidence,path=self.path,payload=data,
                    extension_id=EXT,source_sha256=sha,worker=WORKER,
                    # Hermetic host worker registry: only TAB-77 belongs to
                    # this enrolled extension. Production must use relay proof.
                    authorized_worker=lambda ext,wrk: ext==EXT and wrk==WORKER)
                posted.append((self.path,data))
                if self.path==OBSERVE:
                    try:
                        evidence.chat_access.require_exact_message(OWNER,REQ,MSG)
                        access=True
                    except PermissionError:
                        access=False
                    posted.append(("gate_state",access))
            except (PermissionError,ValueError,TypeError,KeyError):
                status=403
                response={"error":"invalid_or_unauthorized"}
            raw=json.dumps(response).encode()
            self.send_response(status)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    task=threading.Thread(target=server.serve_forever,daemon=True)
    task.start()
    try:
        yield (server.server_port,evidence,posted,sha)
    finally:
        server.shutdown()
        task.join(timeout=3)
        server.server_close()


def post(port,path,payload,*,origin="chrome-extension://"+EXT,
         bearer=TEST_BEARER):
    request=Request(f"http://127.0.0.1:{port}{path}",
                    data=json.dumps(payload).encode(),method="POST",
                    headers={"Origin":origin,"Authorization":bearer,
                             "Content-Type":"application/json"})
    try:
        with urlopen(request,timeout=3) as reply:
            return reply.status,json.loads(reply.read())
    except HTTPError as exc:
        return exc.code,json.loads(exc.read())


def test_real_mv3_producer_transport_v2_challenge_observe_deny(
        v2_http, tmp_path):
    node=shutil.which("node")
    if node is None:
        pytest.skip("Node test-only MV3 execution harness unavailable")
    port,evidence,posted,sha=v2_http
    cmd=[node,str(Path(__file__).with_name("sentra_cos_mv3_http_v2.cjs")),
         str(port)]
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=18,
                          cwd=ROOT)
    assert result.returncode==0, result.stderr
    trace=json.loads(next(line.partition("=")[2] for line in
        result.stdout.splitlines() if line.startswith("SENTRA_MV3_HTTP=")))
    assert trace["challenge"] and trace["observed"] and trace["recovered"]
    assert trace["worker"]==WORKER
    assert trace["message_id"]==MSG and trace["request_id"]==REQ
    assert [x[0] for x in posted if x[0]!="gate_state"] == [
        CHALLENGE,OBSERVE,CHALLENGE,OBSERVE,INVALIDATE]
    # Global profile poison prevents the restarted MV3 from challenging
    # a new document after an ACK of the logout invalidation.
    assert [v for k,v in posted if k=="gate_state"] == [True,False]
    assert posted[0][1]["identity_epoch"]==trace["identity_epoch"]
    assert posted[0][1]["document_id"]==trace["document_id"]
    assert posted[-1][1]["reason"]=="signed_out"
    assert posted[-1][1]["source_sha256"]==sha
    assert set(posted[-1][1])=={
        "worker","document_id","identity_epoch","reason","source_sha256"}
    with pytest.raises(PermissionError):
        evidence.chat_access.require_exact_message(OWNER,REQ,MSG)
    restarted=BrowserEvidenceService(tmp_path)
    with pytest.raises(PermissionError):
        restarted.chat_access.require_allowed(OWNER,REQ)
    with restarted.store.connect("chat_access") as db:
        rec=db.execute("SELECT reason FROM browser_revoked_documents WHERE "
                       "extension_id=? AND worker=? AND document_id=?",
                       (EXT,WORKER,trace["document_id"])).fetchone()
        assert rec["reason"]=="signed_out"
    dumped=json.dumps(trace).lower()
    for prohibited in ("cookie","password","bearer","email","secret"):
        assert prohibited not in dumped


def test_host_http_v2_rejects_untrusted_origin_build_worker_epoch(v2_http):
    port,evidence,posted,sha=v2_http
    original=dict(source_sha256=sha,worker=WORKER,
                  document_id="document-abc123456",
                  identity_epoch="epoch-123456789")
    status,_=post(port,CHALLENGE,original,origin="https://chatgpt.com")
    assert status==403
    status,_=post(port,CHALLENGE,original,bearer="Bearer unknown")
    assert status==403
    status,_=post(port,CHALLENGE,{**original,"source_sha256":"0"*64})
    assert status==403
    status,_=post(port,CHALLENGE,{**original,"worker":"TAB-900"})
    assert status==403
    status,_=post(port,CHALLENGE,{k:v for k,v in original.items()
                                  if k!="identity_epoch"})
    assert status==403
    status,first=post(port,CHALLENGE,original)
    assert status==200 and first["nonce"]
    status,_=post(port,OBSERVE,dict(source_sha256=sha,worker=WORKER,
        evidence={"nonce":first["nonce"],
                  "document_id":original["document_id"],
                  "identity_epoch":"epoch-tampered123",
                  "conversation_id":CHAT,"route_conversation_id":CHAT,
                  "state":"idle","requests":[]}))
    assert status==403
    status,_=post(port,INVALIDATE,{**original,"identity_epoch":"epoch-wrong123",
                                    "reason":"signed_out"})
    assert status==403
    status,_=post(port,INVALIDATE,{**original,"reason":"signed_out"})
    # The host has not observed this challenge; it returns absent and MUST
    # NOT be mistaken by the MV3 producer for confirmed revocation.
    assert status==200
    assert posted[-1][1]["identity_epoch"]==original["identity_epoch"]


def test_uncertain_account_poison_is_profile_wide_and_persistent(tmp_path):
    """An idle DOM after logout cannot restore authorization in another tab."""
    sha=json.loads((ROOT/"edge_extension/manifest.json").read_text(
        encoding="utf-8"))["sentra_source_hash"]
    be=BrowserEvidenceService(tmp_path)
    be.configure(extension_id=EXT,principal=OWNER,workspace=str(tmp_path),
                 source_sha256=sha,enabled=True,expected_revision=0)
    def scan(worker,doc,epoch,chat,req,msg):
        auth=dict(extension_id=EXT,source_sha256=sha,worker=worker)
        nonce=be.challenge(**auth,document_id=doc,
                           identity_epoch=epoch)["nonce"]
        be.observe(**auth,evidence=dict(
            nonce=nonce,document_id=doc,identity_epoch=epoch,
            conversation_id=chat,route_conversation_id=chat,
            state="idle",requests=[{"request_id":req,"message_id":msg}]))
        return auth
    a=scan("TAB-11","document-first123","epoch-first123",
           "conversation-first123","request-first123","message-first123")
    scan("TAB-22","document-second123","epoch-second123",
         "conversation-second123","request-second123","message-second123")
    assert be.chat_access.require_exact_message(
        OWNER,"request-second123","message-second123")["allowed"]
    be.invalidate_document(**a,document_id="document-first123",
                           identity_epoch="epoch-first123",reason="profile_changed")
    with pytest.raises(PermissionError,match="profile or account"):
        be.chat_access.require_exact_message(
            OWNER,"request-second123","message-second123")
    assert be.dispatch_state(OWNER,"conversation-second123")["send_blocked"]
    assert be.dispatch_state(OWNER,"conversation-second123")["state"]=="identity_unknown"
    # Even a new observed document/new collector revision cannot silently
    # clear account uncertainty. Independent host proof is not present.
    scan("TAB-22","document-third123","epoch-third123",
         "conversation-second123","request-third123","message-third123")
    be.configure(extension_id=EXT,principal=OWNER,workspace=str(tmp_path),
                 source_sha256=sha,enabled=True,expected_revision=1)
    with pytest.raises(PermissionError,match="profile or account"):
        BrowserEvidenceService(tmp_path).chat_access.require_exact_message(
            OWNER,"request-third123","message-third123")
    with BrowserEvidenceService(tmp_path).store.connect("chat_access") as db:
        assert db.execute("SELECT reason FROM browser_profile_uncertainty "
                          "WHERE principal=? AND extension_id=?",
                          (OWNER,EXT)).fetchone()["reason"]=="profile_changed"


def test_v2_adapter_requires_host_verified_worker_not_client_claim(tmp_path):
    sha=json.loads((ROOT/"edge_extension/manifest.json").read_text(
        encoding="utf-8"))["sentra_source_hash"]
    be=BrowserEvidenceService(tmp_path)
    be.configure(extension_id=EXT,principal=OWNER,workspace=str(tmp_path),
                 source_sha256=sha,enabled=True,expected_revision=0)
    payload=dict(source_sha256=sha,worker=WORKER,
                 document_id="document-worker123",identity_epoch="epoch-worker123")
    with pytest.raises(PermissionError,match="host ownership"):
        dispatch_authenticated_v2(
            service=be,path=CHALLENGE,payload=payload,
            extension_id=EXT,source_sha256=sha,worker=WORKER,
            authorized_worker=lambda extension,worker: False)
    with be.store.connect("chat_access") as db:
        assert db.execute("SELECT COUNT(*) FROM browser_challenges").fetchone()[0]==0
