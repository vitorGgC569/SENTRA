"""R5 trusted host price quotes fence model-supplied budgets and crash replay."""
import pytest
from sentra_executors.goal_loop import HostPricedGoalLoop,GoalLoopConflict
from test_sentra_executors_cos_goal_loop import setup


def test_host_pricer_blocks_forged_cost_and_reserves_cumulative_sqlite(tmp_path):
    durable,context,control,p=setup(tmp_path)
    try:
        p["max_cost_usd"]=0.9
        control.authorization.grant(p["owner"],principal_type="agent",
            principal_id=p["principal_id"],capability="goal:iterate",
            scope_type="goal",scope_id=p["goal_id"])
        mapping={"step1":700000,"step2":200000,"too-much":300000}
        quote_revision=["pricing-v1"]
        quote_name=["host-quote-original"]
        def catalog(**inputs):
            assert inputs["owner"]==p["owner"]
            assert inputs["run_id"]==p["run_id"]
            assert inputs["goal_id"]==p["goal_id"]
            return {"micro_usd":mapping[inputs["objective"]],
                    "quote_id":quote_name[0], "price_revision":quote_revision[0]}
        loop=HostPricedGoalLoop(control,price_quote=catalog)
        opened=loop.open(**p)
        lid=opened["loop_id"]
        with pytest.raises(PermissionError,match="agent supplied"):
            loop.advance(p["owner"],lid,objective="step1",
                operator_approved=True,estimated_cost_usd=0.000001)
        result=loop.advance(p["owner"],lid,objective="step1",operator_approved=True)
        assert result["host_priced"] and result["reserved_cost_usd"]==0.7
        assert loop.status(p["owner"],lid)["reserved_cost_usd"]==0.7
        # Crash gap: pending WorkItem mapping is wiped, but governance external
        # key retains same central WorkItem. Changed quote cannot be accepted.
        with loop.store.connect("execution_workspace") as db:
            db.execute("UPDATE goal_loop_steps SET work_item_id=NULL "
                       "WHERE loop_id=? AND step=1",(lid,))
        quote_name[0]="host-quote-changed"
        with pytest.raises(GoalLoopConflict,match="durable host quote/objective changed"):
            loop.advance(p["owner"],lid,objective="step1",operator_approved=True)
        quote_name[0]="host-quote-original"
        restored=HostPricedGoalLoop(control,price_quote=catalog).advance(
            p["owner"],lid,objective="step1",operator_approved=True)
        assert restored["work_item_id"]==result["work_item_id"]
        assert len(control.list_work_items(p["owner"],run_id=p["run_id"])["items"])==1
        control.transition_work_item(result["work_item_id"],p["owner"],"RUNNING")
        control.governance.record_quality_gate(result["work_item_id"],p["owner"],
                                                passed=True,evidence=["host-priced fixture"])
        control.transition_work_item(result["work_item_id"],p["owner"],"READY_FOR_PROMOTION")
        control.transition_work_item(result["work_item_id"],p["owner"],"COMPLETED")
        with pytest.raises(GoalLoopConflict,match="cost cap"):
            loop.advance(p["owner"],lid,objective="too-much",operator_approved=True)
        with loop.store.connect("execution_workspace") as db:
            assert db.execute("SELECT COUNT(*) FROM goal_loop_host_quotes WHERE loop_id=? AND step=2", (lid,)).fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM goal_loop_cost_reservations WHERE loop_id=?", (lid,)).fetchone()[0] == 1
        next_item=loop.advance(p["owner"],lid,objective="step2",operator_approved=True)
        assert next_item["reserved_cost_usd"]==0.2
        assert loop.status(p["owner"],lid)["reserved_cost_usd"]==0.9
        assert loop.status(p["owner"],lid)["remaining_steps"]==0
        assert next_item["automatic_execution"] is False
    finally:
        context.close();durable.close()


def test_host_pricer_refuses_missing_or_unbounded_quotes(tmp_path):
    durable,context,control,p=setup(tmp_path)
    try:
        p["max_cost_usd"]=0.3
        control.authorization.grant(p["owner"],principal_type="agent",
            principal_id=p["principal_id"],capability="goal:iterate",
            scope_type="goal",scope_id=p["goal_id"])
        with pytest.raises(TypeError,match="pricing"):
            HostPricedGoalLoop(control,price_quote=None)
        quote=HostPricedGoalLoop(control,price_quote=lambda **_:{"micro_usd":True,
                      "quote_id":"host-quote-12345","price_revision":"v1"})
        lid=quote.open(**p)["loop_id"]
        with pytest.raises(ValueError,match="bounded"):
            quote.advance(p["owner"],lid,objective="anything",
                         operator_approved=True)
        assert quote.status(p["owner"],lid)["remaining_steps"]==2
    finally:
        context.close();durable.close()
