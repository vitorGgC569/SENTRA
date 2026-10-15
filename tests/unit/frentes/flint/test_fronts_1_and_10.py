"""Fronts 1 and 10. These tests do not call a provider or delete a Dot."""
from __future__ import annotations

import hashlib

import pytest

from orchestrator.dispatcher import central_effect_admission, reconcile_coordinator_trio
from orchestrator.providers.fleet_admission import installed_muse_catalog
from sentra_quality.decision_receipt_audit import DecisionReceiptLedger
from sentra_quality.production_audit import record_runner_final_answer
from sentra_runtime.dot_tool_dispatch import remember_live_dot_if_sealed, seal_fleet_admission
from orchestrator.providers.fleet_admission import (
    describe_local_fleet,
    note_uncertain_effect,
    probe_antigravity,
)
from orchestrator.turn_scheduler import ConversationTurnScheduler
from sentra_cli.codex_native import NativeModelError, generate
from sentra_cli.model_fence import ModelInvocationFence
from sentra_mcp.services.authorization import AuthorizationService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.governance import GovernanceService
from sentra_model_gateway.gateway import fleet_status_payload


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _authority() -> dict[str, str]:
    return {
        "owner": "owner-flint",
        "run_id": "run-flint-trio",
        "work_item_id": "wi-flint-parent",
        "operation_id": "op-flint-parent",
        "grant_id": "grant-parent-placeholder",
        "agent_id": "agent-flint-coordinator",
    }


def _receipt(lane: str, body: str) -> dict:
    models = {
        "sentra-cli": "sentra/chatgpt-web/gpt-6",
        "opencode": "opencode/muse-spark-1.3-contributor-free#high",
        "codex": "sentra/codex/current",
    }
    return {
        "status": "SUCCEEDED",
        "verified": True,
        "execution_uncertain": False,
        "echo_only_detected": False,
        "ack_only": False,
        "launch_failed": False,
        "effort": "high",
        "model": models[lane],
        "stdout_sha256": _sha(body),
    }


def test_antigravity_gui_is_explicitly_unavailable(tmp_path):
    gui = tmp_path / "Antigravity.exe"
    gui.write_bytes(b"not-a-model")
    probed = probe_antigravity(gui_paths=(gui,))
    assert probed["installed_gui"] is True
    assert probed["inference_verified"] is False
    assert probed["availability"] == "unavailable"
    assert probed["gui_launch_counts_as_inference"] is False
    assert "graphical" in probed["reason"]
    live = probe_antigravity()
    assert live["inference_verified"] is False
    assert live["gui_launch_counts_as_inference"] is False


def test_antigravity_shape_does_not_count_as_physical_inference(tmp_path):
    observation = {
        "kind": "noninteractive-inference",
        "gui_launch": False,
        "process_verified": True,
        "verified": True,
        "execution_uncertain": False,
        "stdout_sha256": _sha("shaped-observation"),
        "operation_id": "op-anti-shape",
        "work_item_id": "wi-anti-shape",
        "grant_id": "grant-anti-shape",
        "run_id": "run-anti-shape",
        "model": "antigravity-cli",
    }
    authority = _authority()
    authority["grant_id"] = "grant-flint-parent"
    admitted = central_effect_admission(
        authority,
        {"antigravity": {"noninteractive": observation}},
        root=tmp_path,
    )
    anti = next(lane for lane in admitted["lanes"] if lane["id"] == "antigravity")
    assert anti["inference_verified"] is True
    assert admitted["physical_inference"] is False
    assert admitted["inference_executed"] is False
    window = dict(observation, gui_launch=True)
    assert probe_antigravity(window)["inference_verified"] is False


def test_fleet_catalog_keeps_presence_separate_from_inference():
    catalog = describe_local_fleet()
    assert catalog["admitted"] is False
    assert catalog["inference_executed"] is False
    by_id = {lane["id"]: lane for lane in catalog["lanes"]}
    for lane_id in ("sentra-cli", "opencode", "codex", "chatgpt-web", "gemini-web", "antigravity"):
        assert lane_id in by_id
        assert by_id[lane_id]["authenticated"] == "not-checked"
        assert by_id[lane_id]["inference_verified"] is False or lane_id == "antigravity"
    assert by_id["antigravity"]["inference_verified"] is False
    assert by_id["chatgpt-web"]["inference_verified"] is False
    payload = fleet_status_payload()
    assert payload["admitted"] is False
    assert {lane["id"] for lane in payload["lanes"]} >= {"codex", "antigravity", "chatgpt-web"}


