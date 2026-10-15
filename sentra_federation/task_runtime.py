"""Federated tasks use the installation's configured MachineHost.

The wire describes work, never a principal, root, backend, Grant or local
WorkItem. Registration and grants remain host decisions. Every physical step
uses MachineHost's central admission, full-intent fence and existing adapters.
An interrupted task is observed, never started again by reconnecting a peer.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from sentra_collab.scope import ScopeDenied, parse_scope
from sentra_runtime.machine_host import MachineHost

from .errors import FederationDenied
from .protocol import canonical, reject_secrets

EXECUTOR = "central-machine-task-v1"
POLICY = {"require_quality_gate": True, "stages": [
    {"id": "federation-review", "type": "review", "allow_any_authorized": True},
]}


def validate_task(task):
    """Bounded, typed plan; normal provider tool schemas validate arguments."""
    if (not isinstance(task, dict) or set(task) != {"schema", "objective", "steps"}
            or type(task["schema"]) is not int or task["schema"] != 1):
        raise FederationDenied("invalid structured delegation")
    objective, steps = task["objective"], task["steps"]
    if not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 4000:
        raise FederationDenied("invalid delegation objective")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise FederationDenied("delegation requires one to eight bounded steps")
    for step in steps:
        if not isinstance(step, dict) or set(step) != {"machine_kind", "capability_id", "arguments"}:
            raise FederationDenied("invalid task step")
        for name in ("machine_kind", "capability_id"):
            if not isinstance(step[name], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", step[name]):
                raise FederationDenied("invalid task capability")
        if not isinstance(step["arguments"], dict):
            raise FederationDenied("task arguments must be an object")
    reject_secrets(task)
    encoded = canonical(task)
    if len(encoded) > 16000:
        raise FederationDenied("structured delegation exceeds limit")
    # Freeze mutable caller data before any durable reservation or effect.
    return json.loads(encoded)


def _scope(scope):
    try:
        return parse_scope(scope)
    except ScopeDenied as exc:
        raise FederationDenied("invalid task receipt scope") from exc


def request_digest(task, scope):
    return hashlib.sha256(canonical({"task": task, "scope": _scope(scope)})).hexdigest()


def operation_id(owner, peer, intent_id):
    return "op-fedtask-" + hashlib.sha256(canonical([owner, peer, intent_id])).hexdigest()[:32]


def _receipt_valid(receipt, *, objective, scope, ready):
    if not isinstance(receipt, dict) or receipt.get("executor") != EXECUTOR:
        raise FederationDenied("not a central machine task receipt")
    task = validate_task(objective)
    if (receipt.get("task") != task or receipt.get("request_sha256") != request_digest(task, scope)
            or _scope(receipt.get("request_scope")) != _scope(scope)
            or receipt.get("automatic_resend") is not False):
        raise FederationDenied("task receipt does not match the request")
    if receipt.get("result_ready") is not ready or receipt.get("passed") is not ready:
        raise FederationDenied("task result is not ready" if ready else "unresolved task claimed a delivery")
    if not all(isinstance(receipt.get(key), str) and receipt[key]
               for key in ("intent_id", "operation_id", "work_item_id", "run_id", "project_id")):
        raise FederationDenied("task receipt identities are missing")
    return task


def verify_result(receipt, *, objective, scope):
    task = _receipt_valid(receipt, objective=objective, scope=scope, ready=True)
    waiting = receipt.get("remote_state") == "WAITING_EXTERNAL" and receipt.get("work_item_state") == "IN_REVIEW"
    reviewed = (receipt.get("remote_state") == "SUCCEEDED" and receipt.get("work_item_state") == "COMPLETED"
                and receipt.get("review_approved") is True and receipt.get("executed") is True)
    if not waiting and not reviewed:
        raise FederationDenied("task result is not awaiting review")
    document = receipt.get("result_document")
    if not isinstance(document, str) or not receipt.get("artifact_id"):
        raise FederationDenied("task artifact is missing")
    digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
    if digest != receipt.get("artifact_sha256") or len(document.encode("utf-8")) != receipt.get("artifact_size"):
        raise FederationDenied("task artifact did not verify")
    try:
        parsed = json.loads(document)
    except (TypeError, ValueError) as exc:
        raise FederationDenied("task artifact is invalid") from exc
    if not isinstance(parsed, dict):
        raise FederationDenied("task artifact is invalid")
    if any(parsed.get(key) != receipt.get(key) for key in
           ("project_id", "work_item_id", "intent_id", "request_sha256")) or parsed.get("task") != task:
        raise FederationDenied("task artifact identity mismatch")
    results = parsed.get("steps")
    if not isinstance(results, list) or len(results) != len(task["steps"]):
        raise FederationDenied("task artifact lacks completed steps")
    operation_ids = []
    for index, (result, step) in enumerate(zip(results, task["steps"])):
        if (not isinstance(result, dict) or result.get("index") != index
                or result.get("state") != "SUCCEEDED" or result.get("capability_id") != step["capability_id"]
                or result.get("machine_kind") != step["machine_kind"]
                or not isinstance(result.get("operation_id"), str) or not result["operation_id"]
                or not isinstance(result.get("work_item_id"), str) or not result["work_item_id"]
                or not isinstance(result.get("evidence"), dict)):
            raise FederationDenied("task step did not prove completion")
        operation_ids.append(result["operation_id"])
    work_ids = [result["work_item_id"] for result in results]
    if (len(set(operation_ids)) != len(operation_ids) or receipt.get("step_operation_ids") != operation_ids
            or len(set(work_ids)) != len(work_ids) or receipt.get("step_work_item_ids") != work_ids):
        raise FederationDenied("task step receipts are not unique")
    return digest


def verify_unresolved(receipt, *, objective, scope):
    _receipt_valid(receipt, objective=objective, scope=scope, ready=False)
    if (receipt.get("work_item_state") not in {"REPAIRING", "RUNNING", "BLOCKED"}
            or receipt.get("remote_state") not in {"FAILED", "UNCERTAIN", "WAITING_EXTERNAL"}
            or any(receipt.get(key) for key in ("result_document", "artifact_id", "artifact_sha256"))):
        raise FederationDenied("unresolved task claimed a delivery")
    return receipt


class FederatedMachineExecutor:
    def __init__(self, host, *, project_id, agent_id, run_id, workspace=None):
        if not isinstance(host, MachineHost) or not all((project_id, agent_id, run_id)):
            raise ValueError("trusted installation machine host and Dot required")
        run = host.control.durable.run_status(run_id, host.owner, include_details=False)
        agent = host.control.durable.agent_info(agent_id, host.owner)
        if run.get("workspace") != (workspace or project_id) or agent.get("run_id") != run_id:
            raise FederationDenied("task runtime is outside the host project")
        self.host, self.control, self.owner = host, host.control, host.owner
        self.project_id, self.agent_id, self.run_id = project_id, agent_id, run_id

    def _machines(self, task):
        inventory = self.host.inventory(self.project_id)
        selected = []
        for step in task["steps"]:
            candidates = [machine for machine in inventory
                          if machine["agent_id"] == self.agent_id
                          and machine["kind"] == step["machine_kind"]
                          and step["capability_id"] in machine["capabilities"]]
            if len(candidates) != 1:
                raise FederationDenied("task capability is not uniquely configured for this Dot")
            selected.append(candidates[0])
        return selected

    def observe(self, *, peer, intent_id):
        """Only persisted state. Never dispatches or manufactures absence."""
        try:
            operation = self.control.durable.operation_status(operation_id(self.owner, peer, intent_id), self.owner)
        except FileNotFoundError:
            return None
        return operation.get("result") or {
            "intent_id": intent_id, "remote_state": operation["state"],
            "result_ready": False, "automatic_resend": False,
        }

    def execute(self, *, intent_id, task, scope, request_scope, grant_id, peer, artifact_dir, authorize):
        task = validate_task(task)
        if parse_scope(scope)["project_id"] != self.project_id:
            raise FederationDenied("delegation is outside the configured project")
        machines = self._machines(task)
        control, owner = self.control, self.owner
        oid = operation_id(owner, peer, intent_id)
        digest = request_digest(task, request_scope)
        operation = control.durable.create_operation(self.run_id, owner, kind="federation.task",
            operation_id=oid, idempotency_key="fedtask:" + peer + ":" + intent_id, initial_state="QUEUED")
        if operation.get("idempotent_replay"):
            stored = operation.get("result") or {}
            if stored.get("request_sha256") != digest:
                raise FederationDenied("existing task intent differs or is incomplete; it is not restarted")
            return stored
        item = control.create_work_item(self.run_id, owner, external_key="fedtask:" + peer + ":" + intent_id,
            objective=task["objective"], assignee_agent_id=self.agent_id,
            required_capabilities=["federation.delegate"], side_effect_scope="federated-task",
            execution_policy=POLICY, metadata={"workspace_id": self.project_id,
                "federation": {"intent_id": intent_id, "peer": peer, "request_sha256": digest,
                               "automatic_resend": False}})
        receipt = {"executor": EXECUTOR, "intent_id": intent_id, "operation_id": oid,
            "work_item_id": item["work_item_id"], "run_id": self.run_id, "grant_id": grant_id,
            "project_id": self.project_id, "task": task, "request_scope": parse_scope(request_scope),
            "request_sha256": digest, "executed": False, "effect_executed": False,
            "review_approved": False, "result_ready": False, "passed": False,
            "automatic_resend": False, "remote_state": "WAITING_EXTERNAL", "work_item_state": "RUNNING",
            "step_operation_ids": [], "step_work_item_ids": []}
        control.durable.update_operation(oid, owner, state="STARTING", result=receipt)
        control.durable.update_operation(oid, owner, state="WAITING_EXTERNAL", result=receipt)
        try:
            control.start_work_item_execution(item["work_item_id"], owner, run_id=self.run_id, agent_id=self.agent_id)
        except Exception:
            control.transition_work_item(item["work_item_id"], owner, "BLOCKED", reason="central task admission denied")
            receipt.update(remote_state="FAILED", work_item_state="BLOCKED", failure="central task admission denied")
            control.durable.update_operation(oid, owner, state="FAILED", result=receipt)
            return receipt
        results, started = [], False
        try:
            # Validate all machine bindings first. Recheck federation authority
            # immediately before every step as well as the machine's own gate.
            for index, (step, machine) in enumerate(zip(task["steps"], machines)):
                authorize()
                child = control.create_work_item(self.run_id, owner,
                    external_key="fedtask-step:" + peer + ":" + intent_id + ":" + str(index),
                    objective=task["objective"], assignee_agent_id=self.agent_id,
                    required_capabilities=[step["capability_id"]], side_effect_scope="machine:" + machine["machine_id"],
                    execution_policy=POLICY, metadata={"workspace_id": self.project_id,
                        "machine_id": machine["machine_id"], "federation_parent": item["work_item_id"],
                        "federation_intent": intent_id, "peer": peer})
                control.start_work_item_execution(child["work_item_id"], owner,
                    run_id=self.run_id, agent_id=self.agent_id)
                child_oid = "op-fedstep-" + hashlib.sha256(canonical([oid, index])).hexdigest()[:32]
                receipt["step_operation_ids"].append(child_oid)
                receipt["step_work_item_ids"].append(child["work_item_id"])
                control.durable.update_operation(oid, owner, state="WAITING_EXTERNAL", result=receipt)
                from sentra_runtime.authority_bridge import BoundWorkItemPolicy
                from sentra_runtime.contracts import OperationRequest
                preflight = BoundWorkItemPolicy(owner=owner, principal_type="agent",
                    authorization=control.authorization, governance=control.governance)
                probe = OperationRequest(child_oid, self.agent_id, machine["machine_id"],
                    step["capability_id"], child["work_item_id"], child_oid, step["arguments"])
                if preflight(probe).allowed is not True:
                    raise FederationDenied("independent machine capability grant missing")
                started = True
                result = self.host.dispatch(workspace_id=self.project_id, work_item_id=child["work_item_id"],
                    machine_id=machine["machine_id"], capability_id=step["capability_id"],
                    operation_id=child_oid, arguments=step["arguments"], idempotency_key=child_oid,
                    effect_authorize=authorize)
                if result.get("state") != "SUCCEEDED":
                    raise _TaskStopped(result.get("state", "UNCERTAIN"))
                # The durable machine operation must agree with its returned
                # receipt. A returned dict alone cannot pass the result gate.
                persisted = control.durable.operation_status(child_oid, owner)
                if persisted["state"] != "SUCCEEDED":
                    raise _TaskStopped("UNCERTAIN")
                evidence = result.get("evidence") or {}
                reject_secrets(evidence)
                results.append({"index": index, "machine_kind": step["machine_kind"],
                    "capability_id": step["capability_id"], "operation_id": child_oid,
                    "work_item_id": child["work_item_id"], "state": "SUCCEEDED", "evidence": evidence})
                # Bounded wire artifact; original full evidence stays in the
                # central operation/artifact store, never silently truncated.
                if len(canonical(results)) > 20000:
                    raise _TaskStopped("FAILED")
                receipt["effect_executed"] = True
                control.governance.record_quality_gate(child["work_item_id"], owner,
                    passed=True, reason="central machine operation succeeded", evidence=[child_oid])
                control.governance.submit_for_policy(child["work_item_id"], owner, evidence=[child_oid])
            # The final physical step is not authority to publish its result.
            # This callback is installed by the receiving host, never the wire.
            authorize()
            document = canonical({"schema": 2, "project_id": self.project_id, "task": task,
                "intent_id": intent_id, "work_item_id": item["work_item_id"],
                "request_sha256": digest, "steps": results}).decode("utf-8")
            directory = Path(artifact_dir); directory.mkdir(parents=True, exist_ok=True)
            target = directory / (oid + ".json")
            authorize()
            target.write_bytes(document.encode("utf-8"))
            authorize()
            artifact = control.durable.register_artifact(self.run_id, owner, target,
                operation_id=oid, mime_type="application/json",
                expected_sha256=hashlib.sha256(document.encode("utf-8")).hexdigest(),
                metadata={"intent_id": intent_id, "request_sha256": digest})
            # Registration may take time. Keep already captured evidence local
            # if authority disappeared; never convert completed steps to retry.
            authorize()
            control.governance.record_quality_gate(item["work_item_id"], owner, passed=True,
                reason="all central machine steps have durable successful receipts", evidence=[artifact["artifact_id"]])
            authorize()
            control.governance.submit_for_policy(item["work_item_id"], owner, evidence=[artifact["artifact_id"]])
            receipt.update(result_ready=True, passed=True, work_item_state="IN_REVIEW",
                result_document=document, artifact_id=artifact["artifact_id"],
                artifact_sha256=artifact["sha256"], artifact_size=artifact["size_bytes"])
            control.durable.update_operation(oid, owner, state="WAITING_EXTERNAL", result=receipt)
            return receipt
        except Exception as exc:
            # Preserve known partial effects; uncertainty never licenses replay.
            state = exc.state if isinstance(exc, _TaskStopped) else "UNCERTAIN" if started else "FAILED"
            state = "UNCERTAIN" if state not in {"FAILED", "CANCELLED"} else "FAILED"
            if state == "UNCERTAIN" and not receipt["effect_executed"]:
                receipt["effect_executed"] = None
            receipt.update(remote_state=state, work_item_state="REPAIRING",
                           failure="task requires observation; no automatic resend")
            control.governance.record_quality_gate(item["work_item_id"], owner, passed=False,
                reason=receipt["failure"], evidence=list(receipt["step_operation_ids"]))
            control.durable.update_operation(oid, owner, state=state, result=receipt)
            return receipt

    def approve(self, receipt, *, actor_type, actor_id, authorize):
        """Finish child reviews first; restart can continue without any I/O."""
        control, owner = self.control, self.owner
        for oid, work_id in zip(receipt["step_operation_ids"], receipt["step_work_item_ids"]):
            authorize()
            operation = control.durable.operation_status(oid, owner)
            if operation["state"] != "SUCCEEDED" or operation.get("progress", {}).get("work_item_id") != work_id:
                raise FederationDenied("task child operation no longer proves completion")
            item = control.work_item_info(work_id, owner)
            if (item.get("metadata", {}).get("federation_parent") != receipt["work_item_id"]
                    or item["run_id"] != self.run_id or item.get("assignee_agent_id") != self.agent_id):
                raise FederationDenied("task review children are outside this Dot")
            if item["state"] == "COMPLETED":
                continue
            if item["state"] == "IN_REVIEW":
                authorize()
                item = control.governance.decide_policy_stage(work_id, owner,
                    actor_type=actor_type, actor_id=actor_id, decision="approved",
                    comment="federation task review", evidence=[receipt["artifact_id"]])["work_item"]
            if item["state"] != "READY_FOR_PROMOTION":
                raise FederationDenied("task child is not ready for review")
            authorize()
            control.transition_work_item(work_id, owner, "COMPLETED", reason="federated task review accepted")
        authorize()


class _TaskStopped(Exception):
    def __init__(self, state):
        self.state = state
