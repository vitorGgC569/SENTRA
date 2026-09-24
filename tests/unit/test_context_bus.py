from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from orchestrator.models import TokenUsage
from orchestrator.providers.base import AgentRequest, AgentResponse
from orchestrator.conversation_pool import FixedConversationRouter
from mcp import Client

from sentra_mcp.audit import AuditLogger
from sentra_mcp.config import MCPConfig
from sentra_mcp.server import SentraMCPServer
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.context_projection import ControlPlaneContextBridge
from sentra_mcp.services.context_transport import InMemoryContextTransport, RedisStreamsContextTransport
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.research import ResearchService


def _services(tmp_path: Path):
    durable = DurableRunService(tmp_path / ".sentra")
    context = ContextBusService(tmp_path / ".sentra")
    control = ControlPlaneService(durable, context)
    return durable, context, control


def test_context_delta_subscription_cursor_and_idempotency(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        run = durable.create_run("owner-a", workspace="sentra")
        agent = durable.assign_agent(run["run_id"], "owner-a", role="builder", task_id="task-1", agent_id="agent-builder")
        first = control.publish_context(
            run["run_id"], "owner-a", event_type="FACT",
            subject="echo-riot.client-bootstrap", payload={"EchoClientReady": True},
            evidence=[], confidence=0.91, supersedes=[], task_id="task-1",
            agent_id=agent["agent_id"], idempotency_key="fact-client-ready",
        )
        replay = control.publish_context(
            run["run_id"], "owner-a", event_type="FACT",
            subject="echo-riot.client-bootstrap", payload={"EchoClientReady": True},
            evidence=[], confidence=0.91, supersedes=[], task_id="task-1",
            agent_id=agent["agent_id"], idempotency_key="fact-client-ready",
        )
        assert replay["event_id"] == first["event_id"]
        assert replay["idempotent_replay"] is True
        control.publish_context(
            run["run_id"], "owner-a", event_type="HYPOTHESIS",
            subject="resolvenet.bufferbloat", payload={"candidate": "qos"},
            evidence=[], confidence=0.5, supersedes=[], task_id=None,
            agent_id=agent["agent_id"], idempotency_key="hypothesis-qos",
        )
        sub = control.subscribe(run["run_id"], "owner-a", "reviewer", types=["FACT"], subject_prefixes=["echo-riot."])
        assert sub["types"] == ["FACT"]
        delta = control.read_context(run["run_id"], "owner-a", consumer_id="reviewer", limit=50)
        assert [item["event_id"] for item in delta["items"]] == [first["event_id"]]
        ack = control.acknowledge(run["run_id"], "owner-a", "reviewer", delta["last_seq"])
        assert ack["seq"] == first["seq"]
        assert control.read_context(run["run_id"], "owner-a", consumer_id="reviewer")["items"] == []
        snapshot = control.snapshot(run["run_id"], "owner-a", limit=20)
        assert {item["subject"] for item in snapshot["latest_by_subject"]} == {"echo-riot.client-bootstrap", "resolvenet.bufferbloat"}
        with pytest.raises(PermissionError):
            control.read_context(run["run_id"], "owner-b")
    finally:
        context.close()
        durable.close()


def test_claims_require_real_evidence_and_never_complete_run(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        run = durable.create_run("owner-a", workspace="sentra")
        agent = durable.assign_agent(run["run_id"], "owner-a", role="reviewer", agent_id="agent-reviewer")
        op = durable.create_operation(run["run_id"], "owner-a", kind="benchmark", idempotency_key="benchmark-1")
        state_before = durable.run_status(run["run_id"], "owner-a")["state"]
        claim = control.propose_claim(
            run["run_id"], "owner-a", subject="scheduler.wall-clock",
            statement="new scheduler reduced wall-clock validation", evidence=[op["operation_id"]],
            idempotency_key="claim-wall-clock", confidence=0.91, agent_id=agent["agent_id"],
        )
        assert claim["status"] == "PROPOSED"
        challenged = control.challenge_claim(
            claim["claim_id"], "owner-a", reason="benchmark does not control machine load",
            evidence=[op["operation_id"]], idempotency_key="challenge-wall-clock", agent_id=agent["agent_id"],
        )
        assert challenged["claim"]["status"] == "CHALLENGED"
        status = durable.run_status(run["run_id"], "owner-a")["state"]
        assert status == state_before
        assert status not in {"SUCCEEDED", "FAILED", "CANCELLED"}
        with pytest.raises(FileNotFoundError):
            control.propose_claim(
                run["run_id"], "owner-a", subject="invalid", statement="unsupported",
                evidence=["artifact-does-not-exist"], idempotency_key="claim-invalid", agent_id=agent["agent_id"],
            )
    finally:
        context.close()
        durable.close()


def test_context_tool_and_capabilities_are_compact_core_surface(tmp_path: Path) -> None:
    config = MCPConfig(
        allowed_roots=(tmp_path,), audit_log=tmp_path / ".sentra" / "audit.jsonl",
        remote_store_path=tmp_path / ".sentra" / "remote.sqlite3",
        state_root=tmp_path / ".sentra", process_mode="unrestricted",
    )
    runtime = SentraMCPServer(config)
    try:
        names = {tool.name for tool in runtime.mcp._tool_manager.list_tools()}
        assert "sentra_context" in names
        capabilities = runtime.capabilities.server_capabilities()
        for key in ("control_plane", "shared_context", "typed_context_events", "context_cursors", "context_subscriptions", "claims_bus"):
            assert capabilities[key] is True
    finally:
        runtime.processes.shutdown(); runtime.search.close(); runtime.remote_store.close(); runtime.context.close(); runtime.durable.close()


def test_parallel_research_synthesizes_from_shared_context(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    config = MCPConfig(
        allowed_roots=(tmp_path,), audit_log=tmp_path / ".sentra" / "audit.jsonl",
        remote_store_path=tmp_path / ".sentra" / "remote.sqlite3", state_root=tmp_path / ".sentra",
        process_mode="unrestricted",
    )
    service = ResearchService(config, AuditLogger(config.audit_log), object(), durable=durable, control_plane=control, db_path=tmp_path / ".sentra" / "research-context-test.sqlite3")
    run = durable.create_run("owner-a", workspace="sentra")
    async def fake_batch(owner, prompts, *, timeout_s):
        return [
            {"text": "branch one evidence", "conversation_id": "conv-1", "conversation_url": "https://chatgpt.com/c/conv-1"},
            {"text": "branch two objection", "conversation_id": "conv-2", "conversation_url": "https://chatgpt.com/c/conv-2"},
        ]
    async def fake_synthesis(owner, prompt, *, timeout_s):
        assert "SHARED CONTEXT BRANCH RESULTS" in prompt
        assert "branch one evidence" in prompt and "branch two objection" in prompt
        return {"text": "integrated answer", "conversation_id": "conv-synthesis", "conversation_url": "https://chatgpt.com/c/conv-synthesis"}
    service._parallel_chat_batch = fake_batch
    service._chat_retry = fake_synthesis
    try:
        nodes, answer = asyncio.run(service._parallel(run["run_id"], "research objective", "owner-a", 2, 60, []))
        assert answer == "integrated answer"
        assert len(nodes) == 3
        assert all(node.get("context_event_id") for node in nodes)
        assert all(node.get("agent_id") and node.get("chat_id") for node in nodes)
        status = durable.run_status(run["run_id"], "owner-a")
        assert len(status["agents"]) == 3
        assert len(status["chats"]) == 3
        assert {chat["conversation_id"] for chat in status["chats"]} == {"conv-1", "conv-2", "conv-synthesis"}
        shared = control.read_context(run["run_id"], "owner-a", after_seq=0, limit=20)
        assert [item["type"] for item in shared["items"]] == ["RESULT", "RESULT", "DECISION"]
        assert shared["items"][-1]["evidence"] == [nodes[0]["context_event_id"], nodes[1]["context_event_id"]]
    finally:
        asyncio.run(service.close()); context.close(); durable.close()


def test_context_idempotency_conflicts_and_payload_bound(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        run = durable.create_run("owner-a")
        control.publish_context(run["run_id"], "owner-a", event_type="FACT", subject="subject", payload={"value": 1}, evidence=[], confidence=None, supersedes=[], task_id=None, agent_id=None, idempotency_key="same-key")
        with pytest.raises(FileExistsError):
            control.publish_context(run["run_id"], "owner-a", event_type="FACT", subject="subject", payload={"value": 2}, evidence=[], confidence=None, supersedes=[], task_id=None, agent_id=None, idempotency_key="same-key")
        with pytest.raises(ValueError):
            control.publish_context(run["run_id"], "owner-a", event_type="FACT", subject="oversized", payload={"blob": "x" * (256 * 1024 + 1)}, evidence=[], confidence=None, supersedes=[], task_id=None, agent_id=None, idempotency_key="oversized")
        op = durable.create_operation(run["run_id"], "owner-a", kind="probe", idempotency_key="op")
        control.propose_claim(run["run_id"], "owner-a", subject="claim.subject", statement="one", evidence=[op["operation_id"]], idempotency_key="claim-key")
        with pytest.raises(FileExistsError):
            control.propose_claim(run["run_id"], "owner-a", subject="claim.subject", statement="different", evidence=[op["operation_id"]], idempotency_key="claim-key")
    finally:
        context.close(); durable.close()


def test_claim_resolution_is_control_plane_only(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        run = durable.create_run("owner-a")
        op = durable.create_operation(run["run_id"], "owner-a", kind="deterministic.test", idempotency_key="resolution-evidence")
        claim = control.propose_claim(run["run_id"], "owner-a", subject="candidate.correctness", statement="candidate passes deterministic verification", evidence=[op["operation_id"]], idempotency_key="resolution-claim")
        resolved = control.resolve_claim(claim["claim_id"], "owner-a", verdict="VERIFIED", authority="quality_gate", reason="deterministic validation accepted", evidence=[op["operation_id"]], idempotency_key="resolution-1")
        assert resolved["claim"]["status"] == "VERIFIED"
        info = control.claim_info(claim["claim_id"], "owner-a")
        assert info["resolutions"][0]["authority"] == "quality_gate"
        with pytest.raises(ValueError):
            control.challenge_claim(claim["claim_id"], "owner-a", reason="late objection", evidence=[op["operation_id"]], idempotency_key="late-challenge")
        with pytest.raises(PermissionError):
            context.resolve_claim(claim["claim_id"], "owner-a", verdict="REJECTED", authority="agent", reason="agent cannot resolve", evidence=[op["operation_id"]], idempotency_key="bad-authority")
        assert durable.run_status(run["run_id"], "owner-a")["state"] != "SUCCEEDED"
    finally:
        context.close(); durable.close()


def test_agent_messages_are_routed_and_replyable(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        run = durable.create_run("owner-a")
        a = durable.assign_agent(run["run_id"], "owner-a", role="builder", agent_id="agent-a")
        b = durable.assign_agent(run["run_id"], "owner-a", role="reviewer", agent_id="agent-b")
        c_agent = durable.assign_agent(run["run_id"], "owner-a", role="judge", agent_id="agent-c")
        direct = control.send_message(run["run_id"], "owner-a", from_agent_id=a["agent_id"], to_agent_id=b["agent_id"], body="Please challenge benchmark X.", idempotency_key="msg-direct-1")
        broadcast = control.send_message(run["run_id"], "owner-a", from_agent_id=a["agent_id"], to_agent_id="*", body="Shared checkpoint available.", idempotency_key="msg-broadcast-1")
        reply = control.send_message(run["run_id"], "owner-a", from_agent_id=b["agent_id"], to_agent_id=a["agent_id"], body="Benchmark X lacks a load-control baseline.", reply_to=direct["event_id"], idempotency_key="msg-reply-1")
        assert [i["event_id"] for i in control.read_messages(run["run_id"], "owner-a", agent_id=b["agent_id"], after_seq=0)["items"]] == [direct["event_id"], broadcast["event_id"]]
        assert [i["event_id"] for i in control.read_messages(run["run_id"], "owner-a", agent_id=c_agent["agent_id"], after_seq=0)["items"]] == [broadcast["event_id"]]
        inbox_a = control.read_messages(run["run_id"], "owner-a", agent_id=a["agent_id"], after_seq=0)
        assert [i["event_id"] for i in inbox_a["items"]] == [broadcast["event_id"], reply["event_id"]]
        assert inbox_a["items"][-1]["payload"]["reply_to"] == direct["event_id"]
        with pytest.raises(FileNotFoundError):
            control.send_message(run["run_id"], "owner-a", from_agent_id=a["agent_id"], to_agent_id="agent-missing", body="x", idempotency_key="bad-dest")
    finally:
        context.close(); durable.close()


def test_context_transport_is_best_effort_and_non_authoritative(tmp_path: Path) -> None:
    durable = DurableRunService(tmp_path / ".sentra")
    transport = InMemoryContextTransport()
    context = ContextBusService(tmp_path / ".sentra", transport=transport)
    control = ControlPlaneService(durable, context)
    try:
        run = durable.create_run("owner-a")
        event = control.publish_context(run["run_id"], "owner-a", event_type="FACT", subject="transport.probe", payload={"ok": True}, evidence=[], confidence=1.0, supersedes=[], task_id=None, agent_id=None, idempotency_key="transport-probe")
        assert [item["event_id"] for item in transport.events] == [event["event_id"]]
    finally:
        context.close(); durable.close()
    class BrokenTransport:
        def publish(self, event): raise RuntimeError("transient bus unavailable")
        def close(self): return None
    durable = DurableRunService(tmp_path / ".sentra-broken")
    context = ContextBusService(tmp_path / ".sentra-broken", transport=BrokenTransport())
    control = ControlPlaneService(durable, context)
    try:
        run = durable.create_run("owner-a")
        event = control.publish_context(run["run_id"], "owner-a", event_type="FACT", subject="durable.survives.bus.failure", payload={"ok": True}, evidence=[], confidence=None, supersedes=[], task_id=None, agent_id=None, idempotency_key="bus-failure")
        assert context.last_transport_error == "transient bus unavailable"
        assert control.read_context(run["run_id"], "owner-a", after_seq=0)["items"][0]["event_id"] == event["event_id"]
    finally:
        context.close(); durable.close()


def test_redis_streams_transport_uses_run_scoped_stream() -> None:
    class FakeRedis:
        def __init__(self): self.calls = []
        def xadd(self, key, fields, **kwargs): self.calls.append((key, fields, kwargs))
    client = FakeRedis()
    transport = RedisStreamsContextTransport(client, prefix="sentra-test", maxlen=5000)
    transport.publish({"run_id": "run-123", "event_id": "ctx-1", "type": "FACT", "subject": "probe"})
    key, fields, kwargs = client.calls[0]
    assert key == "sentra-test:run:run-123:context"
    assert '"event_id":"ctx-1"' in fields["event"]
    assert kwargs == {"maxlen": 5000, "approximate": True}


def test_context_prefix_filter_and_snapshot_scale_beyond_page_window(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        run = durable.create_run("owner-a")
        for index in range(20):
            control.publish_context(run["run_id"], "owner-a", event_type="FACT", subject=f"noise.{index}", payload={"index": index}, evidence=[], confidence=None, supersedes=[], task_id=None, agent_id=None, idempotency_key=f"noise-{index}")
        relevant = control.publish_context(run["run_id"], "owner-a", event_type="FACT", subject="wanted.deep.subject", payload={"value": "found"}, evidence=[], confidence=None, supersedes=[], task_id=None, agent_id=None, idempotency_key="wanted")
        filtered = control.read_context(run["run_id"], "owner-a", after_seq=0, subject_prefixes=["wanted."], limit=1)
        assert [item["event_id"] for item in filtered["items"]] == [relevant["event_id"]]
        with context.lock:
            for index in range(510):
                context._publish_locked(run["run_id"], "owner-a", event_type="RESULT", subject="rolling.subject", payload={"version": index}, evidence=[], confidence=None, supersedes=[], task_id=None, agent_id=None, idempotency_key=f"rolling-{index}")
            context.db.commit()
        snapshot = control.snapshot(run["run_id"], "owner-a", subject_prefixes=["rolling."], limit=5)
        assert snapshot["counts"]["RESULT"] == 510
        assert snapshot["latest_by_subject"][0]["payload"]["version"] == 509
        assert snapshot["last_seq"] > 500
    finally:
        context.close(); durable.close()


def test_control_plane_context_bridge_projects_task_delta_and_publishes_response(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        run = durable.create_run("owner-a")
        control.publish_context(run["run_id"], "owner-a", event_type="FACT", subject="global.fact", payload={"value": "global"}, evidence=[], confidence=1.0, supersedes=[], task_id=None, agent_id=None, idempotency_key="global-fact")
        control.publish_context(run["run_id"], "owner-a", event_type="RESULT", subject="task.other", payload={"value": "ignore"}, evidence=[], confidence=None, supersedes=[], task_id="T-2", agent_id=None, idempotency_key="other-task")
        wanted = control.publish_context(run["run_id"], "owner-a", event_type="OBJECTION", subject="task.current", payload={"value": "review this"}, evidence=[], confidence=None, supersedes=[], task_id="T-1", agent_id=None, idempotency_key="current-task")
        bridge = ControlPlaneContextBridge(control, "owner-a", max_chars=5000)
        seat = f"{run['run_id']}:executor"
        batch = bridge.prepare(
            run_id=run["run_id"], role="executor", task_id="T-1", seat=seat
        )
        assert batch.count == 2
        assert "global.fact" in batch.text
        assert "task.current" in batch.text
        assert "task.other" not in batch.text
        assert batch.last_seq >= wanted["seq"]

        status = durable.run_status(run["run_id"], "owner-a")
        executor_agent = next(
            item for item in status["agents"]
            if item["metadata"].get("seat") == seat
        )
        assert executor_agent["role"] == "executor"

        bridge.acknowledge(
            run_id=run["run_id"], role="executor", task_id="T-1", seat=seat,
            consumer_id=batch.consumer_id, last_seq=batch.last_seq,
        )
        assert bridge.prepare(
            run_id=run["run_id"], role="executor", task_id="T-1", seat=seat
        ).count == 0

        sender = durable.assign_agent(
            run["run_id"], "owner-a", role="reviewer", agent_id="agent-reviewer-bridge"
        )
        message = control.send_message(
            run["run_id"], "owner-a",
            from_agent_id=sender["agent_id"],
            to_agent_id=executor_agent["agent_id"],
            body="Review the new benchmark evidence.",
            idempotency_key="bridge-message-1",
        )
        message_batch = bridge.prepare(
            run_id=run["run_id"], role="executor", task_id="T-1", seat=seat
        )
        assert message_batch.count == 1
        assert message["event_id"] in message_batch.text
        assert "Review the new benchmark evidence." in message_batch.text

        bridge.publish_response(
            run_id=run["run_id"], role="executor", task_id="T-1", seat=seat,
            content="candidate response",
            metadata={
                "conversation_id": "conv-1",
                "conversation_url": "https://chatgpt.com/c/conv-1",
                "ignored": "x",
            },
            request_sha256="req-1",
        )
        bridge.publish_response(
            run_id=run["run_id"], role="executor", task_id="T-1", seat=seat,
            content="candidate response",
            metadata={
                "conversation_id": "conv-1",
                "conversation_url": "https://chatgpt.com/c/conv-1",
            },
            request_sha256="req-1",
        )
        responses = [
            item for item in control.read_context(
                run["run_id"], "owner-a",
                after_seq=batch.last_seq,
                types=["RESULT"],
                limit=20,
            )["items"]
            if item["subject"] == "oma.response.executor.T-1"
        ]
        assert len(responses) == 1
        assert responses[0]["agent_id"] == executor_agent["agent_id"]
        assert responses[0]["payload"]["response_meta"] == {
            "conversation_id": "conv-1",
            "conversation_url": "https://chatgpt.com/c/conv-1",
        }

        status = durable.run_status(run["run_id"], "owner-a")
        executor_chat = next(
            item for item in status["chats"]
            if item["agent_id"] == executor_agent["agent_id"]
        )
        assert executor_chat["conversation_id"] == "conv-1"
        assert executor_chat["conversation_url"] == "https://chatgpt.com/c/conv-1"
        assert status["state"] not in {"SUCCEEDED", "FAILED", "CANCELLED"}
    finally:
        context.close(); durable.close()


def test_context_grant_is_scoped_revocable_and_hash_only(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        run = durable.create_run("owner-a")
        agent = durable.assign_agent(run["run_id"], "owner-a", role="reviewer", agent_id="agent-b")
        grant = control.create_context_grant(run["run_id"], "owner-a", agent_id=agent["agent_id"], permissions=["read", "publish", "message", "claims"], ttl_hours=1)
        token = grant["context_token"]
        assert token.startswith("cg1.")
        secret = token.rsplit(".", 1)[-1]
        stored_hash = context.db.execute("SELECT token_hash FROM context_grants WHERE grant_id=?", (grant["grant_id"],)).fetchone()["token_hash"]
        assert secret not in stored_hash
        authorized = control.authorize_context_grant(run["run_id"], token, permission="publish", agent_id="agent-b")
        assert authorized["owner"] == "owner-a" and authorized["agent_id"] == "agent-b"
        with pytest.raises(PermissionError): control.authorize_context_grant(run["run_id"], token, permission="publish", agent_id="agent-other")
        with pytest.raises(PermissionError): control.authorize_context_grant(run["run_id"], token, permission="admin")
        other = durable.create_run("owner-a")
        with pytest.raises(PermissionError): control.authorize_context_grant(other["run_id"], token, permission="read")
        assert control.revoke_context_grant(grant["grant_id"], "owner-a")["revoked"] is True
        with pytest.raises(PermissionError): control.authorize_context_grant(run["run_id"], token, permission="read")
    finally:
        context.close(); durable.close()


def test_context_grant_expires_without_weakening_run_owner(tmp_path: Path) -> None:
    clock = [1000.0]
    durable = DurableRunService(tmp_path / ".sentra")
    context = ContextBusService(tmp_path / ".sentra", clock=lambda: clock[0])
    control = ControlPlaneService(durable, context)
    try:
        run = durable.create_run("owner-a")
        durable.assign_agent(run["run_id"], "owner-a", role="builder", agent_id="agent-a")
        grant = control.create_context_grant(run["run_id"], "owner-a", agent_id="agent-a", permissions=["read"], ttl_hours=0.05)
        assert control.authorize_context_grant(run["run_id"], grant["context_token"], permission="read")["agent_id"] == "agent-a"
        with pytest.raises(PermissionError): durable.run_status(run["run_id"], "session:delegate")
        clock[0] += 181
        with pytest.raises(PermissionError): control.authorize_context_grant(run["run_id"], grant["context_token"], permission="read")
    finally:
        context.close(); durable.close()


def test_context_tool_exposes_grants_but_not_claim_resolution(tmp_path: Path) -> None:
    config = MCPConfig(allowed_roots=(tmp_path,), audit_log=tmp_path / ".sentra" / "audit.jsonl", remote_store_path=tmp_path / ".sentra" / "remote.sqlite3", state_root=tmp_path / ".sentra", process_mode="unrestricted")
    runtime = SentraMCPServer(config)
    try:
        tools = {tool.name: tool for tool in runtime.mcp._tool_manager.list_tools()}
        props = tools["sentra_context"].parameters["properties"]
        actions = set(props["action"]["enum"])
        assert {"grant_create", "grant_revoke"} <= actions
        assert "claim_resolve" not in actions
        for name in ("context_token", "permissions", "ttl_hours", "grant_id"): assert name in props
    finally:
        runtime.processes.shutdown(); runtime.search.close(); runtime.remote_store.close(); runtime.context.close(); runtime.durable.close()



def test_context_grant_crosses_mcp_sessions_without_crossing_authority(tmp_path: Path) -> None:
    async def probe() -> None:
        config = MCPConfig(
            allowed_roots=(tmp_path,),
            audit_log=tmp_path / ".sentra" / "audit.jsonl",
            remote_store_path=tmp_path / ".sentra" / "remote.sqlite3",
            state_root=tmp_path / ".sentra",
            process_mode="unrestricted",
        )
        runtime = SentraMCPServer(config)
        try:
            async with Client(runtime.mcp) as client:
                opened_a = await client.call_tool("sentra_session_open", {})
                opened_b = await client.call_tool("sentra_session_open", {})
                token_a = opened_a.structured_content["data"]["session_token"]
                token_b = opened_b.structured_content["data"]["session_token"]

                created = await client.call_tool("sentra_run", {
                    "action": "create",
                    "workspace": "sentra",
                    "idempotency_key": "cross-chat-run",
                    "session_token": token_a,
                })
                run_id = created.structured_content["data"]["run_id"]

                assigned = await client.call_tool("sentra_run", {
                    "action": "agent_assign",
                    "run_id": run_id,
                    "role": "reviewer",
                    "agent_id": "agent-b",
                    "session_token": token_a,
                })
                assert assigned.structured_content["ok"] is True

                grant_result = await client.call_tool("sentra_context", {
                    "action": "grant_create",
                    "run_id": run_id,
                    "agent_id": "agent-b",
                    "permissions": ["read", "publish"],
                    "ttl_hours": 1,
                    "session_token": token_a,
                })
                grant = grant_result.structured_content["data"]
                context_token = grant["context_token"]

                denied_without_grant = await client.call_tool("sentra_context", {
                    "action": "read",
                    "run_id": run_id,
                    "after_seq": 0,
                    "session_token": token_b,
                })
                assert denied_without_grant.structured_content["ok"] is False
                assert denied_without_grant.structured_content["error"]["code"] == "forbidden"

                published = await client.call_tool("sentra_context", {
                    "action": "publish",
                    "run_id": run_id,
                    "event_type": "FACT",
                    "subject": "cross-chat.fact",
                    "payload": {"source": "chat-b"},
                    "agent_id": "agent-b",
                    "idempotency_key": "cross-chat-fact",
                    "context_token": context_token,
                    "session_token": token_b,
                })
                assert published.structured_content["ok"] is True
                assert published.structured_content["data"]["agent_id"] == "agent-b"

                read = await client.call_tool("sentra_context", {
                    "action": "read",
                    "run_id": run_id,
                    "context_token": context_token,
                    "session_token": token_b,
                })
                assert read.structured_content["ok"] is True
                assert read.structured_content["data"]["consumer_id"] == "agent-b"
                assert read.structured_content["data"]["items"][0]["subject"] == "cross-chat.fact"

                impersonation = await client.call_tool("sentra_context", {
                    "action": "publish",
                    "run_id": run_id,
                    "event_type": "FACT",
                    "subject": "cross-chat.impersonation",
                    "payload": {},
                    "agent_id": "agent-other",
                    "idempotency_key": "cross-chat-impersonation",
                    "context_token": context_token,
                    "session_token": token_b,
                })
                assert impersonation.structured_content["ok"] is False
                assert impersonation.structured_content["error"]["code"] == "forbidden"

                missing_permission = await client.call_tool("sentra_context", {
                    "action": "message_send",
                    "run_id": run_id,
                    "agent_id": "agent-b",
                    "to_agent_id": "*",
                    "body": "not granted",
                    "idempotency_key": "cross-chat-message-denied",
                    "context_token": context_token,
                    "session_token": token_b,
                })
                assert missing_permission.structured_content["ok"] is False
                assert missing_permission.structured_content["error"]["code"] == "forbidden"

                revoked = await client.call_tool("sentra_context", {
                    "action": "grant_revoke",
                    "grant_id": grant["grant_id"],
                    "session_token": token_a,
                })
                assert revoked.structured_content["data"]["revoked"] is True

                denied_after_revoke = await client.call_tool("sentra_context", {
                    "action": "read",
                    "run_id": run_id,
                    "context_token": context_token,
                    "session_token": token_b,
                })
                assert denied_after_revoke.structured_content["ok"] is False
                assert denied_after_revoke.structured_content["error"]["code"] == "forbidden"
        finally:
            runtime.processes.shutdown()
            runtime.search.close()
            runtime.remote_store.close()
            runtime.context.close()
            runtime.durable.close()

    asyncio.run(probe())



def test_fixed_conversation_router_uses_real_control_plane_bridge(tmp_path: Path) -> None:
    class Inner:
        def __init__(self) -> None:
            self.providers = {}
            self.requests = []

        async def execute(self, request, preferred_provider=None):
            self.requests.append(request)
            url = "https://chatgpt.com/c/context-bridge-e2e"
            return AgentResponse(
                content="executor incorporated shared evidence",
                success=True,
                model="fake",
                token_usage=TokenUsage(model="fake"),
                metadata={
                    "conversation_url": url,
                    "conversation_id": "context-bridge-e2e",
                    "worker": "TAB-CONTEXT",
                },
            )

    async def probe() -> None:
        durable, context, control = _services(tmp_path)
        try:
            run = durable.create_run("owner-a")
            control.publish_context(
                run["run_id"], "owner-a",
                event_type="FACT",
                subject="shared.baseline",
                payload={"artifact": "baseline-1"},
                evidence=[],
                confidence=1.0,
                supersedes=[],
                task_id=None,
                agent_id=None,
                idempotency_key="shared-baseline",
            )
            bridge = ControlPlaneContextBridge(control, "owner-a", max_chars=5000)
            inner = Inner()
            pool = FixedConversationRouter(
                inner,
                run_id=run["run_id"],
                store_dir=tmp_path / "conversations",
                shared_context_bridge=bridge,
            )
            request = AgentRequest(
                system_prompt="executor system",
                user_prompt="perform task",
                role="executor",
                timeout=30,
                metadata={"task_id": "T-1"},
            )
            response = await pool.execute(request)
            assert response.success is True
            assert len(inner.requests) == 1
            sent = inner.requests[0]
            assert "SHARED_CONTEXT_NON_AUTHORITATIVE" in sent.user_prompt
            assert "shared.baseline" in sent.user_prompt
            assert sent.metadata["shared_context_count"] == 1

            delta = control.read_context(
                run["run_id"], "owner-a",
                after_seq=0,
                types=["RESULT"],
                subject_prefixes=["oma.response.executor."],
                limit=20,
            )
            assert len(delta["items"]) == 1
            result = delta["items"][0]
            assert result["payload"]["text"] == "executor incorporated shared evidence"
            assert result["payload"]["response_meta"]["conversation_id"] == "context-bridge-e2e"

            status = durable.run_status(run["run_id"], "owner-a")
            seat_agent = next(
                item for item in status["agents"]
                if item["metadata"].get("seat") == f"{run['run_id']}:executor"
            )
            assert seat_agent["role"] == "executor"
            chat = next(
                item for item in status["chats"]
                if item["agent_id"] == seat_agent["agent_id"]
            )
            assert chat["conversation_id"] == "context-bridge-e2e"
        finally:
            context.close()
            durable.close()

    asyncio.run(probe())


def test_control_plane_context_compiler_preserves_relevant_overflow_cursor(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        run = durable.create_run("owner-a")
        ignored = control.publish_context(
            run["run_id"], "owner-a",
            event_type="RESULT", subject="other.task",
            payload={"value": "ignored"}, evidence=[], confidence=None,
            supersedes=[], task_id="T-other", agent_id=None,
            idempotency_key="compiler-ignored",
        )
        first = control.publish_context(
            run["run_id"], "owner-a",
            event_type="FACT", subject="current.first",
            payload={"value": 1}, evidence=[], confidence=1.0,
            supersedes=[], task_id="T-1", agent_id=None,
            idempotency_key="compiler-first",
        )
        second = control.publish_context(
            run["run_id"], "owner-a",
            event_type="OBJECTION", subject="current.second",
            payload={"value": 2}, evidence=[], confidence=None,
            supersedes=[], task_id="T-1", agent_id=None,
            idempotency_key="compiler-second",
        )
        bridge = ControlPlaneContextBridge(
            control, "owner-a", max_chars=5000, max_items=1
        )
        seat = f"{run['run_id']}:executor"

        batch = bridge.prepare(
            run_id=run["run_id"], role="executor", task_id="T-1", seat=seat
        )
        assert batch.count == 1
        assert "current.first" in batch.text
        assert "current.second" not in batch.text
        assert batch.last_seq == first["seq"]
        assert batch.last_seq > ignored["seq"]
        assert batch.truncated is True
        assert batch.epoch.startswith("ctx-")
        assert batch.estimated_tokens > 0

        bridge.acknowledge(
            run_id=run["run_id"], role="executor", task_id="T-1", seat=seat,
            consumer_id=batch.consumer_id, last_seq=batch.last_seq,
        )
        next_batch = bridge.prepare(
            run_id=run["run_id"], role="executor", task_id="T-1", seat=seat
        )
        assert next_batch.count == 1
        assert next_batch.last_seq == second["seq"]
        assert "current.second" in next_batch.text
    finally:
        context.close()
        durable.close()