def test_admission_refuses_guest_without_a_verified_process():
    authority = _authority()
    authority["grant_id"] = "grant-flint-parent"
    with pytest.raises(PermissionError, match="verified guest process"):
        central_effect_admission(authority, placement="guest", guest_process={"verified": False, "pid": 12})
    admitted = central_effect_admission(authority, placement="host")
    assert admitted["placement"]["claims_guest_execution"] is False
    assert admitted["admitted"] is True
    with pytest.raises(PermissionError, match="process id is not a guest execution"):
        central_effect_admission(
            authority, placement="guest",
            guest_process={"verified": True, "pid": 4242, "evidence_sha256": "a" * 64},
        )
    from orchestrator.providers.fleet_admission import place_execution
    with pytest.raises(PermissionError, match="verified guest process"):
        place_execution("guest", {"vm_registry_bound": True, "verified": False, "vm_id": "../other"})
    placed = place_execution("guest", {"vm_registry_bound": True, "verified": False, "vm_id": "owned-guest-vm"})
    assert placed["claims_guest_execution"] is False
    assert placed["vm_id"] == "owned-guest-vm"


def test_model_fence_rejects_antigravity_before_a_provider_call():
    fence = ModelInvocationFence.__new__(ModelInvocationFence)
    with pytest.raises(PermissionError, match="not a verified non-interactive inference"):
        fence.checkpoint("session", "workspace", provider="antigravity-app")


def test_native_codex_does_not_resend_an_uncertain_effect():
    note_uncertain_effect("op-flint-native-uncertain")
    with pytest.raises(NativeModelError, match="not resent"):
        generate(None, [], "sentra/codex/current", lambda *_args: None, effect_key="op-flint-native-uncertain")


@pytest.mark.asyncio
async def test_turn_scheduler_does_not_resend_uncertain():
    started = []

    async def start(item):
        started.append(item)
        return {"ok": True}

    async def collect(started_item):
        return {"collected": True, **started_item}

    scheduler = ConversationTurnScheduler(start=start, collect=collect)
    result = await scheduler.run_batch([
        {"provider": "codex", "delivery_state": "UNCERTAIN", "operation_id": "op-flint-sched-uncertain"},
        "plain",
    ])
    assert started == ["plain"]
    assert result[0]["resend"] is False
    assert result[0]["_scheduler_phase"] == "refused"
    assert result[1]["collected"] is True


@pytest.mark.asyncio
async def test_conversation_pool_does_not_replay_uncertain_seat(tmp_path):
    from orchestrator.conversation_pool import FixedConversationRouter
    from orchestrator.providers.base import AgentRequest

    class Inner:
        def __init__(self):
            self.calls = 0
            self.providers = {}

        async def execute(self, request, preferred_provider=None):
            self.calls += 1
            raise AssertionError("provider was called")

    pool = FixedConversationRouter(Inner(), run_id="runflint", store_dir=tmp_path)
    pool._map["runflint:executor"] = {"state": "UNCERTAIN", "role": "executor"}
    pool._save()
    response = await pool.execute(AgentRequest(
        system_prompt="s", user_prompt="u", role="executor", metadata={"task_id": "t"},
    ))
    assert response.success is False
    assert response.error == (
        "[CONVERSATION_BLOCKED] runflint:executor is UNCERTAIN; "
        "delivery reconciliation required, no replay"
    )
    assert response.metadata["delivery_state"] == "UNCERTAIN"
    assert response.metadata["retry_safe"] is False


def _succeeded(durable, owner, run_id, operation_id):
    durable.create_operation(
        run_id, owner, kind="fleet.trio", idempotency_key=operation_id,
        operation_id=operation_id, initial_state="RUNNING",
    )
    durable.update_operation(operation_id, owner, state="SUCCEEDED")


