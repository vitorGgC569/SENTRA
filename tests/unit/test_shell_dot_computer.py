"""The computer workspace retains Dot ownership and real machine authority."""
import uuid
import pytest
from test_shell_dot_features import shell, dot
from sentra_canvas.shell_dot_computer import DotComputerServices
from sentra_canvas.store import Denied
from test_sentra_runtime_canvas_center_http import request as http_request


def configure(shell):
    app, server, scope, call = shell
    root, other = dot(call, "Computer owner"), dot(call, "Separate owner")
    child = dot(call, "Child terminal", canvas_root_dot_id=root["dot_id"])
    ca = call("conversation_create", dot_id=root["dot_id"])
    cb = call("conversation_create", dot_id=other["dot_id"])
    a = call("access_set", conversation_id=ca["conversation_id"], mode="full")
    b = call("access_set", conversation_id=cb["conversation_id"], mode="full")
    service = DotComputerServices(app)
    return service, {"space_id": scope["space_id"], "dot_id": root["dot_id"], "conversation_id": ca['conversation_id']}, root, other, child, a, b


def test_inventory_contains_only_machines_and_terminals_of_this_canvas(shell):
    service, params, root, other, child, a, b = configure(shell)
    pid = shell[2]["project_id"]
    value = service.dispatch(pid, "dot_computer_get", params)
    assert {item["dot_id"] for item in value["dots"]} == {root["dot_id"], child["dot_id"]}
    assert value["canvas_root_dot_id"] == root["dot_id"]
    assert {item["agent_id"] for item in value["machines"]} == {root["agent_id"]}
    assert value["work_items"] and all(item["agent_id"] == root["agent_id"] for item in value["work_items"])
    assert all(item["id"] != other["agent_id"] for item in value["agents"])


def test_machine_action_and_work_item_cannot_cross_root(shell, monkeypatch):
    service, params, root, other, child, a, b = configure(shell)
    pid = shell[2]["project_id"]
    all_machines = service.host.inventory(pid)
    mine = next(item for item in all_machines if item["agent_id"] == root["agent_id"])
    theirs = next(item for item in all_machines if item["agent_id"] == other["agent_id"])
    called = []
    monkeypatch.setattr(service.machines, "dispatch", lambda *args: called.append(args))
    for machine, work in [(theirs, b["work_item_id"]), (mine, b["work_item_id"])]:
        with pytest.raises(Denied):
            service.dispatch(pid, "dot_computer_action", {**params, "request": {
                "action": "machine_execute", "machine_id": machine["machine_id"],
                "work_item_id": work, "capability_id": "computer:file.read",
                "arguments": {"action": "list", "path": "."}}}, uuid.uuid4().hex)
    assert called == []


def test_work_item_cannot_be_borrowed_from_other_conversation_of_same_dot(shell, monkeypatch):
    service, params, root, other, child, a, b = configure(shell)
    app, server, scope, call = shell
    second = call('conversation_create', dot_id=root['dot_id'])
    access = call('access_set', conversation_id=second['conversation_id'], mode='full')
    machine = next(m for m in service.host.inventory(scope['project_id']) if m['agent_id'] == root['agent_id'])
    called = []
    monkeypatch.setattr(service.machines, 'dispatch', lambda *args: called.append(args))
    with pytest.raises(Denied, match='another conversation'):
        service.dispatch(scope['project_id'], 'dot_computer_action', {**params, 'request': {
            'action': 'machine_execute', 'machine_id': machine['machine_id'],
            'work_item_id': access['work_item_id'], 'capability_id': 'computer:file.read',
            'arguments': {'action': 'list', 'path': '.'}}}, uuid.uuid4().hex)
    assert called == []


