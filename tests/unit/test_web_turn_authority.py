from __future__ import annotations

import json
import os
import time

import pytest

from sentra_model_gateway.turn_authority import TurnAuthority
from sentra_mcp.services.context import ContextBusService
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


def test_native_turn_correlation_survives_authority_restart(tmp_path):
    path = tmp_path / "browser.json"
    authority = TurnAuthority(tmp_path / "state", path)
    token = authority.issue(request_identity=json.dumps({
        "thread_id": "thread-persisted", "turn_id": "native-persisted",
    }))
    authority.authorize("register", {
        "capability": token, "traceId": "trace-persisted", "allowedTools": [],
    })
    authority.durable.close()
    recovered = TurnAuthority(tmp_path / "state", path)
    try:
        evidence = recovered.telemetry_metadata(token)
        assert evidence["correlation_id"] == "native-persisted"
        assert evidence["trace_id"] == "trace-persisted"
        assert evidence["completion_verified"] is False
        assert token not in json.dumps(evidence)
        recovered.retire(token, failed=True)
    finally:
        recovered.durable.close()


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


def test_turn_authority_records_harness_goal(tmp_path: Path) -> None:
    descriptor = tmp_path / "launcher-browser.json"
    authority = TurnAuthority(tmp_path / "state", descriptor)
    try:
        token = authority.issue(
            request_identity="goal-turn-1",
            goal_text="Make the SENTRA release gates green.",
        )
        capability = authority._capability(token)
        run = authority.durable.run_status(capability.run_id, capability.owner)
        assert len(run["goals"]) == 1
        goal = run["goals"][0]
        assert goal["objective"] == "Make the SENTRA release gates green."
        assert goal["metadata"]["harness_owned"] is True
        assert goal["external_key"] == "codex-native-goal"
    finally:
        authority.durable.close()


def test_codex_goal_persists_across_turns_clear_and_restart(tmp_path) -> None:
    state = tmp_path / "state"
    descriptor_path = tmp_path / "browser.json"
    owner = "sentra:web-model-gateway"
    conversation_uri = "conversation://goal-continuity"
    authority = TurnAuthority(state, descriptor_path)
    try:
        first = authority.issue(
            conversation_uri=conversation_uri,
            request_identity=json.dumps({"thread_id": "thread-1", "turn_id": "turn-1"}),
            goal_text="Ship SENTRA with all gates green.",
            goal_present=True,
        )
        first_cap = authority._capability(first)
        first_events = authority.durable.events(first_cap.run_id, owner, limit=100)
        link = [
            item for item in first_events["items"]
            if item.get("type") == "CHECKPOINT"
            and (item.get("payload") or {}).get("label") == "codex-goal-link"
        ][-1]
        link_data = link["payload"]["data"]
        goal_run_id = link_data["goal_run_id"]
        goal_id = link_data["goal_id"]

        authority.issue(
            conversation_uri="conversation://replacement-chat",
            request_identity=json.dumps({"thread_id": "thread-1", "turn_id": "turn-2"}),
            goal_text=None,
            goal_present=False,
        )
        persisted = authority.durable.goal_info(goal_id, owner)
        assert persisted["state"] == "ACTIVE"
        assert persisted["objective"] == "Ship SENTRA with all gates green."

        authority.issue(
            conversation_uri=conversation_uri,
            request_identity=json.dumps({"thread_id": "thread-1", "turn_id": "turn-3"}),
            goal_text=None,
            goal_present=True,
        )
        cleared = authority.durable.goal_info(goal_id, owner)
        assert cleared["state"] == "PAUSED"
        assert cleared["metadata"]["cleared"] is True

        authority.issue(
            conversation_uri=conversation_uri,
            request_identity=json.dumps({"thread_id": "thread-1", "turn_id": "turn-4"}),
            goal_text="Ship SENTRA after real Edge E2E passes.",
            goal_present=True,
        )
        resumed = authority.durable.goal_info(goal_id, owner)
        assert resumed["state"] == "ACTIVE"
        assert resumed["objective"] == "Ship SENTRA after real Edge E2E passes."
        assert resumed["metadata"]["cleared"] is False
        assert resumed["run_id"] == goal_run_id
    finally:
        authority.durable.close()

    recovered = TurnAuthority(state, descriptor_path)
    try:
        recovered_goal = recovered.durable.goal_info(goal_id, owner)
        assert recovered_goal["state"] == "ACTIVE"
        assert recovered_goal["objective"] == "Ship SENTRA after real Edge E2E passes."
        authority_runs = [
            item for item in recovered.durable.list_runs(owner, limit=1000)["items"]
            if (item.get("capability_snapshot") or {}).get("kind") == "codex-goal-authority"
        ]
        assert len(authority_runs) == 1
        assert authority_runs[0]["run_id"] == goal_run_id
    finally:
        recovered.durable.close()