def test_trio_closes_only_through_central_run_work_grant_and_receipt(tmp_path):
    state = tmp_path / ".sentra"
    owner = "owner-flint"
    run_id = "run-flint-trio"
    parent_id = "wi-flint-parent"
    auth = AuthorizationService(state)
    durable = DurableRunService(state)
    governance = GovernanceService(state, durable=durable)
    durable.create_run(owner, run_id=run_id, workspace=str(tmp_path), idempotency_key="flint-trio")
    durable.transition_run(run_id, owner, "RUNNING")
    durable.create_operation(
        run_id, owner, kind="fleet.trio.parent", idempotency_key="op-flint-parent",
        operation_id="op-flint-parent", initial_state="RUNNING",
    )
    governance.create_work_item(
        run_id, owner, objective="coordinate the trio", work_item_id=parent_id,
        assignee_agent_id="agent-flint-coordinator",
        required_capabilities=["canvas.coordinator.dot_tool_dispatch"],
        execution_policy={"require_quality_gate": False},
    )
    governance.transition_work_item(parent_id, owner, "RUNNING")
    parent_grant = auth.grant(
        owner, principal_type="agent", principal_id="agent-flint-coordinator",
        capability="canvas.coordinator.dot_tool_dispatch", scope_type="work_item", scope_id=parent_id,
    )
    lanes = (
        ("sentra-cli", "wi-flint-sentra", "op-flint-sentra", "agent-flint-sentra"),
        ("opencode", "wi-flint-opencode", "op-flint-opencode", "agent-flint-opencode"),
        ("codex", "wi-flint-codex", "op-flint-codex", "agent-flint-codex"),
    )
    children = []
    grants = {}
    for lane, work_id, operation_id, agent_id in lanes:
        governance.create_work_item(
            run_id, owner, objective=lane, work_item_id=work_id,
            parent_work_item_id=parent_id, assignee_agent_id=agent_id,
            required_capabilities=["model:invoke"],
            execution_policy={"require_quality_gate": False},
        )
        governance.transition_work_item(work_id, owner, "RUNNING")
        governance.transition_work_item(work_id, owner, "VALIDATING")
        governance.transition_work_item(work_id, owner, "IN_REVIEW")
        grant = auth.grant(
            owner, principal_type="agent", principal_id=agent_id,
            capability="model:invoke", scope_type="work_item", scope_id=work_id,
        )
        grants[lane] = grant["grant_id"]
        _succeeded(durable, owner, run_id, operation_id)
        children.append({
            "lane": lane, "owner": owner, "run_id": run_id, "work_item_id": work_id,
            "operation_id": operation_id, "grant_id": grant["grant_id"], "agent_id": agent_id,
            "state": "IN_REVIEW", "receipt": _receipt(lane, lane + "-inference"),
        })
    coordinator_operation = "op-flint-coordinator"
    _succeeded(durable, owner, run_id, coordinator_operation)
    authority = _authority()
    authority["grant_id"] = parent_grant["grant_id"]
    admission = central_effect_admission(authority, placement="host")
    coordinator = {
        "operation_id": coordinator_operation,
        "work_item_id": parent_id,
        "grant_id": parent_grant["grant_id"],
        "status": "SUCCEEDED",
        "verified": True,
        "execution_uncertain": False,
        "echo_only_detected": False,
        "ack_only": False,
        "launch_failed": False,
        "effort": "high",
        "model": "sentra/chatgpt-web/gpt-6",
        "stdout_sha256": _sha("coordinator-body"),
        "text_sha256": _sha("coordinator-text"),
    }
    preview = reconcile_coordinator_trio(
        admission, children, coordinator, placement="host", authorizer=auth, durable=durable,
    )
    assert preview["closed"] is False
    assert preview["applied"] is False
    assert preview["physical_inference"] is False
    assert governance.work_item_info(children[0]["work_item_id"], owner)["state"] == "IN_REVIEW"
    with pytest.raises(PermissionError, match="verified guest process"):
        reconcile_coordinator_trio(
            admission, children, coordinator, placement="guest",
            authorizer=auth, durable=durable, governance=governance,
        )
    echoed = [dict(child) for child in children]
    echoed[0]["receipt"] = dict(echoed[0]["receipt"], echo_only_detected=True)
    with pytest.raises(PermissionError, match="echo is not an inference"):
        reconcile_coordinator_trio(
            admission, echoed, coordinator, authorizer=auth, durable=durable, governance=governance,
        )
    acknowledged = [dict(child) for child in children]
    acknowledged[1]["receipt"] = dict(acknowledged[1]["receipt"], status="ADMITTED", verified=False, ack_only=True)
    with pytest.raises(PermissionError, match="ACK is not an inference"):
        reconcile_coordinator_trio(
            admission, acknowledged, coordinator, authorizer=auth, durable=durable, governance=governance,
        )
    closed = reconcile_coordinator_trio(
        admission, children, coordinator, placement="host",
        authorizer=auth, durable=durable, governance=governance,
    )
    assert closed["closed"] is True
    assert closed["applied"] is True
    assert closed["promoted"] is False
    assert closed["physical_inference"] is False
    assert closed["placement"]["placement"] == "host"
    for lane, work_id, _operation_id, _agent_id in lanes:
        assert governance.work_item_info(work_id, owner)["state"] == "READY_FOR_PROMOTION"
        assert closed["work_items"][lane]["to"] == "READY_FOR_PROMOTION"
        assert closed["work_items"][lane]["grant_id"] == grants[lane]
    assert governance.work_item_info(parent_id, owner)["state"] == "RUNNING"


