from __future__ import annotations

import json
import os
import time

import pytest

from sentra_model_gateway.turn_authority import TurnAuthority
from sentra_mcp.services.durable import DurableStateConflict, StaleFenceError


def descriptor(path, trace="trace123", tab="tab-one", conversation="conversation-one", status="running"):
    path.write_text(json.dumps({
        "version": 3, "kind": "codex-web-gpt-launcher", "sentraManaged": True, "pid": os.getpid(),
        "surfaceTargets": {"surface-one": "target-one", "surface-two": "target-two"},
        "sentraTabs": [{"tabId": tab, "surfaceId": "surface-one" if tab == "tab-one" else "surface-two",
                       "traceId": trace, "conversationKey": conversation, "status": status,
                       "lastHeartbeatAt": time.time() * 1000}],
    }), encoding="utf-8")


def test_tool_and_completion_are_fenced_by_the_same_physical_tab(tmp_path):
    path = tmp_path / "browser.json"
    authority = TurnAuthority(tmp_path / "state", path)
    try:
        token = authority.issue()
        registered = authority.authorize("register", {"capability": token, "traceId": "trace123", "allowedTools": ["exec_command"]})
        descriptor(path)
        authority.authorize("tool", {"capability": token, "traceId": "trace123", "wireName": "exec_command"})
        operation = authority.durable.operation_status(registered["operation_id"], "sentra:web-model-gateway")
        assert operation["state"] == "RUNNING"
        descriptor(path, tab="tab-two")
        with pytest.raises(StaleFenceError):
            authority.authorize("complete", {"capability": token, "traceId": "trace123", "revision": 2})
        descriptor(path)
        authority.authorize("complete", {"capability": token, "traceId": "trace123", "revision": 2})
        assert authority.authorize("complete", {"capability": token, "traceId": "trace123", "revision": 2})["idempotent_replay"]
        operation = authority.durable.operation_status(registered["operation_id"], "sentra:web-model-gateway")
        assert operation["state"] == "SUCCEEDED"
        assert operation["result"]["broker_revision"] == 2
        authority.retire(token)
        with pytest.raises(PermissionError):
            authority.authorize("tool", {"capability": token, "traceId": "trace123", "wireName": "exec_command"})
    finally:
        authority.durable.close()


def test_conversation_lease_blocks_concurrent_physical_tabs(tmp_path):
    path = tmp_path / "browser.json"
    authority = TurnAuthority(tmp_path / "state", path)
    try:
        first = authority.issue()
        second = authority.issue()
        authority.authorize("register", {"capability": first, "traceId": "trace-one", "allowedTools": ["tool"]})
        authority.authorize("register", {"capability": second, "traceId": "trace-two", "allowedTools": ["tool"]})
        descriptor(path, trace="trace-one")
        authority.authorize("tool", {"capability": first, "traceId": "trace-one", "wireName": "tool"})
        descriptor(path, trace="trace-two", tab="tab-two")
        with pytest.raises(DurableStateConflict):
            authority.authorize("tool", {"capability": second, "traceId": "trace-two", "wireName": "tool"})
        authority.retire(first, failed=True)
        authority.authorize("tool", {"capability": second, "traceId": "trace-two", "wireName": "tool"})
    finally:
        authority.durable.close()


def test_read_only_turn_and_compaction_phase_bind_conversation_uri(tmp_path):
    path = tmp_path / "browser.json"
    authority = TurnAuthority(tmp_path / "state", path)
    try:
        token = authority.issue(conversation_uri="conversation://builder-primary")
        descriptor(path, trace="phase-one")
        first = authority.authorize("browser-start", {"capability": token, "traceId": "phase-one"})
        heartbeat = authority.authorize("browser-heartbeat", {"capability": token, "traceId": "phase-one"})
        assert heartbeat["physical_resource"] == first["physical_resource"]
        authority.authorize("browser-complete", {"capability": token, "traceId": "phase-one"})
        info = authority.durable.operation_status(first["operation_id"], "sentra:web-model-gateway")
        assert info["result"]["conversation_uri"] == "conversation://builder-primary"
        descriptor(path, trace="phase-two", tab="tab-two")
        authority.authorize("browser-start", {"capability": token, "traceId": "phase-two"})
        authority.authorize("browser-complete", {"capability": token, "traceId": "phase-two"})
        authority.retire(token)
        run = authority.durable.run_status(info["run_id"], "sentra:web-model-gateway")
        assert run["state"] == "SUCCEEDED"
    finally:
        authority.durable.close()


