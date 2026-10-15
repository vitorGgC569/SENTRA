"""Persistent Dot preferences and non-destructive removal preflight."""
import uuid

import pytest

from test_sentra_runtime_canvas_center_http import running_canvas, request


@pytest.fixture
def lifecycle_shell(tmp_path, monkeypatch):
    with running_canvas(tmp_path) as (app, server):
        monkeypatch.setattr(app, "model_catalog", lambda: {"models": ["sentra/test-one"]})
        project = app.create_workspace("Dot_lifecycle")["id"]
        runtime = app._runtime()
        run = runtime.run(project)
        if run["state"] != "RUNNING":
            runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING")
        home = app.shell_bridge({"action": "home", "project_id": project})["value"]
        space_id = home["space"]["space_id"]

        def call(action, *, project_id=project, space=space_id, **fields):
            code, body = request(server, "/api/shell/bridge", json_body={"action": action,
                "project_id": project_id, "space_id": space,
                "request_key": "lifecycle-" + uuid.uuid4().hex, **fields})
            return code, body

        def dot(space=space_id, name="Lifecycle Dot", canvas_root_dot_id=None):
            code, body = call("dot_create", space=space, name=name, role="specialist", model="sentra/test-one",
                **({"canvas_root_dot_id": canvas_root_dot_id} if canvas_root_dot_id else {}))
            assert code == 200, body
            return body["value"]

        yield app, project, space_id, call, dot


def value(call_result):
    code, body = call_result
    assert code == 200, body
    assert body["ok"] is True, body
    return body["value"]