def test_files_view_executes_authorized_read_and_observation_is_scoped(shell, tmp_path):
    service, params, root, other, child, a, b = configure(shell)
    pid = shell[2]["project_id"]
    inventory = service.dispatch(pid, "dot_computer_get", params)
    machine = next(item for item in inventory["machines"] if item["kind"] == "computer-local")
    path = tmp_path / "computer-view.txt"
    path.write_text("Real authorized computer view", encoding="utf-8")
    request = {**params, "request": {"action": "machine_execute", "machine_id": machine["machine_id"],
        "work_item_id": a["work_item_id"], "capability_id": "computer:file.read",
        "arguments": {"action": "read", "path": str(path)}}}
    result = service.dispatch(pid, "dot_computer_action", request, uuid.uuid4().hex)
    assert result["state"] == "SUCCEEDED"
    assert result["evidence"]["content"] == "Real authorized computer view"
    observe = {**params, "dot_id": other["dot_id"], "request": {
        "action": "machine_observe", "target_operation_id": result["operation_id"]}}
    with pytest.raises(Denied):
        service.dispatch(pid, "dot_computer_read", observe)
    observe["dot_id"] = root["dot_id"]
    assert service.dispatch(pid, "dot_computer_read", observe)["evidence"]["content"] == "Real authorized computer view"


def test_viewer_close_and_nested_identity_require_dot_scope(shell, monkeypatch):
    service, params, root, other, child, a, b = configure(shell)
    pid = shell[2]["project_id"]
    called = []
    monkeypatch.setattr(service.machines, "dispatch", lambda *args: called.append(args) or {"closed": True})
    service.viewers["test-viewer"] = (pid, root["dot_id"])
    with pytest.raises(Denied):
        service.dispatch(pid, "dot_computer_action", {**params, "dot_id": other["dot_id"], "request": {
            "action": "remote_viewer_close", "viewer_id": "test-viewer"}}, uuid.uuid4().hex)
    assert service.dispatch(pid, "dot_computer_action", {**params, "request": {
        "action": "remote_viewer_close", "viewer_id": "test-viewer"}}, uuid.uuid4().hex)["closed"] is True
    for field in ["owner", "agent_id", "operation_id", "project_id", "request_key"]:
        with pytest.raises(ValueError):
            service.dispatch(pid, "dot_computer_action", {**params, "request": {
                "action": "remote_viewer_open", field: "forged"}}, uuid.uuid4().hex)
    assert len(called) == 1


def test_http_bindings_read_real_file_and_reject_cross_canvas(shell, tmp_path):
    service, params, root, other, child, a, b = configure(shell)
    app, server, scope, call = shell
    value = call("dot_computer_get", dot_id=root["dot_id"], conversation_id=params['conversation_id'])
    assert value["canvas_root_dot_id"] == root["dot_id"]
    machine = next(item for item in value["machines"] if item["kind"] == "computer-local")
    path = tmp_path / "http-computer-view.txt"
    path.write_text("HTTP routes use the authorized executor", encoding="utf-8")
    result = call("dot_computer_action", dot_id=root["dot_id"], conversation_id=params['conversation_id'], request={
        "action": "machine_execute", "machine_id": machine["machine_id"],
        "work_item_id": a["work_item_id"], "capability_id": "computer:file.read",
        "arguments": {"action": "read", "path": str(path)}})
    assert result["state"] == "SUCCEEDED" and result["evidence"]["content"] == "HTTP routes use the authorized executor"
    observed = call("dot_computer_read", dot_id=root["dot_id"], conversation_id=params['conversation_id'], request={
        "action": "machine_observe", "target_operation_id": result["operation_id"]})
    assert observed["operation_id"] == result["operation_id"]
    for intention in [
        {"action": "input_status", "machine_id": machine["machine_id"], "work_item_id": a["work_item_id"], "capability_id": "computer:file.read"},
        {"action": "machine_observe", "target_operation_id": result["operation_id"]},
    ]:
        code, body = http_request(server, "/api/shell/bridge", json_body={"action": "dot_computer_read", **scope,
            "dot_id": other["dot_id"], "request": intention})
        assert code != 200, body
