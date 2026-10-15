"""Front 6 contract: bytes, MIME, size and SHA-256, or it is not a delivered image.

ADMITTED without a binary is not success. UNCERTAIN_NO_RESEND is not resent.
The PNG below is a synthetic fixture, not a ChatGPT Web capture.
"""
import base64
import hashlib
import io
import sqlite3
from types import SimpleNamespace

from PIL import Image

from native_bridge.shell_multimodal import dispatch_shell_turn, project_native_image
from native_bridge.web_generated_assets import ADMITTED, UNCERTAIN_NO_RESEND, VERIFIED, WebGeneratedAssets
import pytest


JOB = "websend_" + "b" * 64
OWNER = "iris-owner"
RUN = "run-12345678"
WORK = "work-12345678"
OPERATION = "op-12345678"
CONV = "remote-conversation-1234"
USER = "remote-user-1234"
ASSISTANT = "remote-assistant-1234"
REQUEST = "remote-request-1234"
DOCUMENT = "remote-document-1234"
EPOCH = "remote-epoch-1234"
FILE = "file-nativegenerated1234"
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
        self.bound = {"job_id": JOB, "owner": OWNER, "run_id": RUN, "work_item_id": WORK,
                      "operation_id": OPERATION, "worker": WORKER, "send_fence": 1}
        self.enabled = True
        self.answered = True
        self.web_send = SimpleNamespace(
            binding=lambda job: self.bound if job == JOB else None,
            _authority=lambda bound, effect=False: None,
            _collector=lambda extension_id, source: "principal-12345678",
            receipts=SimpleNamespace(
                require_attested=lambda owner, run_id, job_id, evidence: {"request_id": REQUEST},
                prove_message=lambda **_kwargs: None),
            status=lambda owner, job_id: {"state": "ANSWERED", "answer_message_id": ASSISTANT})

    def _original_worker(self, job_id, worker, lease_token):
        if (job_id, worker, lease_token) != (JOB, WORKER, LEASE):
            raise PermissionError("original worker lease required")

    def delivery_status(self, job_id):
        return {"state": "sent", "receipt": {"conversation_id": CONV, "message_id": USER}}


def _media(tmp_path):
    relay = FakeRelay()
    control = SimpleNamespace(session_checkpoints=SimpleNamespace(
        store=FakeStore(tmp_path / "native.sqlite3")))
    media = WebGeneratedAssets(control, relay)
    scope = dict(extension_id=EXTENSION, source_sha256=SOURCE, job_id=JOB, worker=WORKER,
                 lease_token=LEASE, request_id=REQUEST, document_id=DOCUMENT,
                 identity_epoch=EPOCH, conversation_id=CONV, message_id=ASSISTANT, file_id=FILE)
    image = Image.new("RGB", (8, 6), (20, 40, 60))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    raw = stream.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    descriptor = dict(mime_type="image/png",
                      filename="chatgpt-native-" + hashlib.sha256(FILE.encode()).hexdigest()[:16] + ".png",
                      byte_length=len(raw), sha256=digest)
    return media, scope, descriptor, raw, digest


def _verdict(media):
    return media.verdict(owner=OWNER, run_id=RUN, work_item_id=WORK, operation_id=OPERATION,
                         job_id=JOB, conversation_id=CONV, message_id=ASSISTANT)


def _send(media, scope, descriptor, raw):
    media.chunk(**scope, **descriptor, part=0, chunk_sha256=hashlib.sha256(raw).hexdigest(),
                data_base64=base64.b64encode(raw).decode())
    return media.finalize(**scope)


