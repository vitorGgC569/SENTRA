from __future__ import annotations
from sentra_mcp.services.context_projection import ControlPlaneContextBridge
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService

import pytest

from orchestrator.shared_context import ContextBusSharedContextBridge
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.context_projection import ControlPlaneContextBridge
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService


def test_context_bridge_routes_private_and_broadcast_messages_with_cursor(tmp_path) -> None:
    bus = ContextBusService(tmp_path / ".sentra")
    owner = "oma:R1"
    bridge = ContextBusSharedContextBridge(bus, owner=owner, max_events=20, max_chars=8000)
    try:
        fact = bus.publish(
            "R1", owner,
            event_type="FACT",
            subject="benchmark.baseline",
            payload={"artifact": "artifact-1"},
            evidence=[],
            confidence=0.9,
            supersedes=[],
            task_id="T-1",
            agent_id="builder",
            idempotency_key="fact-1",
        )
        other = bus.send_message(
            "R1", owner,
            from_agent_id="builder",
            to_agent_id="judge",
            body="private for judge",
            idempotency_key="msg-other",
        )
        direct = bus.send_message(
            "R1", owner,
            from_agent_id="builder",
            to_agent_id="reviewer.primary",
            body="challenge benchmark",
            idempotency_key="msg-direct",
        )
        broadcast = bus.send_message(
            "R1", owner,
            from_agent_id="builder",
            to_agent_id="*",
            body="checkpoint ready",
            idempotency_key="msg-broadcast",
        )

        batch = bridge.prepare(
            run_id="R1", role="reviewer", task_id="T-1", seat="reviewer.primary"
        )
        assert batch.count == 3
        assert "benchmark.baseline" in batch.text
        assert "challenge benchmark" in batch.text
        assert "checkpoint ready" in batch.text
        assert "private for judge" not in batch.text
        assert batch.last_seq == broadcast["seq"]
        assert batch.last_seq > other["seq"] > fact["seq"]

        bridge.acknowledge(
            run_id="R1", role="reviewer", task_id="T-1", seat="reviewer.primary",
            consumer_id=batch.consumer_id, last_seq=batch.last_seq,
        )
        empty = bridge.prepare(
            run_id="R1", role="reviewer", task_id="T-1", seat="reviewer.primary"
        )
        assert empty.count == 0
        assert empty.text == ""

        bridge.publish_response(
            run_id="R1", role="reviewer", task_id="T-1", seat="reviewer.primary",
            content="benchmark challenged",
            metadata={"model": "fake", "nested": {"ignored": True}},
            request_sha256="a" * 64,
        )
        events = bus.read_delta("R1", owner, after_seq=0, limit=50)["items"]
        response = events[-1]
        assert response["type"] == "RESULT"
        assert response["subject"] == "agent.response.reviewer.reviewer.primary"
        assert response["payload"]["content"] == "benchmark challenged"
        assert response["payload"]["metadata"] == {"model": "fake"}

        bridge.publish_response(
            run_id="R1", role="reviewer", task_id="T-1", seat="reviewer.primary",
            content="benchmark challenged",
            metadata={"model": "fake"},
            request_sha256="a" * 64,
        )
        with pytest.raises(FileExistsError):
            bridge.publish_response(
                run_id="R1", role="reviewer", task_id="T-1", seat="reviewer.primary",
                content="different answer for same request",
                metadata={"model": "fake"},
                request_sha256="a" * 64,
            )
    finally:
        bus.close()


def test_context_bridge_does_not_ack_unrendered_overflow(tmp_path) -> None:
    bus = ContextBusService(tmp_path / ".sentra")
    owner = "oma:R2"
    bridge = ContextBusSharedContextBridge(bus, owner=owner, max_events=1, max_chars=2000)
    try:
        first = bus.publish(
            "R2", owner,
            event_type="FACT", subject="one", payload={"v": 1},
            evidence=[], confidence=None, supersedes=[],
            task_id=None, agent_id=None, idempotency_key="one",
        )
        second = bus.publish(
            "R2", owner,
            event_type="FACT", subject="two", payload={"v": 2},
            evidence=[], confidence=None, supersedes=[],
            task_id=None, agent_id=None, idempotency_key="two",
        )
        batch = bridge.prepare(run_id="R2", role="builder", task_id=None, seat="builder")
        assert batch.count == 1
        assert batch.last_seq == first["seq"]
        bridge.acknowledge(
            run_id="R2", role="builder", task_id=None, seat="builder",
            consumer_id=batch.consumer_id, last_seq=batch.last_seq,
        )
        next_batch = bridge.prepare(run_id="R2", role="builder", task_id=None, seat="builder")
        assert next_batch.count == 1
        assert next_batch.last_seq == second["seq"]
        assert "two" in next_batch.text
    finally:
        bus.close()


def test_control_plane_context_projection_includes_authoritative_goal(tmp_path):
    durable = DurableRunService(tmp_path)
    context = ContextBusService(tmp_path)
    try:
        run = durable.create_run("owner", idempotency_key="goal-context")
        control = ControlPlaneService(durable, context)
        control.create_goal(
            run["run_id"], "owner",
            objective="Keep working until release gates are green",
            acceptance_criteria=["all gates green"],
            priority="HIGH",
        )
        bridge = ControlPlaneContextBridge(control, "owner")
        batch = bridge.prepare(
            run_id=run["run_id"], role="executor", task_id="T-1", seat="executor"
        )
        assert "control_plane_goal" in batch.text
        assert "Keep working until release gates are green" in batch.text
        assert batch.count >= 1
    finally:
        context.close()
        durable.close()

