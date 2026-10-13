"""Safe receipt projection and owner-scoped cleanup decisions from central SQLite.

Never infer success from a language-model statement. This layer is read-only
and intentionally has NO PID-based kill/GC fallback after process restart.
"""
from __future__ import annotations

import math
from typing import Any


class OperationReceiptViews:
    """Read actual DurableRunService rows; project only allowlisted metadata."""

    def __init__(self, control: Any):
        self.control = control

    def receipt(self, owner: str, operation_id: str, *,
                work_item_id: str | None = None) -> dict[str, Any]:
        row = self.control.durable.operation_status(operation_id, owner)
        run = self.control.durable.run_status(row["run_id"], owner,
                                              include_details=False)
        if work_item_id is not None:
            work = self.control.work_item_info(work_item_id, owner)
            if work["run_id"] != row["run_id"]:
                raise PermissionError("operation and WorkItem belong to different Runs")
            actual = (row.get("progress") or {}).get("work_item_id")
            if actual != work_item_id:
                raise PermissionError("operation is not bound to this WorkItem")
        state = row["state"]
        actual = row.get("result") if isinstance(row.get("result"), dict) else {}
        progress = row.get("progress") or {}
        # Structured field projection only: never include stdout, prompts,
        # arbitrary error text, environment, command strings or file paths.
        summary = {"SUCCEEDED":"Operation succeeded",
                   "FAILED":"Operation failed",
                   "CANCELLED":"Operation cancelled",
                   "UNCERTAIN":"Outcome uncertain; reconcile before retry",
                   "RUNNING":"Operation in progress",
                   "QUEUED":"Operation queued",
                   "WAITING_EXTERNAL":"Waiting for external result"}.get(
                       state,"Operation " + state.lower().replace("_"," "))
        details: dict[str, Any] = {}
        exit_code = actual.get("exit_code")
        if type(exit_code) is int and -32768 <= exit_code <= 32767:
            details["exit_code"] = exit_code
        for field in ("files_changed", "lines_added", "lines_removed", "hits"):
            count = actual.get(field)
            if type(count) is int and 0 <= count <= 1_000_000:
                details[field] = count
        return {"operation_id":operation_id,"owner":owner,
                "run_id":row["run_id"],
                "work_item_id":progress.get("work_item_id")
                    if isinstance(progress.get("work_item_id"),str) else None,
                "state":state,"summary":summary,"details":details,
                "source":"durable_operation",
                "terminal":bool(row["terminal"]),
                "requires_reconciliation":state == "UNCERTAIN",
                "cleanup_policy":row["cleanup_policy"],
                "read_only":True}

    def cleanup_candidates(self, owner: str, run_id: str, *,
                           idle_before: float, limit: int = 100) -> dict[str, Any]:
        """Produce a no-kill GC plan. Resource ownership must be proved by host.

        Even if the Run is terminal, expired worker lease or an OS PID alone
        is not evidence of right to terminate a process (PID reuse / ConPTY).
        """
        if type(idle_before) not in (int,float) or not math.isfinite(idle_before):
            raise ValueError("finite idle cutoff required")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("GC planning limit must be 1..100")
        run = self.control.durable.run_status(run_id, owner, include_details=False)
        page = self.control.durable.list_operations(run_id, owner, limit=limit)
        candidates = []
        for op in page["items"]:
            if (op["terminal"] and op["updated_at"] <= idle_before
                    and op["state"] != "UNCERTAIN"):
                full = self.control.durable.operation_status(op["operation_id"],owner)
                if full.get("cleanup_policy") == "preserve":
                    continue
                candidates.append({
                    "operation_id":op["operation_id"],
                    "state":op["state"],
                    "work_item_id":op.get("work_item_id"),
                    "cleanup_policy":full.get("cleanup_policy"),
                    "action":"host_ownership_review_only",
                    "may_kill_process":False})
        return {"run_id":run_id,"owner":owner,"run_terminal":bool(run["terminal"]),
                "candidates":candidates,"destructive_actions_executed":0,
                "gc_supported_for_unknown_pid":False,
                "next_offset":page["page"]["next_offset"]}


class HumanReceiptViews(OperationReceiptViews):
    """Human-readable receipts with lineage for shell/approval surfaces.

    Extends the sanitized :class:`OperationReceiptViews` projection with the
    durable lineage a human supervisor needs: which routine occurrence, goal
    loop step, workflow activity or terminal write produced the operation,
    whether an approval is still pending, and what to do next. Still
    read-only and still field-projected: no stdout, prompts, credentials,
    command strings or file paths are ever included.
    """

    _NEXT = {
        "SUCCEEDED": "This operation succeeded. Provider start/signal/ACK receipts require separate completion or recipient observation.",
        "FAILED": "Review the evidence. Retry needs a confirmed NOT_STARTED, retryable outcome and a separately admitted operation.",
        "CANCELLED": "Cancellation does not prove rollback. Observe started effects before any new request.",
        "UNCERTAIN": "Outcome uncertain: reconcile before any retry. Query this "
                     "same operation_id again; do not submit a duplicate effect.",
        "RUNNING": "Operation in progress. Wait for its receipt instead of "
                   "submitting the same effect again.",
        "QUEUED": "Operation queued behind central admission. Wait for its receipt.",
        "WAITING_EXTERNAL": "Waiting for an external result (provider, human "
                            "approval or signal). No duplicate submission.",
    }

    def human_receipt(self, owner: str, operation_id: str, *,
                      work_item_id: str | None = None) -> dict[str, Any]:
        """Full human receipt: sanitized state, lineage, approval, next step."""
        base = self.receipt(owner, operation_id, work_item_id=work_item_id)
        row = self.control.durable.operation_status(operation_id, owner)
        progress = row.get("progress") if isinstance(row.get("progress"), dict) else {}
        lineage: dict[str, Any] = {}
        for key in ("routine_id", "routine_source", "routine_occurrence_key",
                    "goal_loop_id", "goal_loop_step", "workflow_id",
                    "workflow_namespace", "workflow_step_id", "terminal_id"):
            value = progress.get(key)
            if isinstance(value, (str, int)) and value != "":
                lineage[key] = value
        work_id = base.get("work_item_id")
        approval: dict[str, Any] = {"required": False}
        if isinstance(work_id, str) and work_id:
            try:
                work = self.control.work_item_info(work_id, owner)
                grants = work.get("grants") or work.get("approvals") or []
                pending = [grant for grant in (grants if isinstance(grants, list) else [])
                           if isinstance(grant, dict) and grant.get("state") in {
                               "PENDING", "WAITING_APPROVAL"}]
                if pending:
                    approval = {"required": True, "state": "waiting_approval",
                                "pending_count": len(pending)}
                elif work.get("state") in {"WAITING_APPROVAL", "BLOCKED"}:
                    approval = {"required": True, "state": work["state"],
                                "pending_count": 1}
            except (FileNotFoundError, PermissionError, KeyError):
                approval = {"required": False, "state": "unknown"}
        state = base["state"]
        return {**base, "lineage": lineage, "approval": approval,
                "human_summary": base["summary"],
                "next_step": self._NEXT.get(
                    state, "Query this operation_id again for its current state."),
                "reconcile_before_retry": state == "UNCERTAIN"}
