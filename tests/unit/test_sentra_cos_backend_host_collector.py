"""Opt-in Electron host collector; public Edge validators remain strict."""
import pytest

from native_bridge.web_send import WebSendConflict
from test_sentra_cos_backend_web_send import backend, OWNER, SOURCE, DOC, EPOCH, CHAT, REQUEST, USER, lease, receipt_args


COLLECTOR = "sentra-committed-account-menu-v1"
SURFACE = "electron-surface-physical-713"
WORKER = "electron-worker-physical-713"


def configure(control, workspace, **overrides):
    return control.browser_evidence.configure_host(**{
        "kind": "electron", "collector_id": COLLECTOR, "source_sha256": SOURCE,
        "principal": "local-operator", "workspace": workspace, "surface_id": SURFACE,
        "worker": WORKER, "enabled": True, "expected_revision": 0, **overrides})


def observe(control):
    challenge = control.browser_evidence.challenge_host(collector_id=COLLECTOR, source_sha256=SOURCE,
        surface_id=SURFACE, worker=WORKER, document_id=DOC, identity_epoch=EPOCH)
    evidence = {"nonce": challenge["nonce"], "document_id": DOC, "identity_epoch": EPOCH,
                "conversation_id": CHAT, "route_conversation_id": CHAT, "state": "idle",
                "requests": [{"request_id": REQUEST, "message_id": USER}]}
    control.browser_evidence.observe_host(collector_id=COLLECTOR, source_sha256=SOURCE,
        surface_id=SURFACE, worker=WORKER, evidence=evidence)
    return evidence


def test_host_collector_real_ids_use_existing_receipt_and_fence(backend):
    d, _, control, jobs, api, p, _ = backend
    result = configure(control, p["workspace"])
    assert result["kind"] == "electron" and result["grants_created"] is False
    assert control.browser_evidence.browser_principal_for(WORKER, collector_id=COLLECTOR,
        source_sha256=SOURCE, surface_id=SURFACE) == "local-operator"
    with pytest.raises(PermissionError):
        control.browser_evidence.browser_principal_for(WORKER, surface_id="other-surface")
    observe(control)
    exact = control.chat_access.require_exact_message("local-operator", REQUEST, USER)
    assert exact["source"] == "proven" and exact["conversation_id"] == CHAT
    job_id = api.admit(OWNER, **{**p, "target_worker": WORKER})["job_id"]
    claim = api.claim(OWNER, job_id, worker=WORKER)
    authority = lease(d, p, worker=WORKER)
    api.pre_send(OWNER, job_id, worker=WORKER, lease_token=claim["lease_token"],
                 resource_key=authority["resource_key"], fencing_token=authority["fencing_token"])
    receipt = {**receipt_args(claim), "worker": WORKER, "extension_id": COLLECTOR}
    assert api.receipt(OWNER, job_id, **receipt)["state"] == "SENT"
    with control.store.connect("session_checkpoint") as db:
        assert db.execute("SELECT count(*) FROM authenticated_web_receipts WHERE job_id=?", (job_id,)).fetchone()[0] == 1
    with control.store.connect("chat_access") as db:
        bound = db.execute("SELECT extension_id,kind FROM browser_collectors WHERE extension_id=?", (COLLECTOR,)).fetchone()
        assert tuple(bound) == (COLLECTOR, "electron")
        assert db.execute("SELECT worker FROM browser_documents WHERE extension_id=?", (COLLECTOR,)).fetchone()[0] == WORKER
    assert jobs.counts()["submitted"] == 1
    control.browser_evidence.invalidate_host(collector_id=COLLECTOR, source_sha256=SOURCE,
        surface_id=SURFACE, worker=WORKER, document_id=DOC, identity_epoch=EPOCH, reason="account_changed")
    assert api.status(OWNER, job_id)["state"] == "UNCONFIRMED"
    with pytest.raises(PermissionError):
        api.receipt(OWNER, job_id, **receipt)
    with pytest.raises(WebSendConflict):
        api.claim(OWNER, job_id, worker=WORKER)


def test_host_surface_build_epoch_and_public_edge_boundaries(backend):
    _, _, control, _, _, p, _ = backend
    service = control.browser_evidence
    with pytest.raises(PermissionError):
        service.challenge_host(collector_id=COLLECTOR, source_sha256=SOURCE,
            surface_id=SURFACE, worker=WORKER, document_id=DOC, identity_epoch=EPOCH)
    configure(control, p["workspace"])
    for altered in ({"surface_id": "foreign-surface"}, {"worker": "foreign-worker"}, {"source_sha256": "0" * 64}):
        with pytest.raises(PermissionError):
            service.challenge_host(**{ "collector_id": COLLECTOR, "source_sha256": SOURCE,
                "surface_id": SURFACE, "worker": WORKER, "document_id": DOC, "identity_epoch": EPOCH, **altered})
    with pytest.raises(ValueError):
        service.challenge(extension_id=COLLECTOR, source_sha256=SOURCE, worker=WORKER, document_id=DOC)
    with pytest.raises(ValueError):
        service.configure(extension_id=COLLECTOR, source_sha256=SOURCE, principal="local-operator",
                          workspace=p["workspace"], enabled=True, expected_revision=1)
    evidence = observe(control)
    with pytest.raises(ValueError):
        service.observe(extension_id=COLLECTOR, source_sha256=SOURCE, worker=WORKER, evidence=evidence)
    with pytest.raises(PermissionError):
        service.challenge_host(collector_id=COLLECTOR, source_sha256=SOURCE, surface_id=SURFACE,
            worker=WORKER, document_id=DOC, identity_epoch="different-identity-epoch")
    with pytest.raises(PermissionError):
        configure(control, p["workspace"], expected_revision=1, surface_id="other-real-surface")
