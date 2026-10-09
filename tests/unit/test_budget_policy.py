from __future__ import annotations

from pathlib import Path

import pytest

from sentra_mcp.services.budget_policy import BudgetExceeded
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService


def _services(tmp_path: Path):
    durable = DurableRunService(tmp_path / ".sentra")
    context = ContextBusService(tmp_path / ".sentra")
    control = ControlPlaneService(durable, context)
    return durable, context, control


def test_work_budget_records_cost_then_blocks_future_execution(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        owner = "owner-a"
        authority = durable.create_run(owner, workspace="project")
        executor = durable.create_run(owner, workspace="project")
        item = control.create_work_item(
            authority["run_id"],
            owner,
            objective="Stay under budget",
            budget={
                "limits": {
                    "actual_cost": 1.0,
                    "market_cost": 3.0,
                    "quota_usage": 1.0,
                    "total_tokens": 5000,
                },
                "mode": "hard_stop",
            },
        )
        policies = control.budget_list(owner)["items"]
        assert len(policies) == 1
        assert policies[0]["scope_id"] == item["work_item_id"]

        first = control.record_cost(
            owner,
            work_item_id=item["work_item_id"],
            run_id=authority["run_id"],
            actual_cost=0.75,
            market_cost=1.5,
            quota_usage=0.4,
            input_tokens=1000,
            output_tokens=500,
        )
        assert first["budget"]["allowed"] is True

        second = control.record_cost(
            owner,
            work_item_id=item["work_item_id"],
            run_id=authority["run_id"],
            actual_cost=0.50,
            market_cost=0.5,
            quota_usage=0.1,
            input_tokens=100,
        )
        assert second["budget"]["allowed"] is False
        current = control.work_item_info(item["work_item_id"], owner)
        assert current["state"] == "BLOCKED"

        with pytest.raises(BudgetExceeded):
            control.start_work_item_execution(
                item["work_item_id"], owner, run_id=executor["run_id"]
            )
    finally:
        context.close()
        durable.close()


def test_budget_hierarchy_and_warn_mode_do_not_hide_usage(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        owner = "owner-a"
        run = durable.create_run(owner, workspace="project")
        item = control.create_work_item(run["run_id"], owner, objective="Budget hierarchy")
        control.budget_set(
            owner,
            scope_type="instance",
            limits={"market_cost": 1.0},
            mode="warn",
        )
        control.budget_set(
            owner,
            scope_type="work_item",
            scope_id=item["work_item_id"],
            limits={"quota_usage": 0.5},
            mode="hard_stop",
        )
        control.record_cost(
            owner,
            run_id=run["run_id"],
            work_item_id=item["work_item_id"],
            market_cost=2.0,
            quota_usage=0.25,
        )
        check = control.budget_check(
            owner, work_item_id=item["work_item_id"]
        )
        assert check["allowed"] is True
        assert len(check["warnings"]) == 1

        projected = control.budget_check(
            owner,
            work_item_id=item["work_item_id"],
            proposed={"quota_usage": 0.30},
        )
        assert projected["allowed"] is False
        assert projected["blocking"][0]["exceeded"]["quota_usage"]["projected"] == pytest.approx(0.55)
    finally:
        context.close()
        durable.close()


def test_budget_scopes_include_run_and_operation(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        owner = "owner-a"
        run = durable.create_run(owner, workspace="project")
        operation = durable.create_operation(
            run["run_id"], owner, kind="TEST", idempotency_key="budget-operation"
        )
        control.budget_set(
            owner,
            scope_type="run",
            scope_id=run["run_id"],
            limits={"market_cost": 1.0},
            mode="hard_stop",
        )
        control.budget_set(
            owner,
            scope_type="operation",
            scope_id=operation["operation_id"],
            limits={"quota_usage": 0.5},
            mode="hard_stop",
        )
        control.record_cost(
            owner,
            run_id=run["run_id"],
            operation_id=operation["operation_id"],
            market_cost=0.5,
            quota_usage=0.25,
        )

        decision = control.budget_check(
            owner,
            run_id=run["run_id"],
            operation_id=operation["operation_id"],
            proposed={"market_cost": 0.6, "quota_usage": 0.30},
        )
        assert decision["allowed"] is False
        exceeded = {
            item["scope_type"]: set(item["exceeded"])
            for item in decision["blocking"]
        }
        assert exceeded["run"] == {"market_cost"}
        assert exceeded["operation"] == {"quota_usage"}
    finally:
        context.close()
        durable.close()
