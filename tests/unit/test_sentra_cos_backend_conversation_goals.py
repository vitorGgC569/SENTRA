"""Shared ConversationStore and real ControlPlane Goal/Loop across restarts."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from sentra_core.conversations import ConversationStore
from sentra_executors.goal_loop import ConversationGoalLoop, GoalLoopConflict
from test_governance_coordination import _services


def setup(tmp_path):
    d, c, control = _services(tmp_path)
    conversations = ConversationStore(tmp_path, principal="test-sid")
    session = conversations.open(tmp_path)
    owner = "cli:test-sid"
    run = d.create_run(owner, workspace=str(tmp_path))["run_id"]
    control.ensure_agent(run, owner, agent_id="goal-agent", role="builder")
    return d, c, control, conversations, session, owner, run


def test_unset_and_encrypted_objective_survive_full_restart(tmp_path):
    d, c, control, conversations, session, owner, run = setup(tmp_path)
    try:
        api = ConversationGoalLoop(control, conversations)
        assert api.status(owner, session)["state"] == "UNSET"
        assert api.loop_status(owner, session)["state"] == "UNSET"
        goal = api.set(owner, session, run_id=run, objective="PRIVATE_GOAL_SENTINEL", operator_approved=True)
        assert goal["goal"]["objective"] == "PRIVATE_GOAL_SENTINEL"
        assert api.set(owner, session, run_id=run, objective="PRIVATE_GOAL_SENTINEL", operator_approved=True)["goal_id"] == goal["goal_id"]
        assert "PRIVATE_GOAL_SENTINEL" not in control.goal_info(goal["goal_id"], owner)["objective"]
        assert b"PRIVATE_GOAL_SENTINEL" not in control.store.path_for("execution_workspace").read_bytes()
        blocked = api.open(owner, session, principal_id="goal-agent", operator_approved=True)
        assert blocked["blocked"] and blocked["state"] == "BLOCKED"
        assert len(d.list_runs(owner)["items"]) == 1
    finally:
        c.close(); d.close()
    d2, c2, control2 = _services(tmp_path)
    try:
        restored = ConversationGoalLoop(control2, ConversationStore(tmp_path, principal="test-sid"))
        status = restored.status(owner, session)
        assert status["goal_id"] == goal["goal_id"] and status["run_id"] == run
        assert status["goal"]["objective"] == "PRIVATE_GOAL_SENTINEL"
        assert status["loop"] is None
        with pytest.raises(PermissionError):
            restored.status("cli:other-sid", session)
        with pytest.raises(PermissionError):
            restored.status("admin:test-sid", session)
    finally:
        c2.close(); d2.close()


def test_bounded_loop_grant_stop_and_no_auto_execution(tmp_path):
    d, c, control, conversations, session, owner, run = setup(tmp_path)
    try:
        api = ConversationGoalLoop(control, conversations)
        goal = api.set(owner, session, run_id=run, objective="Build artifact", operator_approved=True)
        grant = control.authorization.grant(owner, principal_type="agent", principal_id="goal-agent",
            capability="goal:iterate", scope_type="goal", scope_id=goal["goal_id"])
        opened = api.open(owner, session, principal_id="goal-agent", max_steps=2, operator_approved=True)
        assert opened["state"] == "ACTIVE" and opened["loop"]["remaining_steps"] == 2
        first = api.advance(owner, session, objective="Review one", operator_approved=True)
        assert first["automatic_execution"] is False
        assert control.work_item_info(first["work_item_id"], owner)["state"] == "PENDING"
        with pytest.raises(GoalLoopConflict):
            api.set(owner, session, run_id=run, objective="Different objective", operator_approved=True)
        assert api.loop_stop(owner, session, operator_approved=True)["state"] == "STOPPED"
        assert api.status(owner, session)["state"] == "ACTIVE"
        control.authorization.revoke(grant["grant_id"], owner)
        with pytest.raises(PermissionError):
            api.advance(owner, session, objective="Review two", operator_approved=True)
        assert api.stop(owner, session, operator_approved=True)["state"] == "CANCELLED"
        assert api.status(owner, session)["loop"]["state"] == "STOPPED"
        # Owner stop never relaunches or erases a pending physical WorkItem.
        assert control.work_item_info(first["work_item_id"], owner)["state"] == "PENDING"
    finally:
        c.close(); d.close()


def test_concurrent_goal_set_one_goal_and_workitem_creation_crash_gap(tmp_path, monkeypatch):
    d, c, control, conversations, session, owner, run = setup(tmp_path)
    try:
        api = ConversationGoalLoop(control, conversations)
        with ThreadPoolExecutor(max_workers=4) as pool:
            goals = list(pool.map(lambda _: api.set(owner, session, run_id=run,
                objective="One objective", operator_approved=True), range(8)))
        assert len({goal["goal_id"] for goal in goals}) == 1
        control.authorization.grant(owner, principal_type="agent", principal_id="goal-agent",
            capability="goal:iterate", scope_type="goal", scope_id=goals[0]["goal_id"])
        api.open(owner, session, principal_id="goal-agent", operator_approved=True)
        original = control.create_work_item
        created = []
        def crash_after_creation(*args, **kwargs):
            created.append(original(*args, **kwargs)["work_item_id"])
            raise SystemExit("crash before step binding")
        monkeypatch.setattr(control, "create_work_item", crash_after_creation)
        with pytest.raises(SystemExit):
            api.advance(owner, session, objective="Durable step", operator_approved=True)
        monkeypatch.setattr(control, "create_work_item", original)
        restored = ConversationGoalLoop(control, conversations)
        step = restored.advance(owner, session, objective="Durable step", operator_approved=True)
        assert step["work_item_id"] == created[0]
        assert len(control.list_work_items(owner, run_id=run)["items"]) == 1
        assert restored.loop_status(owner, session)["loop"]["remaining_steps"] == 1
    finally:
        c.close(); d.close()


def test_loop_pins_original_grant_and_paused_goal_cannot_advance(tmp_path):
    d, c, control, conversations, session, owner, run = setup(tmp_path)
    try:
        api = ConversationGoalLoop(control, conversations)
        goal = api.set(owner, session, run_id=run, objective="Pinned grant goal", operator_approved=True)
        grant_args = dict(principal_type="agent", principal_id="goal-agent", capability="goal:iterate",
                          scope_type="goal", scope_id=goal["goal_id"])
        grant = control.authorization.grant(owner, **grant_args)
        api.open(owner, session, principal_id="goal-agent", operator_approved=True)
        assert api.loop_status(owner, session)["loop"]["grant_id"] == grant["grant_id"]
        control.update_goal(goal["goal_id"], owner, state="PAUSED", reason="host pause")
        with pytest.raises(GoalLoopConflict, match="not active"):
            api.advance(owner, session, objective="blocked pause", operator_approved=True)
        control.update_goal(goal["goal_id"], owner, state="ACTIVE", reason="host resume")
        control.authorization.revoke(grant["grant_id"], owner)
        control.authorization.grant(owner, **grant_args)
        with pytest.raises(PermissionError, match="revoked or replaced"):
            api.advance(owner, session, objective="blocked replacement", operator_approved=True)
        assert api.open(owner, session, principal_id="goal-agent", operator_approved=True)["state"] == "BLOCKED"
        assert len(control.list_work_items(owner, run_id=run)["items"]) == 0
    finally:
        c.close(); d.close()