def test_favorite_and_order_are_persistent_and_space_scoped(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    first, second, third = dot(name="First"), dot(name="Second"), dot(name="Third")
    prefs = value(call("dot_preferences_get"))
    assert [item["dot_id"] for item in prefs["items"]] == [first["dot_id"], second["dot_id"], third["dot_id"]]

    favorite = value(call("dot_preference_set", dot_id=third["dot_id"], favorite=True))
    assert next(item for item in favorite["items"] if item["dot_id"] == third["dot_id"])["favorite"] is True
    moved = value(call("dot_order_move", dot_id=third["dot_id"], direction="up"))
    assert moved["moved"] is False  # favorite moves only within its favorite group
    value(call("dot_preference_set", dot_id=second["dot_id"], favorite=True))
    moved = value(call("dot_order_move", dot_id=third["dot_id"], direction="up"))
    assert moved["moved"] is True
    ordered = sorted(moved["items"], key=lambda item: (not item["favorite"], item["position"]))
    assert [item["dot_id"] for item in ordered] == [third["dot_id"], second["dot_id"], first["dot_id"]]

    # A fresh service instance reads the same durable values from the project database.
    from sentra_canvas.shell_dot_lifecycle import DotLifecycleServices
    service = DotLifecycleServices(app)
    restored = service.dispatch(project, "dot_preferences_get", {"space_id": space_id})
    assert restored["items"] == moved["items"]

    other_space = value(call("space_create", name="Other lifecycle Space"))
    foreign = dot(space=other_space["space_id"], name="Foreign")
    code, _ = call("dot_preference_set", dot_id=foreign["dot_id"], favorite=True)
    assert code != 200

    other_project = app.create_workspace("Foreign_lifecycle_project")["id"]
    code, _ = call("dot_preference_set", project_id=other_project, dot_id=first["dot_id"], favorite=True)
    assert code != 200


def test_remove_preflight_reports_conversations_canvas_and_vm_without_mutation(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    root = dot(name="Root")
    child = dot(name="Child", canvas_root_dot_id=root["dot_id"])
    graph = value(call("dot_canvas_get", dot_id=root["dot_id"]))
    if len(graph["nodes"]) >= 2:
        value(call("dot_canvas_link", dot_id=root["dot_id"],
            source=graph["nodes"][0]["id"], target=graph["nodes"][1]["id"]))
    conversation = value(call("conversation_create", dot_id=root["dot_id"]))

    # Insert a synthetic persisted VM reservation; no VM process or guest is started.
    from contextlib import closing
    from sentra_core.conversations import _encode
    from sentra_canvas.shell_dot_vm import VmStore
    vm_store = VmStore(app._shell_service(), app._runtime().owner)
    with closing(app._shell_service().store.connect("shell")) as db, db:
        db.execute("INSERT INTO shell_dot_vms(owner,project,root,cpus,memory_mb,body) VALUES(?,?,?,?,?,?)",
            (app._runtime().owner, project, root["dot_id"], 1, 512,
             _encode({"vm_id": "synthetic-vm", "agent_id": root["agent_id"], "cpus": 1, "memory_mb": 512})))
    assert vm_store.get(project, root["dot_id"])["vm_id"] == "synthetic-vm"

    before = value(call("dot_list"))["items"]
    report = value(call("dot_remove_preflight", dot_id=root["dot_id"]))
    assert report["removed"] is False and report["status"] == "blocked"
    assert {key: report["resources"][key] for key in (
        "conversations", "canvas_dots", "canvas_links", "canvas_terminals", "vm_configured")} == {
        "conversations": 1, "canvas_dots": 2,
        "canvas_links": len(graph["links"]) + int(len(graph["nodes"]) >= 2),
        "canvas_terminals": 0, "vm_configured": True}
    assert report["archive_ready"] is False
    assert report["resources"]["active_grants"] > 0
    assert report["resources"]["work_items"] > 0
    assert {item["kind"] for item in report["blockers"]} >= {
        "chatgpt_archive_confirmation", "canvas_resources", "vm", "dot_delete_unavailable"}
    assert any(item["conversation_id"] == conversation["conversation_id"]
        for item in value(call("conversation_list"))["items"])
    assert value(call("dot_list"))["items"] == before


def test_even_empty_dot_removal_is_blocked_without_a_real_delete_operation(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    empty = dot()
    result = value(call("dot_remove_preflight", dot_id=empty["dot_id"]))
    assert result["resources"]["conversations"] == 0
    assert result["resources"]["canvas_dots"] == 1
    assert result["resources"]["canvas_links"] == 0
    assert result["resources"]["vm_configured"] is False
    assert result["removed"] is False
    assert {item["kind"] for item in result["blockers"]} == {"dot_delete_unavailable"}
    assert any(item["dot_id"] == empty["dot_id"] for item in value(call("dot_list"))["items"])


def test_drop_places_relative_to_target_and_rejects_foreign_space(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    first, second, third = dot(name="First"), dot(name="Second"), dot(name="Third")
    value(call("dot_preference_set", dot_id=first["dot_id"], favorite=True))
    placed = value(call("dot_order_place", dot_id=third["dot_id"], target_dot_id=first["dot_id"], edge="before"))
    assert [item["dot_id"] for item in placed["items"]] == [third["dot_id"], first["dot_id"], second["dot_id"]]
    assert placed["items"][0]["favorite"] is True
    other = value(call("space_create", name="Foreign drop Space"))
    foreign = dot(space=other["space_id"])
    before = value(call("dot_preferences_get"))["items"]
    code, _ = call("dot_order_place", dot_id=second["dot_id"], target_dot_id=foreign["dot_id"], edge="after")
    assert code != 200
    assert value(call("dot_preferences_get"))["items"] == before


def test_order_request_reconciliation_does_not_move_twice(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    first, second, third = dot(name="First"), dot(name="Second"), dot(name="Third")
    from sentra_canvas.shell_dot_lifecycle import DotLifecycleServices
    service = DotLifecycleServices(app)
    params = {"space_id": space_id, "dot_id": third["dot_id"], "direction": "up"}
    result = service.dispatch(project, "dot_order_move", params, "same-order-intent")
    assert service.dispatch(project, "dot_order_move", params, "same-order-intent") == result
    ordered = sorted(service.dispatch(project, "dot_preferences_get", {"space_id": space_id})["items"], key=lambda item: item["position"])
    assert [item["dot_id"] for item in ordered] == [first["dot_id"], third["dot_id"], second["dot_id"]]
    with pytest.raises(Exception, match="another intention"):
        service.dispatch(project, "dot_order_move", {**params, "direction": "down"}, "same-order-intent")


def test_preflight_includes_child_conversations_and_retains_remote_history(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    root = dot(name="Root")
    child = dot(name="Child", canvas_root_dot_id=root["dot_id"])
    convo = value(call("conversation_create", dot_id=child["dot_id"]))
    from contextlib import closing
    # Synthetic remote binding only: never touch a real ChatGPT account.
    with closing(app._shell_service().store.connect("shell")) as db, db:
        db.execute("INSERT INTO canvas_shell_web_conversations VALUES(?,?,?,?)",
            (app._runtime().owner, project, convo["conversation_id"], "fixture-remote-only"))
    report = value(call("dot_remove_preflight", dot_id=root["dot_id"]))
    assert report["resources"]["conversations"] == 1
    assert report["resources"]["remote_conversations"] == 1
    assert report["remote_archive_verified"] is False
    assert report["remote_archived"] is False
    assert report["claims_remote_archived"] is False
    assert report["archive_scope"] == "local_projection_only"
    assert report["remote_archive_state"] == "not_archived"
    assert report["provider_archive_receipt"] is None
    assert report["status"] == "blocked"
    assert "remote_conversations" in {x["kind"] for x in report["blockers"]}
    assert value(call("conversation_list"))["items"]


def test_archive_local_is_fenced_by_authority_and_receipted_after_fixture_cleanup(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    root = dot(name="ArchiveFixture")
    control, owner = app._shell_service(), app._runtime().owner
    control.authorization_grant(owner, principal_type="agent",
        principal_id=root["agent_id"], capability="fixture:active",
        scope_type="work_item", scope_id="fixture-only")
    report = value(call("dot_remove_preflight", dot_id=root["dot_id"]))
    assert report["archive_ready"] is False
    assert report["resources"]["active_grants"] == 1
    code, _ = call("dot_archive_local", dot_id=root["dot_id"],
        confirm_name=root["name"], snapshot=report["snapshot"])
    assert code != 200
    assert value(call("dot_preferences_get"))["items"][0]["archived_local"] is False

    # Only this ephemeral test project's agent: revoke its actual Grants and
    # close its WorkItems through central public APIs. No production Dot touched.
    control, owner = app._shell_service(), app._runtime().owner
    for grant in control.authorization.list_grants(owner, principal_type="agent",
            principal_id=root["agent_id"])["items"]:
        control.authorization_revoke(grant["grant_id"], owner)
    for item in control.list_work_items(owner, run_id=root["run_id"], limit=1000)["items"]:
        if item["assignee_agent_id"] == root["agent_id"] and not item["terminal"]:
            control.transition_work_item(item["work_item_id"], owner, "CANCELLED")

    ready = value(call("dot_remove_preflight", dot_id=root["dot_id"]))
    assert ready["archive_ready"] is True, ready["archive_blockers"]
    code, _ = call("dot_archive_local", dot_id=root["dot_id"],
        confirm_name="wrong", snapshot=ready["snapshot"])
    assert code != 200
    code, _ = call("dot_archive_local", dot_id=root["dot_id"],
        confirm_name=root["name"], snapshot="stale")
    assert code != 200

    payload = {"action": "dot_archive_local", "project_id": project, "space_id": space_id,
        "dot_id": root["dot_id"], "confirm_name": root["name"], "snapshot": ready["snapshot"],
        "request_key": "fixture-archive-fixed-key"}
    first = app.shell_bridge(payload)["value"]
    assert first["status"] == "archived_local"
    assert first["retained"] is True and first["remote_archive_verified"] is False
    assert first["remote_archived"] is False
    assert first["claims_remote_archived"] is False
    assert first["archive_scope"] == "local_projection_only"
    assert first["remote_archive_state"] == "not_archived"
    assert first["provider_archive_receipt"] is None
    assert first["receipt_id"].startswith("dot-local-")
    assert app.shell_bridge(payload)["value"] == first  # no duplicate effect or receipt
    with pytest.raises(Exception, match="different intention"):
        app.shell_bridge({**payload, "confirm_name": "changed"})
    listed = value(call("dot_preferences_get"))["items"][0]
    assert listed["archived_local"] is True
    assert listed["remote_archived"] is False
    assert listed["remote_archive_verified"] is False
    assert listed["claims_remote_archived"] is False
    assert listed["archive_scope"] == "local_projection_only"
    assert any(d["dot_id"] == root["dot_id"] for d in value(call("dot_list"))["items"])
    assert value(call("dot_remove_preflight", dot_id=root["dot_id"]))["archived_local"] is True

    restored = value(call("dot_restore_local", dot_id=root["dot_id"]))
    assert restored["status"] == "restored_local"
    assert restored["remote_archive_verified"] is False
    assert restored["remote_archived"] is False
    assert restored["claims_remote_archived"] is False
    assert restored["receipt_id"] != first["receipt_id"]
    print("FIXTURE_ARCHIVE_RECEIPT", first["receipt_id"], "FIXTURE_RESTORE_RECEIPT", restored["receipt_id"])
    assert value(call("dot_preferences_get"))["items"][0]["archived_local"] is False
    assert any(d["dot_id"] == root["dot_id"] for d in value(call("dot_list"))["items"])


def test_uncertain_shell_turn_blocks_archival_without_replay(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    root = dot(name="UncertainFixture")
    convo = value(call("conversation_create", dot_id=root["dot_id"]))
    from contextlib import closing
    from sentra_core.conversations import _encode
    with closing(app._shell_service().store.connect("shell")) as db, db:
        db.execute("INSERT INTO canvas_shell_queue("
            "operation_id,owner,project_id,conversation_id,message_id,protected_input,state,created_at,receipt_id) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            ("fixture-uncertain-op", app._runtime().owner, project,
             convo["conversation_id"], "fixture-message", _encode({}),
             "uncertain", 1.0, None))
    before = value(call("conversation_list"))["items"]
    report = value(call("dot_remove_preflight", dot_id=root["dot_id"]))
    assert report["resources"]["pending_shell_turns"] == 1
    assert "shell_turns" in {item["kind"] for item in report["blockers"]}
    assert report["archive_ready"] is False
    code, _ = call("dot_archive_local", dot_id=root["dot_id"],
        confirm_name=root["name"], snapshot=report["snapshot"])
    assert code != 200
    assert value(call("conversation_list"))["items"] == before


def test_authority_closure_reconciles_and_preserves_dot(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    root = dot(name="CloseFixture")
    control, owner = app._shell_service(), app._runtime().owner
    from uuid import uuid4
    item = control.create_work_item(root["run_id"], owner,
        work_item_id="close-test-" + uuid4().hex,
        objective="Temporary fixture authority", assignee_agent_id=root["agent_id"],
        required_capabilities=["fixture:close"],
        metadata={"workspace_id": project, "root_dot_id": root["dot_id"]})
    control.transition_work_item(item["work_item_id"], owner, "RUNNING")
    grant = control.authorization_grant(owner, principal_type="agent",
        principal_id=root["agent_id"], capability="fixture:close",
        scope_type="work_item", scope_id=item["work_item_id"])
    preflight = value(call("dot_remove_preflight", dot_id=root["dot_id"]))
    assert preflight["authority_close_ready"] is True, preflight["authority_close_blockers"]
    assert preflight["resources"]["active_grants"] >= 1
    code, _ = call("dot_retire_authority_close", dot_id=root["dot_id"],
        confirm_name="Wrong", confirm_phrase="ENCERRAR AUTORIZACOES",
        snapshot=preflight["snapshot"])
    assert code != 200
    code, _ = call("dot_retire_authority_close", dot_id=root["dot_id"],
        confirm_name=root["name"], confirm_phrase="ENCERRAR AUTORIZACOES",
        snapshot="stale")
    assert code != 200
    payload = {"action": "dot_retire_authority_close", "project_id": project,
        "space_id": space_id, "dot_id": root["dot_id"],
        "confirm_name": root["name"], "confirm_phrase": "ENCERRAR AUTORIZACOES",
        "snapshot": preflight["snapshot"], "request_key": "fixture-close-authority-unique"}
    result = app.shell_bridge(payload)["value"]
    assert result["status"] == "authority_closed", result
    assert result["receipt_id"].startswith("dot-authority-")
    print("FIXTURE_AUTHORITY_RECEIPT", result["receipt_id"], "CONFIRMED_STEPS", len(result["steps"]))
    assert all(s["state"] == "confirmed" and s["receipt_id"] for s in result["steps"])
    assert {s["kind"] for s in result["steps"]} == {"pause_agent", "cancel_work", "revoke_grant"}
    assert control.durable.agent_info(root["agent_id"], owner)["desired_state"] == "WAITING"
    assert control.authorization.info(grant["grant_id"], owner)["revoked"]
    assert control.work_item_info(item["work_item_id"], owner)["state"] == "CANCELLED"
    assert app.shell_bridge(payload)["value"] == result
    read = value(call("dot_retire_authority_status", dot_id=root["dot_id"],
        retirement_key=payload["request_key"]))
    assert read == result
    with pytest.raises(Exception, match="another retirement intention"):
        app.shell_bridge({**payload, "confirm_name": "Other"})
    with pytest.raises(Exception, match="changed since preflight|journal already owns"):
        app.shell_bridge({**payload, "request_key": "another-close-authority-key"})
    assert any(x["dot_id"] == root["dot_id"] for x in value(call("dot_list"))["items"])


def test_authority_uncertain_reconciles_only_by_observation(lifecycle_shell, monkeypatch):
    app, project, space_id, call, dot = lifecycle_shell
    root = dot(name="ObservedFixture")
    control, owner = app._shell_service(), app._runtime().owner
    preflight = value(call("dot_remove_preflight", dot_id=root["dot_id"]))
    assert preflight["authority_close_ready"] is True
    real_update = control.durable.update_agent
    seen = []
    def effect_then_lost_receipt(*args, **kwargs):
        seen.append(args[0])
        real_update(*args, **kwargs)
        raise TimeoutError("fixture simulated lost acknowledgement AFTER effect")
    monkeypatch.setattr(control.durable, "update_agent", effect_then_lost_receipt)
    payload = {"action": "dot_retire_authority_close", "project_id": project,
        "space_id": space_id, "dot_id": root["dot_id"],
        "confirm_name": root["name"], "confirm_phrase": "ENCERRAR AUTORIZACOES",
        "snapshot": preflight["snapshot"], "request_key": "fixture-uncertain-authority-01"}
    uncertain = app.shell_bridge(payload)["value"]
    assert uncertain["status"] == "uncertain"
    assert uncertain["automatic_retry"] is False
    assert seen == [root["agent_id"]]
    assert app.shell_bridge(payload)["value"] == uncertain
    assert seen == [root["agent_id"]]  # no duplicate physical/CP effect
    verified = value(call("dot_retire_authority_reconcile", dot_id=root["dot_id"],
        retirement_key=payload["request_key"]))
    assert verified["status"] == "authority_closed"
    assert all(s["state"] == "confirmed" for s in verified["steps"])
    assert seen == [root["agent_id"]]
    assert control.durable.agent_info(root["agent_id"], owner)["desired_state"] == "WAITING"


def test_authority_closure_closes_only_owned_fixture_terminal(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    root = dot(name="TerminalFixture")
    terminal = app.store.create_terminal(project, "FixtureTerm", "cmd")
    app.store.attach_agent_terminal(project, root["agent_id"], terminal["id"])
    preflight = value(call("dot_remove_preflight", dot_id=root["dot_id"]))
    assert preflight["resources"]["active_terminals"] == 1
    assert preflight["authority_close_ready"] is True, preflight["authority_close_blockers"]
    result = value(call("dot_retire_authority_close", dot_id=root["dot_id"],
        confirm_name=root["name"], confirm_phrase="ENCERRAR AUTORIZACOES",
        snapshot=preflight["snapshot"]))
    assert result["status"] == "authority_closed", result
    assert any(step["kind"] == "close_terminal" and step["state"] == "confirmed"
        for step in result["steps"])
    assert app.store.resource("terminals", terminal["id"], project)["status"] == "closed"
    assert any(x["dot_id"] == root["dot_id"] for x in value(call("dot_list"))["items"])


def test_vm_retirement_preview_rejects_foreign_reservation_without_disk_effects(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    root = dot(name="VmForeignFixture")
    from contextlib import closing
    from sentra_core.conversations import _encode
    from sentra_canvas.shell_dot_vm import VmStore
    vm = VmStore(app._shell_service(), app._runtime().owner)
    with closing(app._shell_service().store.connect("shell")) as db, db:
        db.execute("INSERT INTO shell_dot_vms VALUES(?,?,?,?,?,?)",
            (app._runtime().owner, project, root["dot_id"], 1, 1024,
             _encode({"vm_id": "foreign-uuid", "agent_id": root["agent_id"],
                "root_dot_id": root["dot_id"], "cpus": 1, "memory_mb": 1024})))
    preview = value(call("dot_vm_retire_preflight", dot_id=root["dot_id"]))
    assert preview["configured"] is True
    assert preview["status"] == "blocked"
    assert "reservation_identity_mismatch" in preview["blockers"]
    assert preview["physical_effect_performed"] is False
    assert preview["vdi_removed"] is False
    assert vm.get(project, root["dot_id"])["vm_id"] == "foreign-uuid"


def test_vm_retirement_preview_scopes_poweroff_and_disk_without_deleting(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    root = dot(name="VmOwnedFixture")
    from pathlib import Path
    import uuid
    from sentra_canvas.shell_dot_vm import VmStore
    from sentra_canvas.shell_dot_vm_retirement import DotVmRetirementInspector
    from sentra_canvas.shell_dot_retirement import DotRetirement
    control, owner = app._shell_service(), app._runtime().owner
    ident = uuid.uuid5(uuid.NAMESPACE_URL, "|".join((owner, project, root["dot_id"])))
    vm_id = str(ident)
    name = "SENTRA-Dot-" + ident.hex[:16]
    marker = "SENTRA-DOT:" + vm_id
    base = Path(control.durable.root) / "dot-vms"
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)
    disk = folder / "owned-test.vdi"
    disk.write_bytes(b"fixture-not-a-real-vdi")
    VmStore(control, owner).reserve(project, root["dot_id"], {
        "root_dot_id": root["dot_id"], "vm_id": vm_id, "agent_id": root["agent_id"],
        "name": name, "marker": marker, "base_folder": str(base),
        "cpus": 1, "memory_mb": 1024})
    class FakeVirtualBox:
        def __init__(self):
            self.calls = []
        def run(self, *args, **kwargs):
            self.calls.append(("list", args))
            assert args == ("list", "vms")
            assert kwargs == {"physical": False}
            return f'"{name}" {{{vm_id}}}'
        def status(self, binding):
            self.calls.append(("status", binding.vm_id))
            assert binding.vm_id == vm_id
            return {"UUID": vm_id, "description": marker, "name": name,
                "VMState": "poweroff", "CfgFile": str(folder / (name + ".vbox"))}
        def disk_attachments(self, binding):
            self.calls.append(("disks", binding.vm_id))
            return [{"disk_uuid": str(uuid.uuid4()), "parent_uuid": None,
                "location": str(disk)}]
    fake = FakeVirtualBox()
    preview = DotVmRetirementInspector(DotRetirement(app, control, owner)).preview(
        project, root, client=fake)
    assert preview["identity_verified"] is True
    assert preview["poweroff_verified"] is True
    assert preview["disk_count"] == 1
    assert preview["deletion_available"] is False
    assert "shared_medium_exclusivity_not_attested" in preview["blockers"]
    assert "central_vm_delete_capability_not_implemented" in preview["blockers"]
    assert [kind for kind, _ in fake.calls] == ["list", "status", "disks"]
    assert disk.read_bytes() == b"fixture-not-a-real-vdi"
    assert VmStore(control, owner).get(project, root["dot_id"])["vm_id"] == vm_id


def test_central_uncertain_operation_prevents_authority_retirement(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    root = dot(name="CentralUncertainFixture")
    control, owner = app._shell_service(), app._runtime().owner
    import uuid
    oid = "fixture-uncertain-" + uuid.uuid4().hex
    control.durable.create_operation(root["run_id"], owner, kind="fixture.retirement",
        operation_id=oid, idempotency_key=oid, cleanup_policy="manual")
    control.durable.update_operation(oid, owner, state="RUNNING",
        progress={"principal_id": root["agent_id"], "project_id": project})
    preflight = value(call("dot_remove_preflight", dot_id=root["dot_id"]))
    assert preflight["resources"]["unsettled_operations"] >= 1
    assert "unsettled_operations" in preflight["authority_close_blockers"]
    code, _ = call("dot_retire_authority_close", dot_id=root["dot_id"],
        confirm_name=root["name"], confirm_phrase="ENCERRAR AUTORIZACOES",
        snapshot=preflight["snapshot"])
    assert code != 200
    control.durable.update_operation(oid, owner, state="UNCERTAIN")
    again = value(call("dot_remove_preflight", dot_id=root["dot_id"]))
    assert again["resources"]["unsettled_operations"] >= 1
    assert again["authority_close_ready"] is False
    assert any(d["dot_id"] == root["dot_id"] for d in value(call("dot_list"))["items"])


def test_retirement_does_not_revoke_grants_of_other_dot(lifecycle_shell):
    app, project, space_id, call, dot = lifecycle_shell
    retired = dot(name="RetiredScopeFixture")
    other = dot(name="OtherScopeFixture")
    control, owner = app._shell_service(), app._runtime().owner
    own_grant = control.authorization_grant(owner, principal_type="agent",
        principal_id=retired["agent_id"], capability="fixture:close",
        scope_type="work_item", scope_id="fixture-owned")
    foreign = control.authorization_grant(owner, principal_type="agent",
        principal_id=other["agent_id"], capability="fixture:keep",
        scope_type="work_item", scope_id="fixture-foreign")
    report = value(call("dot_remove_preflight", dot_id=retired["dot_id"]))
    assert report["authority_close_ready"] is True
    result = value(call("dot_retire_authority_close", dot_id=retired["dot_id"],
        confirm_name=retired["name"], confirm_phrase="ENCERRAR AUTORIZACOES",
        snapshot=report["snapshot"]))
    assert result["status"] == "authority_closed", result
    assert control.authorization.info(own_grant["grant_id"], owner)["revoked"]
    assert control.authorization.info(foreign["grant_id"], owner)["revoked"] is False
    assert control.durable.agent_info(other["agent_id"], owner)["desired_state"] != "WAITING"
    assert len(value(call("dot_list"))["items"]) == 2


def test_remote_archive_projection_rejects_caller_supplied_proof():
    from sentra_canvas.shell_dot_retirement import remote_archive_projection

    class _Forged:
        receipt_id = "provider-archive-forged"
        verified = True
        issued_by = "provider"

    forged = (
        None,
        True,
        False,
        "provider-archive-local",
        {"remote_archive_verified": True, "remote_archived": True, "issued_by": "provider",
         "effect": "archived", "provider_archive_receipt": "provider-archive-abc"},
        {"conversation_id": "remote-1", "attested": True},
        _Forged(),
    )
    for proof in forged:
        projection = remote_archive_projection(proof)
        assert projection["remote_archive_verified"] is False
        assert projection["remote_archived"] is False
        assert projection["claims_remote_archived"] is False
        assert projection["archive_scope"] == "local_projection_only"
        assert projection["remote_archive_state"] == "not_archived"
        assert projection["provider_archive_receipt"] is None
        rendered = str(projection)
        assert "provider_attested" not in rendered
