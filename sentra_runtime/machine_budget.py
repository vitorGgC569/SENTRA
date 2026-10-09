"""Machine-attempt admission uses the existing scoped budget/cost authority."""
import hashlib

from .contracts import PolicyDecision


def quota_event_id(operation_id):
    return "cost-machine-"+hashlib.sha256(operation_id.encode()).hexdigest()


def quota_context(control,owner,request):
    item=control.work_item_info(request.work_item_id,owner)
    run=control.durable.run_status(item["run_id"],owner,include_details=False)
    return {"workspace":run.get("workspace"),"goal_id":item.get("goal_id"),
        "work_item_id":request.work_item_id,"run_id":run["run_id"],"operation_id":request.operation_id,
        "agent_id":request.principal_id,"provider":"sentra-machines"}


class BudgetedMachinePolicy:
    def __init__(self,base,*,control,owner,observation_predicate=None):
        self.base,self.control,self.owner=base,control,owner
        self.observation_predicate=observation_predicate
    def __call__(self,request):
        decision=self.base(request)
        if decision.allowed is not True:return decision
        if self.observation_predicate is not None and self.observation_predicate(request) is True:return decision
        try:
            context=quota_context(self.control,self.owner,request)
            result=self.control.budgets.check_quota(self.owner,event_id=quota_event_id(request.operation_id),**context)
            if result.get("allowed") is not True:return PolicyDecision(False,"SENTRA machine budget exhausted")
            return decision
        except Exception:return PolicyDecision(False,"SENTRA machine budget unavailable")
