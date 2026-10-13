"""Isolated authorization UX regressions. No real Grants, files or project mutations."""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sentra_canvas.service import Canvas
from sentra_canvas.store import Denied


def _canvas(*, tasks, eligible=(), run_state="RUNNING"):
    owner, workspace, conversation, agent = "canvas:owner", "project-test", "conv-one", "dot-agent"
    machine_id = "canvas-workspace-files-test"
    machine = dict(machine_id=machine_id, kind="workspace-files", workspace_id=workspace,
                   agent_id=agent, capabilities=["workspace:file.read", "workspace:file.write",
                                                   "workspace:file.delete"])
    status = dict(run_id="run-test", state=run_state)
    entity = Mock(side_effect=lambda db, _owner, _workspace, kind, _id, **kw:
                  {"dot_id": "dot-one", "space_id": "space-one"} if kind == "conversation"
                  else {"agent_id": agent, "name": "Test Dot"})
    auth = SimpleNamespace(list_grants=Mock(return_value={"items": []}))
    state = {}
    grant_counter = [0]

    def create(*args, **kwargs):
        state["created"] = kwargs
        return {"work_item_id": kwargs["work_item_id"], "state": "QUEUED"}

    def grant(*args, **kwargs):
        grant_counter[0] += 1
        return {"grant_id": f"grant-test-{grant_counter[0]}"}

    control = SimpleNamespace(
        store=SimpleNamespace(connect=lambda _: sqlite3.connect(":memory:")),
        shell=SimpleNamespace(_entity=entity),
        list_work_items=Mock(return_value={"items": tasks}),
        authorization=auth, ensure_agent=Mock(), create_work_item=Mock(side_effect=create),
        authorization_grant=Mock(side_effect=grant), transition_work_item=Mock(),
        work_item_info=Mock(side_effect=lambda wi, _owner: {"work_item_id": wi, "state": "RUNNING"}),
    )
    host = SimpleNamespace(owner=owner, control=control,
                           inventory=Mock(return_value=[machine]),
                           task_catalog=Mock(return_value=list(eligible)))
    runtime = SimpleNamespace(owner=owner, run=Mock(return_value=status),
                              durable=SimpleNamespace(transition_run=Mock()))
    canvas = object.__new__(Canvas)
    canvas.store = SimpleNamespace(workspace=Mock(return_value={"id": workspace}))
    canvas._machine_service = lambda: host
    canvas._runtime = lambda: runtime
    return canvas, host, control, runtime, state, machine


def test_file_workitems_are_scoped_and_only_live_grants_are_selectable():
    def item(wi, cid, aid="dot-agent", mid="canvas-workspace-files-test"):
        return dict(work_item_id=wi, run_id="run-test", state="RUNNING",
                    assignee_agent_id=aid, required_capabilities=["workspace:file.read"],
                    metadata={"workspace_id":"project-test", "machine_id":mid,
                              "conversation_id":cid, "file_access_owner_approved":True})
    tasks = [item("wi-right", "conv-one"), item("wi-other", "conv-other"),
             item("wi-other-dot", "conv-one", aid="another-agent"),
             item("wi-wrong-machine", "conv-one", mid="other-machine")]
    canvas, host, control, _, _, _ = _canvas(tasks=tasks,
        eligible=[{"work_item_id":"wi-right","capabilities":["workspace:file.read"]}])
    result = canvas.center_file_work_items("project-test", "conv-one")
    assert len(result["items"]) == 1
    assert result["items"][0]["work_item_id"] == "wi-right"
    assert result["items"][0]["authorized"] is True
    assert result["items"][0]["granted_capabilities"] == ["workspace:file.read"]
    control.create_work_item.assert_not_called()
    control.authorization_grant.assert_not_called()


def test_preparing_requires_explicit_consent_and_creates_scoped_grants():
    canvas, host, control, runtime, state, machine = _canvas(tasks=[])
    with pytest.raises(Denied, match="explicit owner approval"):
        canvas.center_prepare_task("project-test", machine["machine_id"],
                                   ["workspace:file.read"], "Test", conversation_id="conv-one", approve=False)
    control.create_work_item.assert_not_called()
    value = canvas.center_prepare_task("project-test", machine["machine_id"],
                                      ["workspace:file.read"], "Test",
                                      conversation_id="conv-one", approve=True)
    assert value["work_item"]["work_item_id"].startswith("WI-machine-")
    assert value["grant_ids"] == ["grant-test-1"]
    assert state["created"]["metadata"]["conversation_id"] == "conv-one"
    assert state["created"]["metadata"]["file_access_owner_approved"] is True
    assert state["created"]["required_capabilities"] == ["workspace:file.read"]


def test_configured_machine_is_not_an_authorized_workitem():
    canvas, host, control, _, _, _ = _canvas(tasks=[])
    value = canvas.center_file_work_items("project-test", "conv-one")
    assert value["machine_configured"] is True
    assert value["items"] == []
    control.authorization_grant.assert_not_called()


