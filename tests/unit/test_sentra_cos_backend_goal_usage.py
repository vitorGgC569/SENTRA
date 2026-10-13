"""Actual provider ledger scopes use the same durable conversation Goal authority."""
import pytest

from sentra_core.conversations import ConversationStore
from sentra_core.provider_usage import UsageLedger
from sentra_executors.goal_loop import ConversationGoalLoop
from sentra_mcp.services.budget_policy import BudgetExceeded
from test_governance_coordination import _services


def setup(tmp_path):
    durable, bus, control = _services(tmp_path)
    store = ConversationStore(tmp_path / ".sentra", principal="usage-sid")
    session = store.open(tmp_path)
    owner = "cli:" + store.principal
    run = durable.create_run(owner, workspace=str(tmp_path))["run_id"]
    goals = ConversationGoalLoop(control, store)
    goal = goals.set(owner, session, run_id=run, objective="PRIVATE_USAGE_GOAL", operator_approved=True)
    return durable, bus, control, store, session, owner, run, goals, goal


def test_goal_scoped_reported_usage_and_hard_stop_survive_restart(tmp_path):
    durable, bus, control, store, session, owner, run, goals, goal = setup(tmp_path)
    try:
        ledger = UsageLedger(store)
        scope = ledger.context(session, tmp_path)
        assert scope == {"owner": owner, "workspace": str(tmp_path), "run_id": run, "goal_id": goal["goal_id"]}
        policy = ledger.budgets.set_policy(owner, scope_type="goal", scope_id=goal["goal_id"],
                                          limits={"total_tokens": 12})
        assert ledger.require(session, tmp_path, "gateway")["allowed"]
        turn, _ = store.begin_turn(session, "private provider input")
        store.provider_state(session, turn, "gateway", "reported-one", "submitted", context=scope)
        store.record_provider_usage(session, turn, "gateway", "reported-one", "requested-model",
                                    {"input_tokens": 10, "output_tokens": 2}, scope)
        # Crash before projecting the already persisted usage outbox.
        restarted = ConversationStore(tmp_path / ".sentra", principal=store.principal)
        restored = UsageLedger(restarted)
        with pytest.raises(BudgetExceeded, match="goal:"):
            restored.require(session, tmp_path, "gateway")
        summary = restored.governance.cost_summary(owner, goal_id=goal["goal_id"], run_id=run)
        assert summary["total_tokens"] == 12 and summary["count"] == 1
        assert restored.flush() == 0
        other = restarted.open(tmp_path)
        assert restored.require(other, tmp_path, "gateway")["allowed"]
        assert len(durable.list_runs(owner)["items"]) == 1
        assert control.authorization.list_grants(owner)["items"] == []
        assert policy["scope_id"] == goal["goal_id"]
    finally:
        bus.close(); durable.close()


def test_goal_scope_ignores_inactive_and_foreign_session_owner(tmp_path):
    durable, bus, control, store, session, owner, run, goals, goal = setup(tmp_path)
    try:
        ledger = UsageLedger(store)
        control.update_goal(goal["goal_id"], owner, state="PAUSED", reason="host pause")
        assert "goal_id" not in ledger.context(session, tmp_path)
        control.update_goal(goal["goal_id"], owner, state="ACTIVE", reason="host resume")
        with pytest.raises(PermissionError):
            ledger.context(session, tmp_path / "other-workspace")
        foreign = ConversationStore(tmp_path / ".sentra", principal="foreign-sid")
        with pytest.raises(PermissionError):
            UsageLedger(foreign).context(session, tmp_path)
        # A valid but different owner row must not shadow the exact CLI binding.
        with control.store.connect("execution_workspace") as db:
            db.execute("INSERT INTO conversation_goal_bindings SELECT ?,conversation_id,run_id,goal_id,"
                       "revision,protected_objective,loop_id,updated FROM conversation_goal_bindings WHERE owner=?",
                       ("canvas:" + store.principal, owner))
        assert ledger.context(session, tmp_path)["goal_id"] == goal["goal_id"]
        goals.stop(owner, session, operator_approved=True)
        assert "goal_id" not in ledger.context(session, tmp_path)
    finally:
        bus.close(); durable.close()


