"""Native ChatGPT Web binary tests: synthetic PNG fixture, not a site receipt."""
import base64
import hashlib
import io
import sqlite3
from types import SimpleNamespace

import pytest
from PIL import Image

from native_bridge.web_generated_assets import WebGeneratedAssets, _asset_id
from test_shell_dot_features import shell


JOB = "websend_" + "1" * 64
USER = "remote-user-1234"
ASSISTANT = "remote-assistant-1234"
CONV = "remote-conversation-1234"
REQUEST = "remote-request-1234"
DOCUMENT = "remote-document-1234"
EPOCH = "remote-epoch-1234"
FILE = "file-nativegenerated1234"
OWNER = "the-owner"
WORKER = "TAB-42"
LEASE = "the-original-lease"
EXTENSION = "abcdefghijklmnopabcdefghijklmnop"
SOURCE = "a" * 64


class FakeStore:
    def __init__(self, filename):
        self.filename = str(filename)

    def connect(self, namespace):
        assert namespace == "session_checkpoint"
        db = sqlite3.connect(self.filename)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db


class FakeRelay:
    def __init__(self):
        self.bound = {"job_id": JOB, "owner":OWNER, "run_id":"run-12345678",
                      "work_item_id":"work-12345678", "operation_id":"op-12345678",
                      "worker":WORKER, "send_fence":1}
        self.enabled = True
        self.answered = True
        self.web_send = SimpleNamespace(
            binding=lambda job: self.bound if job == JOB else None,
            _authority=self.authority,
            _collector=self.collector,
            receipts=SimpleNamespace(require_attested=self.attested,
                                     prove_message=self.prove),
            status=self.status)

    def _original_worker(self, job_id, worker, lease_token):
        if (job_id,worker,lease_token) != (JOB,WORKER,LEASE):
            raise PermissionError("original worker lease required")

    def authority(self, bound, effect=False):
        if not self.enabled or bound is not self.bound:
            raise PermissionError("original grant revoked")

    def collector(self, extension_id, source_sha256):
        if (extension_id,source_sha256) != (EXTENSION,SOURCE):
            raise PermissionError("collector source changed")
        return "principal-12345678"

    def delivery_status(self, job_id):
        return {"state":"sent","receipt":{"conversation_id":CONV,
                                             "message_id":USER}}

    def attested(self, owner, *, run_id, job_id, evidence):
        if owner != OWNER or run_id != self.bound["run_id"] or job_id != JOB:
            raise PermissionError("attested receipt mismatch")
        return {"request_id":REQUEST}

    def prove(self, **kwargs):
        if ((kwargs["request_id"],kwargs["worker"],kwargs["conversation_id"],
             kwargs["message_id"],kwargs["document_id"],kwargs["identity_epoch"],
             kwargs["extension_id"]) !=
            (REQUEST,WORKER,CONV,USER,DOCUMENT,EPOCH,EXTENSION)):
            raise PermissionError("committed parent proof mismatch")

    def status(self, owner, job_id):
        return {"state":"ANSWERED" if self.answered else "UNCONFIRMED",
                "answer_message_id":ASSISTANT}


def setup(tmp_path):
    relay = FakeRelay()
    control = SimpleNamespace(session_checkpoints=SimpleNamespace(
        store=FakeStore(tmp_path / "native-protected.sqlite3")))
    media = WebGeneratedAssets(control,relay)
    scope = dict(extension_id=EXTENSION, source_sha256=SOURCE,job_id=JOB,
                 worker=WORKER,lease_token=LEASE,request_id=REQUEST,
                 document_id=DOCUMENT,identity_epoch=EPOCH,
                 conversation_id=CONV,message_id=ASSISTANT,file_id=FILE)
    Image.MAX_IMAGE_PIXELS = 32_000_000
    image = Image.new("RGB",(17,19),(44,110,203))
    stream = io.BytesIO()
    image.save(stream,format="PNG")
    raw = stream.getvalue()
    sha = lambda content: hashlib.sha256(content).hexdigest()
    descriptor = dict(mime_type="image/png",
                      filename="chatgpt-native-" + sha(FILE.encode())[:16] + ".png",
                      byte_length=len(raw),sha256=sha(raw))
    return media,relay,scope,descriptor,raw


