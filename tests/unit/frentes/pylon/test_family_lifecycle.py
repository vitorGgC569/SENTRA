"""Front 5: pause, resume, archive, restore and blocked deletion for a Dot family.

The temporary Canvas is the same shell bridge the desktop calls. No VM, VDI,
conversation or Dot is removed. Physical deletion stays unapproved.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import json
from threading import Thread
import uuid

import pytest

from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas
from sentra_canvas.shell_dot_lifecycle import DOT_LIFECYCLE_ACTIONS
from sentra_canvas.shell_dot_retirement import DotRetirement
from sentra_runtime.uncertain_recovery import UncertainRecovery


@contextmanager
def running_canvas(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    state = tmp_path / "state" / "canvas"
    app = Canvas(project, principal="pylon-owner", state_dir=state)
    app.model_catalog = lambda: {"models": ["sentra/test-one"]}
    server = CanvasServer(app, 0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield app, server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        app.shutdown()


def request(server, path, *, json_body):
    import urllib.error
    import urllib.request
    url = f"http://127.0.0.1:{server.server_port}{path}"
    data = json.dumps(json_body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": "Bearer " + server.secret,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


@pytest.fixture
def family_shell(tmp_path):
    with running_canvas(tmp_path) as (app, server):
        project = app.create_workspace("Pylon_family")["id"]
        runtime = app._runtime()
        run = runtime.run(project)
        if run["state"] != "RUNNING":
            runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING")
        home = app.shell_bridge({"action": "home", "project_id": project})["value"]
        space_id = home["space"]["space_id"]

        def call(action, **fields):
            body = {"action": action, "project_id": project, "space_id": space_id,
                "request_key": "pylon-" + uuid.uuid4().hex}
            body.update(fields)
            return request(server, "/api/shell/bridge", json_body=body)

        def dot(name, root=None):
            fields = {"name": name, "role": "specialist", "model": "sentra/test-one"}
            if root:
                fields["canvas_root_dot_id"] = root
            code, payload = call("dot_create", **fields)
            assert code == 200, payload
            assert payload["ok"] is True, payload
            return payload["value"]

        yield app, project, space_id, call, dot


def value(result):
    code, payload = result
    assert code == 200, payload
    assert payload["ok"] is True, payload
    return payload["value"]


def _retirement(app):
    return DotRetirement(app, app._shell_service(), app._runtime().owner)


def _states(control, owner, run_ids, agent_ids):
    found = []
    for run_id in sorted(set(run_ids)):
        offset = 0
        while True:
            page = control.list_work_items(owner, run_id=run_id, limit=1000, offset=offset)
            for item in page["items"]:
                if item.get("assignee_agent_id") in agent_ids:
                    found.append((item["work_item_id"], item["state"]))
            offset = page["page"]["next_offset"]
            if offset is None:
                break
    return sorted(found)


def _grants(control, owner, agent_ids):
    found = []
    for agent_id in agent_ids:
        for grant in control.authorization.list_grants(
                owner, principal_type="agent", principal_id=agent_id)["items"]:
            info = control.authorization.info(grant["grant_id"], owner)
            found.append((grant["grant_id"], bool(info["revoked"])))
    return sorted(found)


def _release_authority(control, owner, run_ids, agent_ids):
    for agent_id in agent_ids:
        for grant in control.authorization.list_grants(
                owner, principal_type="agent", principal_id=agent_id)["items"]:
            if not control.authorization.info(grant["grant_id"], owner)["revoked"]:
                control.authorization_revoke(grant["grant_id"], owner)
    for run_id in set(run_ids):
        offset = 0
        while True:
            page = control.list_work_items(owner, run_id=run_id, limit=1000, offset=offset)
            for item in page["items"]:
                if item.get("assignee_agent_id") in agent_ids and not item.get("terminal"):
                    control.transition_work_item(item["work_item_id"], owner, "CANCELLED")
            offset = page["page"]["next_offset"]
            if offset is None:
                break


def test_pause_resume_archive_restore_and_blocked_deletion(family_shell):
    app, project, space_id, call, dot = family_shell
    root = dot("PylonRoot")
    child = dot("PylonChild", root["dot_id"])
    other = dot("PylonOther")
    conversation = value(call("conversation_create", dot_id=child["dot_id"]))
    control, owner = app._shell_service(), app._runtime().owner
    retirement = _retirement(app)
    agents = (root["agent_id"], child["agent_id"])
    run_ids = (root["run_id"], child["run_id"])
    assert {"dot_pause_family", "dot_resume_family", "dot_reconcile_family",
        "dot_incident_reconcile", "dot_delete_request"} <= DOT_LIFECYCLE_ACTIONS
    priors = {agent_id: control.durable.agent_info(agent_id, owner)["desired_state"] for agent_id in agents}
    other_prior = control.durable.agent_info(other["agent_id"], owner)["desired_state"]
    work_before = _states(control, owner, run_ids, set(agents))
    grants_before = _grants(control, owner, agents)
    calls = []
    real_update = control.durable.update_agent

    def counting(*args, **kwargs):
        calls.append(args[0])
        return real_update(*args, **kwargs)

    control.durable.update_agent = counting
    try:
        paused = value(call("dot_pause_family", dot_id=root["dot_id"], confirm_name=root["name"],
            request_key="pylon-pause-family-01"))
        assert paused["status"] == "paused", paused
        assert paused["automatic_retry"] is False
        assert paused["effects_executed"] == 0
        assert paused["effects_replayed"] == 0
        assert paused["grants_revoked"] is False
        assert paused["physical_effect_performed"] is False
        assert paused["orphans_created"] == []
        assert paused["family_dot_ids"][0] == root["dot_id"]
        assert set(paused["family_dot_ids"]) == {root["dot_id"], child["dot_id"]}
        assert paused["receipt_id"].startswith("dot-family-")
        assert value(call("dot_pause_family", dot_id=root["dot_id"], confirm_name=root["name"],
            request_key="pylon-pause-family-01")) == paused
        assert [step["state"] for step in paused["steps"]] == ["confirmed", "confirmed"]
        for agent_id in agents:
            assert control.durable.agent_info(agent_id, owner)["desired_state"] == "WAITING"
        assert control.durable.agent_info(other["agent_id"], owner)["desired_state"] == other_prior
        assert _states(control, owner, run_ids, set(agents)) == work_before
        assert _grants(control, owner, agents) == grants_before
        assert calls == [agent_id for agent_id in agents if priors[agent_id] != "WAITING"]

        resumed = value(call("dot_resume_family", dot_id=root["dot_id"], confirm_name=root["name"],
            request_key="pylon-resume-family-01"))
        assert resumed["status"] == "resumed", resumed
        assert resumed["receipt_id"].startswith("dot-family-")
        assert resumed["effects_executed"] == 0
        assert value(call("dot_resume_family", dot_id=root["dot_id"], confirm_name=root["name"],
            request_key="pylon-resume-family-01")) == resumed
        for agent_id, prior in priors.items():
            assert control.durable.agent_info(agent_id, owner)["desired_state"] == prior
        assert calls.count(root["agent_id"]) == (2 if priors[root["agent_id"]] != "WAITING" else 0)
        assert calls.count(child["agent_id"]) == (2 if priors[child["agent_id"]] != "WAITING" else 0)
    finally:
        control.durable.update_agent = real_update

    refused, refused_body = call("dot_delete_request", dot_id=root["dot_id"], confirm_name=root["name"],
        confirm_phrase="APAGAR", request_key="pylon-delete-wrong")
    assert refused == 403, refused_body
    assert "operation failed" not in json.dumps(refused_body)
    _release_authority(control, owner, run_ids, set(agents) | {other["agent_id"]})
    ready = value(call("dot_remove_preflight", dot_id=root["dot_id"]))
    assert ready["archive_ready"] is True, ready["archive_blockers"]
    assert set(ready["family_dot_ids"]) == {root["dot_id"], child["dot_id"]}
    archived = value(call("dot_archive_local", dot_id=root["dot_id"], confirm_name=root["name"],
        snapshot=ready["snapshot"], request_key="pylon-archive-family-01"))
    assert archived["status"] == "archived_local"
    assert set(archived["family_dot_ids"]) == {root["dot_id"], child["dot_id"]}
    assert archived["orphans_created"] == []
    assert archived["dot_deleted"] is False
    assert value(call("dot_archive_local", dot_id=root["dot_id"], confirm_name=root["name"],
        snapshot=ready["snapshot"], request_key="pylon-archive-family-01")) == archived
    flags = retirement.archived(project, space_id)
    assert flags[root["dot_id"]] is True and flags[child["dot_id"]] is True
    assert flags.get(other["dot_id"], False) is False
    restored = value(call("dot_restore_local", dot_id=root["dot_id"],
        request_key="pylon-restore-family-01"))
    assert restored["status"] == "restored_local"
    assert set(restored["family_dot_ids"]) == {root["dot_id"], child["dot_id"]}
    flags = retirement.archived(project, space_id)
    assert flags[root["dot_id"]] is False and flags[child["dot_id"]] is False

    from sentra_core.conversations import _encode
    from sentra_canvas.shell_dot_vm import VmStore
    vm_store = VmStore(control, owner)
    with closing(control.store.connect("shell")) as db, db:
        db.execute("INSERT INTO shell_dot_vms(owner,project,root,cpus,memory_mb,body) VALUES(?,?,?,?,?,?)",
            (owner, project, root["dot_id"], 1, 512,
             _encode({"vm_id": "pylon-synthetic-vm", "agent_id": root["agent_id"], "cpus": 1, "memory_mb": 512})))
    blocked = value(call("dot_delete_request", dot_id=root["dot_id"], confirm_name=root["name"],
        confirm_phrase="EXCLUIR DOT", request_key="pylon-delete-family-01"))
    assert blocked["status"] == "deletion_blocked_pending_user_approval"
    assert blocked["receipt_id"].startswith("dot-delete-request-")
    assert blocked["effects_executed"] == 0
    assert blocked["physical_effect_performed"] is False
    assert blocked["removed"] is False
    assert blocked["dot_deleted"] is False
    assert blocked["vm_deleted"] is False
    assert blocked["conversations_deleted"] is False
    assert blocked["awaiting_user_approval"] is True
    assert blocked["orphans_created"] == []
    assert child["dot_id"] in blocked["would_orphan_if_root_removed_alone"]
    assert value(call("dot_delete_request", dot_id=root["dot_id"], confirm_name=root["name"],
        confirm_phrase="EXCLUIR DOT", request_key="pylon-delete-family-01")) == blocked
    recovery = UncertainRecovery("canvas_closed").reconcile_durable(control, owner, root["run_id"])
    assert recovery["effects_executed"] == 0
    assert recovery["may_resend"] is False
    assert recovery["promoted_work_items"] == 0
    assert vm_store.get(project, root["dot_id"])["vm_id"] == "pylon-synthetic-vm"
    listed = value(call("conversation_list"))["items"]
    assert any(item["conversation_id"] == conversation["conversation_id"] for item in listed)
    dots = value(call("dot_list"))["items"]
    assert {item["dot_id"] for item in dots} >= {root["dot_id"], child["dot_id"], other["dot_id"]}


def test_bridge_rejects_wrong_name_repeat_pause_and_archived_family(family_shell):
    app, project, space_id, call, dot = family_shell
    root = dot("PylonGuard")
    child = dot("PylonGuardChild", root["dot_id"])
    conversation = value(call("conversation_create", dot_id=child["dot_id"]))
    control, owner = app._shell_service(), app._runtime().owner
    agents = (root["agent_id"], child["agent_id"])
    desired = {agent_id: control.durable.agent_info(agent_id, owner)["desired_state"]
        for agent_id in agents}
    calls = []
    real_update = control.durable.update_agent

    def counting(*args, **kwargs):
        calls.append(args[0])
        return real_update(*args, **kwargs)

    control.durable.update_agent = counting
    try:
        code, body = call("dot_pause_family", dot_id=root["dot_id"], confirm_name="not-the-dot",
            request_key="pylon-pause-wrong-name")
        assert code == 403, body
        assert "operation failed" not in json.dumps(body)
        assert calls == []
        for agent_id, prior in desired.items():
            assert control.durable.agent_info(agent_id, owner)["desired_state"] == prior

        paused = value(call("dot_pause_family", dot_id=root["dot_id"], confirm_name=root["name"],
            request_key="pylon-pause-guard-01"))
        assert paused["status"] == "paused"
        assert paused["effects_executed"] == 0
        assert paused["receipt_id"].startswith("dot-family-")
        replay = value(call("dot_pause_family", dot_id=root["dot_id"], confirm_name=root["name"],
            request_key="pylon-pause-guard-01"))
        assert replay == paused
        assert replay["receipt_id"] == paused["receipt_id"]
        after_first = list(calls)
        code, body = call("dot_pause_family", dot_id=root["dot_id"], confirm_name=root["name"],
            request_key="pylon-pause-guard-02")
        assert code == 403, body
        assert "operation failed" not in json.dumps(body)
        assert calls == after_first
        assert value(call("dot_pause_family", dot_id=root["dot_id"], confirm_name=root["name"],
            request_key="pylon-pause-guard-01")) == paused
        for agent_id in agents:
            assert control.durable.agent_info(agent_id, owner)["desired_state"] == "WAITING"
    finally:
        control.durable.update_agent = real_update

    _release_authority(control, owner, (root["run_id"], child["run_id"]), set(agents))
    ready = value(call("dot_remove_preflight", dot_id=root["dot_id"]))
    assert ready["archive_ready"] is True, ready["archive_blockers"]
    archived = value(call("dot_archive_local", dot_id=root["dot_id"], confirm_name=root["name"],
        snapshot=ready["snapshot"], request_key="pylon-guard-archive"))
    assert archived["dot_deleted"] is False
    code, body = call("dot_pause_family", dot_id=root["dot_id"], confirm_name=root["name"],
        request_key="pylon-pause-while-archived")
    assert code == 403, body
    assert "operation failed" not in json.dumps(body)
    flags = _retirement(app).archived(project, space_id)
    assert flags[root["dot_id"]] is True and flags[child["dot_id"]] is True
    for agent_id in agents:
        assert control.durable.agent_info(agent_id, owner)["desired_state"] == "WAITING"

    from sentra_core.conversations import _encode
    from sentra_canvas.shell_dot_vm import VmStore
    vm_store = VmStore(control, owner)
    with closing(control.store.connect("shell")) as db, db:
        db.execute("INSERT INTO shell_dot_vms(owner,project,root,cpus,memory_mb,body) VALUES(?,?,?,?,?,?)",
            (owner, project, root["dot_id"], 1, 512,
             _encode({"vm_id": "pylon-guard-vm", "agent_id": root["agent_id"], "cpus": 1, "memory_mb": 512})))
    code, body = call("dot_delete_request", dot_id=root["dot_id"], confirm_name="not-the-dot",
        confirm_phrase="EXCLUIR DOT", request_key="pylon-delete-wrong-name")
    assert code == 403, body
    assert "operation failed" not in json.dumps(body)
    blocked = value(call("dot_delete_request", dot_id=root["dot_id"], confirm_name=root["name"],
        confirm_phrase="EXCLUIR DOT", request_key="pylon-delete-guard-01"))
    assert blocked["status"] == "deletion_blocked_pending_user_approval"
    assert blocked["effects_executed"] == 0
    assert blocked["physical_effect_performed"] is False
    assert blocked["receipt_id"].startswith("dot-delete-request-")
    assert value(call("dot_delete_request", dot_id=root["dot_id"], confirm_name=root["name"],
        confirm_phrase="EXCLUIR DOT", request_key="pylon-delete-guard-01")) == blocked
    assert vm_store.get(project, root["dot_id"])["vm_id"] == "pylon-guard-vm"
    listed = value(call("conversation_list"))["items"]
    assert any(item["conversation_id"] == conversation["conversation_id"] for item in listed)
    dots = {item["dot_id"] for item in value(call("dot_list"))["items"]}
    assert {root["dot_id"], child["dot_id"]} <= dots


def test_uncertain_operation_survives_pause_without_replay(family_shell):
    app, project, space_id, call, dot = family_shell
    root = dot("PylonUncertain")
    control, owner = app._shell_service(), app._runtime().owner
    operation_id = "pylon-uncertain-" + uuid.uuid4().hex
    created = control.durable.create_operation(root["run_id"], owner, kind="pylon.observe",
        operation_id=operation_id, idempotency_key=operation_id, cleanup_policy="manual",
        initial_state="RUNNING")
    control.durable.update_operation(created["operation_id"], owner, state="UNCERTAIN",
        progress={"principal_id": root["agent_id"], "project_id": project},
        result={"stdout": "SECRET_SHOULD_NOT_RESEND", "secret": "do-not-copy"})
    before = control.durable.operation_status(operation_id, owner)
    paused = value(call("dot_pause_family", dot_id=root["dot_id"], confirm_name=root["name"],
        request_key="pylon-pause-uncertain-01"))
    assert paused["receipt_id"].startswith("dot-family-")
    assert paused["effects_executed"] == 0
    after = control.durable.operation_status(operation_id, owner)
    assert paused["status"] == "paused"
    assert after["state"] == "UNCERTAIN"
    assert after["updated_at"] == before["updated_at"]
    assert after["operation_id"] == before["operation_id"]


def test_bridge_incident_reconcile_observes_without_resend(family_shell, monkeypatch):
    app, project, space_id, call, dot = family_shell
    root = dot("PylonIncident")
    control, owner = app._shell_service(), app._runtime().owner
    operation_id = "pylon-incident-" + uuid.uuid4().hex
    created = control.durable.create_operation(root["run_id"], owner, kind="pylon.observe",
        operation_id=operation_id, idempotency_key=operation_id, cleanup_policy="manual",
        initial_state="RUNNING")
    control.durable.update_operation(created["operation_id"], owner, state="UNCERTAIN",
        result={"stdout": "SECRET_SHOULD_NOT_RESEND"})
    before = control.durable.operation_status(operation_id, owner)
    desired = control.durable.agent_info(root["agent_id"], owner)["desired_state"]

    def refuse_update(*args, **kwargs):
        raise AssertionError("incident reconcile called update_agent")

    monkeypatch.setattr(control.durable, "update_agent", refuse_update)
    code, body = call("dot_incident_reconcile", dot_id=root["dot_id"], incident="not-an-incident",
        request_key="pylon-incident-bad")
    assert code == 400, body
    assert "operation failed" not in json.dumps(body)
    first_digest = None
    for incident in ("crash", "canvas_closed", "relay_down", "reboot"):
        plan = value(call("dot_incident_reconcile", dot_id=root["dot_id"], incident=incident,
            request_key="pylon-incident-" + incident))
        again = value(call("dot_incident_reconcile", dot_id=root["dot_id"], incident=incident,
            request_key="pylon-incident-" + incident + "-again"))
        assert plan == again
        assert plan["incident"] == incident
        assert plan["effects_executed"] == 0
        assert plan["may_resend"] is False
        assert plan["automatic_retry"] is False
        assert plan["second_effect"] is False
        assert plan["promoted_work_items"] == 0
        item = next(row for row in plan["items"] if row["id"] == operation_id)
        assert item["state"] == "UNCERTAIN"
        assert item["disposition"] == "observe"
        assert item["action"] == "none"
        assert item["may_resend"] is False
        assert "SECRET" not in json.dumps(plan)
        if first_digest is None:
            first_digest = plan["digest"]
        else:
            assert plan["digest"] != first_digest
    after = control.durable.operation_status(operation_id, owner)
    assert after["state"] == "UNCERTAIN"
    assert after["updated_at"] == before["updated_at"]
    assert control.durable.agent_info(root["agent_id"], owner)["desired_state"] == desired
    dots = {item["dot_id"] for item in value(call("dot_list"))["items"]}
    assert root["dot_id"] in dots


def test_bridge_incident_plan_reads_owner_conversation_and_grant(family_shell, monkeypatch):
    app, project, space_id, call, dot = family_shell
    root = dot("PylonRelay")
    control, owner = app._shell_service(), app._runtime().owner
    conversation = value(call("conversation_create", dot_id=root["dot_id"]))
    grant = control.authorization_grant(owner, principal_type="agent", principal_id=root["agent_id"],
        capability="fixture:observe", scope_type="work_item", scope_id="fixture-relay")
    grant_before = control.authorization.info(grant["grant_id"], owner)["updated_at"]
    operation_id = "pylon-relay-" + uuid.uuid4().hex
    created = control.durable.create_operation(root["run_id"], owner, kind="pylon.observe",
        operation_id=operation_id, idempotency_key=operation_id, cleanup_policy="manual",
        initial_state="RUNNING")
    control.durable.update_operation(created["operation_id"], owner, state="UNCERTAIN")
    operation_before = control.durable.operation_status(operation_id, owner)["updated_at"]
    desired = control.durable.agent_info(root["agent_id"], owner)["desired_state"]
    with closing(control.store.connect("shell")) as db, db:
        db.execute("INSERT INTO canvas_shell_queue VALUES(?,?,?,?,?,?,?,?,?)",
            ("pylon-relay-turn", owner, project, conversation["conversation_id"], "pylon-relay-message",
             "sealed-turn", "in_flight", 1, None))
    with closing(control.store.connect("authorization")) as db, db:
        db.execute("INSERT INTO authorization_events(event_id,owner,action,grant_id,principal_type,"
            "principal_id,capability,scope_type,scope_id,outcome,reason,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("auth-pylon-relay-uncertain", owner, "observe", grant["grant_id"], "agent",
             root["agent_id"], "fixture:observe", "work_item", "fixture-relay", "UNCERTAIN",
             "permission delivery unknown", 2))
    relay_id = "pylon-relay-job-" + uuid.uuid4().hex
    with closing(control.store.connect("execution_workspace")) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS jobs("
            "id TEXT PRIMARY KEY, owner TEXT NOT NULL, state TEXT NOT NULL, updated REAL NOT NULL)")
        db.execute("INSERT INTO jobs VALUES(?,?,?,?)", (relay_id, owner, "IN_FLIGHT", 4))
    with closing(control.store.connect("execution_workspace")) as db:
        relay_before = db.execute("SELECT updated FROM jobs WHERE id=?", (relay_id,)).fetchone()["updated"]

    def refuse_update(*args, **kwargs):
        raise AssertionError("incident reconcile called update_agent")

    monkeypatch.setattr(control.durable, "update_agent", refuse_update)
    first = None
    for incident in ("crash", "canvas_closed", "relay_down", "reboot"):
        plan = value(call("dot_incident_reconcile", dot_id=root["dot_id"], incident=incident,
            request_key="pylon-relay-" + incident))
        again = value(call("dot_incident_reconcile", dot_id=root["dot_id"], incident=incident,
            request_key="pylon-relay-" + incident + "-2"))
        assert again == plan
        assert again["digest"] == plan["digest"]
        assert plan["effects_executed"] == 0
        assert plan["may_resend"] is False
        by_id = {item["id"]: item for item in plan["items"]}
        turn = by_id[conversation["conversation_id"]]
        permission = by_id[grant["grant_id"]]
        operation = by_id[operation_id]
        relay = by_id[relay_id]
        assert relay["kind"] == "relay_job"
        assert relay["state"] == "IN_FLIGHT"
        assert relay["disposition"] == "blocked"
        assert relay["may_resend"] is False
        assert relay["action"] == "none"
        assert turn["kind"] == "conversation"
        assert turn["state"] == "in_flight"
        assert turn["disposition"] in {"observe", "blocked"}
        assert turn["may_resend"] is False
        assert permission["kind"] == "grant"
        assert permission["state"] == "UNCERTAIN"
        assert permission["disposition"] == "observe"
        assert permission["may_resend"] is False
        assert operation["disposition"] == "observe"
        assert operation["may_resend"] is False
        if first is None:
            first = plan["digest"]
        else:
            assert plan["digest"] != first
    assert control.durable.operation_status(operation_id, owner)["state"] == "UNCERTAIN"
    assert control.durable.operation_status(operation_id, owner)["updated_at"] == operation_before
    assert control.authorization.info(grant["grant_id"], owner)["updated_at"] == grant_before
    with closing(control.store.connect("execution_workspace")) as db:
        relay_after = db.execute("SELECT state, updated FROM jobs WHERE id=?", (relay_id,)).fetchone()
    assert relay_after["state"] == "IN_FLIGHT"
    assert relay_after["updated"] == relay_before
    assert control.durable.agent_info(root["agent_id"], owner)["desired_state"] == desired
    listed = value(call("conversation_list"))["items"]
    assert any(item["conversation_id"] == conversation["conversation_id"] for item in listed)
    assert root["dot_id"] in {item["dot_id"] for item in value(call("dot_list"))["items"]}


def test_lost_pause_acknowledgement_is_not_replayed(family_shell, monkeypatch):
    app, project, space_id, call, dot = family_shell
    root = dot("PylonLostRoot")
    child = dot("PylonLostChild", root["dot_id"])
    control, owner = app._shell_service(), app._runtime().owner
    child_before = control.durable.agent_info(child["agent_id"], owner)["desired_state"]
    real = control.durable.update_agent
    seen = []

    def effect_then_lost(*args, **kwargs):
        seen.append(args[0])
        real(*args, **kwargs)
        raise TimeoutError("lost acknowledgement after effect")

    monkeypatch.setattr(control.durable, "update_agent", effect_then_lost)
    uncertain = value(call("dot_pause_family", dot_id=root["dot_id"], confirm_name=root["name"],
        request_key="pylon-pause-lost-ack"))
    assert uncertain["status"] == "uncertain"
    assert uncertain["automatic_retry"] is False
    assert uncertain["effects_executed"] == 0
    assert uncertain["receipt_id"] is None
    assert seen == [root["agent_id"]]
    assert value(call("dot_pause_family", dot_id=root["dot_id"], confirm_name=root["name"],
        request_key="pylon-pause-lost-ack")) == uncertain
    assert seen == [root["agent_id"]]
    observed = value(call("dot_reconcile_family", dot_id=root["dot_id"],
        request_key="pylon-pause-lost-ack"))
    assert seen == [root["agent_id"]]
    assert observed["effects_executed"] == 0
    assert observed["effects_replayed"] == 0
    assert observed["status"] == "uncertain"
    assert observed["steps"][0]["state"] == "confirmed"
    assert observed["steps"][0]["receipt_id"].startswith("dot-family-step-")
    assert observed["steps"][1]["state"] == "pending"
    again = value(call("dot_reconcile_family", dot_id=root["dot_id"],
        request_key="pylon-pause-lost-ack"))
    assert again == observed
    assert seen == [root["agent_id"]]
    replay = value(call("dot_pause_family", dot_id=root["dot_id"], confirm_name=root["name"],
        request_key="pylon-pause-lost-ack"))
    assert replay["effects_executed"] == 0
    assert replay["steps"][1]["state"] == "pending"
    assert seen == [root["agent_id"]]
    assert control.durable.agent_info(root["agent_id"], owner)["desired_state"] == "WAITING"
    assert control.durable.agent_info(child["agent_id"], owner)["desired_state"] == child_before
    dots = {item["dot_id"] for item in value(call("dot_list"))["items"]}
    assert {root["dot_id"], child["dot_id"]} <= dots
    refused, refused_body = call("dot_resume_family", dot_id=root["dot_id"], confirm_name=root["name"],
        request_key="pylon-resume-while-uncertain")
    assert refused == 403, refused_body
    assert "operation failed" not in json.dumps(refused_body)
