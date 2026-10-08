"""Admission gates exercised against actual protected stores and CLI effects."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sentra_canvas.service import Canvas
from sentra_mcp.services.budget_policy import BudgetPolicyService
from sentra_mcp.services.governance import GovernanceService, GovernanceConflict
from tests.unit.test_canvas_task_queue import wait, team, terminal


def test_quota_reservations_serialize_and_replay_without_overbooking(tmp_path):
    governance=GovernanceService(tmp_path)
    policies=BudgetPolicyService(tmp_path,governance=governance)
    policies.set_policy("owner",scope_type="instance",limits={"quota_usage":1})
    def reserve(index):
        return policies.reserve_quota("owner",event_id="attempt-"+str(index),
                                      operation_id="operation-"+str(index))
    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions=list(pool.map(reserve,range(8)))
    admitted=[i for i,decision in enumerate(decisions) if decision["allowed"]]
    assert len(admitted)==1
    assert policies.check_quota("owner",event_id="attempt-"+str(admitted[0]),
        operation_id="operation-"+str(admitted[0]))["allowed"]
    assert not policies.check_quota("owner",event_id="new-attempt",operation_id="new")["allowed"]
    assert reserve(admitted[0])["idempotent_replay"] is True
    assert governance.cost_summary("owner")["quota"]==1
    with pytest.raises(ValueError,match="collision"):
        policies.reserve_quota("other",event_id="attempt-"+str(admitted[0]),
                               operation_id="operation-"+str(admitted[0]))


def test_admission_compare_checks_state_blockers_and_dependencies(tmp_path):
    governance=GovernanceService(tmp_path)
    dependency=governance.create_work_item("run","owner",objective="dependency")
    task=governance.create_work_item("run","owner",objective="blocked",blockers=["pending input"])
    governance.transition_work_item(task["work_item_id"],"owner","QUEUED")
    with pytest.raises(GovernanceConflict,match="blocked"):
        governance.start_execution(task["work_item_id"],"owner",run_id="run",expected_state="QUEUED")
    task=governance.create_work_item("run","owner",objective="dependent",
                                     dependencies=[dependency["work_item_id"]])
    governance.transition_work_item(task["work_item_id"],"owner","QUEUED")
    with pytest.raises(GovernanceConflict,match="dependency"):
        governance.start_execution(task["work_item_id"],"owner",run_id="run",expected_state="QUEUED")
    assert governance.work_item_info(task["work_item_id"],"owner")["state"]=="QUEUED"
    governance.transition_work_item(task["work_item_id"],"owner","CANCELLED")
    with pytest.raises(GovernanceConflict,match="state changed"):
        governance.start_execution(task["work_item_id"],"owner",run_id="run",expected_state="QUEUED")


@pytest.mark.skipif(os.name!="nt",reason="Windows protected task stores")
def test_interrupted_admission_requires_explicit_release_and_keeps_one_reservation(tmp_path):
    app=Canvas(tmp_path)
    restored=None
    try:
        ws,group,workers=team(app)
        app.run_control(ws,"pause")
        app.budget_set(ws,"workspace",{"quota_usage":1})
        task=app.delegate(ws,group,workers[0],"[[W|admitted.txt|ONE_EFFECT]]",
                          "admission","sentra-cli",True)
        runtime=app._runtime()
        with app._lock:
            runtime.project(task)
            assert runtime.admission(task,reserve=True)["allowed"]
        assert app.store.resource("tasks",task["id"],ws)["status"]=="queued"
        app.shutdown()
        restored=Canvas(tmp_path)
        restored.run_control(ws,"resume")
        wait(lambda:restored._runtime().work_item(task)["state"]=="BLOCKED")
        root=Path(restored.store.workspace(ws)["path"])
        assert not (root/"admitted.txt").exists()
        restored.task_control(ws,task["id"],"unblock")
        assert wait(lambda:terminal(restored,ws,task))["status"]=="succeeded"
        assert (root/"admitted.txt").read_text()=="ONE_EFFECT"
        assert restored._runtime().governance.cost_summary(restored._runtime().owner)["quota"]==1
    finally:
        if restored:restored.shutdown()
        app.shutdown()


@pytest.mark.skipif(os.name!="nt",reason="Windows protected task stores")
def test_real_cli_budget_block_restart_and_quality_separation(tmp_path):
    app=Canvas(tmp_path,max_task_workers=2)
    restored=None
    try:
        ws,group,workers=team(app)
        app.run_control(ws,"pause")
        policy=app.budget_set(ws,"workspace",{"quota_usage":1})
        first=app.delegate(ws,group,workers[0],"[[W|first.txt|PRIVATE_GOVERNANCE_FIRST]]",
                           "first","sentra-cli",True)
        second=app.delegate(ws,group,workers[1],"[[W|second.txt|PRIVATE_GOVERNANCE_SECOND]]",
                            "second","sentra-cli",True)
        app.task_control(ws,first["id"],"block")
        app.run_control(ws,"resume")
        assert wait(lambda:terminal(app,ws,second))["status"]=="succeeded"
        governed=wait(lambda:app.task_governance(ws,second["id"])
                      if app._runtime().work_item(second)["state"]=="VALIDATING" else None)
        assert governed["work_item"]["state"]=="VALIDATING"
        assert governed["work_item"]["execution_policy"]["require_quality_gate"] is True
        assert not governed["work_item"]["execution_state"].get("quality_gate")
        assert governed["work_item"]["execution_run_id"] is None
        assert "PRIVATE_GOVERNANCE" not in str(governed)
        runtime=app._runtime()
        with pytest.raises(GovernanceConflict,match="Quality Gate"):
            runtime.governance.transition_work_item(second["work_item_id"],runtime.owner,"READY_FOR_PROMOTION")
        app.task_control(ws,first["id"],"unblock")
        assert app.task_governance(ws,first["id"])["admission"]["allowed"] is False
        root=Path(app.store.workspace(ws)["path"])
        assert not (root/"first.txt").exists()
        app.shutdown()
        restored=Canvas(tmp_path,max_task_workers=2)
        assert restored.task_governance(ws,first["id"])["admission"]["allowed"] is False
        assert not (root/"first.txt").exists()
        restored.budget_set(ws,"workspace",None,policy_id=policy["budget_policy_id"],enabled=False)
        assert wait(lambda:terminal(restored,ws,first))["status"]=="succeeded"
        assert (root/"first.txt").read_text()=="PRIVATE_GOVERNANCE_FIRST"
        assert (root/"second.txt").read_text()=="PRIVATE_GOVERNANCE_SECOND"
        wait(lambda:restored._runtime().work_item(first)["state"]=="VALIDATING")
        assert restored._runtime().governance.cost_summary(restored._runtime().owner)["quota"]==2
        assert restored.delegate(ws,group,workers[0],first["prompt"],"first","sentra-cli",True)["id"]==first["id"]
        assert restored._runtime().governance.cost_summary(restored._runtime().owner)["quota"]==2
        other=restored.create_workspace("other")["id"]
        with pytest.raises(PermissionError):
            restored.budget_set(other,"workspace",None,policy_id=policy["budget_policy_id"],enabled=True)
    finally:
        if restored:restored.shutdown()
        app.shutdown()
