"""Temporary full host composition. Attestations are fixtures, never real E2E."""
import hashlib
import json

import pytest

from native_bridge.job_store import JobStore
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_model_gateway.turn_authority import TurnAuthority
from sentra_model_gateway.web_transport import DurableWebTransport
from test_web_turn_authority import descriptor


@pytest.mark.parametrize("host_wire", [False, True])
def test_bound_responses_physical_send_receipt_answer_and_rollback_share_authority(tmp_path, monkeypatch, host_wire):
    state = tmp_path / "state"
    authority = TurnAuthority(state, tmp_path / "descriptor.json")
    context = ContextBusService(state)
    control = ControlPlaneService(authority.durable, context)
    jobs = JobStore(tmp_path / "relay.sqlite3")
    owner = "canvas:composition-test"
    run = authority.durable.create_run(owner, workspace=str(tmp_path))["run_id"]
    authority.durable.transition_run(run, owner, "RUNNING")
    control.ensure_agent(run, owner, agent_id="composition-agent", role="builder")
    work = control.create_work_item(run, owner, objective="Approved fixture", assignee_agent_id="composition-agent")
    grant = control.authorization.grant(owner, principal_type="agent", principal_id="composition-agent",
        capability="web:send", scope_type="work_item", scope_id=work["work_item_id"])
    proof = {"account_verified": True, "authentication_revision": 1, "collector_kind": "electron", "extension_id": "sentra-committed-account-menu-v1",
        "source_sha256": "b" * 64, "worker": "electron-worker-one", "browser_principal": "local-operator",
        "document_id": "document-composition-one", "identity_epoch": "epoch-composition-one", "approval_state": "idle",
        "selection_verified": True, "requested_model": "sentra/chatgpt-web/high", "requested_effort": "high",
        "model": "gpt-6", "effort": "high", "conversation_url": "https://chatgpt.com/c/conversation-one"}
    control.browser_evidence.configure_host(collector_id=proof["extension_id"], source_sha256=proof["source_sha256"],
        principal=proof["browser_principal"], workspace=str(tmp_path), surface_id="surface-one", worker=proof["worker"],
        enabled=True, expected_revision=0)
    # Explicitly synthetic account + message observations; no real-account proof.
    snapshot_revision = 1
    snapshot_identity = {"document_id": proof["document_id"], "identity_epoch": proof["identity_epoch"]}
    def host_message_fixture(*args, expected, **kwargs):
        return {"authentication_revision": snapshot_revision, "host_revision": 1,
            "body_sha256": expected["body_sha256"], "complete": expected.get("complete", False),
            "collector_id": "host-message-fixture", "collector_sha256": "c" * 64,
            **snapshot_identity}
    monkeypatch.setattr("sentra_model_gateway.browser_host_identity.read_host_message", host_message_fixture)
    callbacks = {} if host_wire else {
        "assistant_attestor": lambda **expected: {**expected, "authenticated": True},
        "message_attestor": lambda **expected: {**expected, "authenticated": True}}
    transport = DurableWebTransport(authority, control=control, jobs=jobs,
        account_attestor=lambda *_: proof, **callbacks)
    try:
        assert transport.status()["mode"] == "legacy"
        with pytest.raises(PermissionError):
            transport.set_mode("durable_v2", expected_revision=0)
        transport.bind("conversation://composition", owner=owner, run_id=run, work_item_id=work["work_item_id"],
                       principal_id="composition-agent", grant_id=grant["grant_id"])
        token = transport.admit_responses(conversation_uri="conversation://composition",
            request_identity='{"thread_id":"composition","turn_id":"one"}',
            payload={"model": "sentra/chatgpt-web/high", "reasoning": {"effort": "high"}, "input": "PRIVATE_ORIGINAL_INTENT"})
        descriptor(authority.descriptor)
        if host_wire:
            current_descriptor = json.loads(authority.descriptor.read_text())
            current_descriptor["sentraTabs"][0].update(documentId=proof["document_id"], identityEpoch=proof["identity_epoch"])
            authority.descriptor.write_text(json.dumps(current_descriptor))
        authority.authorize("browser-start", {"capability": token, "traceId": "trace123"})
        # An administrative rebinding must never silently replace the grant
        # pinned when this original Responses intent was admitted.
        with control.store.connect("session_checkpoint") as db:
            db.execute("UPDATE gateway_web_bindings SET grant_id='replacement-grant' WHERE conversation_uri=?",
                       ("conversation://composition",))
        physical = {"capability": token, "traceId": "trace123", "submission_index": 0,
            "prompt": "PRIVATE_TRANSFORMED_PROMPT", "prompt_sha256": hashlib.sha256(b"PRIVATE_TRANSFORMED_PROMPT").hexdigest(),
            "document_id": proof["document_id"], "identity_epoch": proof["identity_epoch"],
            "surface_id": "surface-one", "conversation_id": "conversation-one", "model": "gpt-6", "effort": "high"}
        with pytest.raises(PermissionError, match="binding changed"):
            transport.browser_event("preflight", physical)
        assert jobs.counts()["submitted"] == 0
        restarted = TurnAuthority(state, authority.descriptor)
        try:
            restored = restarted._capability(token)
            assert restored.web_grant_id == grant["grant_id"]
            assert restored.agent_id == "composition-agent"
        finally:
            restarted.durable.close()
        transport.bind("conversation://composition", owner=owner, run_id=run,
            work_item_id=work["work_item_id"], principal_id="composition-agent", grant_id=grant["grant_id"])
        ready = transport.browser_event("preflight", physical)
        physical["request_id"] = ready["request_id"]
        assert ready["state"] == "READY"
        assert transport.browser_event("preflight", physical)["idempotent_replay"] is True
        assert transport.browser_event("sending", physical)["state"] == "SENDING"
        with pytest.raises(RuntimeError):
            transport.browser_event("sending", physical)
        receipt = {**physical, "observed_request_id": "provider-request-one", "message_id": "provider-user-message"}
        if host_wire:
            for snapshot_revision in (True, None, "1", 2):
                with pytest.raises(PermissionError, match="account changed"):
                    transport.browser_event("receipt", receipt)
                assert transport.web.status(owner, ready["request_id"])["state"] == "SENDING"
            snapshot_revision = 1
            expected_user = {"owner": owner, "run_id": run, "job_id": ready["request_id"],
                "worker": proof["worker"], "identity_epoch": proof["identity_epoch"], "role": "user",
                "conversation_id": physical["conversation_id"], "message_id": receipt["message_id"],
                "request_id": receipt["observed_request_id"], "body_sha256": physical["prompt_sha256"]}
            for snapshot_field, tab_field in (("document_id", "documentId"), ("identity_epoch", "identityEpoch")):
                changed_descriptor = json.loads(json.dumps(current_descriptor))
                changed_descriptor["sentraTabs"][0][tab_field] = "changed-original-binding"
                authority.descriptor.write_text(json.dumps(changed_descriptor))
                with pytest.raises(PermissionError, match="original submission"):
                    transport._host_observation(**expected_user)
                authority.descriptor.write_text(json.dumps(current_descriptor))
                snapshot_identity[snapshot_field] = "changed-original-binding"
                with pytest.raises(PermissionError, match="document/epoch changed"):
                    transport.browser_event("receipt", receipt)
                assert transport.web.status(owner, ready["request_id"])["state"] == "SENDING"
                snapshot_identity[snapshot_field] = proof[snapshot_field]
        assert transport.browser_event("receipt", receipt)["state"] == "SENT"
        with pytest.raises(PermissionError):
            transport.require_receipts(token)
        answer = {**physical, "observed_request_id": "provider-request-one", "message_id": "provider-assistant-message",
                  "parent_user_message_id": "provider-user-message", "body": "PRIVATE_OBSERVED_ANSWER", "revision": 17, "complete": True}
        answered = transport.browser_event("answer", answer)
        assert answered["ok"] is True and answered["state"] == "ANSWERED"
        if host_wire:
            with control.store.connect("provider_content") as db:
                host_clock = db.execute("SELECT revision FROM web_history_host_observations").fetchone()[0]
                central_clock = db.execute("SELECT revision FROM web_history_messages WHERE role='assistant'").fetchone()[0]
            assert host_clock == 1 and central_clock == 17
        transport.require_receipts(token)
        assert transport.set_mode("legacy", expected_revision=0)["revision"] == 1
        assert transport.web.status(owner, ready["request_id"])["state"] == "ANSWERED"
        assert jobs.counts()["submitted"] == 1
        assert len(authority.durable.list_runs(owner)["items"]) == 1
        assert len(control.authorization.list_grants(owner)["items"]) == 1
        # A compaction/browser successor phase can reuse physical index zero,
        # while retaining the same root request and central Run.
        authority.authorize("browser-complete", {"capability": token, "traceId": "trace123"})
        descriptor(authority.descriptor, trace="trace-phase-two")
        authority.authorize("browser-start", {"capability": token, "traceId": "trace-phase-two"})
        phase_two = {**physical, "traceId": "trace-phase-two", "prompt": "SECOND_PHYSICAL_PHASE",
                     "prompt_sha256": hashlib.sha256(b"SECOND_PHYSICAL_PHASE").hexdigest()}
        next_ready = transport.browser_event("preflight", phase_two)
        assert next_ready["request_id"] != ready["request_id"]
        assert jobs.counts()["submitted"] == 2
        assert len(authority.durable.list_runs(owner)["items"]) == 1
        phase_two["request_id"] = next_ready["request_id"]
        transport.browser_event("sending", phase_two)
        authority.descriptor.unlink()  # Lost/reloaded page cannot claim not-run.
        failure = transport.browser_event("failure", {**phase_two, "may_have_sent": False})
        assert failure["state"] == "UNCONFIRMED" and failure["automatic_resend"] is False
        transport.close()
        assert jobs.counts()["submitted"] == 2  # Borrowed runtime stays open.
    finally:
        jobs.close()
        context.close()
        authority.durable.close()