def test_uncertain_trio_operation_is_not_resent(tmp_path):
    state = tmp_path / ".sentra"
    owner = "owner-flint"
    run_id = "run-flint-uncertain"
    parent_id = "wi-flint-uncertain-parent"
    auth = AuthorizationService(state)
    durable = DurableRunService(state)
    governance = GovernanceService(state, durable=durable)
    durable.create_run(owner, run_id=run_id, workspace=str(tmp_path), idempotency_key="flint-uncertain")
    durable.transition_run(run_id, owner, "RUNNING")
    durable.create_operation(
        run_id, owner, kind="fleet.trio.parent", idempotency_key="op-flint-uncertain-parent",
        operation_id="op-flint-uncertain-parent", initial_state="RUNNING",
    )
    governance.create_work_item(
        run_id, owner, objective="coordinate", work_item_id=parent_id,
        assignee_agent_id="agent-flint-coordinator",
        required_capabilities=["canvas.coordinator.dot_tool_dispatch"],
        execution_policy={"require_quality_gate": False},
    )
    parent_grant = auth.grant(
        owner, principal_type="agent", principal_id="agent-flint-coordinator",
        capability="canvas.coordinator.dot_tool_dispatch", scope_type="work_item", scope_id=parent_id,
    )
    authority = _authority()
    authority["run_id"] = run_id
    authority["work_item_id"] = parent_id
    authority["operation_id"] = "op-flint-uncertain-parent"
    authority["grant_id"] = parent_grant["grant_id"]
    children = []
    specs = (
        ("sentra-cli", "wi-u-sentra", "op-u-sentra", "agent-u-sentra", False),
        ("opencode", "wi-u-opencode", "op-u-opencode", "agent-u-opencode", True),
        ("codex", "wi-u-codex", "op-u-codex", "agent-u-codex", False),
    )
    for lane, work_id, operation_id, agent_id, uncertain in specs:
        governance.create_work_item(
            run_id, owner, objective=lane, work_item_id=work_id,
            parent_work_item_id=parent_id, assignee_agent_id=agent_id,
            required_capabilities=["model:invoke"],
            execution_policy={"require_quality_gate": False},
        )
        for target in ("RUNNING", "VALIDATING", "IN_REVIEW"):
            governance.transition_work_item(work_id, owner, target)
        grant = auth.grant(
            owner, principal_type="agent", principal_id=agent_id,
            capability="model:invoke", scope_type="work_item", scope_id=work_id,
        )
        durable.create_operation(
            run_id, owner, kind="fleet.trio", idempotency_key=operation_id,
            operation_id=operation_id, initial_state="RUNNING",
        )
        if uncertain:
            durable.update_operation(operation_id, owner, state="UNCERTAIN")
        else:
            durable.update_operation(operation_id, owner, state="SUCCEEDED")
        receipt = _receipt(lane, lane)
        if uncertain:
            receipt = dict(receipt, execution_uncertain=True, status="UNCERTAIN", verified=False)
        children.append({
            "lane": lane, "owner": owner, "run_id": run_id, "work_item_id": work_id,
            "operation_id": operation_id, "grant_id": grant["grant_id"], "agent_id": agent_id,
            "state": "IN_REVIEW", "execution_uncertain": uncertain, "receipt": receipt,
        })
    admission = central_effect_admission(authority)
    coordinator = {
        "operation_id": "op-u-coordinator",
        "work_item_id": parent_id,
        "grant_id": parent_grant["grant_id"],
        **_receipt("sentra-cli", "coordinator"),
        "text_sha256": _sha("coordinator"),
    }
    with pytest.raises(PermissionError, match="not resent"):
        reconcile_coordinator_trio(
            admission, children, coordinator,
            authorizer=auth, durable=durable, governance=governance,
        )
    repaired = [dict(child) for child in children]
    repaired[1]["execution_uncertain"] = False
    repaired[1]["receipt"] = _receipt("opencode", "late-repair")
    with pytest.raises(PermissionError, match="not resent"):
        reconcile_coordinator_trio(
            admission, repaired, coordinator,
            authorizer=auth, durable=durable, governance=governance,
        )
    assert governance.work_item_info("wi-u-opencode", owner)["state"] == "IN_REVIEW"