def test_native_codex_subagent_binds_to_parent_goal_and_survives_restart(tmp_path) -> None:
    state = tmp_path / "state"
    descriptor_path = tmp_path / "browser.json"
    owner = "sentra:web-model-gateway"
    authority = TurnAuthority(state, descriptor_path)
    try:
        root_token = authority.issue(
            request_identity=json.dumps({
                "thread_id": "thread-root",
                "turn_id": "turn-root-1",
                "request_kind": "turn",
                "agent_name": "/root",
            }),
            goal_text="Release SENTRA only after all gates pass.",
            goal_present=True,
        )
        root_cap = authority._capability(root_token)
        root_progress = authority.durable.operation_status(
            root_cap.operation_id, owner
        )["progress"]
        root_goal_run_id = root_progress["goal_run_id"]
        root_goal_id = root_progress["goal_id"]

        child_token = authority.issue(
            request_identity=json.dumps({
                "thread_id": "thread-child-a",
                "turn_id": "turn-child-a-1",
                "request_kind": "turn",
                "parent_thread_id": "thread-root",
                "agent_name": "/root/auditor",
                "subagent_kind": "thread_spawn",
            }),
            goal_text="Release SENTRA only after all gates pass.",
            goal_present=True,
            task_text="Audit the browser bridge independently.",
        )
        child_cap = authority._capability(child_token)
        child_progress = authority.durable.operation_status(
            child_cap.operation_id, owner
        )["progress"]
        assert child_progress["goal_run_id"] == root_goal_run_id
        assert child_progress["goal_id"] != root_goal_id
        assert child_progress["agent_id"].startswith("agent-codex-")

        child_goal = authority.durable.goal_info(child_progress["goal_id"], owner)
        assert child_goal["parent_goal_id"] == root_goal_id
        assert child_goal["objective"] == "Audit the browser bridge independently."
        status = authority.durable.run_status(root_goal_run_id, owner)
        agent = next(
            item for item in status["agents"]
            if item["agent_id"] == child_progress["agent_id"]
        )
        assert agent["goal_id"] == child_progress["goal_id"]
        assert agent["metadata"]["codex_thread_id"] == "thread-child-a"

        follow_token = authority.issue(
            request_identity=json.dumps({
                "thread_id": "thread-child-a",
                "turn_id": "turn-child-a-2",
                "request_kind": "turn",
            }),
            goal_present=False,
            task_text="Continue",
        )
        follow_cap = authority._capability(follow_token)
        follow_progress = authority.durable.operation_status(
            follow_cap.operation_id, owner
        )["progress"]
        assert follow_progress["goal_run_id"] == root_goal_run_id
        assert follow_progress["goal_id"] == child_progress["goal_id"]
        assert follow_progress["agent_id"] == child_progress["agent_id"]
    finally:
        authority.durable.close()

    recovered = TurnAuthority(state, descriptor_path)
    try:
        after_restart = recovered.issue(
            request_identity=json.dumps({
                "thread_id": "thread-child-a",
                "turn_id": "turn-child-a-3",
                "request_kind": "turn",
            }),
            goal_present=False,
            task_text="Continue after restart",
        )
        cap = recovered._capability(after_restart)
        progress = recovered.durable.operation_status(
            cap.operation_id, owner
        )["progress"]
        assert progress["goal_run_id"] == root_goal_run_id
        assert progress["goal_id"] == child_progress["goal_id"]
        assert progress["agent_id"] == child_progress["agent_id"]
    finally:
        recovered.durable.close()


