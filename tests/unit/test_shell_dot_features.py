"""Exercise shell identity, model changes, canvas separation and durable goals."""
import uuid
import pytest
from test_sentra_runtime_canvas_center_http import running_canvas, request
from sentra_canvas.shell_goals import goal_context
from sentra_executors.goal_loop import ConversationGoalLoop


@pytest.fixture
def shell(tmp_path, monkeypatch):
    with running_canvas(tmp_path) as (app, server):
        monkeypatch.setattr(app, "model_catalog", lambda: {"models": ["sentra/test-one", "sentra/test-two"]})
        ws = app.create_workspace("Dot_features")["id"]
        runtime = app._runtime()
        run = runtime.run(ws)
        if run["state"] != "RUNNING":
            runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING")
        home = app.shell_bridge({"action": "home", "project_id": ws})["value"]
        scope = {"project_id": ws, "space_id": home["space"]["space_id"]}
        def call(action, **fields):
            code, body = request(server, "/api/shell/bridge", json_body={"action": action, **scope,
                "request_key": "test-" + uuid.uuid4().hex, **fields})
            assert code == 200, body
            assert body["ok"] is True, body
            return body["value"]
        yield app, server, scope, call


def dot(call, name, **fields):
    return call("dot_create", name=name, role="coordinator", model="sentra/test-one", **fields)


@pytest.mark.parametrize("mascot", ["blue", "mint", "orange", "purple"])
def test_dot_color_and_model_update_preserve_agent_and_conversation(shell, mascot):
    app, server, scope, call = shell
    original = dot(call, "Personal", mascot=mascot)
    conversation = call("conversation_create", dot_id=original["dot_id"])
    updated = call("dot_update", dot_id=original["dot_id"], expected_revision=original["revision"],
        model="sentra/test-two", effort="high", mascot=mascot)
    assert updated["agent_id"] == original["agent_id"]
    assert updated["model"] == "sentra/test-two" and updated["mascot"] == mascot
    assert updated["effort"] == "high"
    assert app.store.resource("agents", original["agent_id"], scope["project_id"])["model"] == "sentra/test-two"
    assert call("conversation_list")["items"][0]["conversation_id"] == conversation["conversation_id"]


def test_canvas_membership_and_actor_targets_cannot_cross_dot_roots(shell):
    app, server, scope, call = shell
    first, second = dot(call, "First"), dot(call, "Second")
    child = dot(call, "Child", canvas_root_dot_id=first["dot_id"])
    a = call("dot_canvas_get", dot_id=first["dot_id"])
    b = call("dot_canvas_get", dot_id=second["dot_id"])
    assert {row["dot_id"] for row in a["dots"]} == {first["dot_id"], child["dot_id"]}
    assert {row["dot_id"] for row in b["dots"]} == {second["dot_id"]}
    an = next(n["id"] for n in a["nodes"] if n["resource_id"] == first["agent_id"])
    cn = next(n["id"] for n in a["nodes"] if n["resource_id"] == child["agent_id"])
    bn = b["nodes"][0]["id"]
    call("dot_canvas_link", dot_id=first["dot_id"], source=an, target=cn)
    code, _ = request(server, "/api/shell/bridge", json_body={"action": "dot_canvas_link", **scope,
        "dot_id": first["dot_id"], "source": an, "target": bn, "request_key": uuid.uuid4().hex})
    assert code != 200
    code, _ = request(server, "/api/shell/bridge", json_body={"action": "dot_canvas_move", **scope,
        "dot_id": first["dot_id"], "id": bn, "x": 5, "y": 8, "request_key": uuid.uuid4().hex})
    assert code != 200
    # An owner-created legacy project link must not grant an agent cross-canvas access.
    app.graph_link(scope["project_id"], an, bn)
    actors = app._shell_runtime.actors
    assert actors.connected_agents(scope["project_id"], first["agent_id"]) == [child["agent_id"]]
    assert len(call("dot_canvas_get", dot_id=first["dot_id"])["links"]) == 1


