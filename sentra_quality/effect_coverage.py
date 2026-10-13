"""Coverage against central effect_started rows; no completeness by declaration."""
import json

from .protected_state import digest, StateConflict


class EffectCoverage:
    def __init__(self, state, references):
        self.state, self.references = state.scoped("selo.coverage"), references

    def capture(self, context, *, phase):
        if phase not in {"admitted", "returned", "uncertain"}:
            raise ValueError("unknown effect coverage phase")
        if (context.receipt.owner != self.state.owner
                or context.authority.durable is not self.references.control.durable):
            raise PermissionError("real owner-scoped central effect context required")
        snapshot = self.references.snapshot(context.receipt.operation_id)
        if snapshot["effect_started"] is not True:
            raise PermissionError("central physical boundary not marked")
        if snapshot["origin"]["work_item_id"] != context.request.work_item_id:
            raise PermissionError("effect marker WorkItem mismatch")
        key = "operation:" + context.receipt.operation_id
        with self.state.transaction() as tx:
            row = tx.get(key)
            value = row["value"] if row else {"origin": snapshot["origin"],
                "capability_id": context.request.capability_id, "phases": []}
            if value["origin"] != snapshot["origin"]:
                raise StateConflict("central effect coverage origin changed")
            if phase not in value["phases"]: value["phases"].append(phase)
            tx.put(key, value, expected_revision=row["revision"] if row else None)
        return {"recorded": True, "operation_id": context.receipt.operation_id, "audit_complete": False}

    def report(self, run_id):
        suffix = " FOR UPDATE" if self.references.store.backend == "postgres" else ""
        with self.references.guard() as query:
            run = query("durable", "SELECT workspace FROM {table}runs WHERE run_id=? AND owner=?" + suffix,
                        (run_id, self.state.owner)).fetchone()
            if run is None or not self.references.root_matches(run["workspace"]):
                raise PermissionError("coverage Run outside workspace")
            operations = query("durable", "SELECT operation_id,progress_json,state FROM {table}operations "
                               "WHERE run_id=? AND owner=? ORDER BY operation_id LIMIT 10001" + suffix,
                               (run_id, self.state.owner)).fetchall()
            scoped = []
            for operation in operations:
                work_id = json.loads(operation["progress_json"] or "{}").get("work_item_id")
                if not work_id: continue
                work = query("governance", "SELECT run_id,metadata_json FROM {table}work_items "
                             "WHERE work_item_id=? AND owner=?" + suffix,
                             (work_id, self.state.owner)).fetchone()
                if work and work["run_id"] == run_id and self.references.work_matches(dict(work)):
                    scoped.append(operation)
        if len(operations) > 10000: raise ValueError("narrow coverage Run to bounded operation set")
        marked = [r for r in scoped if json.loads(r["progress_json"] or "{}").get("effect_started") is True]
        missing = [r["operation_id"] for r in marked if self.state.get("operation:" + r["operation_id"]) is None]
        incomplete = [r["operation_id"] for r in marked if r["state"] not in {"SUCCEEDED", "FAILED", "CANCELLED"}]
        return {"run_id": run_id, "central_operations": len(scoped), "central_marked_effects": len(marked),
                "captured_effects": len(marked) - len(missing), "missing_operation_ids": missing,
                "uncertain_operation_ids": incomplete, "audit_complete": False,
                "coverage_outside_central_boundary": "unknown", "external_witness_coverage_proved": False}