def send_all(media,scope,descriptor,raw):
    for index,offset in enumerate(range(0,len(raw),65536)):
        part=raw[offset:offset+65536]
        media.chunk(**scope,**descriptor,part=index,
                    chunk_sha256=hashlib.sha256(part).hexdigest(),
                    data_base64=base64.b64encode(part).decode())


def test_native_binary_is_protected_finalized_and_readable_for_original_scope(tmp_path):
    media,relay,scope,descriptor,raw = setup(tmp_path)
    media.declare(owner=OWNER,job_id=JOB,conversation_id=CONV,
                  message_id=ASSISTANT,file_ids=[FILE])
    assert media.ready_for_job(owner=OWNER,job_id=JOB,
                               conversation_id=CONV,message_id=ASSISTANT) is False
    send_all(media,scope,descriptor,raw)
    assert media.ready_for_job(owner=OWNER,job_id=JOB,
                               conversation_id=CONV,message_id=ASSISTANT) is False
    assert media.finalize(**scope)["sha256"] == descriptor["sha256"]
    assert media.finalize(**scope)["replayed"] is True
    assert media.ready_for_job(owner=OWNER,job_id=JOB,
                               conversation_id=CONV,message_id=ASSISTANT) is True
    asset_id=_asset_id(JOB,ASSISTANT,FILE)
    manifest,received=media.read(owner=OWNER,operation_id="op-12345678",asset_id=asset_id)
    assert received==raw
    assert manifest["message_id"]==ASSISTANT
    assert media.for_job(owner=OWNER,run_id="run-12345678",
                         work_item_id="work-12345678",operation_id="op-12345678",
                         job_id=JOB,conversation_id=CONV,message_id=ASSISTANT)[0]["asset_id"] == asset_id
    with pytest.raises(PermissionError):
        media.read(owner="other-owner",operation_id="op-12345678",asset_id=asset_id)
    with pytest.raises(PermissionError):
        media.read(owner=OWNER,operation_id="other-op",asset_id=asset_id)
    with media.store.connect("session_checkpoint") as db:
        protected = db.execute("SELECT protected_bytes FROM web_native_generated_chunks").fetchone()[0]
        assert protected.startswith(("dpapi:","keyring:"))
        assert base64.b64encode(raw).decode() not in protected


def test_native_asset_needs_declared_final_receipt_and_exact_bound_collector(tmp_path):
    media,relay,scope,descriptor,raw = setup(tmp_path)
    part=dict(part=0,chunk_sha256=hashlib.sha256(raw).hexdigest(),
              data_base64=base64.b64encode(raw).decode())
    with pytest.raises(PermissionError,match="not declared"):
        media.chunk(**scope,**descriptor,**part)
    media.declare(owner=OWNER,job_id=JOB,conversation_id=CONV,
                  message_id=ASSISTANT,file_ids=[FILE])
    for field,value in [
        ("worker","TAB-99"),("lease_token","different-lease"),
        ("extension_id","other-collector"),("source_sha256","other-build"),
        ("request_id","different-request"),("document_id","other-document"),
        ("identity_epoch","different-epoch"),("conversation_id","other-conversation"),
        ("message_id","other-assistant")]:
        with pytest.raises((PermissionError,ValueError)):
            media.chunk(**{**scope,field:value},**descriptor,**part)
    relay.answered=False
    with pytest.raises(PermissionError,match="final assistant"):
        media.chunk(**scope,**descriptor,**part)
    relay.answered=True
    relay.enabled=False
    with pytest.raises(PermissionError,match="revoked"):
        media.chunk(**scope,**descriptor,**part)


