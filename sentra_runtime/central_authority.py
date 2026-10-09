"""Central SENTRA DurableRunService adapter; no second operation store.

The adapter binds DurableOperationGate to the SAME state DB and fencing lease
used by SENTRA's production Control Plane. It MUST be used with the existing
AuthorizationService/GovernanceService policy and a physical executor that
also checks the fencing token at its effect boundary for unsafe side effects.

This host integration exercises the real central authority, not a SQLite test
double. Do not expose this module as an unauthenticated RPC endpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from sentra_mcp.services.durable import DurableRunService, DurableStateConflict, StaleFenceError

from .contracts import OperationRequest, OperationResult
from .durable_admission import IntentReceipt
from .executor import DuplicateOperation, _request_snapshot


class CentralDurableIntentAuthority:
    """ControlPlane-owned adapter over DurableRunService's atomic reservation."""

    def __init__(self, durable: DurableRunService, *, ttl_s: float = 60.0,
                 release_on_terminal: bool = False, budgets=None,observation_predicate=None):
        if not isinstance(durable, DurableRunService):
            raise TypeError("real SENTRA DurableRunService required")
        if type(ttl_s) not in (float, int) or not 1 <= ttl_s <= 3600:
            raise ValueError("invalid bounded lease TTL")
        if not callable(getattr(durable, "reserve_operation_intent", None)):
            raise TypeError("core does not implement atomic intent reservation")
        self.durable = durable
        self.ttl_s = ttl_s
        self.release_on_terminal = release_on_terminal
        if budgets is not None:
            from sentra_mcp.services.budget_policy import BudgetPolicyService
            if not isinstance(budgets,BudgetPolicyService) or budgets.store.path_for("governance").parent!=durable.root:
                raise ValueError("machine budget must share this central authority")
        self.budgets=budgets
        if observation_predicate is not None and not callable(observation_predicate):raise ValueError("trusted observation classifier required")
        self.observation_predicate=observation_predicate

    def _observation(self,request):
        return self.observation_predicate is not None and self.observation_predicate(request) is True

    def _resource(self,request: OperationRequest) -> str:
        return ("machine-observation:" if self._observation(request) else "machine:")+request.machine_id

    def reserve_intent(
        self, *, run_id: str, owner: str, request: OperationRequest,
        intent_sha256: str,
    ) -> IntentReceipt:
        _, fingerprint = _request_snapshot(request)
        if fingerprint != intent_sha256:
            raise DuplicateOperation("operation intent hash mismatch")
        try:
            result = self.durable.reserve_operation_intent(
                run_id, owner, operation_id=request.operation_id,
                idempotency_key=request.idempotency_key,
                intent_sha256=fingerprint,
                resource_key=self._resource(request),
                kind="sentra.machine.observation" if self._observation(request) else "sentra.machine",
                ttl_s=self.ttl_s,
                operation_context={
                    "work_item_id": request.work_item_id,
                    "principal_id": request.principal_id,
                    "machine_id": request.machine_id,
                    "capability_id": request.capability_id,
                },
            )
        except (DurableStateConflict, ValueError) as exc:
            raise DuplicateOperation("durable intent conflicts with authoritative state") from exc
        return IntentReceipt(
            operation_id=result["operation_id"],
            intent_sha256=result["intent_sha256"],
            run_id=result["run_id"],
            owner=result["owner"],
            fencing_token=result["fencing_token"],
            status=result["status"],
        )

    def _binding(self, receipt: IntentReceipt):
        with self.durable.lock:
            row = self.durable._operation_row(receipt.operation_id, receipt.owner)
            if (row["run_id"] != receipt.run_id
                    or row["intent_sha256"] != receipt.intent_sha256
                    or row["fencing_token"] != receipt.fencing_token
                    or row["kind"] not in {"sentra.machine","sentra.machine.observation"}
                    or not isinstance(row["resource_key"], str)):
                raise StaleFenceError("stored intent, run or fence mismatch")
            return row

    def receipt_for_operation(self, operation_id: str, owner: str) -> IntentReceipt:
        """Host-scoped lookup; callers must authorize access before exposing it."""
        with self.durable.lock:
            row = self.durable._operation_row(operation_id, owner)
            if (row["kind"] not in {"sentra.machine","sentra.machine.observation"} or not row["intent_sha256"]
                    or type(row["fencing_token"]) is not int):
                raise ValueError("operation has no central machine intent")
            return IntentReceipt(operation_id, row["intent_sha256"], row["run_id"],
                                 owner, row["fencing_token"], "EXISTING")

    def fence_active(self, receipt: IntentReceipt) -> bool:
        try:
            row = self._binding(receipt)
            resource = row["resource_key"]
            with self.durable.lock:
                self.durable._verify_fence_locked(resource, receipt.fencing_token)
                current = self.durable._operation_row(receipt.operation_id, receipt.owner)
                lease = self.durable.db.execute(
                    "SELECT operation_id,owner FROM leases WHERE resource_key=?",
                    (resource,),
                ).fetchone()
                if (lease is None or lease["operation_id"] != receipt.operation_id
                        or lease["owner"] != receipt.owner
                        or self.durable.run_status(receipt.run_id, receipt.owner,
                                                   include_details=False)["state"] != "RUNNING"
                        or current["state"] not in ("STARTING", "RUNNING")):
                    return False
                if current["state"] == "STARTING":
                    self.durable.update_operation(
                        receipt.operation_id, receipt.owner,
                        state="RUNNING", event_type="MACHINE_EFFECT_ADMITTED",
                        resource_key=resource, fencing_token=receipt.fencing_token,
                    )
            return True
        except (StaleFenceError, FileNotFoundError, PermissionError, DurableStateConflict):
            return False

    def renew(self, receipt: IntentReceipt) -> bool:
        """Keep ownership while the physical worker is still in flight.

        Even when its waiting caller timed out, the worker must keep excluding
        another process until its blocking I/O actually returns.
        """
        try:
            row = self._binding(receipt)
            self.durable.renew_lease(row["resource_key"], receipt.owner,
                                    receipt.fencing_token, ttl_s=self.ttl_s)
            return True
        except (StaleFenceError, FileNotFoundError, PermissionError, DurableStateConflict):
            return False

    def begin_effect(self, receipt: IntentReceipt) -> None:
        row = self._binding(receipt)
        if self.budgets is not None and row["kind"]!="sentra.machine.observation":
            from .machine_budget import quota_event_id
            from .executor import AuthorizationRequired
            progress=json.loads(row["progress_json"])
            item=self.budgets.governance.work_item_info(progress["work_item_id"],receipt.owner)
            run=self.durable.run_status(receipt.run_id,receipt.owner,include_details=False)
            result=self.budgets.reserve_quota(receipt.owner,event_id=quota_event_id(receipt.operation_id),
                workspace=run.get("workspace"),goal_id=item.get("goal_id"),work_item_id=progress["work_item_id"],
                run_id=receipt.run_id,operation_id=receipt.operation_id,agent_id=progress["principal_id"],provider="sentra-machines")
            if result.get("allowed") is not True:raise AuthorizationRequired("SENTRA machine budget exhausted")
        self.durable.begin_machine_effect(
            receipt.operation_id, receipt.owner, intent_sha256=receipt.intent_sha256,
            resource_key=row["resource_key"], fencing_token=receipt.fencing_token,
        )

    def _store_evidence(self, receipt: IntentReceipt, result: OperationResult,
                        payload: bytes) -> dict:
        """Store owner-scoped bytes in the existing Artifact registry.

        The journal still contains references/digests only. This private
        artifact is recoverable and hash verified; it is not a telemetry export.
        """
        evidence_digest = hashlib.sha256(payload).hexdigest()
        envelope = json.dumps({"schema": 1, "operation_id": receipt.operation_id,
                               "intent_sha256": receipt.intent_sha256,
                               "state": result.state, "evidence": json.loads(payload),
                               "error": result.error}, ensure_ascii=False, sort_keys=True,
                              allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(envelope) > 2_010_000:
            raise ValueError("result envelope exceeds bounded storage")
        digest = hashlib.sha256(envelope).hexdigest()
        identity = hashlib.sha256(json.dumps(
            [receipt.owner, receipt.run_id, receipt.operation_id, digest],
            separators=(",", ":")).encode()).hexdigest()
        directory = self.durable.artifact_root / "machine-evidence"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (identity + ".json")
        if not target.exists():
            temporary = directory / (identity + "." + uuid.uuid4().hex + ".tmp")
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(envelope)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("result artifact content changed")
        artifact = self.durable.register_artifact(
            receipt.run_id, receipt.owner, target,
            operation_id=receipt.operation_id, mime_type="application/json",
            artifact_id="effect-evidence-" + identity[:48], expected_sha256=digest,
            metadata={"kind": "machine-result", "schema": 1,
                      "intent_sha256": receipt.intent_sha256},
        )
        return {"state": result.state, "evidence_sha256": evidence_digest,
                "evidence_artifact_id": artifact["artifact_id"],
                "evidence_artifact_sha256": digest}

    def result_for_receipt(self, receipt: IntentReceipt) -> OperationResult | None:
        """Recover a recorded result without contacting or restarting a provider."""
        self._binding(receipt)
        row = self.durable.operation_status(receipt.operation_id, receipt.owner)
        if row["state"] not in {"SUCCEEDED", "FAILED", "CANCELLED", "UNCERTAIN"}:
            return None
        stored = row.get("result") or {}
        aid = stored.get("evidence_artifact_id")
        if not aid:
            # Legacy digest-only records cannot assert a reconstructed payload.
            return None
        artifact = self.durable.artifact_info(aid, receipt.owner)
        if (artifact["run_id"] != receipt.run_id
                or artifact["operation_id"] != receipt.operation_id
                or artifact["sha256"] != stored.get("evidence_artifact_sha256")
                or artifact["metadata"].get("intent_sha256") != receipt.intent_sha256):
            raise ValueError("result artifact is not bound to the stored intent")
        data = json.loads(self.durable.read_artifact(aid, max_bytes=2_010_000))
        evidence = data["evidence"]
        payload = json.dumps(evidence, sort_keys=True, allow_nan=False,
                             ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if (data["schema"] != 1 or data["operation_id"] != receipt.operation_id
                or data["intent_sha256"] != receipt.intent_sha256
                or data["state"] != row["state"]
                or hashlib.sha256(payload).hexdigest() != stored.get("evidence_sha256")):
            raise ValueError("stored result receipt does not verify")
        return OperationResult(receipt.operation_id, row["state"], evidence, data.get("error"))

    def record_late_return(self,receipt: IntentReceipt,*,value=None,error_type=None) -> None:
        """Keep worker-return evidence without promoting an uncertain operation.

        This is a diagnostic annotation, not another physical dispatch or a
        terminal acknowledgement. A revoked/expired execution lease cannot
        authorize new I/O; it does not erase bytes returned by prior admitted I/O.
        """
        row=self._binding(receipt)
        if row["state"] not in {"RUNNING","UNCERTAIN","CANCEL_REQUESTED"}:return
        if isinstance(value,OperationResult):
            value={"reported_state":value.state,"evidence":dict(value.evidence),"error":value.error}
        evidence={"worker_returned":True,"operation_reconciled":False,
                  "reported_return":value,"error_type":error_type}
        try:
            payload=json.dumps(evidence,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(",",":")).encode()
            if len(payload)>2_000_000:raise ValueError("late return exceeds bound")
        except (ValueError,TypeError,OverflowError):
            evidence={"worker_returned":True,"operation_reconciled":False,
                      "reported_return_available":False,"error_type":error_type}
            payload=json.dumps(evidence,sort_keys=True,separators=(",",":")).encode()
        result=OperationResult(receipt.operation_id,"UNCERTAIN",evidence)
        stored=self._store_evidence(receipt,result,payload)
        self.durable.update_operation(receipt.operation_id,receipt.owner,
            progress={"late_return_artifact_id":stored["evidence_artifact_id"],
                      "late_return_artifact_sha256":stored["evidence_artifact_sha256"],
                      "late_return_evidence_sha256":stored["evidence_sha256"]},
            event_type="MACHINE_WORKER_RETURN_RECORDED")

    def late_return_for_receipt(self,receipt: IntentReceipt):
        row=self._binding(receipt);progress=json.loads(row["progress_json"])
        artifact_id=progress.get("late_return_artifact_id")
        if not artifact_id:return None
        artifact=self.durable.artifact_info(artifact_id,receipt.owner)
        if (artifact["operation_id"]!=receipt.operation_id or artifact["run_id"]!=receipt.run_id
                or artifact["sha256"]!=progress.get("late_return_artifact_sha256")
                or artifact["metadata"].get("intent_sha256")!=receipt.intent_sha256):
            raise ValueError("late return artifact scope mismatch")
        envelope=json.loads(self.durable.read_artifact(artifact_id,max_bytes=2_010_000))
        payload=json.dumps(envelope["evidence"],ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(",",":")).encode()
        if (envelope.get("schema")!=1 or envelope.get("operation_id")!=receipt.operation_id
                or envelope.get("intent_sha256")!=receipt.intent_sha256
                or hashlib.sha256(payload).hexdigest()!=progress.get("late_return_evidence_sha256")):
            raise ValueError("late return evidence does not verify")
        return envelope["evidence"]

    def record_result(self, receipt: IntentReceipt, result: OperationResult) -> bool:
        if (not isinstance(result, OperationResult)
                or receipt.operation_id != result.operation_id):
            return False
        try:
            row = self._binding(receipt)
            if result.state not in {"SUCCEEDED", "FAILED", "UNCERTAIN", "CANCELLED"}:
                return False
            # Keep result bytes in the owner-scoped Artifact registry, with
            # references/digests only in the authoritative operation ledger.
            try:
                payload = json.dumps(dict(result.evidence), sort_keys=True,
                                     allow_nan=False, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")
                if len(payload) > 2_000_000:
                    return False
            except (TypeError, ValueError, OverflowError, RecursionError):
                return False
            stored_result = self._store_evidence(receipt, result, payload)
            self.durable.update_operation(
                receipt.operation_id, receipt.owner,
                state=result.state,
                event_type="MACHINE_EFFECT_" + result.state,
                result=stored_result,
                error={"error_type": "external_result_uncertain"}
                      if result.state in {"FAILED", "UNCERTAIN"} else None,
                resource_key=row["resource_key"],
                fencing_token=receipt.fencing_token,
            )
            if self.release_on_terminal and (result.state in {"SUCCEEDED", "FAILED", "CANCELLED"}
                    or row["kind"]=="sentra.machine.observation" and result.state=="UNCERTAIN"):
                self.durable.release_lease(row["resource_key"], receipt.owner,
                                          receipt.fencing_token)
            return True
        except (StaleFenceError, DurableStateConflict, ValueError,
                FileNotFoundError, PermissionError, OSError, TypeError):
            return False
