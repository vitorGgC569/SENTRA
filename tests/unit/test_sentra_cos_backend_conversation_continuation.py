"""Real protected stores; account/browser callbacks below are hermetic fixtures."""
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from native_bridge.conversation_continuation import ConversationWebContinuation
from native_bridge.job_store import JobStore
from sentra_core.conversations import ConversationStore
from sentra_executors.goal_loop import ConversationGoalLoop
from test_governance_coordination import _services


def test_preferences_protected_restart_workspace_owner_and_ciphertext_binding(tmp_path):
    store = ConversationStore(tmp_path, principal="preference-owner")
    one, two = store.open(tmp_path), store.open(tmp_path)
    assert store.model_preferences(one)["requested_model"] is None
    requested = store.set_model_preferences(one, "PRIVATE_MODEL_SENTINEL", "high", workspace=tmp_path)
    assert requested == {"requested_model": "PRIVATE_MODEL_SENTINEL", "requested_effort": "high",
                         "requested": True, "observed": False}
    assert b"PRIVATE_MODEL_SENTINEL" not in store.path.read_bytes()
    restored = ConversationStore(tmp_path, principal="preference-owner")
    assert restored.model_preferences(one) == requested
    assert restored.model_preferences(two)["requested_model"] is None
    with pytest.raises(PermissionError):
        restored.model_preferences(one, workspace=tmp_path / "foreign-workspace")
    with pytest.raises(PermissionError):
        ConversationStore(tmp_path, principal="foreign-owner").set_model_preferences(one, "model", "low")
    with pytest.raises(ValueError):
        restored.set_model_preferences(one, "\nunsafe", "high")
    with restored._connect() as db:
        protected = db.execute("SELECT protected_preferences FROM conversation_model_preferences WHERE conversation_id=?", (one,)).fetchone()[0]
        db.execute("INSERT INTO conversation_model_preferences VALUES(?,?,0)", (two, protected))
    with pytest.raises(PermissionError, match="identity mismatch"):
        restored.model_preferences(two)
    assert restored.set_model_preferences(one, None, None)["requested_model"] is None


def test_concurrent_preferences_never_mix_model_and_effort(tmp_path):
    store = ConversationStore(tmp_path, principal="preference-owner")
    session = store.open(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: store.set_model_preferences(session, "model-" + str(n), "effort-" + str(n)), range(8)))
    result = store.model_preferences(session)
    assert result["requested_model"].split("-")[1] == result["requested_effort"].split("-")[1]


def test_web_delivery_projection_protected_display_only_without_prompt_history(tmp_path):
    store = ConversationStore(tmp_path, principal="projection-owner")
    session, other = store.open(tmp_path), store.open(tmp_path)
    assert store.web_delivery_status(session) is None
    view = {"transport": "durable_v2", "run_id": "existing-run", "operation_id": "existing-op",
            "messages": [{"job_id": "job-private-projection", "state": "UNCONFIRMED", "automatic_resend": False}],
            "automatic_resend": False}
    assert store.record_web_delivery(session, view, workspace=tmp_path) == {**view, "display_only": True}
    assert store.messages(session) == [] and store.history_window(session)["total"] == 0
    assert b"job-private-projection" not in store.path.read_bytes()
    restored = ConversationStore(tmp_path, principal="projection-owner")
    assert restored.web_delivery_status(session, workspace=tmp_path) == {**view, "display_only": True}
    assert restored.web_delivery_status(other) is None
    with pytest.raises(PermissionError):
        restored.record_web_delivery(session, view, workspace=tmp_path / "other")
    with pytest.raises(PermissionError):
        ConversationStore(tmp_path, principal="foreign").web_delivery_status(session)
    with restored._connect() as db:
        cipher = db.execute("SELECT protected_view FROM conversation_web_delivery_views WHERE conversation_id=?", (session,)).fetchone()[0]
        db.execute("INSERT INTO conversation_web_delivery_views VALUES(?,?,0)", (other, cipher))
    with pytest.raises(PermissionError, match="identity mismatch"):
        restored.web_delivery_status(other)
    final = {**view, "messages": [{"job_id": "job-private-projection", "state": "ANSWERING"}]}
    restored.record_web_delivery(session, final)
    assert restored.web_delivery_status(session)["messages"][0]["state"] == "ANSWERING"
    assert restored.messages(session) == []


