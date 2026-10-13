"""Inject the composed Control Plane into the existing Canvas task runtime."""
from sentra_canvas.task_runtime import TaskRuntime
from sentra_core.conversations import ConversationStore
from sentra_core.provider_usage import UsageLedger


class CanvasAuthorityRuntime(TaskRuntime):
    def __init__(self, state_root, canvas_store, *, control, owner):
        if owner != "canvas:" + canvas_store.principal:
            raise PermissionError("Canvas runtime principal mismatch")
        if hasattr(control.store, "assert_principal"):
            control.store.assert_principal(owner)
        self.store, self.owner, self.control = canvas_store, owner, control
        self.durable, self.governance, self.budgets = control.durable, control.governance, control.budgets
        self.usage = UsageLedger(ConversationStore(state_root, principal=canvas_store.principal), control=control)
        from sentra_canvas.quality import TaskValidation
        self.validation = TaskValidation(self)
        self._runs = set()

    def work_item(self, task):
        agent = self.store.resource("agents", task["agent_id"], task["workspace_id"])
        self.control.ensure_agent(task["run_id"], self.owner, agent_id=agent["id"], role=agent["role"],
                                  metadata={"workspace_id": task["workspace_id"]})
        return super().work_item(task)

    def admission(self, task, *, reserve=False):
        actor = self.control.durable.agent_info(task["agent_id"],self.owner)
        if actor["run_id"] != task["run_id"] or actor["desired_state"] == "WAITING":
            return {"allowed":False,"reason":"agent_paused_or_outside_run"}
        return super().admission(task,reserve=reserve)

    def close(self):
        # Composition owns the shared service lifetime, not this borrowed facade.
        self.usage.flush()
