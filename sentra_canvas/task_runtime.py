"""Canvas task state projected into SENTRA's existing durable run runtime.

Canvas owns execution and commits a revisioned outbox with every task update.
The common durable registry contains metadata only and never launches/replays a
Canvas worker. Projection can be repeated after either database commit crashes.
"""
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.governance import GovernanceService, GovernanceConflict
from sentra_mcp.services.budget_policy import BudgetPolicyService
from sentra_core.conversations import ConversationStore
from sentra_core.provider_usage import UsageLedger


class TaskRuntime:
    def __init__(self,state_root,store):
        self.store=store
        self.owner="canvas:"+store.principal
        self.durable=DurableRunService(state_root)
        self.governance=GovernanceService(state_root,durable=self.durable)
        self.budgets=BudgetPolicyService(state_root,governance=self.governance)
        self.usage=UsageLedger(ConversationStore(state_root,principal=store.principal))
        from .quality import TaskValidation
        self.validation=TaskValidation(self)
        self._runs=set()

    def work_item(self,task):
        wid=task["work_item_id"]
        try:
            item=self.governance.work_item_info(wid,self.owner)
        except FileNotFoundError:
            item=self.governance.create_work_item(task["run_id"],self.owner,
                work_item_id=wid,external_key=wid,objective="Canvas task "+task["id"],
                assignee_agent_id=task["agent_id"],
                execution_policy={"require_quality_gate":True},
                metadata={"canvas_task_id":task["id"],"workspace_id":task["workspace_id"],
                          "operation_id":task["operation_id"],"content_in_protected_canvas_store":True})
        if item["run_id"]!=task["run_id"] or item["metadata"].get("canvas_task_id")!=task["id"]:
            raise RuntimeError("Canvas work item identity mismatch")
        return item

    def budget_context(self,task):
        return {"workspace":self.store.workspace(task["workspace_id"])["path"],
                "work_item_id":task["work_item_id"],"run_id":task["run_id"],
                "operation_id":task["operation_id"],"agent_id":task["agent_id"],
                "provider":task["provider"]}

    def admission(self,task,*,reserve=False):
        self.usage.flush()
        if self.usage.store.pending_usage():
            return {"allowed":False,"reason":"provider_usage_projection_backlog"}
        item=self.work_item(task)
        if task["provider"]=="sentra-cli" and not task["approved"]:
            return {"allowed":False,"reason":"authorization_required"}
        if item["blockers"]:
            return {"allowed":False,"reason":"work_item_blockers"}
        if item["state"]!="QUEUED":
            return {"allowed":False,"reason":"work_item_"+item["state"].lower()}
        for dependency in item["dependencies"]:
            try:state=self.governance.work_item_info(dependency,self.owner)["state"]
            except FileNotFoundError:state="missing"
            if state!="COMPLETED":return {"allowed":False,"reason":"dependency_incomplete"}
        context=self.budget_context(task)
        if not reserve:
            return self.budgets.check_quota(self.owner,event_id="canvas-admission-"+task["id"],**context)
        decision=self.budgets.reserve_quota(self.owner,event_id="canvas-admission-"+task["id"],**context)
        if decision["allowed"]:
            try:
                self.governance.start_execution(task["work_item_id"],self.owner,
                    run_id=task["run_id"],agent_id=task["agent_id"],expected_state="QUEUED")
            except GovernanceConflict:
                return {"allowed":False,"reason":"work_item_admission_changed"}
        return decision

    def _project_work_item(self,task):
        item=self.work_item(task)
        current=item["state"]
        # Preserve externally controlled blockers/reviews/recovery. Completion of
        # a process is execution evidence, never a deterministic Quality Gate.
        status=task["status"]
        target={"queued":"QUEUED","running":"RUNNING","succeeded":"VALIDATING",
                "failed":"FAILED","cancelled":"CANCELLED","uncertain":"BLOCKED"}[status]
        if status=="queued" and current=="RUNNING":
            self.governance.transition_work_item(item["work_item_id"],self.owner,"BLOCKED",
                reason="interrupted admission requires explicit reconciliation")
            return
        if current=="PENDING":
            current="QUEUED"
            self.governance.transition_work_item(item["work_item_id"],self.owner,current)
        if current=="QUEUED" and target in {"RUNNING","VALIDATING"}:
            current="RUNNING"
            self.governance.start_execution(item["work_item_id"],self.owner,
                run_id=task["run_id"],agent_id=task["agent_id"],expected_state="QUEUED")
        if current!=target and (current in {"QUEUED","RUNNING"} or
                target in {"FAILED","CANCELLED"} and current not in {"COMPLETED","FAILED","CANCELLED"}):
            self.governance.transition_work_item(item["work_item_id"],self.owner,target,
                reason="Canvas execution "+status,
                metadata={"canvas_revision":task["revision"],"execution_status":status})
        if status not in {"queued","running"}:
            item=self.governance.work_item_info(item["work_item_id"],self.owner)
            if task["run_id"] in {item["checkout_run_id"],item["execution_run_id"]}:
                self.governance.release_run_locks(item["work_item_id"],self.owner,run_id=task["run_id"])

    def project(self,task):
        ws=task["workspace_id"]
        rid,oid=task["run_id"],task["operation_id"]
        if rid not in self._runs:
            self.durable.create_run(self.owner,workspace=self.store.workspace(ws)["path"],
                run_id=rid,idempotency_key=rid)
            self._runs.add(rid)
        operation=self.durable.create_operation(rid,self.owner,kind="canvas.agent_task",
            operation_id=oid,idempotency_key=oid,cleanup_policy="manual")
        if operation["operation_id"]!=oid or operation["kind"]!="canvas.agent_task":
            raise RuntimeError("Canvas durable operation identity mismatch")
        if operation["state"] in {"CANCEL_REQUESTED","CANCELLED"} and task["status"] in {"queued","running"}:
            task=self.store.request_task_cancel(ws,task["id"])
            if task["status"]=="queued":
                self.store.task_state(ws,task["id"],"cancelled")
                task=self.store.resource("tasks",task["id"],ws)
        target={"queued":"QUEUED","running":"RUNNING","succeeded":"SUCCEEDED",
                "failed":"FAILED","cancelled":"CANCELLED","uncertain":"UNCERTAIN"}[task["status"]]
        if target=="RUNNING" and task["cancel_requested"]:target="CANCEL_REQUESTED"
        current=operation["state"]
        # A coalesced outbox may already contain final execution evidence.
        if current=="QUEUED" and target in {"SUCCEEDED","UNCERTAIN","CANCEL_REQUESTED"}:
            current="RUNNING"
            self.durable.update_operation(oid,self.owner,state=current,event_type="CANVAS_TASK_OBSERVED_RUNNING")
        progress={"canvas_task_id":task["id"],"workspace_id":ws,
                  "team_id":task["team_id"],"agent_id":task["agent_id"],
                  "conversation_id":"task_"+task["id"],"revision":task["revision"],
                  "authorized":task["approved"],"cancel_requested":task["cancel_requested"]}
        if current!=target or operation["progress"].get("revision")!=task["revision"]:
            self.durable.update_operation(oid,self.owner,state=target,progress=progress,
                event_type="CANVAS_TASK_"+target,
                result={"canvas_task_id":task["id"],"result_in_protected_canvas_store":True}
                       if target=="SUCCEEDED" else None)
        self._project_work_item(task)
        self.flush_usage(task)
        if task["status"]=="succeeded" and task["checks"] and task["provider"]=="sentra-cli":
            item=self.work_item(task)
            if item["state"] in {"VALIDATING","READY_FOR_PROMOTION"} and self.task_run(task)["state"]=="RUNNING":
                self.validation.validate(task)
        self.store.acknowledge_projection(task["id"],task["revision"])

    def flush_usage(self,task):
        if self._has_conversation(task):self.usage.flush(ident="task_"+task["id"])

    def verify(self,task):
        self.project(task)
        return self.validation.validate(task,force=True)

    def usage_summary(self,task):
        if self._has_conversation(task):return self.usage.store.usage_summary("task_"+task["id"])
        return {"reported_calls":0,"unreported_calls":0,"fully_reported":False,"pricing_known":False}

    def _has_conversation(self,task):
        try:self.usage.store.status("task_"+task["id"])
        except PermissionError:return False
        return True

    def operation(self,task):
        return self.durable.operation_status(task["operation_id"],self.owner)

    def run(self,ws):
        rid=self.store.workspace(ws)["run_id"]
        if rid not in self._runs:
            self.durable.create_run(self.owner,workspace=self.store.workspace(ws)["path"],
                                    run_id=rid,idempotency_key=rid)
            self._runs.add(rid)
        return self.durable.run_status(rid,self.owner,include_details=False)

    def task_run(self,task):
        return self.durable.run_status(task["run_id"],self.owner,include_details=False)

    def control(self,ws,action):
        states={"pause":"PAUSED","resume":"RUNNING","cancel":"CANCELLED"}
        run=self.run(ws)
        if action=="resume" and run["state"] in {"CANCELLED","SUCCEEDED","FAILED"}:
            self.store.new_run(ws)
            result=self.run(ws)
            return {"run_id":result["run_id"],"state":result["state"]}
        result=self.durable.transition_run(run["run_id"],self.owner,states[action],
                                          reason="explicit native Canvas control")
        return {"run_id":result["run_id"],"state":result["state"]}

    def close(self):
        self.durable.close()