def test_nested_native_subagent_uses_same_goal_tree_and_notification_closes_subgoal(tmp_path) -> None:
    state = tmp_path / "state"
    descriptor_path = tmp_path / "browser.json"
    owner = "sentra:web-model-gateway"
    authority = TurnAuthority(state, descriptor_path)
    try:
        root = authority.issue(
            request_identity=json.dumps({
                "thread_id": "thread-root-nested",
                "turn_id": "turn-root-1",
                "request_kind": "turn",
                "agent_name": "/root",
            }),
            goal_text="Release SENTRA with native multi-agent coordination.",
            goal_present=True,
        )
        root_cap = authority._capability(root)
        root_progress = authority.durable.operation_status(
            root_cap.operation_id, owner
        )["progress"]

        child = authority.issue(
            request_identity=json.dumps({
                "thread_id": "thread-child-nested",
                "turn_id": "turn-child-1",
                "request_kind": "turn",
                "parent_thread_id": "thread-root-nested",
                "agent_name": "/root/child",
                "subagent_kind": "thread_spawn",
            }),
            goal_text="Release SENTRA with native multi-agent coordination.",
            goal_present=True,
            task_text="Audit the Control Plane.",
        )
        child_cap = authority._capability(child)
        child_progress = authority.durable.operation_status(
            child_cap.operation_id, owner
        )["progress"]

        grandchild = authority.issue(
            request_identity=json.dumps({
                "thread_id": "thread-grandchild-nested",
                "turn_id": "turn-grandchild-1",
                "request_kind": "turn",
                "parent_thread_id": "thread-child-nested",
                "agent_name": "/root/child/reviewer",
                "subagent_kind": "thread_spawn",
            }),
            goal_present=False,
            task_text="Review the child findings adversarially.",
        )
        grand_cap = authority._capability(grandchild)
        grand_progress = authority.durable.operation_status(
            grand_cap.operation_id, owner
        )["progress"]

        assert child_progress["goal_run_id"] == root_progress["goal_run_id"]
        assert grand_progress["goal_run_id"] == root_progress["goal_run_id"]
        grand_goal = authority.durable.goal_info(grand_progress["goal_id"], owner)
        assert grand_goal["parent_goal_id"] == child_progress["goal_id"]

        authority.issue(
            request_identity=json.dumps({
                "thread_id": "thread-root-nested",
                "turn_id": "turn-root-2",
                "request_kind": "turn",
                "agent_name": "/root",
            }),
            goal_present=False,
            subagent_notifications=[{
                "agent_path": "thread-grandchild-nested",
                "status": {"completed": "review complete"},
                "turn_id": "turn-root-2",
            }],
        )
        closed_goal = authority.durable.goal_info(grand_progress["goal_id"], owner)
        assert closed_goal["state"] == "SUCCEEDED"
        run_status = authority.durable.run_status(root_progress["goal_run_id"], owner)
        closed_agent = next(
            item for item in run_status["agents"]
            if item["agent_id"] == grand_progress["agent_id"]
        )
        assert closed_agent["state"] == "AVAILABLE"

        followup = authority.issue(
            request_identity=json.dumps({
                "thread_id": "thread-grandchild-nested",
                "turn_id": "turn-grandchild-2",
                "request_kind": "turn",
            }),
            goal_present=False,
            task_text="Review one additional edge case.",
        )
        followup_cap = authority._capability(followup)
        followup_progress = authority.durable.operation_status(
            followup_cap.operation_id, owner
        )["progress"]
        assert followup_progress["agent_id"] == grand_progress["agent_id"]
        assert followup_progress["goal_run_id"] == root_progress["goal_run_id"]
        assert followup_progress["goal_id"] != grand_progress["goal_id"]
        successor = authority.durable.goal_info(
            followup_progress["goal_id"], owner
        )
        assert successor["state"] == "ACTIVE"
        assert successor["parent_goal_id"] == child_progress["goal_id"]
        assert successor["metadata"]["successor_of"] == grand_progress["goal_id"]
        resumed_agent = next(
            item for item in authority.durable.run_status(
                root_progress["goal_run_id"], owner
            )["agents"]
            if item["agent_id"] == grand_progress["agent_id"]
        )
        assert resumed_agent["state"] == "ACTIVE"
        assert resumed_agent["goal_id"] == followup_progress["goal_id"]

        authority.issue(
            request_identity=json.dumps({
                "thread_id": "thread-root-nested",
                "turn_id": "turn-root-3",
                "request_kind": "turn",
                "agent_name": "/root",
            }),
            goal_present=False,
            subagent_notifications=[{
                "agent_path": "thread-grandchild-nested",
                "status": {"completed": "review complete"},
                "turn_id": "turn-root-2",
            }],
        )
        successor_after_replay = authority.durable.goal_info(
            followup_progress["goal_id"], owner
        )
        assert successor_after_replay["state"] == "ACTIVE"

        context = ContextBusService(state)
        try:
            delta = context.read_delta(
                root_progress["goal_run_id"],
                owner,
                types=["RESULT"],
                limit=100,
            )
            event = next(
                item for item in delta["items"]
                if item["agent_id"] == grand_progress["agent_id"]
            )
            assert event["payload"]["result"] == "review complete"
            assert event["payload"]["goal_id"] == grand_progress["goal_id"]
        finally:
            context.close()
    finally:
        authority.durable.close()


