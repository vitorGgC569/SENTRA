"""Reported usage projected idempotently from the conversation transaction outbox."""
import json
import re
import sqlite3
from contextlib import closing

from sentra_mcp.services.governance import GovernanceService
from sentra_mcp.services.budget_policy import BudgetPolicyService


class UsageLedger:
    def __init__(self,store):
        self.store=store
        self.governance=GovernanceService(store.telemetry_root)
        self.budgets=BudgetPolicyService(store.telemetry_root,governance=self.governance)

    def context(self,ident,workspace):
        with self.store._connect() as db:
            conversation=self.store._owned(db,ident,workspace)
        context=self._canvas_context(ident,conversation["workspace"])
        return self._web_context(ident,self._goal_context(ident,context))

    def _web_context(self,ident,context):
        path=self.governance.store.path_for("session_checkpoint")
        if not path.is_file():return context
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
            db.row_factory=sqlite3.Row
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='gateway_web_transport_mode'").fetchone()
            if not exists:return context
            mode=db.execute("SELECT mode FROM gateway_web_transport_mode WHERE singleton=1").fetchone()
            if mode is None or mode["mode"]!="durable_v2":return context
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='gateway_web_bindings'").fetchone()
            if not exists:return context
            binding=db.execute("SELECT * FROM gateway_web_bindings WHERE conversation_uri=? AND owner=?",
                ("conversation://sentra-cli/"+ident,context["owner"])).fetchone()
            if binding is None:return context
            scopes={"run_id":binding["run_id"],"work_item_id":binding["work_item_id"],
                    "agent_id":binding["principal_id"]}
            if any(context.get(key) and context[key]!=value for key,value in scopes.items()):
                raise PermissionError("Web binding conflicts with existing usage authority")
            authority=self.store.telemetry_root/"durable"/"durable.sqlite3"
            db.execute("ATTACH DATABASE ? AS authority",(authority.resolve().as_uri()+"?mode=ro",))
            db.execute("ATTACH DATABASE ? AS governance",(self.governance.path.resolve().as_uri()+"?mode=ro",))
            authority_row=db.execute("SELECT r.state,r.desired_state FROM authority.runs r "
                "JOIN authority.agents a ON a.run_id=r.run_id AND a.owner=r.owner "
                "JOIN governance.work_items w ON w.run_id=r.run_id AND w.owner=r.owner "
                "WHERE r.run_id=? AND r.owner=? AND r.workspace=? AND a.agent_id=? "
                "AND w.work_item_id=? AND w.assignee_agent_id=a.agent_id "
                "AND w.state NOT IN ('COMPLETED','FAILED','CANCELLED')",
                (binding["run_id"],context["owner"],context["workspace"],
                 binding["principal_id"],binding["work_item_id"])).fetchone()
            if authority_row is None or (authority_row["state"],authority_row["desired_state"])!=("RUNNING","RUNNING"):
                raise PermissionError("Web usage requires the same active Run/workspace/WorkItem/assignee")
            if context.get("operation_id"):
                operation=db.execute("SELECT 1 FROM authority.operations WHERE operation_id=? AND run_id=? AND owner=?",
                    (context["operation_id"],binding["run_id"],context["owner"])).fetchone()
                if operation is None:
                    raise PermissionError("Web usage Operation differs from bound Run")
        return {**context,**scopes}

    def _goal_context(self,ident,context):
        # Read existing central authority only. An absent adapter/table is the
        # normal legacy case; a storage error must not silently bypass budgets.
        path=self.governance.store.path_for("execution_workspace")
        if not path.is_file():return context
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
            db.row_factory=sqlite3.Row
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='conversation_goal_bindings'").fetchone()
            if not exists:return context
            binding=db.execute("SELECT run_id,goal_id FROM conversation_goal_bindings "
                "WHERE owner=? AND conversation_id=?",(context["owner"],ident)).fetchone()
            if binding is None:return context
            if context.get("run_id") and context["run_id"]!=binding["run_id"]:
                return context
            authority=self.store.telemetry_root/"durable"/"durable.sqlite3"
            # A persisted binding with no central Run/Goal authority is corrupt,
            # rather than permission to submit without its scoped budget.
            db.execute("ATTACH DATABASE ? AS authority",(authority.resolve().as_uri()+"?mode=ro",))
            goal=db.execute("SELECT g.state FROM authority.goals g JOIN authority.runs r "
                "ON r.run_id=g.run_id AND r.owner=g.owner WHERE g.goal_id=? "
                "AND g.run_id=? AND g.owner=? AND r.workspace=?",
                (binding["goal_id"],binding["run_id"],context["owner"],context["workspace"])).fetchone()
            if goal is None:
                raise PermissionError("conversation goal differs from central owner/Run/workspace")
            if goal["state"]!="ACTIVE":return context
        return {**context,"run_id":binding["run_id"],"goal_id":binding["goal_id"]}

    def _canvas_context(self,ident,workspace):
        context={"owner":"cli:"+self.store.principal,"workspace":str(workspace)}
        path=self.store.telemetry_root/"canvas"/"canvas.sqlite3"
        if not path.is_file():return context
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
            db.row_factory=sqlite3.Row
            if db.execute("PRAGMA user_version").fetchone()[0]<5:return context
            if re.fullmatch(r"task_[a-f0-9]{32}",ident):
                row=db.execute("SELECT t.id,t.run_id,t.agent_id FROM tasks t JOIN workspaces w "
                    "ON w.id=t.workspace_id WHERE t.id=? AND w.owner=? AND w.path=? AND t.provider='sentra-cli'",
                    (ident[5:],self.store.principal,str(workspace))).fetchone()
                if row:
                    return {**context,"owner":"canvas:"+self.store.principal,"run_id":row["run_id"],
                        "agent_id":row["agent_id"],"work_item_id":"canvas-work-"+row["id"],
                        "operation_id":"canvas-task-"+row["id"]}
            row=db.execute("SELECT a.id,w.run_id FROM agents a JOIN workspaces w ON w.id=a.workspace_id "
                "WHERE a.conversation_id=? AND w.owner=? AND w.path=?",
                (ident,self.store.principal,str(workspace))).fetchone()
            if row:
                return {**context,"owner":"canvas:"+self.store.principal,
                        "agent_id":row["id"],"run_id":row["run_id"]}
        return context

    def flush(self,*,ident=None):
        count=0
        for row in self.store.pending_usage(ident=ident):
            usage=json.loads(row["usage_json"])
            context=json.loads(row["context_json"])
            owner=context.pop("owner")
            self.governance.record_cost(owner,cost_event_id="provider-usage-"+row["call_id"],
                provider=row["provider"],model=row["model"],**context,
                input_tokens=usage.get("input_tokens",0),output_tokens=usage.get("output_tokens",0),
                # Reasoning/cached tokens are subsets of reported input/output,
                # retained as metadata rather than added to the budget twice.
                reasoning_tokens=usage.get("reasoning_tokens",0),
                metadata={"kind":"provider_usage","pricing_known":False,"reasoning_in_output":True,
                    "reported_metrics":usage,"conversation_id":row["conversation_id"]})
            self.store.acknowledge_usage(row["call_id"])
            count+=1
        return count

    def require(self,ident,workspace,provider,*,authority_context=None):
        self.flush()
        if self.store.pending_usage():raise RuntimeError("provider usage projection backlog")
        context=self.context(ident,workspace)
        # Private host snapshot only; this is a comparison, never a caller-
        # supplied substitute for resolving current central authority.
        if authority_context is not None and authority_context!=context:
            raise PermissionError("provider usage authority changed before budget check")
        owner=context.pop("owner")
        decision=self.budgets.require(owner,provider=provider,**context,
            proposed={"input_tokens":1,"output_tokens":1})
        for evaluation in decision["evaluations"]:
            if evaluation["mode"]!="hard_stop":continue
            limits=evaluation["limits"]
            if {"actual_cost","market_cost"}&limits.keys():
                raise PermissionError("provider monetary pricing is unknown; this hard budget cannot be verified")
            metrics=set(limits)&{"input_tokens","output_tokens","reasoning_tokens","total_tokens"}
            if metrics and self._missing_reports(owner,evaluation,metrics):
                raise PermissionError("provider token usage is incomplete; this hard budget cannot be verified")
        return decision

    def _missing_reports(self,owner,evaluation,metrics):
        required=set(metrics)
        if "total_tokens" in required:
            required.remove("total_tokens");required.update(("input_tokens","output_tokens"))
        where=["s.owner=?","json_extract(p.context_json,'$.owner')=?","c.state<>'rejected'",
               "("+" OR ".join("p.known_"+key.removesuffix("_tokens")+"=0" for key in sorted(required))+")"]
        values=[self.store.principal,owner]
        scope=evaluation["scope_type"]
        fields={"workspace":"workspace","goal":"goal_id","work_item":"work_item_id",
                "run":"run_id","operation":"operation_id","agent":"agent_id"}
        if scope in fields:
            where.append("json_extract(p.context_json,'$."+fields[scope]+"')=?")
            values.append(evaluation["scope_id"])
        elif scope=="provider":
            where.append("c.operation=?");values.append(evaluation["scope_id"])
        policy=self.budgets.info(evaluation["budget_policy_id"],owner)
        if policy["window_seconds"] is not None:
            where.append("c.created>=?");values.append(self.budgets.clock()-policy["window_seconds"])
        with self.store._connect() as db:
            return db.execute("SELECT 1 FROM provider_context p JOIN calls c ON c.id=p.call_id "
                "JOIN conversations s ON s.id=c.conversation_id WHERE "+
                " AND ".join(where)+" LIMIT 1",values).fetchone() is not None


def normalize_usage(raw):
    if not isinstance(raw,dict):return {}
    result={}
    for target,keys in {"input_tokens":("input_tokens","prompt_tokens"),
                        "output_tokens":("output_tokens","completion_tokens")}.items():
        for key in keys:
            if key in raw:
                result[target]=raw[key]
                break
    for target,keys,child in (
        ("cached_input_tokens",("input_tokens_details","prompt_tokens_details"),"cached_tokens"),
        ("reasoning_tokens",("output_tokens_details","completion_tokens_details"),"reasoning_tokens")):
        for key in keys:
            details=raw.get(key)
            if isinstance(details,dict) and child in details:
                result[target]=details[child]
                break
    return result