def test_native_asset_replay_conflict_incomplete_and_uncertain(tmp_path):
    media,relay,scope,descriptor,raw = setup(tmp_path)
    media.declare(owner=OWNER,job_id=JOB,conversation_id=CONV,
                  message_id=ASSISTANT,file_ids=[FILE])
    assert media.declare(owner=OWNER,job_id=JOB,conversation_id=CONV,
                         message_id=ASSISTANT,file_ids=[FILE]) is None
    with pytest.raises(PermissionError,match="replay changed"):
        media.declare(owner=OWNER,job_id=JOB,conversation_id=CONV,
                      message_id=ASSISTANT,file_ids=[])
    part=dict(part=0,chunk_sha256=hashlib.sha256(raw).hexdigest(),
              data_base64=base64.b64encode(raw).decode())
    assert media.chunk(**scope,**descriptor,**part)["replayed"] is False
    assert media.chunk(**scope,**descriptor,**part)["replayed"] is True
    with pytest.raises((PermissionError,ValueError)):
        media.chunk(**scope,**{**descriptor,"sha256":"0"*64},**part)
    with pytest.raises(ValueError,match="integrity"):
        media.chunk(**scope,**descriptor,**{**part,"chunk_sha256":"0"*64})
    # Declaring a second file makes the final answer UNCERTAIN for canvas
    # publication until ALL declared native files are finalized.
    second="file-nativegenerated5678"
    other,_,_,_,_=setup(tmp_path)
    with pytest.raises(PermissionError,match="replay changed"):
        other.declare(owner=OWNER,job_id=JOB,conversation_id=CONV,
                      message_id=ASSISTANT,file_ids=[FILE,second])
    assert media.ready_for_job(owner=OWNER,job_id=JOB,
                               conversation_id=CONV,message_id=ASSISTANT) is False
    media.finalize(**scope)
    assert media.ready_for_job(owner=OWNER,job_id=JOB,
                               conversation_id=CONV,message_id=ASSISTANT) is True


def test_native_binary_rejects_page_urls_and_forged_format(tmp_path):
    media,relay,scope,descriptor,raw = setup(tmp_path)
    media.declare(owner=OWNER,job_id=JOB,conversation_id=CONV,
                  message_id=ASSISTANT,file_ids=[FILE])
    part=dict(part=0,chunk_sha256=hashlib.sha256(raw).hexdigest(),
              data_base64=base64.b64encode(raw).decode())
    with pytest.raises(ValueError,match="canonical"):
        media.chunk(**{**scope,"file_id":"https://evil.example/image.png"},**descriptor,**part)
    with pytest.raises(ValueError,match="canonical"):
        media.chunk(**scope,**{**descriptor,"mime_type":"image/svg+xml"},**part)
    with pytest.raises(ValueError,match="canonical"):
        media.chunk(**scope,**{**descriptor,"filename":"../../image.png"},**part)
    send_all(media,scope,descriptor,raw)
    with media.store.connect("session_checkpoint") as db:
        # Test tampering in a disposable test DB, never on a real Grant/WorkItem.
        db.execute("UPDATE web_native_generated_chunks SET sha256=?",
                   ("0"*64,))
        db.commit()
    with pytest.raises(ValueError,match="protected chunk changed"):
        media.finalize(**scope)


