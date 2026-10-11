"""Independent host/worker clocks commit in the same existing protected history DB."""
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from sentra_mcp.services.web_history_store import WebHistoryStore, WebHistoryConflict
from native_bridge.web_evidence_ingress import WebReceiptAttestationError
from test_sentra_cos_backend_web_send import (
    backend, start, observe, receipt_args, OWNER, WORKER, REQUEST, CHAT, DOC, EPOCH,
)


def proof(body, *, revision=1, state="partial", **changes):
    return {"revision": revision, "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "state": state, "collector_id": "host-message-collector", "source_sha256": "b" * 64,
            "document_id": DOC, "identity_epoch": EPOCH, **changes}


def record(history, body, *, central=2, host=1, state="partial", observation=None):
    return history.record_frame("owner-clock", "workspace-clock", conversation_id="conversation-clock",
        message_id="assistant-clock", revision=central, role="assistant", state=state, body=body,
        host_observation=observation if observation is not None else proof(body, revision=host, state=state))


def rows(history):
    with history.store.connect("provider_content") as db:
        message = dict(db.execute("SELECT * FROM web_history_messages").fetchone())
        observation = dict(db.execute("SELECT * FROM web_history_host_observations").fetchone())
    return message, observation


def test_independent_clocks_survive_restart_without_plaintext_or_extra_message(tmp_path):
    history = WebHistoryStore(tmp_path)
    assert record(history, "PRIVATE_HOST_STREAM", central=2, host=1)["revision"] == 2
    restored = WebHistoryStore(tmp_path)
    assert record(restored, "PRIVATE_HOST_STREAM", central=3, host=1)["revision"] == 3
    assert record(restored, "PRIVATE_HOST_FINAL", central=7, host=2, state="complete")["revision"] == 7
    final = WebHistoryStore(tmp_path)
    message, host = rows(final)
    assert message["revision"] == 7 and host["revision"] == 2
    assert host["body_sha256"] == message["body_sha256"] and host["state"] == "complete"
    assert message["protected_body"].startswith(("dpapi:", "keyring:"))
    assert "PRIVATE_HOST_FINAL" not in message["protected_body"]
    assert len(final.messages("owner-clock", "workspace-clock", "conversation-clock")) == 1
    # Host can observe a newer revision of the exact already finalized frame.
    assert record(final, "PRIVATE_HOST_FINAL", central=7, host=3, state="complete")["idempotent_replay"]
    assert rows(final)[1]["revision"] == 3


@pytest.mark.parametrize("change", ["revision", "body", "state", "collector_id", "source_sha256", "document_id", "identity_epoch", "missing"])
def test_host_regression_conflicts_and_source_swaps_preserve_original_frame(tmp_path, change):
    history = WebHistoryStore(tmp_path)
    record(history, "original partial", central=2, host=3)
    before = rows(history)
    observation = proof("original partial", revision=3)
    body, state = "original partial", "partial"
    if change == "revision":
        observation["revision"] = 2
    elif change == "body":
        body = "changed text"
        observation = proof(body, revision=3)
    elif change == "state":
        state = "complete"
        observation["state"] = state
    elif change == "missing":
        observation = None
    else:
        observation[change] = "c" * 64 if change == "source_sha256" else "different-host-source"
    with pytest.raises(WebHistoryConflict):
        WebHistoryStore(tmp_path).record_frame("owner-clock", "workspace-clock", conversation_id="conversation-clock",
            message_id="assistant-clock", revision=3, role="assistant", state=state, body=body,
            host_observation=observation)
    assert rows(history) == before