def test_uncertain_incomplete_existing_workitem_does_not_duplicate_grants():
    entry = {
        "work_item_id":"wi-incomplete", "run_id":"run-test", "state":"QUEUED",
        "assignee_agent_id":"dot-agent",
        "required_capabilities":["workspace:file.read"],
        "metadata":{"workspace_id":"project-test",
                    "machine_id":"canvas-workspace-files-test",
                    "conversation_id":"conv-one",
                    "file_access_owner_approved":True},
    }
    canvas, host, control, runtime, _, machine = _canvas(tasks=[entry])
    with pytest.raises(Denied, match="incomplete file WorkItem"):
        canvas.center_prepare_task("project-test", machine["machine_id"],
                                   ["workspace:file.read"], "Test", conversation_id="conv-one", approve=True)
    control.create_work_item.assert_not_called()
    control.authorization_grant.assert_not_called()


def test_terminal_workitem_requires_explicit_conversation_consent():
    canvas, host, control, runtime, state, _ = _canvas(tasks=[])
    terminal = {"machine_id": "canvas-terminal-test", "kind": "terminal",
                "workspace_id": "project-test", "agent_id": "dot-agent",
                "capabilities": ["terminal:start", "terminal:read", "terminal:write", "terminal:close"]}
    host.inventory.return_value = [terminal]
    with pytest.raises(Denied, match="explicit owner approval"):
        canvas.center_prepare_task("project-test", terminal["machine_id"],
            ["terminal:start", "terminal:read"], "Protected terminal",
            conversation_id="conv-one", approve=False)
    control.create_work_item.assert_not_called()
    result = canvas.center_prepare_task("project-test", terminal["machine_id"],
        list(terminal["capabilities"]), "Protected terminal",
        conversation_id="conv-one", approve=True)
    assert len(result["grant_ids"]) == 4
    metadata = state["created"]["metadata"]
    assert metadata["terminal_access_owner_approved"] is True
    assert metadata["conversation_id"] == "conv-one"
    assert "file_access_owner_approved" not in metadata


def test_terminal_catalog_never_promotes_foreign_workitems():
    terminal = {"machine_id": "canvas-terminal-test", "kind": "terminal",
                "workspace_id": "project-test", "agent_id": "dot-agent",
                "capabilities": ["terminal:start", "terminal:read", "terminal:write", "terminal:close"]}
    def row(wi, conv, principal="dot-agent"):
        return {"work_item_id": wi, "run_id": "run-test", "state": "RUNNING",
                "assignee_agent_id": principal,
                "required_capabilities": list(terminal["capabilities"]),
                "metadata": {"workspace_id": "project-test",
                             "machine_id": terminal["machine_id"],
                             "conversation_id": conv,
                             "terminal_access_owner_approved": True}}
    tasks=[row("wi-good","conv-one"),row("wi-foreign","conv-other")]
    canvas, host, control, _, _, _ = _canvas(tasks=tasks, eligible=[
        {"work_item_id": "wi-good", "capabilities": list(terminal["capabilities"])}])
    host.inventory.return_value=[terminal]
    result=canvas.center_file_work_items("project-test","conv-one")
    assert [item["work_item_id"] for item in result["items"]]==["wi-good"]
    assert result["items"][0]["kind"]=="terminal"
    assert result["items"][0]["authorized"] is True
    control.authorization_grant.assert_not_called()


def test_readonly_delivery_diagnosis_does_not_replay(tmp_path, monkeypatch):
    from sentra_core import conversations
    path=tmp_path/"shell.sqlite3"
    conn=sqlite3.connect(path)
    conn.execute("CREATE TABLE canvas_shell_queue "
                 "(owner TEXT, operation_id TEXT, protected_input TEXT, receipt_id TEXT, state TEXT)")
    conn.execute("INSERT INTO canvas_shell_queue VALUES(?,?,?,?,?)",
                 ("canvas:owner","op-test","mock-token",None,"running"))
    conn.commit();conn.close()
    canvas, host, control, _, _, _ = _canvas(tasks=[])
    def connect(_):
        db=sqlite3.connect(path)
        db.row_factory=sqlite3.Row
        return db
    control.store.connect=connect
    control.durable=SimpleNamespace(operation_status=Mock(return_value={
        "operation_id":"op-test","state":"UNCERTAIN","run_id":"run-test",
        "error":{"code":"shell_provider_unconfirmed","message":"hidden-secret"}}))
    canvas._shell_service=lambda: control
    canvas._shell_runtime=SimpleNamespace(_delivery_problem=lambda message: None)
    monkeypatch.setattr(conversations, "_decode",lambda _:{"message":{
        "project_id":"project-test","space_id":"space-one",
        "conversation_id":"conv-one","operation_id":"op-test","run_id":"run-test"}})
    result=canvas.shell_delivery_inspect("project-test","space-one","conv-one","op-test")
    assert result["status"]=="UNCERTAIN"
    assert result["automatic_retry"] is False
    assert result["receipt_confirmed"] is False
    assert "hidden-secret" not in str(result)
    control.create_work_item.assert_not_called()
    control.authorization_grant.assert_not_called()
    with pytest.raises(Denied):
        canvas.shell_delivery_inspect("project-test","space-one","other-conversation","op-test")
