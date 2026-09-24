from __future__ import annotations

import pytest

from orchestrator.shared_context import ContextBusSharedContextBridge
from sentra_mcp.services.context import ContextBusService


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