def test_native_codex_subagent_late_binds_when_parent_goal_appears(tmp_path) -> None:
    state = tmp_path / "state"
    descriptor_path = tmp_path / "browser.json"
    owner = "sentra:web-model-gateway"
    authority = TurnAuthority(state, descriptor_path)
    try:
        child_token = authority.issue(
            request_identity=json.dumps({
                "thread_id": "thread-child-late",
                "turn_id": "turn-child-late-1",
                "request_kind": "turn",
                "parent_thread_id": "thread-root-late",
                "agent_name": "/root/late_child",
                "subagent_kind": "thread_spawn",
            }),
            goal_present=False,
            task_text="Inspect the release gate.",
        )
        child_cap = authority._capability(child_token)
        before = authority.durable.operation_status(
            child_cap.operation_id, owner
        )["progress"]
        assert before["agent_id"].startswith("agent-codex-")
        assert before["goal_id"] is None

        authority.issue(
            request_identity=json.dumps({
                "thread_id": "thread-root-late",
                "turn_id": "turn-root-late-1",
                "request_kind": "turn",
                "agent_name": "/root",
            }),
            goal_text="Release only after every live gate passes.",
            goal_present=True,
        )

        follow_token = authority.issue(
            request_identity=json.dumps({
                "thread_id": "thread-child-late",
                "turn_id": "turn-child-late-2",
                "request_kind": "turn",
            }),
            goal_present=False,
            task_text="Inspect the release gate.",
        )
        follow_cap = authority._capability(follow_token)
        after = authority.durable.operation_status(
            follow_cap.operation_id, owner
        )["progress"]
        assert after["agent_id"] == before["agent_id"]
        assert isinstance(after["goal_id"], str)
        child_goal = authority.durable.goal_info(after["goal_id"], owner)
        assert child_goal["objective"] == "Inspect the release gate."
        assert child_goal["parent_goal_id"]
    finally:
        authority.durable.close()
