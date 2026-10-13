"""Child replies stay inside the current conversation's connected Dot family."""
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentra_canvas.shell_actor import ShellActorService
from sentra_canvas.shell_permissions import ShellTurnPermissions
from sentra_cli.canvas import CanvasBridge
from test_shell_dot_features import shell


def _dot(call, name, role="coordinator", **fields):
    return call("dot_create", name=name, role=role, model="sentra/test-one", **fields)


def _linked_node_ids(app, project_id, root, child):
    graph = app.shell_bridge({"action": "dot_canvas_get", "project_id": project_id,
        "space_id": root["space_id"], "dot_id": root["dot_id"]})["value"]
    nodes = {node["resource_id"]: node["id"] for node in graph["nodes"] if node["kind"] == "agent"}
    return nodes[root["agent_id"]], nodes[child["agent_id"]]


def _actor_for(app, parent, root, monkeypatch):
    actor = ShellActorService(app._shell_runtime)
    owner = app._runtime().owner
    message = {**parent, "project_id": parent["project_id"], "space_id": parent["space_id"],
        "conversation_id": parent["conversation_id"], "run_id": parent["run_id"],
        "work_item_id": parent["work_item_id"], "operation_id": parent["operation_id"]}
    monkeypatch.setattr(actor, "subject", lambda token, payload: {"message": message, "dot": root,
        "deadline": float("inf"), "epoch": "test"})
    return actor, owner, message


def _insert_child_assistant(app, project_id, space_id, conversation_id, operation_id):
    app._shell_service().shell.record_runtime_message(app._runtime().owner, project_id=project_id,
        space_id=space_id, conversation_id=conversation_id, message_id="assistant-test-" + uuid.uuid4().hex,
        content="Child result", revision=1, receipt_id="test-receipt", operation_id=operation_id)


def _prepare_parent_turn(app, call, root, conversation_id):
    sent = call("message_send", conversation_id=conversation_id, content="Coordinate children")
    control, owner = app._shell_service(), app._runtime().owner
    run = app._runtime().run(root["project_id"])["run_id"]
    control.transition_work_item(sent["work_item_id"], owner, "QUEUED")
    control.start_work_item_execution(sent["work_item_id"], owner, run_id=run, agent_id=root["agent_id"])
    control.durable.update_operation(sent["operation_id"], owner, state="RUNNING")
    with control.store.connect("shell") as db:
        db.execute("INSERT INTO canvas_shell_provider_bindings VALUES(?,?,?,?,?,?,?,?,?)",
            (owner, root["project_id"], app.store.workspace(root["project_id"])["path"], conversation_id,
             run, sent["work_item_id"], sent["operation_id"], root["agent_id"], app.store.principal))
    return {**sent, "project_id": root["project_id"], "space_id": root["space_id"],
        "conversation_id": conversation_id, "run_id": run}


def test_children_reads_only_direct_children_of_connected_agents(shell, monkeypatch):
    app, _, scope, call = shell
    root = _dot(call, "ReplyRoot")
    child = _dot(call, "ReplyChild", "worker", canvas_root_dot_id=root["dot_id"])
    outsider = _dot(call, "ReplyOutsider", "worker", canvas_root_dot_id=root["dot_id"])
    foreign_root = _dot(call, "ReplyForeignRoot")
    parent = call("conversation_create", dot_id=root["dot_id"])
    other_parent = call("conversation_create", dot_id=root["dot_id"])
    child_convo = call("conversation_create", dot_id=child["dot_id"], parent_conversation_id=parent["conversation_id"])
    outsider_convo = call("conversation_create", dot_id=outsider["dot_id"], parent_conversation_id=parent["conversation_id"])
    unrelated_convo = call("conversation_create", dot_id=child["dot_id"], parent_conversation_id=other_parent["conversation_id"])
    foreign_convo = call("conversation_create", dot_id=foreign_root["dot_id"], parent_conversation_id=parent["conversation_id"])
    node_root, node_child = _linked_node_ids(app, scope["project_id"], {**root, **scope}, {**child, **scope})
    app.graph_link(scope["project_id"], node_root, node_child)
    child_user = call("message_send", conversation_id=child_convo["conversation_id"], content="Child task")
    _insert_child_assistant(app, scope["project_id"], scope["space_id"], child_convo["conversation_id"], child_user["operation_id"])

    parent_sent = _prepare_parent_turn(app, call, {**root, **scope}, parent["conversation_id"])
    actor, _, _ = _actor_for(app, parent_sent, root, monkeypatch)
    result = actor.dispatch("test-token", {"action": "children", "workspace": app.store.workspace(scope["project_id"])["path"]})

    assert result["parent_conversation_id"] == parent["conversation_id"]
    assert [item["conversation_id"] for item in result["items"]] == [child_convo["conversation_id"]]
    child = result["items"][0]
    assert child["latest_user"]["message_id"] == child_user["message_id"]
    assert child["latest_user"]["operation_state"] in {"QUEUED", "STARTING", "RUNNING"}
    assert child["latest_assistant"]["content"] == "Child result"
    assert child["parent_conversation_id"] == parent["conversation_id"]
    assert outsider_convo["conversation_id"] not in str(result)
    assert unrelated_convo["conversation_id"] not in str(result)
    assert foreign_convo["conversation_id"] not in str(result)


