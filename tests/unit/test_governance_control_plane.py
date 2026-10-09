from __future__ import annotations

from pathlib import Path

import pytest

import sentra_mcp.services.governance as governance_module
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.governance import GovernanceConflict


def _services(tmp_path: Path):
    durable = DurableRunService(tmp_path / ".sentra")
    context = ContextBusService(tmp_path / ".sentra")
    control = ControlPlaneService(durable, context)
    return durable, context, control


def test_work_item_separates_authority_from_execution_and_self_heals_locks(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        owner = "owner-a"
        authority = durable.create_run(owner, workspace="project")
        executor_a = durable.create_run(owner, workspace="project")
        executor_b = durable.create_run(owner, workspace="project")
        goal = control.create_goal(authority["run_id"], owner, objective="Ship the control plane")
        item = control.create_work_item(
            authority["run_id"], owner,
            objective="Implement durable work ownership",
            goal_id=goal["goal_id"],
            external_key="WI-1",
        )
        assert item["run_id"] == authority["run_id"]
        assert item["checkout_run_id"] is None

        started = control.start_work_item_execution(
            item["work_item_id"], owner, run_id=executor_a["run_id"]
        )
        assert started["checkout_run_id"] == executor_a["run_id"]
        assert started["execution_run_id"] == executor_a["run_id"]

        wrong_release = control.release_work_item_locks(
            item["work_item_id"], owner, run_id=executor_b["run_id"]
        )
        assert wrong_release["cleared"] == []
        assert wrong_release["work_item"]["execution_run_id"] == executor_a["run_id"]

        durable.transition_run(executor_a["run_id"], owner, "SUCCEEDED")
        checked_out = control.checkout_work_item(
            item["work_item_id"], owner, run_id=executor_b["run_id"]
        )
        assert checked_out["checkout_run_id"] == executor_b["run_id"]
        resumed = control.start_work_item_execution(
            item["work_item_id"], owner, run_id=executor_b["run_id"]
        )
        assert resumed["execution_run_id"] == executor_b["run_id"]
    finally:
        context.close()
        durable.close()


def test_retry_recovery_policy_is_durable_and_bounded(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        owner = "owner-a"
        authority = durable.create_run(owner, workspace="project")
        item = control.create_work_item(
            authority["run_id"], owner,
            objective="Retry safely",
            retry_policy={
                "max_attempts": 1,
                "retryable_error_classes": ["dependency"],
                "side_effect_replay_policy": "SAFE_ONLY",
                "exhausted_action": "BLOCK",
            },
        )
        first = control.record_work_item_failure(
            item["work_item_id"], owner,
            error_class="dependency", side_effect_may_have_started=False,
        )
        assert first["next_action"] == "RETRY"
        assert first["attempt"] == 1
        second = control.record_work_item_failure(
            item["work_item_id"], owner,
            error_class="dependency", side_effect_may_have_started=False,
            failure_chain_id=first["failure_chain_id"],
        )
        assert second["next_action"] == "BLOCK"
        assert second["attempt"] == 2

        recovery = control.begin_work_item_recovery(
            item["work_item_id"], owner, recovery_class="STATUS_REPAIR"
        )
        assert recovery["recovery_capabilities"] == ["read", "status"]
        control.governance.assert_recovery_capability(item["work_item_id"], owner, "status")
        with pytest.raises(PermissionError):
            control.governance.assert_recovery_capability(
                item["work_item_id"], owner, "source_write"
            )
        with pytest.raises(GovernanceConflict, match="recovery handoff"):
            control.transition_work_item(
                item["work_item_id"], owner, "QUEUED"
            )
        with pytest.raises(GovernanceConflict, match="recovery handoff"):
            control.start_work_item_execution(
                item["work_item_id"], owner, run_id=authority["run_id"]
            )

        resumed = control.complete_work_item_recovery(
            item["work_item_id"], owner,
            outcome="resume", reason="status repaired; normal worker may resume",
        )
        assert resumed["state"] == "QUEUED"
        assert resumed["recovery_class"] is None
        started = control.start_work_item_execution(
            item["work_item_id"], owner, run_id=authority["run_id"]
        )
        assert started["state"] == "RUNNING"
    finally:
        context.close()
        durable.close()


def test_execution_policy_review_changes_and_approval(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        owner = "owner-a"
        authority = durable.create_run(owner, workspace="project")
        item = control.create_work_item(
            authority["run_id"], owner,
            objective="Require staged signoff",
            execution_policy={
                "stages": [
                    {"id": "security-review", "type": "review", "actor_agent_id": "reviewer"},
                    {"id": "operator-approval", "type": "approval", "actor_user_id": "operator"},
                ]
            },
        )
        control.transition_work_item(item["work_item_id"], owner, "RUNNING")
        with pytest.raises(GovernanceConflict, match="quality validation"):
            control.submit_work_item_policy(item["work_item_id"], owner)
        validated = control.record_work_item_quality_gate(
            item["work_item_id"], owner,
            passed=True, reason="deterministic checks passed",
        )
        assert validated["state"] == "VALIDATING"
        submitted = control.submit_work_item_policy(item["work_item_id"], owner)
        assert submitted["state"] == "IN_REVIEW"
        assert submitted["execution_state"]["quality_gate"]["passed"] is True

        with pytest.raises(PermissionError):
            control.decide_work_item_policy(
                item["work_item_id"], owner,
                actor_type="agent", actor_id="intruder",
                decision="approved",
            )

        bounced = control.decide_work_item_policy(
            item["work_item_id"], owner,
            actor_type="agent", actor_id="reviewer",
            decision="changes_requested", comment="Add a negative test.",
        )["work_item"]
        assert bounced["state"] == "CHANGES_REQUESTED"

        restarted = control.transition_work_item(item["work_item_id"], owner, "RUNNING")
        assert restarted["execution_state"]["quality_gate"]["status"] == "stale"
        control.record_work_item_quality_gate(
            item["work_item_id"], owner,
            passed=True, reason="repaired candidate passed deterministic checks",
        )
        resubmitted = control.submit_work_item_policy(item["work_item_id"], owner)
        assert resubmitted["execution_state"]["current_stage_id"] == "security-review"

        reviewed = control.decide_work_item_policy(
            item["work_item_id"], owner,
            actor_type="agent", actor_id="reviewer", decision="approved",
        )["work_item"]
        assert reviewed["state"] == "APPROVAL_REQUIRED"
        assert reviewed["execution_state"]["current_stage_id"] == "operator-approval"

        approved = control.decide_work_item_policy(
            item["work_item_id"], owner,
            actor_type="user", actor_id="operator", decision="approved",
        )["work_item"]
        assert approved["state"] == "READY_FOR_PROMOTION"
        assert approved["execution_state"]["status"] == "passed"
    finally:
        context.close()
        durable.close()


def test_cost_ledger_tracks_actual_market_and_quota_separately(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        owner = "owner-a"
        run = durable.create_run(owner, workspace="project")
        item = control.create_work_item(run["run_id"], owner, objective="Measure cost")
        control.record_cost(
            owner, run_id=run["run_id"], work_item_id=item["work_item_id"],
            provider="chatgpt", model="subscription",
            actual_cost=0.0, market_cost=1.25, quota_usage=0.4,
            input_tokens=1000, output_tokens=200, reasoning_tokens=300,
        )
        control.record_cost(
            owner, run_id=run["run_id"], work_item_id=item["work_item_id"],
            provider="api", model="model-x",
            actual_cost=0.75, market_cost=0.75, quota_usage=0.1,
            input_tokens=500, output_tokens=100,
        )
        summary = control.cost_summary(owner, work_item_id=item["work_item_id"])
        assert summary["count"] == 2
        assert summary["actual"] == pytest.approx(0.75)
        assert summary["market"] == pytest.approx(2.0)
        assert summary["quota"] == pytest.approx(0.5)
        assert summary["input_tokens"] == 1500
        assert summary["reasoning_tokens"] == 300
    finally:
        context.close()
        durable.close()


def test_routine_coalesces_active_work_and_blueprint_scrubs_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(governance_module, "protect_secret", lambda value: "test:" + value)
    monkeypatch.setattr(
        governance_module, "unprotect_secret",
        lambda value: value.removeprefix("test:"),
    )
    durable, context, control = _services(tmp_path)
    try:
        owner = "owner-a"
        run = durable.create_run(owner, workspace="C:/private/project")
        routine = control.create_routine(
            owner,
            name="nightly-audit",
            trigger_kind="schedule",
            trigger_spec={"cron": "0 2 * * *"},
            work_template={"objective": "Audit the project"},
            active_policy="coalesce_if_active",
        )
        first = control.fire_routine(routine["routine_id"], owner, run_id=run["run_id"])
        second = control.fire_routine(routine["routine_id"], owner, run_id=run["run_id"])
        assert first["status"] == "ENQUEUED"
        assert second["status"] == "COALESCED"
        assert second["work_item"]["work_item_id"] == first["work_item"]["work_item_id"]

        secret = control.create_secret(
            owner, name="API_TOKEN", value="super-secret",
            scope_type="workspace", scope_id="project",
        )
        rotated = control.rotate_secret(secret["secret_id"], owner, value="new-secret")
        assert rotated["current_version"] == 2
        control.bind_secret(
            secret["secret_id"], owner,
            target_type="agent", target_id="builder", env_name="API_TOKEN",
            purpose="test",
        )
        assert control.governance.resolve_secret_for_runtime(
            secret["secret_id"], owner,
            actor_type="agent", actor_id="builder", purpose="test",
        ) == "new-secret"
        with pytest.raises(PermissionError, match="not bound"):
            control.governance.resolve_secret_for_runtime(
                secret["secret_id"], owner,
                actor_type="agent", actor_id="builder", purpose="runtime",
            )
        with pytest.raises(PermissionError, match="not bound"):
            control.governance.resolve_secret_for_runtime(
                secret["secret_id"], owner,
                actor_type="agent", actor_id="intruder", purpose="test",
            )

        unbound = control.create_secret(
            owner, name="UNBOUND_TOKEN", value="must-not-leak",
            scope_type="workspace", scope_id="project",
        )
        with pytest.raises(PermissionError, match="not bound"):
            control.governance.resolve_secret_for_runtime(
                unbound["secret_id"], owner,
                actor_type="agent", actor_id="builder", purpose="test",
            )
        assert "must-not-leak" not in str(unbound)

        control.install_skill(
            owner, name="security-review", version="1.0.0",
            content="# Security review\nRequire deterministic evidence.",
        )
        plugin = control.register_plugin(
            owner,
            manifest={"name": "example", "version": "1.0.0",
                      "capabilities": ["read", "write", "network"]},
            verified_methods=["capability:read", "capability:write"],
            narrowed_capabilities=["read", "network"],
        )
        assert plugin["effective_capabilities"] == ["read"]

        blueprint = control.export_blueprint(run["run_id"], owner)
        assert blueprint["contains_secret_values"] is False
        assert blueprint["secret_requirements"][0]["required_value"] is True
        serialized = str(blueprint)
        assert "super-secret" not in serialized
        assert "new-secret" not in serialized
        assert "C:/private/project" not in serialized
    finally:
        context.close()
        durable.close()
