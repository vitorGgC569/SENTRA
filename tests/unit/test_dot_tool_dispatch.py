"""Unit tests for coordinator dot_tool_dispatch intent, fences, receipts, and consolidation.

Covers:
1. Owner cannot emit agent coordinator intent.
2. Agent without Grant is denied (waiting_approval / permission error).
3. Idempotency (same request_key returns recorded receipt without re-running).
4. Nonce echo vs transformation (input echo rejected as UNCERTAIN; transformation accepted as SUCCEEDED -> IN_REVIEW).
5. UNCERTAIN never retries automatically.
6. Consolidation by coordinator (transitions IN_REVIEW -> READY_FOR_PROMOTION -> COMPLETED).
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
import pytest

from test_sentra_runtime_canvas_center_http import running_canvas, request
from sentra_runtime.dot_tool_dispatch import (
    execute_dot_tool_dispatch,
    consolidate_tool_dispatches,
)


@pytest.fixture
def shell_setup(tmp_path, monkeypatch):
    with running_canvas(tmp_path) as (app, server):
        monkeypatch.setattr(app, "model_catalog", lambda: {"models": ["sentra/chatgpt-web/gpt-6", "sentra/test-two"]})
        ws = app.create_workspace("Dot_dispatch_test")["id"]
        runtime = app._runtime()
        run = runtime.run(ws)
        if run["state"] != "RUNNING":
            runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING")
        home = app.shell_bridge({"action": "home", "project_id": ws})["value"]
        scope = {"project_id": ws, "space_id": home["space"]["space_id"]}

        def call(action, **fields):
            code, body = request(
                server, "/api/shell/bridge",
                json_body={"action": action, **scope, "request_key": "test-" + uuid.uuid4().hex, **fields}
            )
            assert code == 200, body
            assert body["ok"] is True, body
            return body["value"]

        yield app, server, scope, call


def _setup_coordinator_and_worker(shell_setup, monkeypatch, required_caps=None):
    app, server, scope, call = shell_setup
    control, owner = app._shell_service(), app._runtime().owner
    pid = scope["project_id"]
    sid = scope["space_id"]

    root = call("dot_create", name="RootCoordinator", role="coordinator", model="sentra/chatgpt-web/gpt-6")
    worker = call("dot_create", name="WorkerOne", role="worker", model="sentra/chatgpt-web/gpt-6", canvas_root_dot_id=root["dot_id"])

    # Link coordinator to worker
    graph = call("dot_canvas_get", dot_id=root["dot_id"])
    node_map = {n["resource_id"]: n["id"] for n in graph["nodes"]}
    call("dot_canvas_link", dot_id=root["dot_id"], source=node_map[root["agent_id"]], target=node_map[worker["agent_id"]])

    # Create coordinator conversation and message turn
    cid = call("conversation_create", dot_id=root["dot_id"])["conversation_id"]
    monkeypatch.setattr(app._shell_runtime, "_execute", lambda _: None)
    sent = call("message_send", conversation_id=cid, content="Coordinate tool execution")
    wid = sent["work_item_id"]
    oid = sent["operation_id"]
    run_id = app._runtime().run(pid)["run_id"]

    # Ensure work item has required_capabilities
    if required_caps is not None:
        with control.governance._connect() as db:
            db.execute(
                "UPDATE work_items SET required_capabilities_json=? WHERE work_item_id=? AND owner=?",
                (json.dumps(required_caps), wid, owner),
            )

    control.transition_work_item(wid, owner, "QUEUED")
    control.start_work_item_execution(wid, owner, run_id=run_id, agent_id=root["agent_id"])
    control.durable.update_operation(oid, owner, state="RUNNING")

    # Set up shell provider binding for coordinator turn
    with control.store.connect("shell") as db:
        db.execute(
            "INSERT OR REPLACE INTO canvas_shell_provider_bindings VALUES (?,?,?,?,?,?,?,?,?)",
            (owner, pid, app.store.workspace(pid)["path"], cid, run_id, wid, oid, root["agent_id"], app.store.principal),
        )

    return {
        "app": app, "control": control, "owner": owner, "pid": pid, "sid": sid,
        "root": root, "worker": worker, "cid": cid, "wid": wid, "oid": oid, "run_id": run_id,
    }


def test_owner_cannot_emit_agent_intent(shell_setup, monkeypatch):
    ctx = _setup_coordinator_and_worker(shell_setup, monkeypatch, ["canvas.coordinator.dot_tool_dispatch.sentra_cli"])
    control, owner = ctx["control"], ctx["owner"]

    intent = {
        "kind": "dot_tool_dispatch",
        "tool": "sentra-cli",
        "target_dot_id": ctx["worker"]["dot_id"],
        "instruction": "Echo test",
    }

    # If called with agent_id == owner -> must raise PermissionError
    with pytest.raises(PermissionError, match="owner cannot emit agent coordinator intent"):
        execute_dot_tool_dispatch(
            control, owner,
            project_id=ctx["pid"], conversation_id=ctx["cid"],
            run_id=ctx["run_id"], work_item_id=ctx["wid"],
            parent_operation_id=ctx["oid"], agent_id=owner,
            intent=intent, request_key="req-" + uuid.uuid4().hex,
            process_alive=lambda: True,
            connected_agents=lambda p, a: [ctx["worker"]["agent_id"]],
        )


def test_agent_without_grant_is_denied(shell_setup, monkeypatch):
    tool_cap = "canvas.coordinator.dot_tool_dispatch.sentra_cli"
    ctx = _setup_coordinator_and_worker(shell_setup, monkeypatch, [tool_cap])
    control, owner = ctx["control"], ctx["owner"]

    intent = {
        "kind": "dot_tool_dispatch",
        "tool": "sentra-cli",
        "target_dot_id": ctx["worker"]["dot_id"],
        "instruction": "Test without grant",
    }

    # No Grant granted yet -> should return waiting_approval
    res = execute_dot_tool_dispatch(
        control, owner,
        project_id=ctx["pid"], conversation_id=ctx["cid"],
        run_id=ctx["run_id"], work_item_id=ctx["wid"],
        parent_operation_id=ctx["oid"], agent_id=ctx["root"]["agent_id"],
        intent=intent, request_key="req-" + uuid.uuid4().hex,
        process_alive=lambda: True,
        connected_agents=lambda p, a: [ctx["worker"]["agent_id"]],
    )
    assert res["status"] == "waiting_approval"
    assert res["grant_created"] is False


def test_agent_with_undeclared_capability_raises_permission_error(shell_setup, monkeypatch):
    # required_caps is empty (capability not declared)
    ctx = _setup_coordinator_and_worker(shell_setup, monkeypatch, [])
    control, owner = ctx["control"], ctx["owner"]

    intent = {
        "kind": "dot_tool_dispatch",
        "tool": "sentra-cli",
        "target_dot_id": ctx["worker"]["dot_id"],
        "instruction": "Test undeclared cap",
    }

    with pytest.raises(PermissionError, match="not explicitly declared by the parent WorkItem"):
        execute_dot_tool_dispatch(
            control, owner,
            project_id=ctx["pid"], conversation_id=ctx["cid"],
            run_id=ctx["run_id"], work_item_id=ctx["wid"],
            parent_operation_id=ctx["oid"], agent_id=ctx["root"]["agent_id"],
            intent=intent, request_key="req-" + uuid.uuid4().hex,
            process_alive=lambda: True,
            connected_agents=lambda p, a: [ctx["worker"]["agent_id"]],
        )


def test_idempotency_returns_recorded_receipt(shell_setup, monkeypatch):
    tool_cap = "canvas.coordinator.dot_tool_dispatch.sentra_cli"
    ctx = _setup_coordinator_and_worker(shell_setup, monkeypatch, [tool_cap])
    control, owner = ctx["control"], ctx["owner"]

    # Grant the capability
    control.authorization_grant(
        owner, principal_type="agent", principal_id=ctx["root"]["agent_id"],
        capability=tool_cap, scope_type="work_item", scope_id=ctx["wid"],
    )

    calls = []
    def mock_runner(argv, prompt, nonce_info):
        calls.append(nonce_info["raw"])
        return (0, f"OK. REVERSE_NONCE={nonce_info['reverse']}\nSHA256_NONCE={nonce_info['sha256']}", "")

    req_key = "idempotent-key-" + uuid.uuid4().hex
    intent = {
        "kind": "dot_tool_dispatch",
        "tool": "sentra-cli",
        "target_dot_id": ctx["worker"]["dot_id"],
        "instruction": "Verify once",
    }

    first = execute_dot_tool_dispatch(
        control, owner,
        project_id=ctx["pid"], conversation_id=ctx["cid"],
        run_id=ctx["run_id"], work_item_id=ctx["wid"],
        parent_operation_id=ctx["oid"], agent_id=ctx["root"]["agent_id"],
        intent=intent, request_key=req_key,
        process_alive=lambda: True,
        connected_agents=lambda p, a: [ctx["worker"]["agent_id"]],
        runner=mock_runner,
    )
    assert first["status"] == "in_review"
    assert first["verified"] is True
    assert len(calls) == 1

    # Second call with same request_key
    second = execute_dot_tool_dispatch(
        control, owner,
        project_id=ctx["pid"], conversation_id=ctx["cid"],
        run_id=ctx["run_id"], work_item_id=ctx["wid"],
        parent_operation_id=ctx["oid"], agent_id=ctx["root"]["agent_id"],
        intent=intent, request_key=req_key,
        process_alive=lambda: True,
        connected_agents=lambda p, a: [ctx["worker"]["agent_id"]],
        runner=mock_runner,
    )
    # Runner must NOT be called again
    assert len(calls) == 1
    assert second["work_item_id"] == first["work_item_id"]
    assert second["operation_id"] == first["operation_id"]


def test_nonce_echo_vs_transformation(shell_setup, monkeypatch):
    tool_cap = "canvas.coordinator.dot_tool_dispatch.sentra_cli"
    ctx = _setup_coordinator_and_worker(shell_setup, monkeypatch, [tool_cap])
    control, owner = ctx["control"], ctx["owner"]

    control.authorization_grant(
        owner, principal_type="agent", principal_id=ctx["root"]["agent_id"],
        capability=tool_cap, scope_type="work_item", scope_id=ctx["wid"],
    )

    # 1. Echo only runner (returns raw nonce without reverse/sha256 transformation)
    def echo_runner(argv, prompt, nonce_info):
        return (0, f"Terminal stdout: echoing input command with token {nonce_info['raw']} and done.", "")

    echo_res = execute_dot_tool_dispatch(
        control, owner,
        project_id=ctx["pid"], conversation_id=ctx["cid"],
        run_id=ctx["run_id"], work_item_id=ctx["wid"],
        parent_operation_id=ctx["oid"], agent_id=ctx["root"]["agent_id"],
        intent={"kind": "dot_tool_dispatch", "tool": "sentra-cli", "target_dot_id": ctx["worker"]["dot_id"], "instruction": "Echo test"},
        request_key="echo-test-" + uuid.uuid4().hex,
        process_alive=lambda: True,
        connected_agents=lambda p, a: [ctx["worker"]["agent_id"]],
        runner=echo_runner,
    )
    assert echo_res["status"] == "uncertain"
    assert echo_res["verified"] is False
    assert echo_res["receipt"]["echo_only_detected"] is True
    assert echo_res["receipt"]["transformed_nonce_found"] is False

    child_op = control.durable.operation_status(echo_res["operation_id"], owner)
    assert child_op["state"] == "UNCERTAIN"
    child_wi = control.work_item_info(echo_res["work_item_id"], owner)
    assert child_wi["state"] == "BLOCKED"

    # 2. Transformed nonce runner (genuine inference output)
    def transform_runner(argv, prompt, nonce_info):
        return (0, f"Assistant output:\nREVERSE_NONCE={nonce_info['reverse']}\nSHA256_NONCE={nonce_info['sha256']}", "")

    trans_res = execute_dot_tool_dispatch(
        control, owner,
        project_id=ctx["pid"], conversation_id=ctx["cid"],
        run_id=ctx["run_id"], work_item_id=ctx["wid"],
        parent_operation_id=ctx["oid"], agent_id=ctx["root"]["agent_id"],
        intent={"kind": "dot_tool_dispatch", "tool": "sentra-cli", "target_dot_id": ctx["worker"]["dot_id"], "instruction": "Transform test"},
        request_key="trans-test-" + uuid.uuid4().hex,
        process_alive=lambda: True,
        connected_agents=lambda p, a: [ctx["worker"]["agent_id"]],
        runner=transform_runner,
    )
    assert trans_res["status"] == "in_review"
    assert trans_res["verified"] is True
    assert trans_res["receipt"]["transformed_nonce_found"] is True
    assert trans_res["receipt"]["echo_only_detected"] is False

    trans_op = control.durable.operation_status(trans_res["operation_id"], owner)
    assert trans_op["state"] == "SUCCEEDED"
    trans_wi = control.work_item_info(trans_res["work_item_id"], owner)
    # Work item transitions to IN_REVIEW, not COMPLETED directly
    assert trans_wi["state"] == "IN_REVIEW"


def test_uncertain_does_not_auto_retry(shell_setup, monkeypatch):
    tool_cap = "canvas.coordinator.dot_tool_dispatch.codex"
    ctx = _setup_coordinator_and_worker(shell_setup, monkeypatch, [tool_cap])
    control, owner = ctx["control"], ctx["owner"]

    control.authorization_grant(
        owner, principal_type="agent", principal_id=ctx["root"]["agent_id"],
        capability=tool_cap, scope_type="work_item", scope_id=ctx["wid"],
    )

    runner_calls = 0
    def failing_runner(argv, prompt, nonce_info):
        nonlocal runner_calls
        runner_calls += 1
        raise RuntimeError("CLI process crashed or disconnected")

    req_key = "crash-key-" + uuid.uuid4().hex
    res = execute_dot_tool_dispatch(
        control, owner,
        project_id=ctx["pid"], conversation_id=ctx["cid"],
        run_id=ctx["run_id"], work_item_id=ctx["wid"],
        parent_operation_id=ctx["oid"], agent_id=ctx["root"]["agent_id"],
        intent={"kind": "dot_tool_dispatch", "tool": "codex", "target_dot_id": ctx["worker"]["dot_id"], "instruction": "Fail turn"},
        request_key=req_key,
        process_alive=lambda: True,
        connected_agents=lambda p, a: [ctx["worker"]["agent_id"]],
        runner=failing_runner,
    )
    assert res["status"] == "uncertain"
    assert res["automatic_retry"] is False
    assert runner_calls == 1

    # Repeat with same key
    res_repeat = execute_dot_tool_dispatch(
        control, owner,
        project_id=ctx["pid"], conversation_id=ctx["cid"],
        run_id=ctx["run_id"], work_item_id=ctx["wid"],
        parent_operation_id=ctx["oid"], agent_id=ctx["root"]["agent_id"],
        intent={"kind": "dot_tool_dispatch", "tool": "codex", "target_dot_id": ctx["worker"]["dot_id"], "instruction": "Fail turn"},
        request_key=req_key,
        process_alive=lambda: True,
        connected_agents=lambda p, a: [ctx["worker"]["agent_id"]],
        runner=failing_runner,
    )
    # No auto-retry
    assert res_repeat["status"] == "uncertain"
    assert res_repeat["automatic_retry"] is False
    assert runner_calls == 1


def test_coordinator_consolidation(shell_setup, monkeypatch):
    tool_cap = "canvas.coordinator.dot_tool_dispatch.opencode"
    ctx = _setup_coordinator_and_worker(shell_setup, monkeypatch, [tool_cap])
    control, owner = ctx["control"], ctx["owner"]

    control.authorization_grant(
        owner, principal_type="agent", principal_id=ctx["root"]["agent_id"],
        capability=tool_cap, scope_type="work_item", scope_id=ctx["wid"],
    )

    def valid_runner(argv, prompt, nonce_info):
        return (0, f"OpenCode result\nREVERSE_NONCE={nonce_info['reverse']}\nSHA256_NONCE={nonce_info['sha256']}", "")

    res = execute_dot_tool_dispatch(
        control, owner,
        project_id=ctx["pid"], conversation_id=ctx["cid"],
        run_id=ctx["run_id"], work_item_id=ctx["wid"],
        parent_operation_id=ctx["oid"], agent_id=ctx["root"]["agent_id"],
        intent={"kind": "dot_tool_dispatch", "tool": "opencode", "target_dot_id": ctx["worker"]["dot_id"], "instruction": "Complete work"},
        request_key="complete-key-" + uuid.uuid4().hex,
        process_alive=lambda: True,
        connected_agents=lambda p, a: [ctx["worker"]["agent_id"]],
        runner=valid_runner,
    )
    child_wid = res["work_item_id"]
    assert control.work_item_info(child_wid, owner)["state"] == "IN_REVIEW"

    # Consolidate via coordinator
    summary = consolidate_tool_dispatches(
        control, owner, ctx["pid"],
        coordinator_work_item_id=ctx["wid"],
        child_work_item_ids=[child_wid],
    )
    assert summary["status"] == "review_required"
    assert summary["completed_child_work_item_ids"] == []
    assert summary["finalized"] is False
    final_wi = control.work_item_info(child_wid, owner)
    assert final_wi["state"] == "IN_REVIEW"


def test_guest_dispatch_uses_guestcontrol_only_with_dot_credentials(shell_setup, monkeypatch):
    tool_cap = "canvas.coordinator.dot_tool_dispatch.sentra_cli"
    ctx = _setup_coordinator_and_worker(shell_setup, monkeypatch, [tool_cap])
    control, owner = ctx["control"], ctx["owner"]
    control.authorization_grant(
        owner, principal_type="agent", principal_id=ctx["root"]["agent_id"],
        capability=tool_cap, scope_type="work_item", scope_id=ctx["wid"],
    )

    def boom(*_args, **_kwargs):
        raise AssertionError("host execution")

    monkeypatch.setattr("sentra_canvas.dot_tool_runner.subprocess.run", boom)
    guest_process = {"verified": True, "pid": 7, "evidence_sha256": "ab" * 32}
    common = dict(
        project_id=ctx["pid"], conversation_id=ctx["cid"], run_id=ctx["run_id"],
        work_item_id=ctx["wid"], parent_operation_id=ctx["oid"],
        agent_id=ctx["root"]["agent_id"], process_alive=lambda: True,
        connected_agents=lambda _p, _a: [ctx["worker"]["agent_id"]],
        runner=boom, placement="guest", guest_process=guest_process,
    )
    intent = {
        "kind": "dot_tool_dispatch",
        "tool": "sentra-cli",
        "target_dot_id": ctx["worker"]["dot_id"],
        "instruction": "Inspect inside the guest",
    }
    blocked = execute_dot_tool_dispatch(
        control, owner, intent=intent, request_key="guest-cred-block-" + uuid.uuid4().hex,
        **common,
    )
    assert blocked["status"] == "uncertain"
    assert blocked["tool_executed"] is False
    assert blocked["execution_surface"] == "blocked"
    assert blocked["claims_guest_execution"] is False
    assert blocked["host_subprocess"] is False
    assert blocked["receipt"]["evidence_source"] == "guest_executor_missing"

    class BoomClient:
        def guest_additions_runlevel(self, vm_id):
            return "0"

        def run(self, *parts, **kwargs):
            raise AssertionError("unready guest channel was called: " + str(parts[:3]))

    for vm_id in ("windows-installing", "owned-guest-vm"):
        denied = execute_dot_tool_dispatch(
            control, owner, intent=intent,
            request_key="guest-windows-deny-" + vm_id[:8] + uuid.uuid4().hex,
            vm_id=vm_id, username="sentra", password="dot-secret",
            os_family="windows", virtualbox_client=BoomClient(), **common,
        )
        assert denied["status"] == "uncertain"
        assert denied["tool_executed"] is False
        assert denied["execution_surface"] == "blocked"
        assert denied["claims_guest_execution"] is False
        assert denied["host_subprocess"] is False
        assert denied["physical_inference"] is False
        assert denied["receipt"]["evidence_source"] == "guest_executor_missing"
        assert denied["receipt"]["verified"] is False
        assert "dot-secret" not in json.dumps(denied)

    class FakeClient:
        def __init__(self):
            self.calls = []

        def run(self, *parts, **kwargs):
            assert parts[0] == "guestcontrol"
            assert parts[1] == "owned-guest-vm"
            assert "SENTRA-Dot-b1a7b4555800414f" not in parts
            self.calls.append((parts, kwargs))
            return "guestcontrol-stdout"

    client = FakeClient()
    ran = execute_dot_tool_dispatch(
        control, owner, intent=intent, request_key="guest-cred-run-" + uuid.uuid4().hex,
        vm_id="owned-guest-vm", username="sentra", password="dot-secret",
        virtualbox_client=client, **common,
    )
    assert len(client.calls) == 1
    parts, options = client.calls[0]
    assert parts[:3] == ("guestcontrol", "owned-guest-vm", "run")
    assert options["password"] == "dot-secret"
    assert "dot-secret" not in parts
    assert ran["execution_surface"] == "guest"
    assert ran["claims_guest_execution"] is True
    assert ran["host_subprocess"] is False
    assert ran["physical_inference"] is False
    assert ran["claims_success"] is False
    assert ran["receipt"]["evidence_source"] == "guest_executor"
    assert ran["receipt"]["live_model_verified"] is False
    assert ran["receipt"]["guest_witness"] == "guestcontrol"
    assert ran["receipt"]["vm_id"] == "owned-guest-vm"
    assert ran["receipt"]["verified"] is False