def test_control_plane_context_bridge_preserves_gemini_provider(tmp_path):
    durable = DurableRunService(tmp_path / "durable-gemini")
    context = ContextBusService(tmp_path / "context-gemini")
    try:
        run = durable.create_run("owner-gemini")
        control = ControlPlaneService(durable, context)
        bridge = ControlPlaneContextBridge(control, "owner-gemini")
        seat = f"{run['run_id']}:gemini-reviewer"
        bridge.prepare(
            run_id=run["run_id"], role="gemini-reviewer",
            task_id="T-G", seat=seat,
        )
        bridge.publish_response(
            run_id=run["run_id"], role="gemini-reviewer",
            task_id="T-G", seat=seat, content="GEMINI_OK",
            metadata={
                "provider": "gemini", "web_model": "pro",
                "model": "gemini-web/pro", "worker": "TAB-42",
                "conversation_id": "abc_DEF-123",
                "conversation_url": "https://gemini.google.com/app/abc_DEF-123",
            },
            request_sha256="b" * 64,
        )
        status = durable.run_status(run["run_id"], "owner-gemini")
        chat = next(item for item in status["chats"] if item["chat_id"] == bridge._chat_id(seat))
        assert chat["provider"] == "gemini"
        assert chat["conversation_id"] == "abc_DEF-123"
        assert chat["metadata"]["provider"] == "gemini"
        assert chat["metadata"]["web_model"] == "pro"
        assert chat["metadata"]["model"] == "gemini-web/pro"
    finally:
        context.close()
        durable.close()


def test_control_plane_reconciles_legacy_wrong_gemini_provider(tmp_path):
    durable = DurableRunService(tmp_path / "durable-legacy-gemini")
    context = ContextBusService(tmp_path / "context-legacy-gemini")
    try:
        run = durable.create_run("owner-legacy")
        control = ControlPlaneService(durable, context)
        agent = durable.assign_agent(
            run["run_id"], "owner-legacy", role="reviewer", agent_id="agent-gemini",
        )
        durable.bind_chat(
            run["run_id"], "owner-legacy", agent_id=agent["agent_id"],
            provider="chatgpt", conversation_id="legacy_123",
            conversation_url="https://gemini.google.com/app/legacy_123",
            chat_id="chat-gemini", state="READY", desired_state="READY",
        )
        fixed = control.bind_agent_chat(
            run["run_id"], "owner-legacy",
            agent_id=agent["agent_id"], chat_id="chat-gemini", role="reviewer",
            conversation_id="legacy_123",
            conversation_url="https://gemini.google.com/app/legacy_123",
            provider="gemini",
        )
        assert fixed["provider"] == "gemini"
        assert fixed["conversation_id"] == "legacy_123"
        with pytest.raises(ValueError, match="provider"):
            control.bind_agent_chat(
                run["run_id"], "owner-legacy",
                agent_id=agent["agent_id"], chat_id="chat-gemini", role="reviewer",
                conversation_id="legacy_123",
                conversation_url="https://gemini.google.com/app/legacy_123",
                provider="chatgpt",
            )
    finally:
        context.close()
        durable.close()


def test_control_plane_rejects_cross_agent_chat_rebinding(tmp_path):
    durable = DurableRunService(tmp_path / "durable-chat-ownership")
    context = ContextBusService(tmp_path / "context-chat-ownership")
    try:
        run = durable.create_run("owner-chat")
        control = ControlPlaneService(durable, context)
        first = control.ensure_agent(
            run["run_id"], "owner-chat", agent_id="agent-a", role="architecture",
        )
        second = control.ensure_agent(
            run["run_id"], "owner-chat", agent_id="agent-b", role="security",
        )
        bound = control.bind_agent_chat(
            run["run_id"], "owner-chat",
            agent_id=first["agent_id"], chat_id="chat-fixed", role="architecture",
            conversation_id="conv-a",
            conversation_url="https://chatgpt.com/c/conv-a",
            provider="chatgpt",
        )
        assert bound["agent_id"] == "agent-a"

        with pytest.raises(FileExistsError, match="another agent"):
            control.bind_agent_chat(
                run["run_id"], "owner-chat",
                agent_id=second["agent_id"], chat_id="chat-fixed", role="security",
                conversation_id="conv-b",
                conversation_url="https://chatgpt.com/c/conv-b",
                provider="chatgpt",
            )

        status = durable.run_status(run["run_id"], "owner-chat")
        chat = next(item for item in status["chats"] if item["chat_id"] == "chat-fixed")
        assert chat["agent_id"] == "agent-a"
        assert chat["conversation_id"] == "conv-a"
    finally:
        context.close()
        durable.close()


def test_local_context_bridge_cursor_belongs_to_persistent_seat(tmp_path) -> None:
    bus = ContextBusService(tmp_path / ".sentra-stable-seat")
    owner = "oma:R-seat"
    bridge = ContextBusSharedContextBridge(bus, owner=owner)
    try:
        first = bridge._consumer_id("R-seat", "executor", "T-1", "executor.primary")
        second = bridge._consumer_id("R-seat", "executor", "T-2", "executor.primary")
        assert first == second

        bus.publish(
            "R-seat", owner,
            event_type="FACT", subject="once", payload={"v": 1},
            evidence=[], confidence=None, supersedes=[],
            task_id=None, agent_id=None, idempotency_key="seat-once",
        )
        batch = bridge.prepare(
            run_id="R-seat", role="executor", task_id="T-1", seat="executor.primary"
        )
        assert batch.count == 1
        bridge.acknowledge(
            run_id="R-seat", role="executor", task_id="T-1",
            seat="executor.primary", consumer_id=batch.consumer_id,
            last_seq=batch.last_seq,
        )
        next_task = bridge.prepare(
            run_id="R-seat", role="executor", task_id="T-2", seat="executor.primary"
        )
        assert next_task.count == 0
        assert next_task.text == ""
    finally:
        bus.close()
