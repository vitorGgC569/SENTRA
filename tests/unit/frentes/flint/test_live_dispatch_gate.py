"""The live dot_tool_dispatch path calls the fleet gate before the runner."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

UNIT = Path(__file__).resolve().parents[2]
if str(UNIT) not in sys.path:
    sys.path.insert(0, str(UNIT))

from orchestrator.providers.fleet_admission import prepare_live_trio
from sentra_canvas.shell_actor import ShellActorService
from sentra_canvas.shell_runtime import CanvasShellRuntime
from sentra_runtime.dot_tool_dispatch import (
    execute_dot_tool_dispatch,
    finalize_reviewed_trio,
    retain_coordinator_turn,
)
from test_sentra_runtime_canvas_center_http import request, running_canvas


FROZEN = "op-94baad8161fb6fd4b4423e6ac1aecdeb"


def _boom(*_args):
    raise AssertionError("runner started")


def _intent(tool, dot_id="dot-target", model=None):
    body = {
        "kind": "dot_tool_dispatch",
        "tool": tool,
        "target_dot_id": dot_id,
        "instruction": "inspect",
    }
    if model:
        body["model"] = model
        body["effort"] = "high"
    return body


def test_live_dispatch_refuses_antigravity_guest_and_frozen_operation_before_the_runner():
    common = dict(
        project_id="p", conversation_id="c", run_id="run-flint",
        work_item_id="wi-flint", agent_id="agent-flint", request_key="req-flint-gate-01",
        runner=_boom,
    )
    with pytest.raises(PermissionError, match="not a verified non-interactive inference"):
        execute_dot_tool_dispatch(
            None, "owner-flint", parent_operation_id="op-parent-flint",
            intent=_intent("antigravity"), **common,
        )
    with pytest.raises(PermissionError, match="verified guest process"):
        execute_dot_tool_dispatch(
            None, "owner-flint", parent_operation_id="op-parent-flint",
            intent=_intent("sentra-cli"), placement="guest",
            guest_process={"verified": False, "pid": 4}, **common,
        )
    with pytest.raises(PermissionError, match="not resent"):
        execute_dot_tool_dispatch(
            None, "owner-flint", parent_operation_id=FROZEN,
            intent=_intent("codex"), **common,
        )


def _runner(argv, prompt, nonce_info):
    return (0, f"REVERSE_NONCE={nonce_info['reverse']}\nSHA256_NONCE={nonce_info['sha256']}", "")


def test_live_dispatch_admits_the_lane_and_reconciles_three_receipts(tmp_path, monkeypatch):
    monkeypatch.setattr("sentra_canvas.dot_tool_runner.resolve_adapters",
        lambda project_dir: {"codex":["synthetic-codex"], "opencode":["synthetic-opencode"]})
    with running_canvas(tmp_path) as (app, server):
        monkeypatch.setattr(app, "model_catalog", lambda: {"models": ["sentra/chatgpt-web/gpt-6"]})
        ws = app.create_workspace("Flint_live_gate")["id"]
        runtime = app._runtime()
        run = runtime.run(ws)
        if run["state"] != "RUNNING":
            runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING")
        home = app.shell_bridge({"action": "home", "project_id": ws})["value"]
        scope = {"project_id": ws, "space_id": home["space"]["space_id"]}

        def call(action, **fields):
            code, body = request(
                server, "/api/shell/bridge",
                json_body={"action": action, **scope, "request_key": "flint-" + uuid.uuid4().hex, **fields},
            )
            assert code == 200, body
            assert body["ok"] is True, body
            return body["value"]

        control, owner = app._shell_service(), runtime.owner
        root = call("dot_create", name="RootCoordinator", role="coordinator", model="sentra/chatgpt-web/gpt-6")
        worker = call("dot_create", name="WorkerOne", role="worker", model="sentra/chatgpt-web/gpt-6",
                      canvas_root_dot_id=root["dot_id"])
        graph = call("dot_canvas_get", dot_id=root["dot_id"])
        node_map = {node["resource_id"]: node["id"] for node in graph["nodes"]}
        call("dot_canvas_link", dot_id=root["dot_id"], source=node_map[root["agent_id"]], target=node_map[worker["agent_id"]])
        cid = call("conversation_create", dot_id=root["dot_id"])["conversation_id"]
        monkeypatch.setattr(app._shell_runtime, "_execute", lambda _: None)
        sent = call("message_send", conversation_id=cid, content="Coordinate the trio")
        parent_id, parent_operation, run_id = sent["work_item_id"], sent["operation_id"], runtime.run(ws)["run_id"]
        caps = [
            "canvas.coordinator.dot_tool_dispatch",
            "canvas.coordinator.dot_tool_dispatch.sentra_cli",
            "canvas.coordinator.dot_tool_dispatch.opencode",
            "canvas.coordinator.dot_tool_dispatch.codex",
        ]
        with control.governance._connect() as db:
            db.execute(
                "UPDATE work_items SET required_capabilities_json=? WHERE work_item_id=? AND owner=?",
                (json.dumps(caps), parent_id, owner),
            )
        control.transition_work_item(parent_id, owner, "QUEUED")
        control.start_work_item_execution(parent_id, owner, run_id=run_id, agent_id=root["agent_id"])
        control.durable.update_operation(parent_operation, owner, state="RUNNING")
        with control.store.connect("shell") as db:
            db.execute(
                "INSERT OR REPLACE INTO canvas_shell_provider_bindings VALUES (?,?,?,?,?,?,?,?,?)",
                (owner, ws, app.store.workspace(ws)["path"], cid, run_id, parent_id,
                 parent_operation, root["agent_id"], app.store.principal),
            )
        for cap in caps:
            control.authorization_grant(
                owner, principal_type="agent", principal_id=root["agent_id"],
                capability=cap, scope_type="work_item", scope_id=parent_id,
            )
        answer = "Os tres recibos ficam em revisao para promocao."
        blocked = execute_dot_tool_dispatch(
            control, owner, project_id=ws, conversation_id=cid, run_id=run_id,
            work_item_id=parent_id, parent_operation_id=parent_operation,
            agent_id=root["agent_id"], intent=_intent("sentra-cli", worker["dot_id"]),
            request_key="answer-before-" + uuid.uuid4().hex,
            process_alive=lambda: True,
            connected_agents=lambda _p, _a: [worker["agent_id"]],
            runner=_boom, coordinator_text=answer,
        )
        assert blocked["tool_executed"] is False
        assert blocked["claims_success"] is False
        assert blocked["coordinator_text"] is None
        assert blocked["status"] == "not_inference"
        assert blocked["physical_inference"] is False
        assert blocked["finalized"] is False
        specs = (
            ("sentra-cli", "sentra/chatgpt-web/gpt-6"),
            ("opencode", "opencode/muse-spark-1.3-contributor-free#high"),
            ("codex", "sentra/codex/current"),
        )
        children = []
        calls = []
        for tool, model in specs:
            result = execute_dot_tool_dispatch(
                control, owner, project_id=ws, conversation_id=cid, run_id=run_id,
                work_item_id=parent_id, parent_operation_id=parent_operation,
                agent_id=root["agent_id"],
                intent=_intent(tool, worker["dot_id"], model),
                request_key="live-" + tool + "-" + uuid.uuid4().hex,
                process_alive=lambda: True,
                connected_agents=lambda _p, _a: [worker["agent_id"]],
                runner=lambda argv, prompt, nonce, bucket=calls: bucket.append(tool) or _runner(argv, prompt, nonce),
            )
            assert result["status"] == "in_review"
            assert result["fleet_gate"]["physical_inference"] is False
            assert result["fleet_gate"]["placement"] == "host"
            assert result["fleet_gate"]["lane"] == tool
            assert result["resend"] is False
            assert result["coordinator_text"] is None
            assert result["claims_success"] is False
            assert result["tool_executed"] is True
            assert result["fleet_audit"]["authorizes_effect"] is False
            assert result["fleet_audit"]["homologated"] is False
            assert result["fleet_audit"]["physical_proof"] is False
            assert result["fleet_audit"]["source"] == "deterministic_fallback"
            assert result["fleet_audit"]["counts_as_model_decision"] is False
            assert result["fleet_audit"]["central_receipt_reached"] is False
            assert result["runner_audit"]["sealed"] is False
            assert result["runner_audit"]["counts_as_model_decision"] is False
            assert result["runner_audit"]["source"] == "deterministic_fallback"
            assert result["runner_audit"].get("model") != "fleet-admission"
            assert result["live_session"]["saved"] is False
            child_id = result["work_item_id"]
            with control.governance._connect() as db:
                db.execute(
                    "UPDATE work_items SET required_capabilities_json=? WHERE work_item_id=? AND owner=?",
                    (json.dumps(["model:invoke"]), child_id, owner),
                )
            control.authorization_grant(
                owner, principal_type="agent", principal_id=worker["agent_id"],
                capability="model:invoke", scope_type="work_item", scope_id=child_id,
            )
            children.append(child_id)
        assert len(calls) == 3
        published = execute_dot_tool_dispatch(
            control, owner, project_id=ws, conversation_id=cid, run_id=run_id,
            work_item_id=parent_id, parent_operation_id=parent_operation,
            agent_id=root["agent_id"], intent=_intent("sentra-cli", worker["dot_id"]),
            request_key="answer-after-" + uuid.uuid4().hex,
            process_alive=lambda: True,
            connected_agents=lambda _p, _a: [worker["agent_id"]],
            runner=_boom, coordinator_text=answer,
        )
        assert published["tool_executed"] is False
        assert published["claims_success"] is False
        assert published["physical_inference"] is False
        assert published["promoted"] is False
        assert published["status"] == "not_inference"
        assert published["coordinator_text"] is None
        assert len(calls) == 3
        for child_id in children:
            assert control.work_item_info(child_id, owner)["state"] == "IN_REVIEW"
        journal = "conversation:" + cid + ":1"
        retained = retain_coordinator_turn(
            control, owner, project_id=ws, coordinator_work_item_id=parent_id,
            journal_receipt=journal, reviewer_agent_id=root["agent_id"],
        )
        assert retained["status"] == "review_open"
        assert retained["finalized"] is False
        assert retained["physical_inference"] is False
        assert "retain_coordinator_turn" in CanvasShellRuntime._publish_answer.__code__.co_names
        assert "retain_coordinator_turn" in ShellActorService.compose.__code__.co_names
        assert "prepare_live_trio" in ShellActorService.compose.__code__.co_names
        for child_id in children:
            decision = control.governance.decide_policy_stage(
                child_id, owner, actor_type="agent", actor_id=root["agent_id"],
                decision="approved", comment="review of the stored lane receipt",
            )
            assert decision["work_item"]["state"] == "READY_FOR_PROMOTION"
        early = finalize_reviewed_trio(
            control, owner, project_id=ws, coordinator_work_item_id=parent_id,
            actor_type="agent", actor_id=root["agent_id"],
        )
        assert early["status"] == "finalized"
        assert early["physical_inference"] is False
        for child_id in children:
            assert control.work_item_info(child_id, owner)["state"] == "COMPLETED"
        # This unit case exercises missing prerequisites independently of the
        # developer's installed CLIs/accounts. Earlier central dispatch gates
        # and receipt checks above ran without this prerequisite-only override.
        with monkeypatch.context() as prerequisites:
            prerequisites.setattr("orchestrator.providers.fleet_admission._file_exists", lambda _path: False)
            prepared = prepare_live_trio(placement="host", operation_id=parent_operation)
        assert prepared["executed"] is False
        assert prepared["vboxmanage_used"] is False
        assert prepared["physical_inference"] is False
        assert {"opencode executable", "codex executable"} <= set(prepared["prerequisites"])
        with pytest.raises(PermissionError, match="verified guest process"):
            prepare_live_trio(placement="guest", operation_id=parent_operation)
        with pytest.raises(PermissionError, match="not resent"):
            prepare_live_trio(placement="host", operation_id="op-94baad8161fb6fd4b4423e6ac1aecdeb")


def test_shell_runtime_saves_the_dot_session_after_a_verified_answer(tmp_path, monkeypatch):
    from orchestrator.memory import LiveDotSession

    with running_canvas(tmp_path) as (app, server):
        monkeypatch.setattr(app, "model_catalog", lambda: {"models": ["sentra/chatgpt-web/gpt-6"]})
        ws = app.create_workspace("Flint_live_session")["id"]
        runtime = app._runtime()
        run = runtime.run(ws)
        if run["state"] != "RUNNING":
            runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING")
        home = app.shell_bridge({"action": "home", "project_id": ws})["value"]
        scope = {"project_id": ws, "space_id": home["space"]["space_id"]}

        def call(action, **fields):
            code, body = request(
                server, "/api/shell/bridge",
                json_body={"action": action, **scope, "request_key": "sess-" + uuid.uuid4().hex, **fields},
            )
            assert code == 200, body
            assert body["ok"] is True, body
            return body["value"]

        owner = runtime.owner
        root = call("dot_create", name="RootCoordinator", role="coordinator", model="sentra/chatgpt-web/gpt-6")
        cid = call("conversation_create", dot_id=root["dot_id"])["conversation_id"]
        monkeypatch.setattr(app._shell_runtime, "_execute", lambda _: None)
        sent = call("message_send", conversation_id=cid, content="plano do turno")
        operation_id = sent["operation_id"]
        state = runtime.durable.operation_status(operation_id, owner)["state"]
        for target in ("STARTING", "RUNNING", "SUCCEEDED"):
            if state == target:
                continue
            if state == "QUEUED" and target == "STARTING":
                runtime.durable.update_operation(operation_id, owner, state="STARTING")
                state = "STARTING"
            elif state == "STARTING" and target == "RUNNING":
                runtime.durable.update_operation(operation_id, owner, state="RUNNING")
                state = "RUNNING"
            elif target == "SUCCEEDED":
                break
        message = {
            "project_id": ws,
            "space_id": home["space"]["space_id"],
            "conversation_id": cid,
            "message_id": sent["message_id"],
            "work_item_id": sent["work_item_id"],
            "operation_id": operation_id,
            "run_id": sent.get("run_id") or run["run_id"],
            "agent_id": root["agent_id"],
        }
        answer = "plano do turno publicado"
        app._shell_runtime.conversations.open(
            Path(app.store.workspace(ws)["path"]), session_id=cid,
        )
        app._shell_runtime._publish_answer(
            message, answer, "conversation:" + cid + ":1", evidence={"protected_journal": True},
        )
        stored = Path(app.store.workspace(ws)["path"]) / ".sentra"
        loaded = LiveDotSession(stored, owner, root["dot_id"], cid).load_dot()
        assert loaded["authorizes_effects"] is False
        assert loaded["plan"]["body"]["objective"] == answer
        assert loaded["context"]["body"]["conversation_ids"] == [cid]
        with pytest.raises(FileNotFoundError):
            LiveDotSession(stored, owner, "dot-other", cid).load_dot()


def test_guest_placement_blocks_without_an_executor_and_calls_an_injected_one(tmp_path, monkeypatch):
    """A verified guest PID is not execution. The host runner must not start."""
    from sentra_executors.guest_execution import InjectableGuestExecutor

    def boom(*_args, **_kwargs):
        raise AssertionError("host execution")

    monkeypatch.setattr("sentra_canvas.dot_tool_runner.subprocess.run", boom)
    verified = {"verified": True, "pid": 4242, "evidence_sha256": "a" * 64}
    with running_canvas(tmp_path) as (app, server):
        monkeypatch.setattr(app, "model_catalog", lambda: {"models": ["sentra/chatgpt-web/gpt-6"]})
        ws = app.create_workspace("Flint_guest_surface")["id"]
        runtime = app._runtime()
        run = runtime.run(ws)
        if run["state"] != "RUNNING":
            runtime.durable.transition_run(run["run_id"], runtime.owner, "RUNNING")
        home = app.shell_bridge({"action": "home", "project_id": ws})["value"]
        scope = {"project_id": ws, "space_id": home["space"]["space_id"]}

        def call(action, **fields):
            code, body = request(
                server, "/api/shell/bridge",
                json_body={"action": action, **scope, "request_key": "gst-" + uuid.uuid4().hex, **fields},
            )
            assert code == 200, body
            assert body["ok"] is True, body
            return body["value"]

        control, owner = app._shell_service(), runtime.owner
        root = call("dot_create", name="RootCoordinator", role="coordinator", model="sentra/chatgpt-web/gpt-6")
        worker = call("dot_create", name="WorkerOne", role="worker", model="sentra/chatgpt-web/gpt-6",
                      canvas_root_dot_id=root["dot_id"])
        graph = call("dot_canvas_get", dot_id=root["dot_id"])
        node_map = {node["resource_id"]: node["id"] for node in graph["nodes"]}
        call("dot_canvas_link", dot_id=root["dot_id"], source=node_map[root["agent_id"]], target=node_map[worker["agent_id"]])
        cid = call("conversation_create", dot_id=root["dot_id"])["conversation_id"]
        monkeypatch.setattr(app._shell_runtime, "_execute", lambda _: None)
        sent = call("message_send", conversation_id=cid, content="Coordinate the guest")
        parent_id, parent_operation, run_id = sent["work_item_id"], sent["operation_id"], runtime.run(ws)["run_id"]
        cap = "canvas.coordinator.dot_tool_dispatch.sentra_cli"
        with control.governance._connect() as db:
            db.execute(
                "UPDATE work_items SET required_capabilities_json=? WHERE work_item_id=? AND owner=?",
                (json.dumps([cap, "canvas.coordinator.dot_tool_dispatch"]), parent_id, owner),
            )
        control.transition_work_item(parent_id, owner, "QUEUED")
        control.start_work_item_execution(parent_id, owner, run_id=run_id, agent_id=root["agent_id"])
        control.durable.update_operation(parent_operation, owner, state="RUNNING")
        with control.store.connect("shell") as db:
            db.execute(
                "INSERT OR REPLACE INTO canvas_shell_provider_bindings VALUES (?,?,?,?,?,?,?,?,?)",
                (owner, ws, app.store.workspace(ws)["path"], cid, run_id, parent_id,
                 parent_operation, root["agent_id"], app.store.principal),
            )
        for name in (cap, "canvas.coordinator.dot_tool_dispatch"):
            control.authorization_grant(
                owner, principal_type="agent", principal_id=root["agent_id"],
                capability=name, scope_type="work_item", scope_id=parent_id,
            )
        common = dict(
            project_id=ws, conversation_id=cid, run_id=run_id, work_item_id=parent_id,
            parent_operation_id=parent_operation, agent_id=root["agent_id"],
            process_alive=lambda: True, connected_agents=lambda _p, _a: [worker["agent_id"]],
            runner=boom, placement="guest", guest_process=verified,
        )
        with pytest.raises(PermissionError, match="process id is not a guest execution"):
            execute_dot_tool_dispatch(control, owner, intent=_intent("sentra-cli", worker["dot_id"]),
                request_key="guest-pid-refused-"+uuid.uuid4().hex, **common)
        common["guest_process"] = {"verified":False, "vm_registry_bound":True, "vm_id":"owned-guest-vm"}
        blocked_key = "guest-block-" + uuid.uuid4().hex
        blocked = execute_dot_tool_dispatch(
            control, owner, intent=_intent("sentra-cli", worker["dot_id"]),
            request_key=blocked_key, **common,
        )
        assert blocked["status"] == "uncertain"
        assert blocked["tool_executed"] is False
        assert blocked["execution_surface"] == "blocked"
        assert blocked["claims_guest_execution"] is False
        assert blocked["host_subprocess"] is False
        assert blocked["resend"] is False
        assert blocked["receipt"]["evidence_source"] == "guest_executor_missing"
        assert blocked["fleet_gate"]["placement"] == "guest"
        assert blocked["fleet_gate"]["claims_guest_execution"] is False
        again = execute_dot_tool_dispatch(
            control, owner, intent=_intent("sentra-cli", worker["dot_id"]),
            request_key=blocked_key, **common,
        )
        assert again["resend"] is False
        assert again["status"] == "uncertain"
        assert again.get("tool_executed") is not True

        def answer(request):
            info = request["nonce_info"]
            return {"exit_code": 0, "stdout": "REVERSE_NONCE=" + info["reverse"], "stderr": ""}

        guest = InjectableGuestExecutor(answer)
        ran = execute_dot_tool_dispatch(
            control, owner, intent=_intent("sentra-cli", worker["dot_id"]),
            request_key="guest-run-" + uuid.uuid4().hex, guest_executor=guest, **common,
        )
        assert len(guest.calls) == 1
        assert guest.calls[0]["placement"] == "guest"
        assert ran["status"] == "in_review"
        assert ran["tool_executed"] is True
        assert ran["execution_surface"] == "guest"
        assert ran["claims_guest_execution"] is True
        assert ran["host_subprocess"] is False
        assert ran["physical_inference"] is False
        assert ran["claims_success"] is False
        assert ran["receipt"]["evidence_source"] == "guest_executor"
        assert ran["receipt"]["live_model_verified"] is False
        assert ran["fleet_gate"]["claims_guest_execution"] is True
        assert ran["fleet_gate"]["execution_surface"] == "guest"
        assert ran["live_session"]["saved"] is False