def test_corrupt_central_goal_binding_cannot_bypass_budget_scope(tmp_path):
    durable, bus, control, store, session, owner, run, goals, goal = setup(tmp_path)
    try:
        wrong = durable.create_run(owner, workspace=str(tmp_path / "foreign"))["run_id"]
        with control.store.connect("execution_workspace") as db:
            db.execute("UPDATE conversation_goal_bindings SET run_id=? WHERE owner=?", (wrong, owner))
        with pytest.raises(PermissionError, match="central owner/Run/workspace"):
            UsageLedger(store).context(session, tmp_path)
    finally:
        bus.close(); durable.close()


def test_goal_hard_budget_blocks_unknown_report_without_blocking_other_session(tmp_path):
    durable, bus, control, store, session, owner, run, goals, goal = setup(tmp_path)
    try:
        ledger = UsageLedger(store)
        scope = ledger.context(session, tmp_path)
        turn, _ = store.begin_turn(session, "unreported provider call")
        store.provider_state(session, turn, "gateway", "unknown-one", "submitted", context=scope)
        store.provider_state(session, turn, "gateway", "unknown-one", "completed")
        ledger.budgets.set_policy(owner, scope_type="goal", scope_id=goal["goal_id"],
                                 limits={"total_tokens": 100})
        with pytest.raises(PermissionError, match="incomplete"):
            UsageLedger(ConversationStore(tmp_path / ".sentra", principal=store.principal)).require(
                session, tmp_path, "gateway")
        other = store.open(tmp_path)
        assert ledger.require(other, tmp_path, "gateway")["allowed"]
    finally:
        bus.close(); durable.close()


def test_canvas_task_authority_is_never_replaced_by_another_goal_run(tmp_path):
    from sentra_canvas.store import Store

    durable, bus, control = _services(tmp_path)
    state = tmp_path / ".sentra"
    projects = tmp_path / "projects"
    projects.mkdir()
    canvas = Store(state / "canvas" / "canvas.sqlite3", projects, principal="usage-sid")
    try:
        workspace = canvas.create_workspace("goal_usage")
        agents = [canvas.create_agent(workspace["id"], name, "sentra/codex/current", "worker")
                  for name in ("coordinator", "worker")]
        team = canvas.create_team(workspace["id"], "team", agents[0]["id"], [agents[1]["id"]])
        task, _ = canvas.create_task(workspace["id"], team["id"], agents[1]["id"], "sentra-cli",
                                     "private", "goal-scope", approved=True)
        store = ConversationStore(state, principal="usage-sid")
        session = store.open(workspace["path"], session_id="task_" + task["id"])
        owner = "canvas:" + store.principal
        durable.create_run(owner, workspace=workspace["path"], run_id=task["run_id"])
        goals = ConversationGoalLoop(control, store)
        goal = goals.set(owner, session, run_id=task["run_id"], objective="task Run goal", operator_approved=True)
        assert UsageLedger(store).context(session, workspace["path"])["goal_id"] == goal["goal_id"]
        other = durable.create_run(owner, workspace=workspace["path"])["run_id"]
        foreign_goal = control.create_goal(other, owner, objective="foreign Run goal")
        with control.store.connect("execution_workspace") as db:
            db.execute("UPDATE conversation_goal_bindings SET run_id=?,goal_id=? WHERE owner=? AND conversation_id=?",
                       (other, foreign_goal["goal_id"], owner, session))
        context = UsageLedger(store).context(session, workspace["path"])
        assert context["run_id"] == task["run_id"]
        assert context["work_item_id"] == task["work_item_id"]
        assert context["agent_id"] == task["agent_id"]
        assert "goal_id" not in context
        assert len(durable.list_runs(owner)["items"]) == 2
        assert control.authorization.list_grants(owner)["items"] == []
    finally:
        canvas.close(); bus.close(); durable.close()