def test_goal_is_per_conversation_durable_and_changes_future_context(shell):
    app, server, scope, call = shell
    first, second = dot(call, "First"), dot(call, "Second")
    ca = call("conversation_create", dot_id=first["dot_id"])["conversation_id"]
    cb = call("conversation_create", dot_id=second["dot_id"])["conversation_id"]
    ga = call("goal_set", conversation_id=ca, objective="Finish project A")
    gb = call("goal_set", conversation_id=cb, objective="Finish project B")
    assert ga["goal_id"] != gb["goal_id"]
    control, owner = app._shell_service(), app._runtime().owner
    assert ConversationGoalLoop(control).status(owner, ca)["goal"]["objective"] == "Finish project A"
    assert goal_context(control, owner, ca)["objective"] == "Finish project A"
    assert call("goal_status", conversation_id=cb)["goal"]["objective"] == "Finish project B"
    code, _ = request(server, "/api/shell/bridge", json_body={"action": "goal_stop", **scope,
        "conversation_id": cb, "goal_id": ga["goal_id"], "request_key": uuid.uuid4().hex})
    assert code != 200
    stopped = call("goal_stop", conversation_id=ca, goal_id=ga["goal_id"])
    assert stopped["state"] == "CANCELLED" and goal_context(control, owner, ca) is None
    assert call("goal_status", conversation_id=cb)["state"] == "ACTIVE"
    assert call("goal_complete", conversation_id=cb, goal_id=gb["goal_id"])["state"] == "SUCCEEDED"


def test_model_change_waits_for_queued_turn_and_rejects_unknown_mascot(shell, monkeypatch):
    app, server, scope, call = shell
    original = dot(call, "Busy")
    conversation = call("conversation_create", dot_id=original["dot_id"])
    monkeypatch.setattr(app._shell_runtime, "_execute", lambda _: None)
    call("message_send", conversation_id=conversation["conversation_id"], content="Queued work")
    for change in ({"model": "sentra/test-two"}, {"mascot": "hammy"}):
        code, _ = request(server, "/api/shell/bridge", json_body={"action": "dot_update", **scope,
            "dot_id": original["dot_id"], "expected_revision": original["revision"],
            "request_key": uuid.uuid4().hex, **change})
        assert code != 200
    assert app.store.resource("agents", original["agent_id"], scope["project_id"])["model"] == "sentra/test-one"


def test_root_dot_can_manage_its_canvas_with_grants_but_cannot_control_other_roots(shell, monkeypatch):
    from sentra_runtime.coordinator_admission import execute_coordinator_intent
    from sentra_canvas.shell_actor import ShellActorService
    app, server, scope, call = shell
    root, other = dot(call, "Root"), dot(call, "Other")
    call("dot_update", dot_id=root["dot_id"], expected_revision=root["revision"], role="specialist")
    cid = call("conversation_create", dot_id=root["dot_id"])["conversation_id"]
    monkeypatch.setattr(app._shell_runtime, "_execute", lambda _: None)
    sent = call("message_send", conversation_id=cid, content="Manage my own agents")
    control, owner = app._shell_service(), app._runtime().owner
    wid, oid = sent["work_item_id"], sent["operation_id"]
    run = app._runtime().run(scope["project_id"])["run_id"]
    control.transition_work_item(wid, owner, "QUEUED")
    control.start_work_item_execution(wid, owner, run_id=run, agent_id=root["agent_id"])
    control.durable.update_operation(oid, owner, state="RUNNING")
    with control.store.connect("shell") as db:
        db.execute("INSERT INTO canvas_shell_provider_bindings VALUES(?,?,?,?,?,?,?,?,?)",
            (owner, scope["project_id"], app.store.workspace(scope["project_id"])["path"], cid,
                run, wid, oid, root["agent_id"], app.store.principal))
    def execute(intent):
        return execute_coordinator_intent(control, owner, project_id=scope["project_id"], conversation_id=cid,
            run_id=run, work_item_id=wid, parent_operation_id=oid, agent_id=root["agent_id"],
            intent=intent, request_key=uuid.uuid4().hex, compose=lambda *_: pytest.fail("no grant, no execution"),
            process_alive=lambda: True, connected_agents=app._shell_runtime.actors.connected_agents)
    assert execute({"kind":"create_dot", "name":"Worker", "model":"sentra/test-one"})["status"] == "waiting_approval"
    with pytest.raises(PermissionError):
        execute({"kind":"connect", "source_dot_id":root["dot_id"], "target_dot_id":other["dot_id"]})
    with pytest.raises(PermissionError):
        execute({"kind":"cancel"})