def test_compact_resume_checkpoint_gates_restart_and_preserves_goal_loop(tmp_path):
    d, c, control = _services(tmp_path)
    owner = "cli:continuity-owner"
    conversations = ConversationStore(tmp_path, principal="continuity-owner")
    session = conversations.open(tmp_path)
    run = d.create_run(owner, workspace=str(tmp_path))["run_id"]
    control.ensure_agent(run, owner, agent_id="continuity-agent", role="builder")
    d.bind_chat(run, owner, agent_id="continuity-agent", provider="chatgpt",
                conversation_id="source-chat-123", chat_id="logical-web-chat")
    item = control.create_work_item(run, owner, objective="Transfer approved context", assignee_agent_id="continuity-agent")
    goals = ConversationGoalLoop(control, conversations)
    goal = goals.set(owner, session, run_id=run, objective="Keep logical objective", operator_approved=True)
    loop_grant = control.authorization.grant(owner, principal_type="agent", principal_id="continuity-agent",
        capability="goal:iterate", scope_type="goal", scope_id=goal["goal_id"])
    pacing = goals.open(owner, session, principal_id="continuity-agent", operator_approved=True)
    conversations.set_model_preferences(session, "requested-model", "high")
    jobs = JobStore(tmp_path / "continuity-relay.sqlite3")
    service = ConversationWebContinuation(control, jobs, conversations)
    args = dict(run_id=run, chat_id="logical-web-chat", work_item_id=item["work_item_id"],
                principal_id="continuity-agent", request_key="compact-713", summary="PRIVATE_COMPACT_SENTINEL",
                operator_approved=True)
    blocked = service.prepare(owner, session, **args)
    assert blocked["state"] == "BLOCKED" and blocked["required_capability"] == "web:send"
    assert jobs.counts()["submitted"] == 0
    send_grant = control.authorization.grant(owner, principal_type="agent", principal_id="continuity-agent",
        capability="web:send", scope_type="work_item", scope_id=item["work_item_id"])
    blocked2 = service.prepare(owner, session, **args)
    assert blocked2["checkpoint_id"] == blocked["checkpoint_id"] and "account proof" in blocked2["reason"]
    assert b"PRIVATE_COMPACT_SENTINEL" not in control.store.path_for("session_checkpoint").read_bytes()
    # This callback only simulates the independently authenticated host.
    service.account_attestor = lambda **expected: {**expected, "authenticated": True}
    allocated = service.prepare(owner, session, **args)
    assert allocated["state"] == "WAITING_RECEIPT" and not allocated["successor_ready"]
    assert service.resume(owner, session, allocation_id=allocated["allocation_id"], operator_approved=True)["state"] == "BLOCKED"
    job = jobs.poll("TAB-456")
    jobs.progress(job["job_id"], "TAB-456", job["lease_token"], "sending")
    receipt = {"conversation_id": "created-chat-45678", "message_id": "created-message-56789",
               "prompt_sha256": hashlib.sha256(job["prompt"].encode()).hexdigest(), "images_attached": 0}
    jobs.delivery_receipt(job["job_id"], "TAB-456", job["lease_token"], receipt)
    assert service.resume(owner, session, allocation_id=allocated["allocation_id"], operator_approved=True)["state"] == "BLOCKED"
    # The shared fixture has web-lab workspace; enroll this actual test workspace instead.
    control.browser_evidence.configure(extension_id="a" * 32, principal="local-operator",
        workspace=str(tmp_path), source_sha256="1" * 64, enabled=True, expected_revision=0)
    from native_bridge.web_evidence_ingress import AuthenticatedWebReceiptBroker
    challenge = control.browser_evidence.challenge(extension_id="a" * 32, source_sha256="1" * 64,
        worker="TAB-456", document_id="continuity-document")
    control.browser_evidence.observe(extension_id="a" * 32, source_sha256="1" * 64, worker="TAB-456",
        evidence={"nonce": challenge["nonce"], "document_id": "continuity-document",
                  "conversation_id": receipt["conversation_id"], "route_conversation_id": receipt["conversation_id"],
                  "state": "idle", "requests": [{"request_id": "continuity-request", "message_id": receipt["message_id"]}]})
    AuthenticatedWebReceiptBroker(control, jobs).attest_existing(owner, run_id=run, job_id=job["job_id"],
        browser_principal="local-operator", request_id="continuity-request", worker="TAB-456", evidence=receipt)
    jobs.close(); c.close(); d.close()
    d2, c2, control2 = _services(tmp_path)
    jobs2 = JobStore(tmp_path / "continuity-relay.sqlite3")
    try:
        restored = ConversationWebContinuation(control2, jobs2, ConversationStore(tmp_path, principal="continuity-owner"))
        assert restored.status(owner, session, allocation_id=allocated["allocation_id"])["successor_ready"] is False
        assert restored.resume(owner, session, allocation_id=allocated["allocation_id"], operator_approved=True)["state"] == "BLOCKED"
        restored.account_attestor = lambda **expected: {**expected, "authenticated": True}
        done = restored.resume(owner, session, allocation_id=allocated["allocation_id"], operator_approved=True)
        assert done["state"] == "PUBLISHED" and done["successor_ready"]
        current = ConversationGoalLoop(control2, restored.conversations).status(owner, session)
        assert current["goal_id"] == goal["goal_id"] and current["loop"]["loop_id"] == pacing["loop"]["loop_id"]
        assert current["loop"]["grant_id"] == loop_grant["grant_id"]
        assert control2.authorization.info(send_grant["grant_id"], owner)["revoked"] is False
        assert len(d2.list_runs(owner)["items"]) == 1 and jobs2.counts()["submitted"] == 1
        assert len(control2.list_work_items(owner, run_id=run)["items"]) == 1
        assert restored.status(owner, session, allocation_id=allocated["allocation_id"])["successor_ready"]
    finally:
        jobs2.close(); c2.close(); d2.close()