def test_installed_opencode_catalog_omits_muse_before_any_login_demand():
    catalog = installed_muse_catalog()
    assert catalog["inference"] is False
    assert catalog["listed"] is False
    assert catalog["catalog_bytes"] == 0


def test_session_is_saved_only_after_the_central_receipt(tmp_path):
    state = tmp_path / "control"
    auth = AuthorizationService(state)
    durable = DurableRunService(state)
    governance = GovernanceService(state, durable=durable)
    owner = "owner-a"
    durable.create_run(owner, run_id="run-1", workspace="ws-1")
    durable.transition_run("run-1", owner, "RUNNING")
    governance.create_work_item("run-1", owner, objective="admit fleet", work_item_id="wi-1",
                                assignee_agent_id="dot-a")
    grant = auth.grant(
        owner, principal_type="agent", principal_id="dot-a",
        capability="canvas.coordinator.dot_tool_dispatch", scope_type="work_item", scope_id="wi-1",
    )
    durable.reserve_operation_intent(
        "run-1", owner, operation_id="op-import-1", idempotency_key="idem-fleet-1",
        intent_sha256="b" * 64, resource_key="resource-dot-a",
        operation_context={"work_item_id": "wi-1", "principal_id": "dot-a",
                           "machine_id": "machine-1", "capability_id": "canvas.coordinator.dot_tool_dispatch"},
    )

    class Control:
        pass

    control = Control()
    control.durable, control.governance, control.authorization = durable, governance, auth
    authority = {
        "owner": owner, "run_id": "run-1", "work_item_id": "wi-1",
        "operation_id": "op-import-1", "grant_id": grant["grant_id"], "agent_id": "dot-a",
    }
    admitted = central_effect_admission(authority, root=tmp_path / "no-clis")
    sealed = seal_fleet_admission(control, admitted)
    assert sealed["source"] == "deterministic_fallback"
    assert sealed["counts_as_model_decision"] is False
    assert sealed["central_receipt_reached"] is False
    assert sealed["authorizes_effect"] is False
    assert sealed["homologated"] is False
    assert sealed["physical_proof"] is False
    admission_session = remember_live_dot_if_sealed(
        control, sealed, receipt={"evidence_source": "deterministic_fallback"},
        owner=owner, dot_id="dot-a", session_id="sess-admission",
        run_id="run-1", work_item_id="wi-1", operation_id="op-import-1",
    )
    assert admission_session["saved"] is False
    ledger = DecisionReceiptLedger(state / "runner-audit")
    instruction = "inspect the project tree"
    injected_receipt = {
        "tool": "sentra-cli",
        "effective_model": "sentra/chatgpt-web/gpt-6",
        "stdout_sha256": "c" * 64,
        "live_model_verified": False,
        "evidence_source": "injected_test_runner",
        "verified": True,
    }
    injected = record_runner_final_answer(
        ledger, injected_receipt, instruction=instruction, authority=authority,
        durable=durable, governance=governance, authorization=auth,
    )
    assert injected["source"] == "deterministic_fallback"
    assert injected["counts_as_model_decision"] is False
    assert injected["sealed"] is False
    assert injected.get("model") != "fleet-admission"
    assert injected.get("tool") != "fleet.admit"
    assert injected_receipt["evidence_source"] == "injected_test_runner"
    injected_session = remember_live_dot_if_sealed(
        control, injected, receipt=injected_receipt, owner=owner, dot_id="dot-a",
        session_id="sess-injected", run_id="run-1", work_item_id="wi-1", operation_id="op-import-1",
    )
    assert injected_session["saved"] is False
    assert injected_session["evidence_source"] == "injected_test_runner"
    synthetic = {
        "source": "model", "counts_as_model_decision": True, "sealed": True,
        "central_receipt_reached": True, "physical_proof": False, "homologated": False,
    }
    synthetic_receipt = {
        "live_model_verified": True, "evidence_source": "native_process", "verified": True,
    }
    skipped = remember_live_dot_if_sealed(
        control, synthetic, receipt=synthetic_receipt, owner=owner, dot_id="dot-a",
        session_id="sess-synthetic", run_id="run-1", work_item_id="wi-1", operation_id="op-import-1",
    )
    assert skipped["saved"] is False
    assert skipped["reason"] == "synthetic audit flags are not a live receipt"
    assert ledger.path.name == "decision_receipt_audit.sqlite3"