def test_child_reply_uses_handoff_grant_but_creates_child_work_item_without_inheritance(shell, monkeypatch):
    app, _, scope, call = shell
    root = _dot(call, "ReplyRoot2")
    child = _dot(call, "ReplyChild2", "worker", canvas_root_dot_id=root["dot_id"])
    parent = call("conversation_create", dot_id=root["dot_id"])
    child_convo = call("conversation_create", dot_id=child["dot_id"], parent_conversation_id=parent["conversation_id"])
    node_root, node_child = _linked_node_ids(app, scope["project_id"], {**root, **scope}, {**child, **scope})
    app.graph_link(scope["project_id"], node_root, node_child)
    monkeypatch.setattr(app._shell_runtime, "_execute", lambda _: None)
    parent_sent = _prepare_parent_turn(app, call, {**root, **scope}, parent["conversation_id"])
    control, owner = app._shell_service(), app._runtime().owner
    capability = "canvas.coordinator.handoff"
    control.authorization_grant(owner, principal_type="agent", principal_id=root["agent_id"],
        capability=capability, scope_type="work_item", scope_id=parent_sent["work_item_id"])
    actor, _, _ = _actor_for(app, parent_sent, root, monkeypatch)
    request_key = uuid.uuid4().hex
    reply = actor.dispatch("test-token", {"action": "child_reply", "workspace": app.store.workspace(scope["project_id"])["path"],
        "value": json.dumps({"conversation_id": child_convo["conversation_id"], "content": "Please clarify your result"}),
        "request_key": request_key})

    assert reply["status"] == "recorded"
    assert reply["child_grant_required"] is True and reply["grant_inherited"] is False
    child_item = control.work_item_info(reply["child"]["work_item_id"], owner)
    assert child_item["assignee_agent_id"] == child["agent_id"]
    assert child_item["metadata"]["workspace_id"] == scope["project_id"]
    grants = control.authorization.list_grants(owner, principal_type="agent", principal_id=child["agent_id"])["items"]
    assert not any(g["scope_type"] == "work_item" and g.get("scope_id") == child_item["work_item_id"]
        and g["capability"] == capability and not g["revoked"] for g in grants)


@pytest.mark.parametrize("selector", ["other-parent", "unconnected-child", "other-root"])
def test_child_reply_rejects_conversation_outside_current_directed_family(shell, monkeypatch, selector):
    app, _, scope, call = shell
    root = _dot(call, "ReplyRoot3")
    child = _dot(call, "ReplyChild3", "worker", canvas_root_dot_id=root["dot_id"])
    outsider = _dot(call, "ReplyOutsider3", "worker", canvas_root_dot_id=root["dot_id"])
    foreign = _dot(call, "ReplyForeign3")
    parent = call("conversation_create", dot_id=root["dot_id"])
    other_parent = call("conversation_create", dot_id=root["dot_id"])
    eligible = call("conversation_create", dot_id=child["dot_id"], parent_conversation_id=parent["conversation_id"])
    other_child = call("conversation_create", dot_id=child["dot_id"], parent_conversation_id=other_parent["conversation_id"])
    unconnected = call("conversation_create", dot_id=outsider["dot_id"], parent_conversation_id=parent["conversation_id"])
    foreign_child = call("conversation_create", dot_id=foreign["dot_id"], parent_conversation_id=parent["conversation_id"])
    node_root, node_child = _linked_node_ids(app, scope["project_id"], {**root, **scope}, {**child, **scope})
    app.graph_link(scope["project_id"], node_root, node_child)
    monkeypatch.setattr(app._shell_runtime, "_execute", lambda _: None)
    parent_sent = _prepare_parent_turn(app, call, {**root, **scope}, parent["conversation_id"])
    actor, _, _ = _actor_for(app, parent_sent, root, monkeypatch)
    target = {"other-parent": other_child, "unconnected-child": unconnected, "other-root": foreign_child}[selector]
    with pytest.raises(PermissionError):
        actor.dispatch("test-token", {"action": "child_reply", "workspace": app.store.workspace(scope["project_id"])["path"],
            "value": json.dumps({"conversation_id": target["conversation_id"], "content": "No"}),
            "request_key": uuid.uuid4().hex})
    assert eligible["conversation_id"] != target["conversation_id"]


