import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from sentra_core.conversations import ConversationStore
from sentra_core.provider_usage import UsageLedger,normalize_usage
from sentra_cli.agent import SentraAgent
from sentra_cli.config import CLIConfig
from sentra_mcp.services.governance import GovernanceConflict

pytestmark=pytest.mark.skipif(os.name!="nt",reason="actual DPAPI conversation storage")


def recorded(tmp_path,*,principal=None):
    store=ConversationStore(tmp_path/"state",principal=principal)
    sid=store.open(tmp_path)
    turn,_=store.begin_turn(sid,"PRIVATE_USAGE_PROMPT")
    store.provider_state(sid,turn,"codex-cli","fixture-provider-call","submitted")
    ledger=UsageLedger(store)
    context=ledger.context(sid,tmp_path)
    usage={"input_tokens":21,"output_tokens":8,"cached_input_tokens":10,"reasoning_tokens":4}
    store.record_provider_usage(sid,turn,"codex-cli","fixture-provider-call","sentra/codex/current",usage,context)
    return store,sid,turn,ledger,context,usage


def test_usage_crash_after_ledger_commit_replays_ack_without_double_charge(tmp_path,monkeypatch):
    store,sid,turn,ledger,context,usage=recorded(tmp_path)
    original=store.acknowledge_usage
    monkeypatch.setattr(store,"acknowledge_usage",lambda _:(_ for _ in ()).throw(sqlite3.OperationalError("lost ack")))
    with pytest.raises(sqlite3.OperationalError):ledger.flush()
    assert len(store.pending_usage(ident=sid))==1
    restarted=ConversationStore(tmp_path/"state")
    restored=UsageLedger(restarted)
    assert restored.flush()==1 and restarted.pending_usage()==[]
    summary=restored.governance.cost_summary(context["owner"])
    assert summary["count"]==1 and summary["input_tokens"]==21
    assert summary["output_tokens"]==8 and summary["reasoning_tokens"]==4 and summary["total_tokens"]==29
    policy=restored.budgets.set_policy(context["owner"],scope_type="instance",limits={"total_tokens":29})
    assert restored.budgets.check(context["owner"])["allowed"]
    assert not restored.budgets.check(context["owner"],proposed={"output_tokens":1})["allowed"]
    restored.budgets.set_policy(context["owner"],scope_type="instance",limits={"reasoning_tokens":4})
    assert not restored.budgets.check(context["owner"],proposed={"reasoning_tokens":1})["allowed"]
    # A completed projection stays acknowledged after a duplicate producer event.
    monkeypatch.setattr(store,"acknowledge_usage",original)
    store.record_provider_usage(sid,turn,"codex-cli","fixture-provider-call","sentra/codex/current",usage,context)
    assert store.pending_usage()==[]
    assert "PRIVATE_USAGE_PROMPT" not in json.dumps(summary)
    metrics=store.telemetry.query(action="provider.usage.reported")["items"][0]["details"]["usage"]
    assert metrics==usage
    visible=store.usage_summary(sid)
    assert visible["fully_reported"] and visible["total_tokens"]==29
    assert visible["cached_input_tokens"]==10 and visible["projection_pending"]==0


def test_usage_identity_and_owner_collisions_are_rejected(tmp_path):
    store,sid,turn,ledger,context,usage=recorded(tmp_path,principal="alice")
    with pytest.raises(ValueError,match="collision"):
        store.record_provider_usage(sid,turn,"codex-cli","fixture-provider-call","sentra/codex/current",{**usage,"input_tokens":22},context)
    with pytest.raises(PermissionError):
        store.record_provider_usage(sid,turn,"codex-cli","fixture-provider-call","sentra/codex/current",usage,{**context,"owner":"canvas:bob"})
    bob=ConversationStore(tmp_path/"state",principal="bob")
    assert bob.pending_usage()==[]
    with pytest.raises(PermissionError):bob.pending_usage(ident=sid)
    ledger.flush()
    with store._connect() as db:call_id=db.execute("SELECT call_id FROM provider_usage").fetchone()[0]
    with pytest.raises(GovernanceConflict,match="collision"):
        ledger.governance.record_cost(context["owner"],cost_event_id="provider-usage-"+call_id,input_tokens=999)


def test_native_usage_blocks_followup_before_any_new_submission(tmp_path,monkeypatch):
    agent=SentraAgent(CLIConfig(workspace=tmp_path,state_root=tmp_path/"state",model="sentra/codex/current",auto_start_gateway=False))
    ledger=agent._ledger();owner="cli:"+agent.store.principal
    ledger.budgets.set_policy(owner,scope_type="instance",limits={"input_tokens":70})
    calls=[]
    def native(config,messages,model,delivery,*,usage_callback=None):
        ident="fixture-native-"+str(len(calls))
        delivery("codex-cli",ident,"submitted")
        calls.append(ident)
        usage_callback("codex-cli",ident,model,{"input_tokens":70,"output_tokens":12})
        delivery("codex-cli",ident,"completed")
        return "completed response"
    monkeypatch.setattr("sentra_cli.codex_native.generate",native)
    assert "completed response" in "".join(agent.step_stream("first"))
    assert "blocked before submission" in "".join(agent.step_stream("second"))
    assert len(calls)==1
    status=agent.store.status(agent.session_id)
    assert not status["uncertain_calls"] and status["state"]=="provider_error"
    assert ledger.governance.cost_summary(owner)["input_tokens"]==70


