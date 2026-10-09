"""Acceptance prepared for final validation; no provider success is simulated."""
import json
from dataclasses import asdict

import pytest

from sentra_core.context import RollingContextCondenser, ContextBudgetExceeded, SummaryCompletion, LedgerSummaryRunner
from sentra_core.conversations import ConversationStore
from sentra_cli.agent import SentraAgent


def messages(count=20):
    return [{"seq":i,"id":f"message-{i}","role":"user" if i%2 else "assistant",
             "content":f"protected original {i}: "+"x"*570} for i in range(1,count+1)]


def test_rolling_projection_preserves_system_initial_latest_and_digest_chain():
    rows=messages()
    condenser=RollingContextCondenser(max_chars=4096,summary_chars=600,keep_first=2,keep_recent=2)
    first=condenser.project(rows,system_prompt="SYSTEM MUST REMAIN")
    assert first.messages[0]["content"]=="SYSTEM MUST REMAIN"
    assert [m["id"] for m in first.messages if "id" in m][:2]==["message-1","message-2"]
    assert first.messages[-1]["id"]=="message-20"
    assert first.summary.origin=="extractive-offline"
    assert rows==messages()  # originals are not modified by projection.
    later=condenser.project(messages(30),system_prompt="SYSTEM MUST REMAIN",previous=first.summary)
    assert later.summary.previous_digest==first.summary.sha256
    assert later.summary.source_digest!=first.summary.source_digest
    assert all(m["role"]!="system" for m in later.messages if "CONTEXT SUMMARY" in m["content"])


def test_pinned_oversize_and_latest_message_not_silently_truncated():
    condenser=RollingContextCondenser(max_chars=4096,summary_chars=600)
    with pytest.raises(ContextBudgetExceeded):
        condenser.project(messages(1),system_prompt="s"*5000)
    rows=messages(3)
    rows[-1]["content"]="latest user instruction "*2000
    with pytest.raises(ContextBudgetExceeded):
        condenser.project(rows,system_prompt="system")


def test_uncertain_native_operation_receipt_remains_exact_in_condensed_context():
    rows=messages(25)
    rows[4]["content"]='{"machine_operation_receipts":[{"operation_id":"op-keep","state":"UNCERTAIN"}]}'
    condenser=RollingContextCondenser(max_chars=4096,summary_chars=600,keep_first=2,keep_recent=2)
    projected=condenser.project(rows,system_prompt="system")
    assert any(m.get("id")=="message-5" and m["content"]==rows[4]["content"] for m in projected.messages)


def test_summary_cache_retains_original_protected_transcript(tmp_path):
    store=ConversationStore(tmp_path,principal="context-owner")
    ident=store.open(tmp_path)
    for row in messages(): store.append(ident,row["role"],row["content"])
    before=store.messages(ident)
    condenser=RollingContextCondenser(max_chars=4096,summary_chars=600,keep_first=2,keep_recent=2)
    first=store.context_window(ident,system_prompt="system",condenser=condenser)
    second=store.context_window(ident,system_prompt="system",condenser=condenser)
    assert first.summary.sha256==second.summary.sha256
    assert store.messages(ident)==before
    with store._connect() as db:
        rows=db.execute("SELECT protected_summary FROM context_summaries").fetchall()
        assert len(rows)==1 and rows[0][0].startswith(("dpapi:","keyring:"))
    assert b"protected original" not in store.path.read_bytes()


def test_accounted_summary_callback_uses_existing_call_and_usage_ledger(tmp_path):
    store=ConversationStore(tmp_path,principal="summary-owner")
    ident=store.open(tmp_path)
    turn,_=store.begin_turn(ident,"summarize")
    log=[]
    class BudgetDouble:
        def require(self,*args,**kwargs): log.append(("budget",kwargs))
    class LedgerDouble:
        budgets=BudgetDouble()
        def require(self,*args): log.append(("require",args))
        def context(self,*args): return {"owner":"cli:summary-owner","workspace":str(tmp_path)}
        def flush(self,**kwargs): log.append(("usage-flush",kwargs))
    def explicit_provider_double(req):
        # This test validates accounting order, not a real LLM completion.
        assert log[0][0]=="require" and log[1][0]=="budget"
        return SummaryCompletion("unit callback text",{"input_tokens":100,"output_tokens":5})
    runner=LedgerSummaryRunner(store=store,ledger=LedgerDouble(),session_id=ident,workspace=tmp_path,
        turn_id=lambda:turn,provider="test-provider",model="test-model",complete=explicit_provider_double)
    assert runner(messages(2),"previous","a"*64,600)=="unit callback text"
    with store._connect() as db:
        assert db.execute("SELECT state FROM calls WHERE kind='provider'").fetchone()[0]=="completed"
        assert db.execute("SELECT COUNT(*) FROM provider_usage").fetchone()[0]==1
    assert len(store.messages(ident))==1  # summary call did not insert an assistant response.


def test_summary_failure_is_uncertain_without_retry(tmp_path):
    store=ConversationStore(tmp_path,principal="summary-owner")
    ident=store.open(tmp_path)
    turn,_=store.begin_turn(ident,"summarize")
    class BudgetDouble:
        def require(self,*args,**kwargs): pass
    class LedgerDouble:
        budgets=BudgetDouble()
        def require(self,*args): pass
        def context(self,*args): return {"owner":"cli:summary-owner","workspace":str(tmp_path)}
    called=[]
    def fail(req):
        called.append(req.call_id)
        raise TimeoutError("unit provider timeout")
    runner=LedgerSummaryRunner(store=store,ledger=LedgerDouble(),session_id=ident,workspace=tmp_path,
        turn_id=lambda:turn,provider="provider",model="model",complete=fail)
    with pytest.raises(TimeoutError): runner(messages(2),"","a"*64,600)
    assert len(called)==1 and store.status(ident)["uncertain_calls"]


def test_native_machine_receipt_preserves_identity_before_large_evidence():
    result=json.dumps({"operation":{"operation_id":"op-fixed","state":"UNCERTAIN","evidence":{"text":"x"*30000}}})
    retained=SentraAgent._machine_receipt(result)
    assert "op-fixed" in retained[:600]
    assert "SAME operation_id" in retained[:600]
    parsed=json.loads(retained)
    assert parsed["operation"]["operation_id"]=="op-fixed"


def test_cli_default_history_uses_context_projection_without_extra_provider(tmp_path):
    from types import SimpleNamespace
    from sentra_cli.agent import SYSTEM_PROMPT
    store=ConversationStore(tmp_path,principal="cli-context-owner")
    ident=store.open(tmp_path)
    for row in messages(70): store.append(ident,row["role"],row["content"])
    agent=SentraAgent.__new__(SentraAgent)
    agent.store,agent.session_id=store,ident
    agent.canvas=SimpleNamespace(is_available=False)
    agent._turn_id,agent._context_summary_config=None,None
    agent.context_condenser=RollingContextCondenser(max_chars=20000,summary_chars=1000,keep_recent=4)
    history=agent._history()
    assert history[0]["content"]==SYSTEM_PROMPT
    assert agent.context_projection.summary.origin=="extractive-offline"
    assert history[1]["content"].startswith("protected original 1")
    assert len(store.messages(ident))==70