def test_admitted_without_binary_is_not_success_and_uncertain_is_not_resent(tmp_path):
    media, scope, descriptor, raw, _digest = _media(tmp_path)
    media.declare(owner=OWNER, job_id=JOB, conversation_id=CONV, message_id=ASSISTANT, file_ids=[FILE])
    admitted = _verdict(media)
    assert admitted["status"] == ADMITTED and admitted["success"] is False
    assert admitted["generated_asset_verified"] is False and admitted["assets"] == []
    assert project_native_image(admitted)["status"] == ADMITTED
    assert project_native_image(admitted)["success"] is False
    fence = media.mark_uncertain(owner=OWNER, job_id=JOB, operation_id=OPERATION, reason="transfer_failed")
    assert fence["status"] == UNCERTAIN_NO_RESEND and fence["automatic_resend"] is False
    assert media.mark_uncertain(owner=OWNER, job_id=JOB, operation_id=OPERATION,
                                reason="transfer_failed")["already_fenced"] is True
    with pytest.raises(ValueError, match="fence changed"):
        media.mark_uncertain(owner=OWNER, job_id=JOB, operation_id=OPERATION, reason="observation_timeout")
    with pytest.raises(PermissionError, match="UNCERTAIN_NO_RESEND"):
        media.chunk(**scope, **descriptor, part=0, chunk_sha256=hashlib.sha256(raw).hexdigest(),
                    data_base64=base64.b64encode(raw).decode())
    again = _verdict(media)
    assert again["status"] == UNCERTAIN_NO_RESEND and again["success"] is False
    assert again["generated_asset_verified"] is False and again["automatic_resend"] is False
    projected = project_native_image(again)
    assert projected["status"] == UNCERTAIN_NO_RESEND and projected["success"] is False


def test_verified_image_has_mime_size_and_sha256_and_a_broken_copy_stays_uncertain(tmp_path):
    media, scope, descriptor, raw, digest = _media(tmp_path)
    media.declare(owner=OWNER, job_id=JOB, conversation_id=CONV, message_id=ASSISTANT, file_ids=[FILE])
    receipt = _send(media, scope, descriptor, raw)
    assert receipt["mime_type"] == "image/png"
    assert receipt["byte_length"] == len(raw) and receipt["sha256"] == digest
    verdict = _verdict(media)
    assert verdict["status"] == VERIFIED and verdict["success"] is True
    assert verdict["generated_asset_verified"] is True
    assert verdict["run_id"] == RUN and verdict["work_item_id"] == WORK
    assert verdict["operation_id"] == OPERATION
    asset = verdict["assets"][0]
    assert asset["mime_type"] == "image/png" and asset["byte_length"] == len(raw) and asset["sha256"] == digest
    projected = project_native_image(verdict)
    assert projected["success"] is True and projected["assets"][0]["sha256"] == digest
    with pytest.raises(PermissionError, match="cannot be reclassified"):
        media.mark_uncertain(owner=OWNER, job_id=JOB, operation_id=OPERATION, reason="transfer_failed")
    with media.store.connect("session_checkpoint") as db:
        db.execute("UPDATE web_native_generated_chunks SET sha256=?", ("0" * 64,))
        db.commit()
    broken = _verdict(media)
    assert broken["status"] == UNCERTAIN_NO_RESEND and broken["success"] is False
    assert broken["generated_asset_verified"] is False
    stayed = _verdict(media)
    assert stayed["status"] == UNCERTAIN_NO_RESEND and stayed["automatic_resend"] is False
    with pytest.raises(PermissionError, match="UNCERTAIN_NO_RESEND"):
        media.finalize(**scope)
    assert project_native_image({"status": "VERIFIED", "generated_asset_verified": True,
                                 "success": True, "assets": [{"mime_type": "image/png"}]})["status"] == ADMITTED


def test_shell_admission_is_not_an_image_delivery():
    class Web:
        def admit(self, owner, **kwargs):
            self.kwargs = kwargs
            return {"job_id": JOB, "state": "ADMITTED", "send_fence": 1}

    web = Web()
    result = dispatch_shell_turn(
        None, None, None, web, owner="iris-owner", run_id=RUN, work_item_id=WORK,
        operation_id=OPERATION, principal_id="agent-iris", grant_id="grant-iris-1",
        workspace="ws-iris", conversation_id="conv-iris-1", request_identity="request-iris-1",
        prompt="describe the screen", attachments=[], operator_approved=True)
    assert result["admission_status"] == "ADMITTED"
    assert result["generated_asset_verified"] is False
    assert result["image_bytes_verified"] is False
    assert result["web_uploaded"] is False and result["automatic_resend"] is False
    assert web.kwargs["work_item_id"] == WORK and web.kwargs["grant_id"] == "grant-iris-1"