def test_real_cli_goal_budget_blocks_second_provider_submission(tmp_path, monkeypatch):
    from sentra_cli.agent import SentraAgent
    from sentra_cli.config import CLIConfig

    durable, bus, control = _services(tmp_path)
    try:
        agent = SentraAgent(CLIConfig(workspace=tmp_path, state_root=tmp_path / ".sentra",
                                      model="sentra/codex/current", auto_start_gateway=False))
        owner = "cli:" + agent.store.principal
        run = durable.create_run(owner, workspace=str(tmp_path))["run_id"]
        goal = ConversationGoalLoop(control, agent.store).set(owner, agent.session_id, run_id=run,
            objective="PRIVATE_CLI_GOAL_USAGE", operator_approved=True)
        ledger = agent._ledger()
        ledger.budgets.set_policy(owner, scope_type="goal", scope_id=goal["goal_id"],
                                 limits={"input_tokens": 10})
        submissions = []

        def native(config, messages, model, delivery, *, usage_callback=None, checkpoint=None):
            if checkpoint is not None:
                checkpoint()
            assert any("PRIVATE_CLI_GOAL_USAGE" in message["content"] for message in messages)
            ident = "cli-goal-reported-" + str(len(submissions))
            delivery("codex-cli", ident, "submitted")
            submissions.append(ident)
            usage_callback("codex-cli", ident, model, {"input_tokens": 10, "output_tokens": 2})
            delivery("codex-cli", ident, "completed")
            return "fixture observed answer"

        monkeypatch.setattr("sentra_cli.codex_native.generate", native)
        assert "fixture observed answer" in "".join(agent.step_stream("first"))
        assert "blocked before submission" in "".join(agent.step_stream("second"))
        assert len(submissions) == 1
        assert ledger.governance.cost_summary(owner, goal_id=goal["goal_id"], run_id=run)["input_tokens"] == 10
        assert not agent.store.status(agent.session_id)["uncertain_calls"]
        assert len(durable.list_runs(owner)["items"]) == 1
        assert control.authorization.list_grants(owner)["items"] == []
    finally:
        bus.close(); durable.close()


def web_binding(control, store, session, owner, *, run=None):
    run = run or control.durable.create_run(owner, workspace=store.status(session)["workspace"])["run_id"]
    if control.durable.run_status(run, owner)["state"] == "CREATED":
        control.durable.transition_run(run, owner, "RUNNING")
    agent = "usage-web-agent-" + run
    control.ensure_agent(run, owner, agent_id=agent, role="worker")
    work = control.create_work_item(run, owner, objective="host-approved web fixture", assignee_agent_id=agent)
    grant = control.authorization.grant(owner, principal_type="agent", principal_id=agent,
        capability="web:send", scope_type="work_item", scope_id=work["work_item_id"])
    with control.store.connect("session_checkpoint") as db:
        db.execute("CREATE TABLE IF NOT EXISTS gateway_web_transport_mode(singleton INTEGER PRIMARY KEY,mode TEXT,revision INTEGER)")
        db.execute("INSERT INTO gateway_web_transport_mode VALUES(1,'durable_v2',1) ON CONFLICT(singleton) DO UPDATE SET mode='durable_v2'")
        db.execute("CREATE TABLE IF NOT EXISTS gateway_web_bindings(conversation_uri TEXT PRIMARY KEY,owner TEXT,run_id TEXT,work_item_id TEXT,principal_id TEXT,grant_id TEXT)")
        db.execute("INSERT OR REPLACE INTO gateway_web_bindings VALUES(?,?,?,?,?,?)",
            ("conversation://sentra-cli/" + session, owner, run, work["work_item_id"], agent, grant["grant_id"]))
    return {"run_id": run, "work_item_id": work["work_item_id"], "agent_id": agent}


