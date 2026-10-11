"""Cumulative loop reservation remains crash-durable, separate from execution."""
import pytest
from sentra_executors.goal_loop import BoundedGoalLoop,GoalLoopConflict
from test_sentra_executors_cos_goal_loop import setup


def test_micro_usd_budget_cumulative_reservations_and_restart(tmp_path):
    durable,context,control,p=setup(tmp_path)
    try:
        p["max_cost_usd"]=0.9
        control.authorization.grant(p["owner"],principal_type="agent",
            principal_id=p["principal_id"],capability="goal:iterate",
            scope_type="goal",scope_id=p["goal_id"])
        loop=BoundedGoalLoop(control)
        opened=loop.open(**p)
        loop_id=opened["loop_id"]
        with pytest.raises(ValueError,match="explicit step estimate"):
            loop.advance(p["owner"],loop_id,objective="priced step",
                         operator_approved=True)
        with pytest.raises(ValueError,match="finite"):
            loop.advance(p["owner"],loop_id,objective="priced step",
                         operator_approved=True,estimated_cost_usd=float("inf"))
        first=loop.advance(p["owner"],loop_id,objective="priced step",
                  operator_approved=True,estimated_cost_usd=0.7)
        assert BoundedGoalLoop(control).status(p["owner"],loop_id)["reserved_cost_usd"]==0.7
        assert control.work_item_info(first["work_item_id"],p["owner"])["state"]=="PENDING"
        control.transition_work_item(first["work_item_id"],p["owner"],"RUNNING")
        control.governance.record_quality_gate(first["work_item_id"],p["owner"],passed=True,evidence=["unit validation"])
        control.transition_work_item(first["work_item_id"],p["owner"],"READY_FOR_PROMOTION")
        control.transition_work_item(first["work_item_id"],p["owner"],"COMPLETED")
        with pytest.raises(GoalLoopConflict,match="cost cap"):
            loop.advance(p["owner"],loop_id,objective="over budget",
                operator_approved=True,estimated_cost_usd=0.3)
        assert loop.status(p["owner"],loop_id)["remaining_steps"]==1
        second=BoundedGoalLoop(control).advance(p["owner"],loop_id,
                objective="bounded step",operator_approved=True,
                estimated_cost_usd=0.2)
        assert second["work_item_id"] != first["work_item_id"]
        status=loop.status(p["owner"],loop_id)
        assert status["reserved_cost_usd"]==0.9
        assert status["remaining_steps"]==0
        with pytest.raises(GoalLoopConflict,match="iteration cap"):
            control.transition_work_item(second["work_item_id"],p["owner"],"RUNNING")
            control.governance.record_quality_gate(second["work_item_id"],p["owner"],passed=True,evidence=["unit validation"])
            control.transition_work_item(second["work_item_id"],p["owner"],"READY_FOR_PROMOTION")
            control.transition_work_item(second["work_item_id"],p["owner"],"COMPLETED")
            loop.advance(p["owner"],loop_id,objective="third",
                         operator_approved=True,estimated_cost_usd=0.01)
    finally:
        context.close();durable.close()
