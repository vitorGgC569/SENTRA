"""Caller-declared file checks tied to existing artifacts and governance policy."""
import hashlib
import json
import os
import uuid

from .validation import verify_files


class TaskValidation:
    def __init__(self,runtime):self.runtime=runtime

    def validate(self,task,*,force=False):
        runtime=self.runtime
        if task["provider"]!="sentra-cli":return {"status":"real_execution_required"}
        if task["status"]!="succeeded" or not task["checks"]:
            return {"status":"criteria_required" if not task["checks"] else "execution_not_succeeded"}
        item=runtime.work_item(task)
        if item["state"] not in {"VALIDATING","REPAIRING","READY_FOR_PROMOTION","COMPLETED"}:
            return {"status":"policy_pending","work_item_state":item["state"]}
        gate=item["execution_state"].get("quality_gate",{})
        if item["state"]=="REPAIRING" and not force:
            return {"status":"failed","artifact_id":item["metadata"].get("validation_artifact_id")}
        report,outputs=verify_files(runtime.store.workspace(task["workspace_id"])["path"],task["checks"])
        if item["state"]=="COMPLETED":
            status="passed" if report["passed"] else "changed_after_validation"
            runtime.governance.transition_work_item(task["work_item_id"],runtime.owner,"COMPLETED",
                metadata={"current_file_check_status":status})
            return {"status":status,
                    "historical_completion":True,"checks":report["checks"]}
        evidence=[]
        if report["passed"]:
            for index,path,digest in outputs:
                try:
                    artifact=runtime.durable.register_artifact(task["run_id"],runtime.owner,path,
                        operation_id=task["operation_id"],mime_type="application/octet-stream",
                        artifact_id="artifact-canvas-out-"+task["id"]+"-"+str(index)+"-"+digest[:24],
                        expected_sha256=digest,metadata={"canvas_task_id":task["id"],"check_index":index})
                except ValueError as exc:
                    if str(exc)!="artifact content does not match expected SHA-256":raise
                    report["passed"]=False
                    report["checks"][index].update(passed=False,error="file_changed_during_registration")
                    break
                evidence.append(artifact["artifact_id"])
                runtime.governance.register_work_product(task["work_item_id"],runtime.owner,
                    artifact_id=artifact["artifact_id"],kind="canvas_output",title="Verified output "+str(index+1))
        report.update(canvas_task_id=task["id"],task_revision=task["revision"],
            criteria_sha256=hashlib.sha256(json.dumps(task["checks"],sort_keys=True).encode()).hexdigest())
        payload=json.dumps(report,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
        digest=hashlib.sha256(payload).hexdigest()
        directory=runtime.store.path.parent/"verification"/task["id"]
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/(digest+".json")
        if path.exists():
            if path.read_bytes()!=payload:raise RuntimeError("validation evidence content changed")
        else:
            temporary=directory/(uuid.uuid4().hex+".tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(payload);stream.flush();os.fsync(stream.fileno())
                os.replace(temporary,path)
            finally:
                temporary.unlink(missing_ok=True)
        artifact=runtime.durable.register_artifact(task["run_id"],runtime.owner,path,
            operation_id=task["operation_id"],mime_type="application/json",
            artifact_id="artifact-canvas-check-"+task["id"]+"-"+digest[:32],
            metadata={"canvas_task_id":task["id"],"file_check_count":len(task["checks"])})
        evidence.append(artifact["artifact_id"])
        runtime.governance.register_work_product(task["work_item_id"],runtime.owner,
            artifact_id=artifact["artifact_id"],kind="canvas_validation",title="Declared file check evidence")
        if item["state"]=="READY_FOR_PROMOTION" and gate.get("candidate_revision")!=digest:
            runtime.governance.transition_work_item(task["work_item_id"],runtime.owner,"REPAIRING",
                reason="output verification changed before completion")
            item=runtime.work_item(task)
        if gate.get("candidate_revision")!=digest:
            runtime.governance.record_quality_gate(task["work_item_id"],runtime.owner,
                passed=report["passed"],reason="caller-declared file checks",
                evidence=evidence,candidate_revision=digest,
                metadata={"file_check_count":len(task["checks"]),"checks":report["checks"]})
        runtime.governance.transition_work_item(task["work_item_id"],runtime.owner,
            runtime.work_item(task)["state"],metadata={"validation_artifact_id":artifact["artifact_id"]})
        if report["passed"]:
            item=runtime.work_item(task)
            if item["state"]=="VALIDATING":
                item=runtime.governance.submit_for_policy(task["work_item_id"],runtime.owner,evidence=evidence)
            if item["state"]=="READY_FOR_PROMOTION":
                runtime.governance.transition_work_item(task["work_item_id"],runtime.owner,"COMPLETED",
                    reason="declared outputs verified and configured policy passed")
        return {"status":"passed" if report["passed"] else "failed",
                "artifact_id":artifact["artifact_id"],"checks":report["checks"],
                "work_item_state":runtime.work_item(task)["state"]}