def test_web_bound_usage_applies_work_run_and_agent_budgets_before_submission(tmp_path):
    durable, bus, control = _services(tmp_path)
    try:
        store = ConversationStore(tmp_path / ".sentra", principal="usage-sid")
        session = store.open(tmp_path)
        owner = "cli:" + store.principal
        scopes = web_binding(control, store, session, owner)
        ledger = UsageLedger(store)
        approved = ledger.context(session, tmp_path)
        assert approved == {"owner": owner, "workspace": str(tmp_path), **scopes}
        policies = [ledger.budgets.set_policy(owner, scope_type=scope, scope_id=scopes[field],
                    limits={"input_tokens": 10}) for scope, field in
                    (("run", "run_id"), ("work_item", "work_item_id"), ("agent", "agent_id"))]
        assert len(ledger.require(session, tmp_path, "gateway", authority_context=approved)["evaluations"]) == 3
        turn, _ = store.begin_turn(session, "bound usage")
        store.provider_state(session, turn, "gateway", "bound-reported", "submitted", context=approved)
        store.record_provider_usage(session, turn, "gateway", "bound-reported", "fixture-model",
                                    {"input_tokens": 10, "output_tokens": 2}, approved)
        with pytest.raises(BudgetExceeded):
            ledger.require(session, tmp_path, "gateway", authority_context=approved)
        assert all(ledger.governance.cost_summary(owner, **{field: scopes[field]})["input_tokens"] == 10
                   for field in scopes)
        assert len(durable.list_runs(owner)["items"]) == 1
        assert len(control.authorization.list_grants(owner)["items"]) == 1
    finally:
        bus.close(); durable.close()


def test_web_binding_cannot_replace_active_goal_run_or_captured_authority(tmp_path):
    durable, bus, control, store, session, owner, run, goals, goal = setup(tmp_path)
    try:
        ledger = UsageLedger(store)
        approved = ledger.context(session, tmp_path)
        pinned = web_binding(control, store, session, owner)  # Different existing Run.
        with pytest.raises(PermissionError, match="conflicts"):
            ledger.require(session, tmp_path, "gateway", authority_context=approved)
        other = store.open(tmp_path)
        original = web_binding(control, store, other, owner, run=pinned["run_id"])
        before = ledger.context(other, tmp_path)
        replacement = web_binding(control, store, other, owner)
        assert replacement["run_id"] != original["run_id"]
        with pytest.raises(PermissionError, match="changed before budget"):
            ledger.require(other, tmp_path, "gateway", authority_context=before)
        current = ledger.context(other, tmp_path)
        assert ledger.require(other, tmp_path, "gateway", authority_context=current)["allowed"]
        assert current == ledger.context(other, tmp_path)  # require did not mutate host snapshot.
    finally:
        bus.close(); durable.close()


@pytest.mark.parametrize("mutation", ["workspace", "assignee", "work_run", "run_state", "owner"])
def test_web_binding_requires_exact_live_central_authority(tmp_path, mutation):
    durable, bus, control = _services(tmp_path)
    try:
        store = ConversationStore(tmp_path / ".sentra", principal="usage-sid")
        session = store.open(tmp_path)
        owner = "cli:" + store.principal
        scopes = web_binding(control, store, session, owner)
        if mutation in {"workspace", "owner"}:
            with durable.lock, durable.db:
                durable.db.execute("UPDATE runs SET " + mutation + "=? WHERE run_id=?",
                    (str(tmp_path / "foreign") if mutation == "workspace" else "cli:foreign", scopes["run_id"]))
        elif mutation == "run_state":
            durable.transition_run(scopes["run_id"], owner, "PAUSED")
        else:
            with control.store.connect("governance") as db:
                db.execute("UPDATE work_items SET " + ("assignee_agent_id" if mutation == "assignee" else "run_id") +
                           "=? WHERE work_item_id=?", ("foreign-existing-authority", scopes["work_item_id"]))
        with pytest.raises(PermissionError, match="active Run/workspace/WorkItem/assignee"):
            UsageLedger(store).context(session, tmp_path)
    finally:
        bus.close(); durable.close()


