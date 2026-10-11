"""A16/A17 receipt and GC projection against central DurableRunService."""
import pytest

from sentra_executors.operation_receipts import OperationReceiptViews
from test_governance_coordination import _services


def test_operation_receipt_from_real_core_and_owner_bound_gc_plan(tmp_path):
    durable,context,control=_services(tmp_path)
    owner="receipt-owner"
    try:
        run=durable.create_run(owner,workspace="receipt-lab")["run_id"]
        control.ensure_agent(run,owner,agent_id="receipt-agent",role="builder")
        work=control.create_work_item(run,owner,objective="One operation")
        op=durable.create_operation(run,owner,kind="sentra.exec",
                                    idempotency_key="receipt-case")
        control.durable.update_operation(op["operation_id"],owner,
                                         state="RUNNING",
                                         progress={"work_item_id":work["work_item_id"]})
        control.durable.update_operation(
            op["operation_id"],owner,state="SUCCEEDED",
            result={"exit_code":0,"files_changed":3,"lines_added":18,
                    "stdout":"private SECRET not for display",
                    "secret":"should-never-appear","hits":2,
                    "files":["C:\\private\\secret"]})
        views=OperationReceiptViews(control)
        receipt=views.receipt(owner,op["operation_id"],
                              work_item_id=work["work_item_id"])
        assert receipt["summary"]=="Operation succeeded"
        assert receipt["details"]=={"exit_code":0,"files_changed":3,"lines_added":18,"hits":2}
        assert "secret" not in str(receipt).lower()
        assert "stdout" not in str(receipt).lower()
        assert receipt["source"]=="durable_operation"
        plan=views.cleanup_candidates(owner,run,idle_before=10**12)
        assert any(c["operation_id"]==op["operation_id"] for c in plan["candidates"])
        assert plan["destructive_actions_executed"]==0
        assert all(not c["may_kill_process"] for c in plan["candidates"])
        with pytest.raises(PermissionError):
            views.receipt("foreign-owner",op["operation_id"])
        with pytest.raises(PermissionError):
            views.cleanup_candidates("foreign-owner",run,idle_before=10**12)
        with pytest.raises(ValueError):
            views.cleanup_candidates(owner,run,idle_before=float("nan"))
    finally:
        context.close();durable.close()


def test_gc_never_proposes_uncertain_or_preserved_operations(tmp_path):
    durable,context,control=_services(tmp_path)
    owner="gc-owner"
    try:
        run=durable.create_run(owner,workspace="gc-lab")["run_id"]
        uncertain=durable.create_operation(run,owner,kind="sentra.exec",
                                         idempotency_key="gc-uncertain",
                                         initial_state="RUNNING")
        durable.update_operation(uncertain["operation_id"],owner,state="UNCERTAIN")
        preserved=durable.create_operation(run,owner,kind="sentra.exec",
                                          idempotency_key="gc-preserved",
                                          cleanup_policy="preserve",
                                          initial_state="RUNNING")
        durable.update_operation(preserved["operation_id"],owner,state="SUCCEEDED")
        views=OperationReceiptViews(control)
        assert views.receipt(owner,uncertain["operation_id"])["requires_reconciliation"]
        plan=views.cleanup_candidates(owner,run,idle_before=10**12)
        assert plan["candidates"]==[]
        assert plan["destructive_actions_executed"]==0
    finally:
        context.close();durable.close()