def test_central_frame_failure_cannot_advance_host_clock_and_crash_rolls_back_both(tmp_path, monkeypatch):
    history = WebHistoryStore(tmp_path)
    record(history, "first", central=2, host=1)
    before = rows(history)
    with pytest.raises(WebHistoryConflict, match="central|same revision"):
        record(history, "second", central=2, host=2)
    assert rows(history) == before
    original = history._save_host

    def crash(db, scope, host):
        original(db, scope, host)
        raise SystemExit("crash after both writes before commit")

    monkeypatch.setattr(history, "_save_host", crash)
    with pytest.raises(SystemExit):
        record(history, "second", central=4, host=2)
    assert rows(WebHistoryStore(tmp_path)) == before
    assert record(WebHistoryStore(tmp_path), "second", central=4, host=2)["revision"] == 4


def test_two_connections_serialize_host_and_central_revisions(tmp_path):
    first, second = WebHistoryStore(tmp_path), WebHistoryStore(tmp_path)
    record(first, "first", central=2, host=1)

    def update(args):
        history, central, host, body = args
        try:
            record(history, body, central=central, host=host)
            return True
        except WebHistoryConflict:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(update, [(first, 4, 2, "second"), (second, 6, 3, "third")]))
    assert any(result)
    central, host = rows(first)
    assert central["revision"] == 6 and host["revision"] == 3
    assert central["body_sha256"] == host["body_sha256"] == hashlib.sha256(b"third").hexdigest()


def test_authenticated_ingress_forwards_only_trusted_independent_host_projection(backend):
    _, _, control, jobs, web, params, _ = backend
    job_id, claim, _ = start(backend)
    observe(control)
    web.receipt(OWNER, job_id, **receipt_args(claim))
    expected_args = dict(request_id=REQUEST, worker=WORKER, browser_principal="local-operator", conversation_id=CHAT,
        message_id="assistant-host-clocks", revision=2, body="host independent partial", identity_epoch=EPOCH)
    observation = proof(expected_args["body"], revision=1)
    web.assistant_attestor = lambda **expected: {**expected, "authenticated": True, "host_observation": observation}
    assert web.answer(OWNER, job_id, **expected_args)["state"] == "ANSWERING"
    history = WebHistoryStore(control.durable.state_root, store=control.store)
    original = rows(history)
    assert original[0]["revision"] == 2 and original[1]["revision"] == 1
    observation = {**observation, "document_id": "different-document"}
    with pytest.raises(WebReceiptAttestationError):
        web.answer(OWNER, job_id, **{**expected_args, "revision": 3})
    assert rows(history) == original
    assert web.status(OWNER, job_id)["state"] == "ANSWERING" and jobs.result(job_id) is None
    observation = proof("host independent final", revision=2, state="complete")
    assert web.answer(OWNER, job_id, **{**expected_args, "revision": 4,
        "body": "host independent final", "complete": True})["state"] == "ANSWERED"
    central, host = rows(WebHistoryStore(control.durable.state_root, store=control.store))
    assert central["revision"] == 4 and host["revision"] == 2
    assert jobs.result(job_id)["result"] == "host independent final"


@pytest.mark.parametrize("revision", [0, -1, True, 1.5])
def test_unverified_host_clock_never_admits_a_central_frame(tmp_path, revision):
    history = WebHistoryStore(tmp_path)
    with pytest.raises(ValueError, match="positive bounded Host revision"):
        record(history, "unadmitted body", central=2, host=revision)
    with history.store.connect("provider_content") as db:
        assert db.execute("SELECT COUNT(*) FROM web_history_messages").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM web_history_host_observations").fetchone()[0] == 0


def test_approved_purge_removes_frame_and_host_projection_together(tmp_path):
    history = WebHistoryStore(tmp_path)
    record(history, "private purge content", central=2, host=1)
    with pytest.raises(PermissionError):
        history.purge("owner-clock", "workspace-clock", "conversation-clock")
    assert rows(history)[1]["revision"] == 1
    assert history.purge("owner-clock", "workspace-clock", "conversation-clock", operator_approved=True) == 1
    with history.store.connect("provider_content") as db:
        assert db.execute("SELECT COUNT(*) FROM web_history_messages").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM web_history_host_observations").fetchone()[0] == 0