def test_turn_capability_rehydrates_after_gateway_restart(tmp_path):
    path = tmp_path / "browser.json"
    state = tmp_path / "state"
    first = TurnAuthority(state, path)
    token = first.issue(conversation_uri="conversation://builder-primary")
    registered = first.authorize("register", {"capability": token, "traceId": "trace123", "allowedTools": ["exec_command"]})
    descriptor(path)
    first.authorize("tool", {"capability": token, "traceId": "trace123", "wireName": "exec_command"})
    first.durable.close()

    recovered = TurnAuthority(state, path)
    try:
        tool = recovered.authorize("tool", {"capability": token, "traceId": "trace123", "wireName": "exec_command"})
        assert tool["operation_id"] == registered["operation_id"]
        recovered.authorize("complete", {"capability": token, "traceId": "trace123", "revision": 7})
        operation = recovered.durable.operation_status(registered["operation_id"], "sentra:web-model-gateway")
        assert operation["state"] == "SUCCEEDED"
        assert operation["result"]["broker_revision"] == 7
        recovered.retire(token)
    finally:
        recovered.durable.close()


def test_logical_conversation_uri_is_leased_before_upstream_conversation_exists(tmp_path):
    path = tmp_path / "browser.json"
    authority = TurnAuthority(tmp_path / "state", path)
    try:
        first = authority.issue(conversation_uri="conversation://builder-primary")
        second = authority.issue(conversation_uri="conversation://builder-primary")
        descriptor(path, trace="logical-one", tab="tab-one", conversation="")
        authority.authorize("browser-start", {"capability": first, "traceId": "logical-one"})
        descriptor(path, trace="logical-two", tab="tab-two", conversation="")
        with pytest.raises(DurableStateConflict):
            authority.authorize("browser-start", {"capability": second, "traceId": "logical-two"})
        authority.retire(first, failed=True)
        authority.authorize("browser-start", {"capability": second, "traceId": "logical-two"})
        authority.authorize("browser-complete", {"capability": second, "traceId": "logical-two"})
        authority.retire(second)
    finally:
        authority.durable.close()


def test_failed_delivery_blocks_run_after_durable_completion(tmp_path):
    path = tmp_path / "browser.json"
    authority = TurnAuthority(tmp_path / "state", path)
    try:
        token = authority.issue()
        registered = authority.authorize("register", {"capability": token, "traceId": "trace123", "allowedTools": []})
        descriptor(path)
        authority.authorize("complete", {"capability": token, "traceId": "trace123", "revision": 3})
        authority.retire(token, failed=True)
        run = authority.durable.run_status(registered["run_id"], "sentra:web-model-gateway")
        assert run["state"] == "BLOCKED"
        events = authority.durable.events(registered["run_id"], "sentra:web-model-gateway", limit=1000)
        assert any(
            item.get("type") == "CHECKPOINT"
            and (item.get("payload") or {}).get("label") == "web-response-delivery"
            for item in events.get("items", [])
        )
    finally:
        authority.durable.close()


def test_turn_capability_rejects_tool_outside_registered_contract(tmp_path):
    path = tmp_path / "browser.json"
    authority = TurnAuthority(tmp_path / "state", path)
    try:
        token = authority.issue()
        authority.authorize(
            "register",
            {"capability": token, "traceId": "trace-tools", "allowedTools": ["workspace__read_file"]},
        )
        descriptor(path, trace="trace-tools")
        authority.authorize(
            "tool",
            {"capability": token, "traceId": "trace-tools", "wireName": "workspace__read_file"},
        )
        with pytest.raises(PermissionError):
            authority.authorize(
                "tool",
                {"capability": token, "traceId": "trace-tools", "wireName": "exec_command"},
            )
        authority.retire(token, failed=True)
    finally:
        authority.durable.close()


def test_retired_blocked_capability_cannot_rehydrate(tmp_path):
    path = tmp_path / "browser.json"
    state = tmp_path / "state"
    first = TurnAuthority(state, path)
    token = first.issue()
    first.authorize(
        "register",
        {"capability": token, "traceId": "trace-retired", "allowedTools": []},
    )
    descriptor(path, trace="trace-retired")
    first.authorize("complete", {"capability": token, "traceId": "trace-retired", "revision": 1})
    first.retire(token, failed=True)
    first.durable.close()

    recovered = TurnAuthority(state, path)
    try:
        with pytest.raises(PermissionError):
            recovered.authorize(
                "register",
                {"capability": token, "traceId": "trace-retired", "allowedTools": []},
            )
    finally:
        recovered.durable.close()