def test_authenticated_relay_http_chunk_finalize_and_denied_origins(tmp_path):
    """Ephemeral test-only HTTP relay, not a running SENTRA service or real Web result."""
    import json
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    from native_bridge.relay import make_handler

    media,relay,scope,descriptor,raw=setup(tmp_path)
    media.declare(owner=OWNER,job_id=JOB,conversation_id=CONV,
                  message_id=ASSISTANT,file_ids=[FILE])
    state=SimpleNamespace(browser_evidence=object(),generated_assets=media,
                          extension_version=lambda: {"source_hash":SOURCE})
    server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(state,"test-only-bearer"))
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    endpoint=f"http://127.0.0.1:{server.server_port}"
    part=dict(part=0,chunk_sha256=hashlib.sha256(raw).hexdigest(),
              data_base64=base64.b64encode(raw).decode())
    def post(route,body,*,origin="chrome-extension://"+EXTENSION,token="test-only-bearer"):
        wire={key:value for key,value in body.items() if key != 'extension_id'}
        request=urllib.request.Request(endpoint+route,data=json.dumps(wire).encode(),
            headers={"Origin":origin,"Authorization":"Bearer "+token,
                     "Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(request,timeout=3) as response:
            return json.load(response)
    try:
        with pytest.raises(urllib.error.HTTPError) as denied:
            post("/jobs/generated-asset/chunk",{**scope,**descriptor,**part},
                 origin="https://chatgpt.com")
        assert denied.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as denied:
            post("/jobs/generated-asset/chunk",{**scope,**descriptor,**part},
                 token="incorrect")
        assert denied.value.code == 401
        with pytest.raises(urllib.error.HTTPError) as denied:
            post("/jobs/generated-asset/chunk",{**scope,**descriptor,**part},
                 origin="chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        assert denied.value.code == 403
        receipt=post("/jobs/generated-asset/chunk",{**scope,**descriptor,**part,"source_sha256":SOURCE})
        assert receipt["asset_id"] == _asset_id(JOB,ASSISTANT,FILE)
        assert "data_base64" not in receipt
        final=post("/jobs/generated-asset/finalize",{**scope,"source_sha256":SOURCE})
        assert final["byte_length"] == len(raw) and final["sha256"] == descriptor["sha256"]
        assert final["type"] == "sentra.generated_asset"
        assert (final["operation_id"],final["conversation_id"],final["message_id"]) == (
            "op-12345678",CONV,ASSISTANT)
        assert media.read(owner=OWNER,operation_id="op-12345678",
                          asset_id=receipt["asset_id"])[1] == raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_fenced_native_image_is_not_readable(tmp_path):
    media, _relay, scope, descriptor, raw = setup(tmp_path)
    media.declare(owner=OWNER, job_id=JOB, conversation_id=CONV,
                  message_id=ASSISTANT, file_ids=[FILE])
    send_all(media, scope, descriptor, raw)
    media.finalize(**scope)
    asset_id = _asset_id(JOB, ASSISTANT, FILE)
    media._write_fence(owner=OWNER, job_id=JOB, operation_id="op-12345678",
                       reason="integrity_mismatch", allow_finalized=True)
    with pytest.raises(PermissionError, match="UNCERTAIN_NO_RESEND"):
        media.read(owner=OWNER, operation_id="op-12345678", asset_id=asset_id)
    assert media.fenced_asset_ids(OWNER, [asset_id, "cli-asset"]) == {asset_id}
    assert media.for_job(owner=OWNER, run_id="run-12345678", work_item_id="work-12345678",
                         operation_id="op-12345678", job_id=JOB, conversation_id=CONV,
                         message_id=ASSISTANT) == []


def test_canvas_http_reads_only_confirmed_native_web_file(shell,monkeypatch):
    """Disposable Canvas fixture: synthetic native bytes traversing the real HTTP consumer."""
    import time
    import urllib.error
    import urllib.request
    from urllib.parse import urlencode
    from test_shell_generated_media import prepare
    from native_bridge.web_send import WebSendAuthority
    from native_bridge.job_store import JobStore
    from sentra_canvas.shell_generated_media import ShellGeneratedMedia
    from sentra_core.conversations import _encode

    (app,server,scope,call,actor,cid,runtime,turn,native,provider_store,
     provider_asset_id,message,payload,raw)=prepare(shell,monkeypatch)
    temp_jobs=JobStore(":memory:")
    try:
        WebSendAuthority(runtime.control,temp_jobs)
        store=WebGeneratedAssets(runtime.control)
        job_id=JOB
        aid=_asset_id(job_id,ASSISTANT,FILE)
        sha=lambda content: hashlib.sha256(content).hexdigest()
        manifest=dict(transport="authenticated-browser-download-v1",request_id=REQUEST,
                      conversation_id=CONV,message_id=ASSISTANT,file_id=FILE,
                      filename="chatgpt-native-"+sha(FILE.encode())[:16]+".png",
                      mime_type="image/png",byte_length=len(raw),sha256=sha(raw))
        workspace=app.store.workspace(scope['project_id'])['path']
        now=time.time()
        with runtime.control.store.connect("session_checkpoint") as db,db:
            db.execute("""INSERT INTO web_send_intents
                (job_id,owner,request_identity_sha256,submission_index,run_id,operation_id,
                 work_item_id,principal_id,grant_id,workspace,conversation_key,intent_sha256,
                 prompt_sha256,stage,send_fence,worker,answer_message_id,answer_revision,created,updated)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id,runtime.owner,"1"*64,0,message["run_id"],message["operation_id"],
                 message["work_item_id"],actor["agent_id"],"local-test-grant",workspace,
                 cid,"2"*64,"3"*64,"ANSWERED",1,WORKER,ASSISTANT,1,now,now))
            db.execute("""INSERT INTO authenticated_web_receipts
                (job_id,owner,run_id,workspace,browser_principal,request_id,
                 worker,conversation_id,message_id,receipt_sha256,attested_at,identity_epoch)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id,runtime.owner,message["run_id"],workspace,"test-principal",
                 REQUEST,WORKER,CONV,USER,"4"*64,now,EPOCH))
            db.execute("INSERT INTO web_native_generated_assets VALUES(?,?,?,?,?,?,?,?,?,1)",
                (aid,job_id,runtime.owner,message["run_id"],message["work_item_id"],
                 message["operation_id"],CONV,ASSISTANT,
                 JobStore._seal(manifest,aid,"native_manifest")))
            db.execute("INSERT INTO web_native_generated_chunks VALUES(?,?,?,?)",
                (aid,0,sha(raw),JobStore._seal(
                    {"base64":base64.b64encode(raw).decode()},aid,"native_chunk:0")))
        with runtime.control.store.connect("shell") as db,db:
            db.execute("INSERT INTO canvas_shell_web_turns VALUES(?,?,?,?,?,?)",
                (message["operation_id"],runtime.owner,scope["project_id"],cid,
                 _encode({"message":message,"dot":actor}),job_id))
        runtime.conversations.provider_state(cid,turn,'gateway',native,'completed')
        runtime.conversations.finish_response(cid,turn,'')
        runtime.control.durable.update_operation(message['operation_id'],runtime.owner,state='RUNNING')
        runtime._publish_answer(message,'Native image response','web:'+job_id+':'+ASSISTANT,
                                evidence={'web_attested_final':True})
        records=call('message_list',conversation_id=cid)['items']
        assistant=next(record for record in records if record['role']=='assistant')
        assert aid in {item['asset_id'] for item in assistant['generated_assets']}
        values={**scope,'conversation_id':cid,'message_id':assistant['message_id'],'asset_id':aid}
        url=f'http://127.0.0.1:{server.server_port}/api/shell/generated-media?'+urlencode(values)
        req=urllib.request.Request(url,headers={'Authorization':'Bearer '+server.secret})
        with urllib.request.urlopen(req,timeout=3) as response:
            assert response.headers['Content-Type']=='image/png'
            assert response.headers['X-Content-Type-Options']=='nosniff'
            assert response.read()==raw
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(url,timeout=3)
        assert denied.value.code==401
        wrong={**values,'conversation_id':call(
            'conversation_create',dot_id=actor['dot_id'])['conversation_id']}
        req=urllib.request.Request(
            f'http://127.0.0.1:{server.server_port}/api/shell/generated-media?'+urlencode(wrong),
            headers={'Authorization':'Bearer '+server.secret})
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(req,timeout=3)
        assert denied.value.code==403
    finally:
        temp_jobs.close()


def test_multiple_declared_native_files_keep_uncertain_turn_unpublished(tmp_path):
    media,relay,scope,descriptor,raw=setup(tmp_path)
    additional="file-nativegenerated5678"
    media.declare(owner=OWNER,job_id=JOB,conversation_id=CONV,
                  message_id=ASSISTANT,file_ids=[FILE,additional])
    send_all(media,scope,descriptor,raw)
    media.finalize(**scope)
    assert media.ready_for_job(owner=OWNER,job_id=JOB,
                               conversation_id=CONV,message_id=ASSISTANT) is False
    assert media.for_job(owner=OWNER,run_id="run-12345678",
                         work_item_id="work-12345678",operation_id="op-12345678",
                         job_id=JOB,conversation_id=CONV,message_id=ASSISTANT)
    with pytest.raises(PermissionError):
        media.read(owner=OWNER,operation_id="op-12345678",
                   asset_id=_asset_id(JOB,ASSISTANT,additional))
    # A completed transfer is insufficient: the Canvas observation gate
    # must keep this operation unpublished until every expected file arrives.
