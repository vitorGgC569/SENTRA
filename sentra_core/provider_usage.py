"""Reported usage projected idempotently from the conversation transaction outbox."""
import json
import re
import sqlite3
from contextlib import closing

from sentra_mcp.services.governance import GovernanceService
from sentra_mcp.services.budget_policy import BudgetPolicyService


class UsageLedger:
    def __init__(self,store,*,control=None):
        self.store=store
        self.governance=control.governance if control is not None else GovernanceService(store.telemetry_root)
        self.budgets=control.budgets if control is not None else BudgetPolicyService(store.telemetry_root,governance=self.governance)

    def context(self,ident,workspace):
        with self.store._connect() as db:
            conversation=self.store._owned(db,ident,workspace)
        context=self._shell_context(ident,conversation["workspace"])
        if context is None:
            capsule = getattr(self.governance.store,"provider_binding",None)
            if capsule is not None:
                if capsule["conversation_id"] != ident:
                    raise PermissionError("CLI provider conversation differs from its native capsule")
                context = {key:capsule[key] for key in ("owner","run_id","work_item_id","operation_id","agent_id")}
                context["workspace"] = conversation["workspace"]
            else:
                context=self._canvas_context(ident,conversation["workspace"])
        result = self._web_context(ident,self._goal_context(ident,context))
        binding = getattr(self.governance.store, "provider_binding", None)
        if binding is not None:
            if binding["principal"] != self.store.principal or binding["conversation_id"] != ident or any(result.get(name) != binding[name] for name in ("owner", "run_id", "work_item_id", "operation_id", "agent_id")):
                raise PermissionError("CLI provider authority capsule differs from the current bound operation")
        if self.governance.store.backend == "postgres":
            self._validate_native_context(result)
        return result

    def _validate_native_context(self, context):
        store, owner = self.governance.store, context["owner"]
        store.assert_principal(owner)
        if not all(context.get(field) for field in ("run_id","work_item_id","operation_id","agent_id")):
            raise PermissionError("hosted model submission requires a bound central execution")
        with closing(store.connect("durable")) as db:
            run = db.execute("SELECT state,desired_state,workspace FROM runs WHERE owner=? AND run_id=?",(owner,context["run_id"])).fetchone()
            actor = db.execute("SELECT run_id,desired_state FROM agents WHERE owner=? AND agent_id=?",(owner,context["agent_id"])).fetchone()
            operation = db.execute("SELECT run_id,kind,state,progress_json FROM operations WHERE owner=? AND operation_id=?",(owner,context["operation_id"])).fetchone()
        item = self.governance.work_item_info(context["work_item_id"],owner)
        capsule = getattr(store,"provider_binding",None)
        if capsule is not None and item["metadata"].get("workspace_id") != capsule["project_id"]:
            raise PermissionError("hosted CLI WorkItem moved to another project")
        if (run is None or actor is None or operation is None or run["state"] != "RUNNING" or run["desired_state"] != "RUNNING"
                or run["workspace"] != context["workspace"] or actor["run_id"] != context["run_id"] or actor["desired_state"] == "WAITING"
                or item["run_id"] != context["run_id"] or item["state"] != "RUNNING" or item["assignee_agent_id"] != context["agent_id"]
                or operation["run_id"] != context["run_id"] or operation["state"] not in {"STARTING","RUNNING","WAITING_EXTERNAL"}):
            raise PermissionError("hosted provider current authority changed")
        progress = json.loads(operation["progress_json"])
        linked = progress.get("work_item_id") == item["work_item_id"] and progress.get("principal_id") == context["agent_id"]
        legacy = (operation["kind"] == "canvas.agent_task" and progress.get("canvas_task_id") == item["metadata"].get("canvas_task_id")
            and progress.get("agent_id") == context["agent_id"] and item["metadata"].get("operation_id") == context["operation_id"])
        if not linked and not legacy:
            raise PermissionError("hosted provider Operation is not bound to its WorkItem")

    def _shell_context(self, ident, workspace):
        path = self.governance.store.path_for("shell")
        if self.governance.store.backend == "postgres":
            return self._postgres_shell_context(ident, workspace)
        if path is None or not path.is_file():
            if ident.startswith("conversation-"):
                raise PermissionError("shell conversation has no central provider binding")
            return None
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='canvas_shell_provider_bindings'").fetchone()
            if not exists:
                if ident.startswith("conversation-"):
                    raise PermissionError("shell conversation provider binding is unavailable")
                return None
            binding = db.execute("SELECT * FROM canvas_shell_provider_bindings WHERE conversation_id=?", (ident,)).fetchone()
            if binding is None:
                if ident.startswith("conversation-"):
                    raise PermissionError("shell conversation is not bound to an admitted operation")
                return None
            expected_owner = "canvas:" + self.store.principal
            if (binding["owner"] != expected_owner or binding["principal"] != self.store.principal
                    or binding["workspace"] != str(workspace)):
                raise PermissionError("shell usage principal/workspace binding mismatch")
            authority = self.store.telemetry_root / "durable" / "durable.sqlite3"
            canvas = self.store.telemetry_root / "canvas" / "canvas.sqlite3"
            db.execute("ATTACH DATABASE ? AS authority", (authority.resolve().as_uri()+"?mode=ro",))
            db.execute("ATTACH DATABASE ? AS governance", (self.governance.path.resolve().as_uri()+"?mode=ro",))
            db.execute("ATTACH DATABASE ? AS canvas", (canvas.resolve().as_uri()+"?mode=ro",))
            row = db.execute("SELECT r.state AS run_state,r.desired_state,w.state AS work_state,o.state AS operation_state,a.desired_state AS agent_desired,o.progress_json "
                "FROM authority.runs r JOIN authority.agents a ON a.run_id=r.run_id AND a.owner=r.owner "
                "JOIN governance.work_items w ON w.run_id=r.run_id AND w.owner=r.owner "
                "JOIN authority.operations o ON o.run_id=r.run_id AND o.owner=r.owner "
                "JOIN canvas.workspaces p ON p.id=? AND p.path=r.workspace "
                "WHERE r.run_id=? AND r.owner=? AND r.workspace=? AND a.agent_id=? "
                "AND w.work_item_id=? AND w.assignee_agent_id=a.agent_id AND o.operation_id=? "
                "AND p.owner=? AND p.run_id=r.run_id",
                (binding["project_id"], binding["run_id"], expected_owner, str(workspace), binding["agent_id"],
                 binding["work_item_id"], binding["operation_id"], self.store.principal)).fetchone()
            if row is None or row["run_state"] != "RUNNING" or row["desired_state"] != "RUNNING":
                raise PermissionError("shell provider requires the current project Run and assignee")
            if row["work_state"] != "RUNNING" or row["operation_state"] not in {"STARTING", "RUNNING", "WAITING_EXTERNAL"}:
                raise PermissionError("shell provider WorkItem/Operation is not executing")
            progress = json.loads(row["progress_json"])
            if row["agent_desired"] == "WAITING" or progress.get("work_item_id") != binding["work_item_id"] or progress.get("principal_id") != binding["agent_id"]:
                raise PermissionError("shell provider Operation/assignee binding is not current")
        return {"owner": expected_owner, "workspace": str(workspace), "run_id": binding["run_id"],
                "work_item_id": binding["work_item_id"], "operation_id": binding["operation_id"], "agent_id": binding["agent_id"]}

    def _postgres_shell_context(self, ident, workspace):
        store = self.governance.store
        expected_owner = "canvas:" + self.store.principal
        store.assert_principal(expected_owner)
        with closing(store.connect("shell")) as db:
            columns = db.execute("PRAGMA table_info(canvas_shell_provider_bindings)").fetchall()
            if not columns:
                if ident.startswith("conversation-"):
                    raise PermissionError("shell native provider binding unavailable")
                return None
            binding = db.execute("SELECT * FROM canvas_shell_provider_bindings WHERE conversation_id=? AND owner=?", (ident, expected_owner)).fetchone()
        if binding is None:
            if ident.startswith("conversation-"):
                raise PermissionError("shell native conversation is not admitted")
            return None
        if binding["workspace"] != str(workspace) or binding["principal"] != self.store.principal:
            raise PermissionError("native shell principal/workspace mismatch")
        with closing(store.connect("durable")) as db:
            run = db.execute("SELECT * FROM runs WHERE run_id=? AND owner=? AND workspace=?", (binding["run_id"], expected_owner, str(workspace))).fetchone()
            agent = db.execute("SELECT desired_state FROM agents WHERE agent_id=? AND run_id=? AND owner=?", (binding["agent_id"], binding["run_id"], expected_owner)).fetchone()
            operation = db.execute("SELECT * FROM operations WHERE operation_id=? AND run_id=? AND owner=?", (binding["operation_id"], binding["run_id"], expected_owner)).fetchone()
        item = self.governance.work_item_info(binding["work_item_id"], expected_owner)
        if (run is None or agent is None or operation is None or run["state"] != "RUNNING" or run["desired_state"] != "RUNNING"
                or item["run_id"] != run["run_id"] or item["state"] != "RUNNING" or item["assignee_agent_id"] != binding["agent_id"]
                or item["metadata"].get("workspace_id") != binding["project_id"]
                or operation["state"] not in {"STARTING", "RUNNING", "WAITING_EXTERNAL"}):
            raise PermissionError("native shell provider requires current Run/WorkItem/Operation/assignee")
        progress = json.loads(operation["progress_json"])
        if agent["desired_state"] == "WAITING" or progress.get("work_item_id") != binding["work_item_id"] or progress.get("principal_id") != binding["agent_id"]:
            raise PermissionError("native shell provider Operation/assignee binding is not current")
        return {"owner": expected_owner, "workspace": str(workspace), "run_id": binding["run_id"],
                "work_item_id": binding["work_item_id"], "operation_id": binding["operation_id"], "agent_id": binding["agent_id"]}

    def _postgres_web_context(self, ident, context):
        store = self.governance.store
        store.assert_principal(context["owner"])
        with closing(store.connect("session_checkpoint")) as db:
            if not db.execute("PRAGMA table_info(gateway_web_transport_mode)").fetchone():
                return context
            mode = db.execute("SELECT mode FROM gateway_web_transport_mode WHERE singleton=1").fetchone()
            if mode is None or mode["mode"] != "durable_v2" or not db.execute("PRAGMA table_info(gateway_web_bindings)").fetchone():
                return context
            binding = db.execute("SELECT * FROM gateway_web_bindings WHERE conversation_uri=? AND owner=?", ("conversation://sentra-cli/" + ident, context["owner"])).fetchone()
        if binding is None:
            return context
        scopes = {"run_id": binding["run_id"], "work_item_id": binding["work_item_id"], "agent_id": binding["principal_id"]}
        if any(context.get(key) and context[key] != value for key, value in scopes.items()):
            raise PermissionError("native Web binding conflicts with provider authority")
        with closing(store.connect("durable")) as db:
            run = db.execute("SELECT state,desired_state FROM runs WHERE run_id=? AND owner=? AND workspace=?", (binding["run_id"], context["owner"], context["workspace"])).fetchone()
            agent = db.execute("SELECT 1 FROM agents WHERE agent_id=? AND run_id=? AND owner=?", (binding["principal_id"], binding["run_id"], context["owner"])).fetchone()
            operation = True
            if context.get("operation_id"):
                operation = db.execute("SELECT 1 FROM operations WHERE operation_id=? AND run_id=? AND owner=?", (context["operation_id"], binding["run_id"], context["owner"])).fetchone()
        item = self.governance.work_item_info(binding["work_item_id"], context["owner"])
        if (run is None or agent is None or not operation or (run["state"], run["desired_state"]) != ("RUNNING", "RUNNING")
                or item["run_id"] != binding["run_id"] or item["assignee_agent_id"] != binding["principal_id"] or item["state"] in {"COMPLETED", "FAILED", "CANCELLED"}):
            raise PermissionError("native Web usage requires the same active Run/WorkItem/assignee")
        return {**context, **scopes}

    def _web_context(self,ident,context):
        path=self.governance.store.path_for("session_checkpoint")
        if path is None:
            return self._postgres_web_context(ident, context)
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
        if path is None:
            with closing(self.governance.store.connect("execution_workspace")) as db:
                if not db.execute("PRAGMA table_info(conversation_goal_bindings)").fetchone():
                    return context
                binding = db.execute("SELECT run_id,goal_id FROM conversation_goal_bindings WHERE owner=? AND conversation_id=?", (context["owner"], ident)).fetchone()
            if binding is None or context.get("run_id") and context["run_id"] != binding["run_id"]:
                return context
            with closing(self.governance.store.connect("durable")) as db:
                goal = db.execute("SELECT g.state FROM goals g JOIN runs r ON r.run_id=g.run_id AND r.owner=g.owner WHERE g.goal_id=? AND g.run_id=? AND g.owner=? AND r.workspace=?", (binding["goal_id"], binding["run_id"], context["owner"], context["workspace"])).fetchone()
            if goal is None:
                raise PermissionError("native goal differs from central Run/workspace")
            return {**context, "run_id": binding["run_id"], "goal_id": binding["goal_id"]} if goal["state"] == "ACTIVE" else context
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
        descendants = self.budgets.descendant_work_items(owner,evaluation["scope_id"]) if scope == "work_item" else None
        fields={"workspace":"workspace","goal":"goal_id","work_item":"work_item_id",
                "run":"run_id","operation":"operation_id","agent":"agent_id"}
        if scope in fields and scope != "work_item":
            where.append("json_extract(p.context_json,'$."+fields[scope]+"')=?")
            values.append(evaluation["scope_id"])
        elif scope=="provider":
            where.append("c.operation=?");values.append(evaluation["scope_id"])
        policy=self.budgets.info(evaluation["budget_policy_id"],owner)
        if policy["window_seconds"] is not None:
            where.append("c.created>=?");values.append(self.budgets.clock()-policy["window_seconds"])
        with self.store._connect() as db:
            query = ("SELECT 1 FROM provider_context p JOIN calls c ON c.id=p.call_id "
                     "JOIN conversations s ON s.id=c.conversation_id WHERE "+" AND ".join(where))
            if descendants is not None:
                for index in range(0,len(descendants),500):
                    batch = descendants[index:index+500]
                    if db.execute(query+" AND json_extract(p.context_json,'$.work_item_id') IN ("+
                            ",".join("?" for _ in batch)+") LIMIT 1",[*values,*batch]).fetchone() is not None:
                        return True
                return False
            return db.execute(query+" LIMIT 1",values).fetchone() is not None


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
