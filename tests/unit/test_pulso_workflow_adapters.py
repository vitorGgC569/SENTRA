"""Pulso adapters: NATS/Temporal/LangGraph subordinate semantics.

Future validation only (not executed during integral implementation).
Covers intent building, dedupe, failure classification and checkpoint
lineage without requiring live NATS, Temporal or LangGraph services.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from sentra_interop.workflow_nats import NATSWorkflowSignalBridge, NATSTransportMissing
from sentra_interop.workflow_temporal import (
    TemporalRetryPolicy, TemporalUpdateLedger, classify_temporal_failure)
from sentra_interop.workflow_langgraph import (
    LangGraphCheckpointBridge, LangGraphNamespaceStore)
from sentra_interop.workflow_contracts import ActivityReceipt
from sentra_interop.workflow_checkpoint import WorkflowCheckpointStore
from sentra_interop.workflow_contracts import WorkflowDefinition, ActivitySpec


def _request():
    return SimpleNamespace(principal_id="agent1", machine_id="m1", work_item_id="w1")


def test_nats_stage_is_idempotent(tmp_path):
    bridge = NATSWorkflowSignalBridge(str(tmp_path / "nats.sqlite3"),
                                      workspace=str(tmp_path),
                                      workflow_id="wf1")
    first = bridge.stage(event_key="evt-1", signal_name="tick",
                         payload={"n": 1})
    second = bridge.stage(event_key="evt-1", signal_name="tick",
                          payload={"n": 1})
    assert first["arguments"] == second["arguments"]
    assert first["capability_id"] == "workflow:signal"
    with pytest.raises(ValueError):
        bridge.stage(event_key="evt-1", signal_name="tick", payload={"n": 2})


def test_nats_drain_without_transport_fails(tmp_path):
    bridge = NATSWorkflowSignalBridge(str(tmp_path / "nats.sqlite3"),
                                      workspace=str(tmp_path),
                                      workflow_id="wf1")
    with pytest.raises(NATSTransportMissing):
        asyncio.run(bridge.drain())


def test_nats_drain_stages_batch(tmp_path):
    async def fake_pull(max_messages):
        return [{"event_key": "k1", "signal_name": "tick", "payload": {"a": 1}}]

    bridge = NATSWorkflowSignalBridge(str(tmp_path / "nats.sqlite3"),
                                      workspace=str(tmp_path),
                                      workflow_id="wf1",
                                      pull_events=fake_pull)
    staged = asyncio.run(bridge.drain())
    assert len(staged) == 1
    assert staged[0]["arguments"]["signal_id"].startswith("nats-")
    assert bridge.pending()[0]["event_key"] == "k1"


def test_temporal_classification():
    assert classify_temporal_failure(
        failure_type="DEPENDENCY_UNAVAILABLE", effect_state="NOT_STARTED") == "RETRYABLE"
    assert classify_temporal_failure(
        failure_type="ACCEPTANCE_FAILED", effect_state="COMPLETED") == "TERMINAL"
    assert classify_temporal_failure(
        failure_type="HEARTBEAT_TIMEOUT_UNKNOWN_EFFECT",
        effect_state="NOT_STARTED") == "UNCERTAIN"
    assert classify_temporal_failure(
        failure_type="RATE_LIMITED_BEFORE_START",
        effect_state="UNKNOWN") == "UNCERTAIN"


def test_temporal_retry_schedule_bounds():
    policy = TemporalRetryPolicy(max_attempts=3, initial_seconds=1,
                                 maximum_seconds=60, coefficient=2,
                                 expiration_seconds=3600)
    receipt = ActivityReceipt(status="FAILED", effect_state="NOT_STARTED",
                              failure_type="DEPENDENCY_UNAVAILABLE",
                              retryable=True)
    first = policy.next_attempt_at(receipt, attempt=1, first_started=1000, now=1000)
    assert first == pytest.approx(1001)
    assert policy.next_attempt_at(receipt, attempt=3, first_started=1000,
                                  now=1000) is None
    terminal = ActivityReceipt(status="FAILED", effect_state="COMPLETED",
                               failure_type="ACCEPTANCE_FAILED")
    assert policy.next_attempt_at(terminal, attempt=1, first_started=1000,
                                  now=1000) is None
    uncertain = ActivityReceipt(status="UNCERTAIN", effect_state="UNKNOWN")
    assert policy.next_attempt_at(uncertain, attempt=1, first_started=1000,
                                  now=1000) is None


def test_temporal_update_ledger_admitted_vs_completed():
    ledger = TemporalUpdateLedger()
    admitted = ledger.admit(update_id="u1", operation_id="op1", workflow_id="wf1")
    assert admitted["phase"] == "ADMITTED"
    assert ledger.admit(update_id="u1", operation_id="op1",
                        workflow_id="wf1") == admitted
    with pytest.raises(ValueError):
        ledger.admit(update_id="u1", operation_id="op2", workflow_id="wf1")
    done = ledger.complete("u1", operation_id="op1", outcome="SUCCEEDED")
    assert done["phase"] == "COMPLETED"


def _definition():
    from sentra_interop.workflow_contracts import ActivitySpec
    return WorkflowDefinition(definition_id="doc", version="v1",
                              worker_version="worker1", steps=(ActivitySpec("wait", kind="wait", signal_name="done"),))


def test_langgraph_lineage_and_memory(tmp_path):
    from sentra_core.conversations import _encode  # noqa: F401
    store = WorkflowCheckpointStore(str(tmp_path / "wf.sqlite3"),
                                    workspace=str(tmp_path))
    request = _request()
    definition = _definition()
    store.open(workflow_id="wf1", ns="", definition=definition,
               request=request, inputs={"a": 1})
    bridge = LangGraphCheckpointBridge(store, idle_timeout_seconds=60)
    lineage = bridge.checkpoint_lineage(request, workflow_id="wf1", ns="")
    assert lineage[0]["namespace"] == ""
    assert lineage[0]["status"] == "READY"
    memory = LangGraphNamespaceStore(store)
    memory.put(workflow_id="wf1", ns="", key="note", value={"text": "hello"})
    found = memory.scan(request, workflow_id="wf1", ns_prefix="", query="hello")
    assert any(entry["key"] == "note" for entry in found)
    bridge.heartbeat(workflow_id="wf1", ns="", step_id="s1")
    assert bridge.idle_expired(workflow_id="wf1", ns="", step_id="s1",
                               now=1000000 + 61) in (True, False)
