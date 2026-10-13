"""Pulso shell dispatch, terminal ledger and human receipts.

Future validation only (not executed during integral implementation).
Shell dispatch tests use lightweight fake control/governance/canvas handles;
no real Canvas, Control Plane or browser is required.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from sentra_interop.workflow_shell import (
    PulsoShellDispatch, PulsoShellDenied, SHELL_ACTIONS)


class FakeGovernance:
    def __init__(self):
        self.routines = {"r1": {"routine_id": "r1", "owner": "owner1",
                                "name": "morning", "enabled": True,
                                "metadata": {}}}

    def list_routines(self, owner, *, enabled_only=False):
        return {"items": [dict(routine) for routine in self.routines.values()
                          if routine["owner"] == owner
                          and (routine["enabled"] or not enabled_only)]}

    def routine_info(self, routine_id, owner):
        routine = self.routines[routine_id]
        if routine["owner"] != owner:
            raise PermissionError("another owner")
        return dict(routine)

    def create_routine(self, owner, **kwargs):
        rid = "r-new"
        self.routines[rid] = {"routine_id": rid, "owner": owner, **kwargs}
        return dict(self.routines[rid])

    def set_routine_enabled(self, routine_id, owner, *, enabled):
        self.routines[routine_id]["enabled"] = enabled


class FakeCanvasStore:
    def __init__(self, principal, workspaces):
        self.principal = principal
        self._workspaces = workspaces

    def workspace(self, workspace_id):
        return dict(self._workspaces[workspace_id])

    def resource(self, kind, resource_id, workspace_id):
        assert kind == "terminals"
        return {"id": resource_id, "status": "running"}


class FakeCanvas:
    def __init__(self, principal, workspaces, run_id="run1"):
        self.store = FakeCanvasStore(principal, workspaces)
        self._owner = "canvas:" + principal
        self._run_id = run_id

    def _runtime(self):
        return SimpleNamespace(owner=self._owner,
                               run=lambda ws: {"run_id": self._run_id})

    def terminal_output(self, workspace_id, terminal_id, cursor=0):
        assert terminal_id == "t1"
        return {"text": "hello-terminal", "cursor": cursor + 5,
                "status": "running", "truncated": False}


def _control_store(path):
    @contextmanager
    def connect(name):
        assert name == "execution_workspace"
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()
    return connect


class FakeControl:
    def __init__(self, store_path=None, workspace_path="ws-path",
                 run_id="run1"):
        self.store = SimpleNamespace(
            connect=_control_store(store_path)) if store_path else None
        self.durable = SimpleNamespace(
            run_status=lambda rid, owner: {"run_id": rid,
                                           "workspace": workspace_path})
        self.authorization = SimpleNamespace(
            require=lambda **kwargs: {"grant_id": "grant-1"})
        self._fired = []

    def work_item_info(self, work_item_id, owner):
        return {"work_item_id": work_item_id, "run_id": "run1"}

    def fire_routine(self, routine_id, owner, *, run_id, goal_id,
                     source, occurrence_key):
        self._fired.append((routine_id, run_id, occurrence_key))
        return {"status": "ENQUEUED",
                "work_item": {"work_item_id": "wi-fired"}}

    def _run(self, run_id, owner):
        return {"run_id": run_id, "agents": [{"agent_id": "agent1"}]}

    def _agent_from_run(self, run, agent_id):
        if agent_id not in [agent["agent_id"] for agent in run["agents"]]:
            raise FileNotFoundError("agent does not belong to this run")


def _dispatch(tmp_path, **kwargs):
    control = kwargs.pop("control", object())
    governance = kwargs.pop("governance", FakeGovernance())
    return PulsoShellDispatch(control, governance,
                              idempotency_database=str(tmp_path / "shell.sqlite3"),
                              workspace_root=str(tmp_path), **kwargs)


def test_shell_rejects_unknown_action(tmp_path):
    dispatch = _dispatch(tmp_path)
    with pytest.raises(PulsoShellDenied):
        dispatch.dispatch(action="drop_database", owner="owner1",
                          project_id="ws1")


def test_shell_never_accepts_browser_owner(tmp_path):
    dispatch = _dispatch(tmp_path)
    with pytest.raises(PulsoShellDenied):
        dispatch.dispatch(action="schedule_list", owner="",
                          project_id="ws1")


def test_shell_mutation_replays_by_request_key(tmp_path):
    dispatch = _dispatch(tmp_path)
    first = dispatch.dispatch(
        action="schedule_create", owner="owner1", project_id="ws1",
        request_key="req-12345678",
        params={"trigger_spec": {"every_seconds": 3600},
                "work_template": {"objective": "nightly digest"}})
    assert first["ok"] is True
    assert first["request_key"] == "req-12345678"
    second = dispatch.dispatch(
        action="schedule_create", owner="owner1", project_id="ws1",
        request_key="req-12345678",
        params={"trigger_spec": {"every_seconds": 3600},
                "work_template": {"objective": "nightly digest"}})
    assert second["idempotent_replay"] is True
    assert second["value"] == first["value"]


def test_shell_schedule_reads(tmp_path):
    dispatch = _dispatch(tmp_path)
    listed = dispatch.dispatch(action="schedule_list", owner="owner1",
                               project_id="ws1")
    assert listed["ok"] is True
    assert listed["value"]["page"]["total"] == 1
    single = dispatch.dispatch(action="schedule_get", owner="owner1",
                               project_id="ws1",
                               params={"routine_id": "r1"})
    assert single["value"]["routine"]["routine_id"] == "r1"


def test_shell_workflow_intent_builds_without_effect(tmp_path):
    dispatch = _dispatch(tmp_path)
    intent = dispatch.dispatch(
        action="workflow_intent", owner="owner1", project_id="ws1",
        request_key="wf-req-12345678",
        params={"intent_kind": "advance", "workflow_id": "wf1",
                "namespace": ""})
    assert intent["value"]["capability_id"] == "workflow:advance"
    assert intent["value"]["effects_started"] is False


def test_shell_workflow_reads_need_resolver(tmp_path):
    dispatch = _dispatch(tmp_path)
    with pytest.raises(PulsoShellDenied):
        dispatch.dispatch(action="workflow_observe", owner="owner1",
                          project_id="ws1",
                          params={"workflow_id": "wf1"})


def test_shell_terminal_needs_canvas(tmp_path):
    dispatch = _dispatch(tmp_path)
    with pytest.raises(PulsoShellDenied):
        dispatch.dispatch(
            action="terminal_read", owner="owner1", project_id="ws1",
            params={"run_id": "run1", "work_item_id": "wi1",
                    "principal_id": "agent1", "terminal_id": "t1"})


def test_shell_action_catalog_matches_contract(tmp_path):
    expected = {"schedule_list", "schedule_get", "schedule_create",
                "schedule_enable", "schedule_disable", "schedule_pause",
                "schedule_resume", "schedule_fire",
                "goal_status", "goal_set", "goal_open", "goal_advance",
                "goal_stop", "workflow_intent", "workflow_observe",
                "workflow_output", "runtime_intent", "runtime_observe",
                "terminal_list", "terminal_read",
                "terminal_write", "receipt_get",
                "channel_list", "channel_enable", "channel_renew",
                "channel_disable", "channel_revoke", "channel_send_intent",
                "channel_inbox", "channel_claim", "channel_ack"}
    assert SHELL_ACTIONS == expected
    assert len(SHELL_ACTIONS) == 31


def _canvas(tmp_path, principal="vitor"):
    return FakeCanvas(principal, {"ws1": {"owner": principal,
                                          "path": str(tmp_path),
                                          "run_id": "run1"}})


def test_shell_canonical_owner_enforced(tmp_path):
    canvas = _canvas(tmp_path)
    dispatch = _dispatch(tmp_path, control=FakeControl(), canvas=canvas)
    with pytest.raises(PermissionError):
        dispatch.dispatch(action="schedule_list", owner="intruder",
                          project_id="ws1")
    ok_response = dispatch.dispatch(action="schedule_list", owner="canvas:vitor",
                                    project_id="ws1")
    assert ok_response["ok"] is True


def test_shell_denies_browser_identity_params(tmp_path):
    dispatch = _dispatch(tmp_path)
    with pytest.raises(PulsoShellDenied):
        dispatch.dispatch(action="schedule_fire", owner="owner1",
                          project_id="ws1", request_key="fire-key-1",
                          params={"routine_id": "r1", "run_id": "evil-run",
                                  "operator_approved": True})


def test_shell_fire_derives_server_run(tmp_path):
    governance = FakeGovernance()
    governance.routines["rf"] = {
        "routine_id": "rf", "owner": "canvas:vitor", "name": "bound",
        "enabled": True,
        "metadata": {"workspace_id": "ws1",
                     "_runtime_authority_run_id": "run1"}}
    control = FakeControl(workspace_path=str(tmp_path))
    dispatch = _dispatch(tmp_path, control=control, governance=governance,
                         canvas=_canvas(tmp_path))
    outcome = dispatch.dispatch(
        action="schedule_fire", owner="canvas:vitor", project_id="ws1",
        request_key="fire-key-2222",
        params={"routine_id": "rf", "operator_approved": True})
    assert outcome["value"]["status"] == "ENQUEUED"
    assert outcome["value"]["run_id"] == "run1"
    assert control._fired[0][:2] == ("rf", "run1")


def test_shell_fire_rejects_foreign_project(tmp_path):
    governance = FakeGovernance()
    governance.routines["rx"] = {
        "routine_id": "rx", "owner": "canvas:vitor", "name": "foreign",
        "enabled": True,
        "metadata": {"workspace_id": "other-ws",
                     "_runtime_authority_run_id": "run9"}}
    dispatch = _dispatch(tmp_path, control=FakeControl(),
                         governance=governance, canvas=_canvas(tmp_path))
    with pytest.raises(PermissionError):
        dispatch.dispatch(
            action="schedule_get", owner="canvas:vitor", project_id="ws1",
            params={"routine_id": "rx"})
    listed = dispatch.dispatch(action="schedule_list", owner="canvas:vitor",
                               project_id="ws1")
    assert all(item["routine_id"] != "rx"
               for item in listed["value"]["items"])


def test_shell_replay_rejects_different_payload(tmp_path):
    dispatch = _dispatch(tmp_path)
    dispatch.dispatch(
        action="schedule_create", owner="owner1", project_id="ws1",
        request_key="same-key-AAAAAAAA",
        params={"trigger_spec": {"every_seconds": 60},
                "work_template": {"objective": "one"}})
    with pytest.raises(PulsoShellDenied):
        dispatch.dispatch(
            action="schedule_create", owner="owner1", project_id="ws1",
            request_key="same-key-AAAAAAAA",
            params={"trigger_spec": {"every_seconds": 3600},
                    "work_template": {"objective": "two"}})


def test_shell_uncertain_after_handler_crash(tmp_path):
    calls = []

    class FlakyGovernance(FakeGovernance):
        def create_routine(self, owner, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError("simulated crash before receipt")
            return super().create_routine(owner, **kwargs)

    dispatch = _dispatch(tmp_path, governance=FlakyGovernance())
    with pytest.raises(RuntimeError):
        dispatch.dispatch(
            action="schedule_create", owner="owner1", project_id="ws1",
            request_key="crash-key-BBBB",
            params={"trigger_spec": {"every_seconds": 60},
                    "work_template": {"objective": "fragile"}})
    second = dispatch.dispatch(
        action="schedule_create", owner="owner1", project_id="ws1",
        request_key="crash-key-BBBB",
        params={"trigger_spec": {"every_seconds": 60},
                "work_template": {"objective": "fragile"}})
    assert second["value"]["status"] == "uncertain"
    assert len(calls) == 1


def test_shell_terminal_scope_from_server_ledger(tmp_path):
    store_path = str(tmp_path / "ctrl.sqlite3")
    control = FakeControl(store_path=store_path,
                          workspace_path=str(tmp_path))
    from sentra_executors.conpty_sessions import PersistentConPTYLedger
    ledger = PersistentConPTYLedger(control)
    ledger.register("canvas:vitor", workspace_id="ws1", terminal_id="t1",
                    run_id="run1", work_item_id="wi1", principal_id="agent1",
                    name="main", shell="powershell")
    dispatch = _dispatch(tmp_path, control=control, canvas=_canvas(tmp_path))
    viewed = dispatch.dispatch(action="terminal_read", owner="canvas:vitor",
                               project_id="ws1", request_key="term-key-1",
                               params={"terminal_id": "t1"})
    assert viewed["value"]["head"] == "hello-terminal"
    with pytest.raises(PulsoShellDenied):
        dispatch.dispatch(action="terminal_read", owner="canvas:vitor",
                          project_id="ws1", request_key="term-key-2",
                          params={"terminal_id": "ghost"})


def test_shell_runtime_intent_builder(tmp_path):
    dispatch = _dispatch(tmp_path)
    intent = dispatch.dispatch(
        action="runtime_intent", owner="owner1", project_id="ws1",
        request_key="rt-key-1234",
        params={"provider": "temporal", "operation": "signal",
                "workflow_id": "wf1", "occurrence": "occ1",
                "payload": {"cursor": 3}})
    assert intent["value"]["provider"] == "temporal"
    assert intent["value"]["effects_started"] is False
    with pytest.raises(PulsoShellDenied):
        dispatch.dispatch(
            action="runtime_intent", owner="owner1", project_id="ws1",
            request_key="rt-key-5678",
            params={"provider": "temporal", "operation": "configure",
                    "workflow_id": "wf1", "occurrence": "occ1"})
    with pytest.raises(PulsoShellDenied):
        dispatch.dispatch(
            action="runtime_intent", owner="owner1", project_id="ws1",
            request_key="rt-key-9999",
            params={"provider": "temporal", "operation": "fork",
                    "workflow_id": "wf1", "occurrence": "occ1"})
    with pytest.raises(PulsoShellDenied):
        dispatch.dispatch(action="runtime_observe", owner="owner1",
                          project_id="ws1",
                          params={"provider": "langgraph", "workflow_id": "wf1",
                                  "occurrence": "occ1"})


class FakeTriggerBridge:
    def claim_for_workflow(self, owner, *, connector_id, event_id,
                           consumer_id, expected_revision, lease_seconds):
        assert consumer_id.startswith("pulso-trigger:")
        return {"claim_id": "claim-1", "event_id": event_id,
                "connector_id": connector_id, "project_id": "ws1",
                "workspace_id": "ws1", "revision": expected_revision + 1,
                "dispatch_idempotency_key": f"channel:{connector_id}:{event_id}",
                "capability_id": "workflow:signal",
                "arguments": {"workflow_id": "wf1", "namespace": "",
                              "name": "channel_message",
                              "signal_id": "ch-abc",
                              "payload_sha256": "0" * 64},
                "admit_via": "central operation journal",
                "effects_started": False}

    def ack_claim(self, owner, *, claim_id, work_item_id, operation_id,
                  receipt_id=None):
        return {"claim_id": claim_id, "status": "acknowledged",
                "operation_id": operation_id,
                "receipt_id": receipt_id or operation_id}


def test_shell_channel_claim_ack(tmp_path):
    dispatch = _dispatch(tmp_path, trigger_bridge=FakeTriggerBridge())
    claimed = dispatch.dispatch(
        action="channel_claim", owner="owner1", project_id="ws1",
        request_key="ch-claim-1",
        params={"connector_id": "tg1", "event_id": "e100",
                "expected_revision": 1})
    assert claimed["value"]["capability_id"] == "workflow:signal"
    assert claimed["value"]["dispatch_idempotency_key"] == "channel:tg1:e100"
    acked = dispatch.dispatch(
        action="channel_ack", owner="owner1", project_id="ws1",
        request_key="ch-ack-0001",
        params={"claim_id": "claim-1", "work_item_id": "wi1",
                "operation_id": "op1"})
    assert acked["value"]["status"] == "acknowledged"