def test_web_usage_binding_is_ignored_in_legacy_and_other_owner_session(tmp_path):
    durable, bus, control = _services(tmp_path)
    try:
        store = ConversationStore(tmp_path / ".sentra", principal="usage-sid")
        session = store.open(tmp_path)
        owner = "cli:" + store.principal
        web_binding(control, store, session, owner)
        ledger = UsageLedger(store)
        with control.store.connect("session_checkpoint") as db:
            db.execute("UPDATE gateway_web_transport_mode SET mode='legacy'")
        assert ledger.context(session, tmp_path) == {"owner": owner, "workspace": str(tmp_path)}
        with control.store.connect("session_checkpoint") as db:
            db.execute("UPDATE gateway_web_transport_mode SET mode='durable_v2'")
            db.execute("UPDATE gateway_web_bindings SET owner='cli:foreign'")
        assert ledger.context(session, tmp_path) == {"owner": owner, "workspace": str(tmp_path)}
    finally:
        bus.close(); durable.close()


def test_real_cli_never_replaces_original_web_grant_after_scope_enrichment(tmp_path):
    from sentra_cli.agent import SentraAgent
    from sentra_cli.config import CLIConfig

    durable, bus, control = _services(tmp_path)
    try:
        agent = SentraAgent(CLIConfig(workspace=tmp_path, state_root=tmp_path / ".sentra",
            model="sentra/chatgpt-web/high", auto_start_gateway=False))
        owner = "cli:" + agent.store.principal
        scopes = web_binding(control, agent.store, agent.session_id, owner)
        with control.store.connect("session_checkpoint") as db:
            original = db.execute("SELECT grant_id FROM gateway_web_bindings").fetchone()[0]
        control.authorization.revoke(original, owner)
        control.authorization.grant(owner, principal_type="agent", principal_id=scopes["agent_id"],
            capability="web:send", scope_type="work_item", scope_id=scopes["work_item_id"])
        calls = []
        agent.client._gateway_admin_post = lambda *args, **kwargs: (calls.append(kwargs) or True, "")
        captured = agent._ledger().context(agent.session_id, tmp_path)
        with pytest.raises(PermissionError, match="original|pinned|grant"):
            agent._bind_existing_web_authority(authority_context=captured)
        assert calls == []
    finally:
        bus.close(); durable.close()


def test_real_cli_delivery_and_usage_keep_same_approved_goal_during_change(tmp_path, monkeypatch):
    from sentra_cli.agent import SentraAgent
    from sentra_cli.config import CLIConfig

    durable, bus, control = _services(tmp_path)
    try:
        agent = SentraAgent(CLIConfig(workspace=tmp_path, state_root=tmp_path / ".sentra",
            model="sentra/codex/current", auto_start_gateway=False))
        owner = "cli:" + agent.store.principal
        run = durable.create_run(owner, workspace=str(tmp_path))["run_id"]
        goal = ConversationGoalLoop(control, agent.store).set(owner, agent.session_id, run_id=run,
            objective="keep approved accounting scope", operator_approved=True)
        def native(config, messages, model, delivery, *, usage_callback=None, checkpoint=None):
            if checkpoint is not None:
                checkpoint()
            # Consumption already submitted keeps its original accounting scope.
            delivery("codex-cli", "scope-race-one", "submitted")
            control.update_goal(goal["goal_id"], owner, state="PAUSED", reason="owner paused after physical submission")
            usage_callback("codex-cli", "scope-race-one", model, {"input_tokens": 10, "output_tokens": 2})
            delivery("codex-cli", "scope-race-one", "completed")
            return "observed fixture answer"

        monkeypatch.setattr("sentra_cli.codex_native.generate", native)
        assert "observed fixture answer" in "".join(agent.step_stream("fixture scope change"))
        summary = agent._ledger().governance.cost_summary(owner, goal_id=goal["goal_id"], run_id=run)
        assert summary["input_tokens"] == 10 and summary["count"] == 1
    finally:
        bus.close(); durable.close()
