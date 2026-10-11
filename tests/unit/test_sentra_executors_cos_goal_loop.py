"""Bounded human-paced loop on real durable Goals and Governance WorkItems."""
import pytest

from sentra_executors.goal_loop import BoundedGoalLoop, GoalLoopConflict
from test_governance_coordination import _services


def setup(tmp_path):
    durable, context, control = _services(tmp_path)
    owner = "loop-owner"
    run = durable.create_run(owner, workspace="loop-workspace")["run_id"]
    control.ensure_agent(run,owner,agent_id="loop-agent",role="builder")
    goal = control.create_goal(run,owner,objective="Build artifact",
                               acceptance_criteria=["Review final output"])
    params=dict(owner=owner,run_id=run,goal_id=goal["goal_id"],
                principal_id="loop-agent",max_steps=2,max_cost_usd=0.0,
                deadline_seconds=120,operator_approved=True)
    return durable,context,control,params


def test_goal_loop_real_grants_workitem_and_restart(tmp_path):
    durable,context,control,p=setup(tmp_path)
    try:
        loop=BoundedGoalLoop(control)
        with pytest.raises(PermissionError):
            loop.open(**p)
        grant = control.authorization.grant(p["owner"],principal_type="agent",
                     principal_id=p["principal_id"],capability="goal:iterate",
                     scope_type="goal",scope_id=p["goal_id"])
        started = loop.open(**p)
        assert started["remaining_steps"]==2
        with pytest.raises(PermissionError):
            loop.advance(p["owner"],started["loop_id"],objective="Step one")
        first=loop.advance(p["owner"],started["loop_id"],objective="Step one",
                           operator_approved=True)
        assert first["automatic_execution"] is False
        info=control.work_item_info(first["work_item_id"],p["owner"])
        assert info["run_id"]==p["run_id"] and info["goal_id"]==p["goal_id"]
        assert info["state"]=="PENDING"
        with pytest.raises(GoalLoopConflict,match="not completed"):
            loop.advance(p["owner"],started["loop_id"],objective="Step two",
                         operator_approved=True)
        assert BoundedGoalLoop(control).status(
            p["owner"],started["loop_id"])["remaining_steps"]==1
        with pytest.raises(FileNotFoundError):
            loop.status("wrong-owner",started["loop_id"])
        control.authorization.revoke(grant["grant_id"],p["owner"])
        with pytest.raises(PermissionError):
            loop.advance(p["owner"],started["loop_id"],objective="Step two",
                         operator_approved=True)
        stopped=loop.stop(p["owner"],started["loop_id"],operator_approved=True)
        assert stopped["state"]=="STOPPED"
        assert control.work_item_info(first["work_item_id"],p["owner"])["state"]=="PENDING"
    finally:
        context.close();durable.close()


def test_goal_loop_limits_and_no_spending(tmp_path):
    durable,context,control,p=setup(tmp_path)
    try:
        control.authorization.grant(p["owner"],principal_type="agent",
                     principal_id=p["principal_id"],capability="goal:iterate",
                     scope_type="goal",scope_id=p["goal_id"])
        loop=BoundedGoalLoop(control)
        with pytest.raises(ValueError):
            loop.open(**{**p,"max_steps":0})
        with pytest.raises(ValueError):
            loop.open(**{**p,"max_cost_usd":float("nan")})
        with pytest.raises(ValueError):
            loop.open(**{**p,"deadline_seconds":999999})
        opened=loop.open(**p)
        with pytest.raises(GoalLoopConflict):
            loop.open(**{**p,"max_steps":10})
        step=loop.advance(p["owner"],opened["loop_id"],objective="Only planning",
                          operator_approved=True)
        assert loop.status(p["owner"],opened["loop_id"])["remaining_steps"]==1
        assert len(control.list_work_items(p["owner"],run_id=p["run_id"])["items"])==1
        assert step["automatic_execution"] is False
    finally:
        context.close();durable.close()