def test_child_reply_rejects_extra_fields_before_dispatch(shell, monkeypatch):
    app, _, scope, call = shell
    root = _dot(call, "ReplyRoot4")
    parent = call("conversation_create", dot_id=root["dot_id"])
    monkeypatch.setattr(app._shell_runtime, "_execute", lambda _: None)
    parent_sent = _prepare_parent_turn(app, call, {**root, **scope}, parent["conversation_id"])
    actor, _, _ = _actor_for(app, parent_sent, root, monkeypatch)
    with pytest.raises(ValueError, match="only a canonical"):
        actor.dispatch("test-token", {"action": "child_reply", "workspace": app.store.workspace(scope["project_id"])["path"],
            "value": json.dumps({"conversation_id": "cid", "content": "hello", "work_item_id": "forged"}),
            "request_key": uuid.uuid4().hex})


def test_root_specialist_keeps_declared_coordinator_capabilities_but_child_worker_does_not(shell, monkeypatch):
    app, _, scope, call = shell
    root = _dot(call, "SpecialistRoot", "specialist")
    child = _dot(call, "SpecialistWorker", "worker", canvas_root_dot_id=root["dot_id"])
    parent = call("conversation_create", dot_id=root["dot_id"])
    child_conversation = call("conversation_create", dot_id=child["dot_id"], parent_conversation_id=parent["conversation_id"])
    monkeypatch.setattr(app._shell_runtime, "_execute", lambda _: None)
    root_message = call("message_send", conversation_id=parent["conversation_id"], content="Root turn")
    child_message = call("message_send", conversation_id=child_conversation["conversation_id"], content="Child turn")
    control, owner = app._shell_service(), app._runtime().owner
    root_item = control.work_item_info(root_message["work_item_id"], owner)
    child_item = control.work_item_info(child_message["work_item_id"], owner)
    root_operation = control.durable.operation_status(root_message["operation_id"], owner)
    child_operation = control.durable.operation_status(child_message["operation_id"], owner)
    permissions = ShellTurnPermissions(app)

    root_allowed = permissions._allowed(root, root_item, root_operation)
    child_allowed = permissions._allowed(child, child_item, child_operation)

    assert "canvas.coordinator.handoff" in root_allowed
    assert "canvas.coordinator.handoff" not in child_allowed


def test_cli_child_reply_requires_shell_scope_and_exact_json(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTRA_CANVAS_AGENT_TOKEN", "t" * 40)
    monkeypatch.setenv("SENTRA_CANVAS_AGENT_PORT", "34001")
    monkeypatch.setenv("SENTRA_CANVAS_AGENT_SCOPE", "shell")
    bridge = CanvasBridge(SimpleNamespace(workspace=Path(tmp_path)))
    requests = []
    monkeypatch.setattr(bridge, "_request", lambda body: requests.append(body) or {"accepted": True})

    assert json.loads(bridge.execute("children", None)) == {"accepted": True}
    valid = json.dumps({"conversation_id": "child-canonical", "content": "Follow up"})
    assert json.loads(bridge.execute("child_reply|" + valid, "reply-key")) == {"accepted": True}
    assert requests[-1]["value"] == json.dumps({"content": "Follow up", "conversation_id": "child-canonical"},
        ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="only conversation_id"):
        bridge.execute("child_reply|" + json.dumps({"conversation_id": "child", "content": "x", "work_item_id": "forged"}),
            "reply-key-2")
    monkeypatch.setenv("SENTRA_CANVAS_AGENT_SCOPE", "owner")
    owner_bridge = CanvasBridge(SimpleNamespace(workspace=Path(tmp_path)))
    with pytest.raises(PermissionError, match="live shell Dot turn"):
        owner_bridge.execute("children", None)