def test_api_usage_normalization_ignores_unrelated_or_private_fields():
    assert normalize_usage({"prompt_tokens":10,"completion_tokens":5,
        "prompt_tokens_details":{"cached_tokens":7},"completion_tokens_details":{"reasoning_tokens":3},
        "api_key":"excluded"})=={"input_tokens":10,"output_tokens":5,"cached_input_tokens":7,"reasoning_tokens":3}
    assert normalize_usage(None)=={}


def test_missing_report_stays_unknown_instead_of_zero_inference(tmp_path):
    store=ConversationStore(tmp_path/"state")
    sid=store.open(tmp_path)
    turn,_=store.begin_turn(sid,"unknown provider usage")
    store.provider_state(sid,turn,"gateway","fixture-missing","submitted")
    store.provider_state(sid,turn,"gateway","fixture-missing","completed")
    assert store.usage_summary(sid)["unreported_calls"]==1
    assert store.usage_summary(sid)["fully_reported"] is False
    assert store.usage_summary(sid)["pricing_known"] is False


def test_hard_budget_rejects_unknown_consumption_in_another_conversation(tmp_path):
    store=ConversationStore(tmp_path/"state")
    ledger=UsageLedger(store)
    sid=store.open(tmp_path)
    turn,_=store.begin_turn(sid,"missing consumption")
    context=ledger.context(sid,tmp_path)
    store.provider_state(sid,turn,"gateway","fixture-unreported","submitted",context=context)
    store.provider_state(sid,turn,"gateway","fixture-unreported","completed")
    policy=ledger.budgets.set_policy(context["owner"],scope_type="workspace",scope_id=str(tmp_path),limits={"total_tokens":100})
    other=store.open(tmp_path)
    with pytest.raises(PermissionError,match="incomplete"):
        ledger.require(other,tmp_path,"gateway")
    ledger.budgets.set_enabled(policy["budget_policy_id"],context["owner"],enabled=False)
    assert ledger.require(other,tmp_path,"gateway")["allowed"]
    ledger.budgets.set_policy(context["owner"],scope_type="instance",limits={"actual_cost":1})
    with pytest.raises(PermissionError,match="pricing is unknown"):
        ledger.require(other,tmp_path,"gateway")


def test_fresh_conversation_schema_can_initialize_concurrently(tmp_path):
    def start(index):
        store=ConversationStore(tmp_path/"state")
        return store.open(tmp_path,session_id="parallel_"+str(index))
    with ThreadPoolExecutor(max_workers=8) as pool:
        sessions=list(pool.map(start,range(8)))
    store=ConversationStore(tmp_path/"state")
    assert {row["id"] for row in store.list(tmp_path)}==set(sessions)
    with store._connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==2
        assert db.execute("PRAGMA foreign_key_check").fetchall()==[]


def test_canvas_usage_keeps_original_task_run_after_workspace_rollover(tmp_path):
    from sentra_canvas.store import Store
    state=tmp_path/"state"
    (tmp_path/"projects").mkdir()
    (state/"canvas").mkdir(parents=True)
    canvas=Store(state/"canvas"/"canvas.sqlite3",tmp_path/"projects")
    try:
        workspace=canvas.create_workspace("usage_scope")
        agents=[canvas.create_agent(workspace["id"],name,"sentra/codex/current","worker")
                for name in ("coordinator","worker")]
        group=canvas.create_team(workspace["id"],"team",agents[0]["id"],[agents[1]["id"]])
        task,_=canvas.create_task(workspace["id"],group["id"],agents[1]["id"],"sentra-cli","private","usage",approved=True)
        store=ConversationStore(state)
        sid=store.open(workspace["path"],session_id="task_"+task["id"])
        turn,_=store.begin_turn(sid,"PRIVATE_CANVAS_USAGE")
        store.provider_state(sid,turn,"codex-cli","fixture-canvas","submitted")
        ledger=UsageLedger(store)
        context=ledger.context(sid,workspace["path"])
        assert context["owner"]=="canvas:"+store.principal
        assert context["run_id"]==task["run_id"] and context["work_item_id"]==task["work_item_id"]
        store.record_provider_usage(sid,turn,"codex-cli","fixture-canvas","sentra/codex/current",
                                     {"input_tokens":10,"output_tokens":2},context)
        fresh_run=canvas.new_run(workspace["id"])
        assert fresh_run!=task["run_id"]
        ledger.flush()
        assert ledger.governance.cost_summary(context["owner"],run_id=task["run_id"])["total_tokens"]==12
        assert ledger.governance.cost_summary(context["owner"],run_id=fresh_run)["count"]==0
    finally:canvas.close()
