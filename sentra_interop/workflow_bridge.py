"""Subordinate durable *local* workflow boundary; NOT Temporal/LangGraph runtime.

Legacy fixture steps retain their existing API. bind_worker opts into the real
host-admitted worker with protected checkpoints, wait/signal/subflow recovery,
bounded classified retries and configured SDK/HTTP piece execution. Neither
mode is a standalone Temporal/LangGraph service or an operations authority.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Awaitable, Mapping

from sentra_runtime.contracts import OperationRequest, OperationResult
from .gate import InteropGate, DispatchOutcome, _fingerprint
from .requests import _bounded, InteropMappingDenied

SCHEMA_VERSION = 1
STATES = frozenset({"IN_FLIGHT", "SUCCEEDED", "FAILED", "UNCERTAIN", "CANCELLED"})


class WorkflowReplayDenied(ValueError):
    pass


class SubagentWorkflowBridge:
    """Single-workspace, SQLite-local, versioned CAS for two+ worker fixtures."""

    def __init__(self, gate: InteropGate, *, database: str,
                 workspace_root: str, workflow_id: str, work_item_id: str,
                 principal_id: str) -> None:
        root, target = Path(workspace_root).resolve(), Path(database).resolve()
        if (not root.is_dir() or target == root or not target.is_relative_to(root)
            or not all(isinstance(x, str) and 0 < len(x) <= 128
                       for x in (workflow_id, work_item_id, principal_id))):
            raise ValueError("invalid trusted workflow scope or local ledger path")
        target.parent.mkdir(parents=True, exist_ok=True)
        self.gate, self.database, self.workflow_id = gate, target, workflow_id
        self.work_item_id, self.principal_id = work_item_id, principal_id
        self.worker = None
        with self._db() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS workflows(
                workflow_id TEXT PRIMARY KEY, work_item_id TEXT NOT NULL,
                principal_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
                revision INTEGER NOT NULL CHECK(revision>=0))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS steps(
                workflow_id TEXT NOT NULL, step_id TEXT NOT NULL,
                operation_id TEXT UNIQUE NOT NULL, idempotency_key TEXT UNIQUE NOT NULL,
                fingerprint TEXT NOT NULL, state TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision>=0),
                result_sha256 TEXT, PRIMARY KEY(workflow_id,step_id),
                FOREIGN KEY(workflow_id) REFERENCES workflows(workflow_id))""")
            existing = conn.execute("SELECT work_item_id,principal_id,schema_version "
                                    "FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
            if existing:
                if existing != (work_item_id, principal_id, SCHEMA_VERSION):
                    raise ValueError("checkpoint schema/identity mismatch")
            else:
                conn.execute("INSERT INTO workflows VALUES (?,?,?,?,?)",
                             (workflow_id,work_item_id,principal_id,SCHEMA_VERSION,0))

    def bind_worker(self,*,definitions,bindings,worker_version,compatible_worker_versions=frozenset(),payload_resolver=None):
        """Opt into real centrally admitted execution on this existing bridge.

        The old steps table remains a legacy harness projection. Real-mode
        effects use configured bindings and the central operation journal.
        No generic injected effect is executed through legacy run_step.
        """
        from .workflow_checkpoint import WorkflowCheckpointStore
        from .workflow_worker import CheckpointedWorkflowWorker
        self.worker=CheckpointedWorkflowWorker(self.gate,
            store=WorkflowCheckpointStore(str(self.database),workspace=str(self.database.parent)),
            definitions=definitions,bindings=bindings,worker_version=worker_version,
            compatible_worker_versions=compatible_worker_versions,payload_resolver=payload_resolver,
            scope=(self.workflow_id,self.principal_id,self.gate.machine.machine_id,self.work_item_id))
        return self.worker

    async def start_workflow(self,request,*,definition_id,definition_version,inputs):
        if self.worker is None: raise ValueError("real workflow worker not configured")
        return await self.worker.create(request,workflow_id=self.workflow_id,definition_id=definition_id,
                                        definition_version=definition_version,inputs=inputs)

    async def advance(self,request,*,namespace="",resume=False):
        if self.worker is None: raise ValueError("real workflow worker not configured")
        return await self.worker.advance(request,workflow_id=self.workflow_id,ns=namespace,resume=resume)

    async def activity(self,request,*,step_id,namespace=""):
        if self.worker is None: raise ValueError("real workflow worker not configured")
        return await self.worker.run_activity(request,workflow_id=self.workflow_id,ns=namespace,step_id=step_id)

    async def signal(self,request,*,name,signal_id,payload,namespace=""):
        if self.worker is None: raise ValueError("real workflow worker not configured")
        return await self.worker.signal(request,workflow_id=self.workflow_id,ns=namespace,name=name,signal_id=signal_id,payload=payload)

    async def cancel_workflow(self,request,*,namespace=""):
        if self.worker is None: raise ValueError("real workflow worker not configured")
        return await self.worker.cancel(request,workflow_id=self.workflow_id,ns=namespace)

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.database,timeout=10)
        try:
            conn.execute("PRAGMA busy_timeout=10000")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def checkpoint(self) -> Mapping[str, Any]:
        if self.worker is not None:
            raise WorkflowReplayDenied("real workflow checkpoints require an admitted worker.observe request")
        with self._db() as conn:
            revision, schema = conn.execute(
                "SELECT revision,schema_version FROM workflows WHERE workflow_id=?",
                (self.workflow_id,)).fetchone()
            entries = conn.execute(
                "SELECT step_id,state,revision,result_sha256 FROM steps WHERE workflow_id=? "
                "ORDER BY step_id", (self.workflow_id,)).fetchall()
        return {"workflow_id":self.workflow_id,"work_item_id":self.work_item_id,
                "schema_version":schema, "revision":revision,
                "steps":[{"step_id":s,"state":state,"revision":rev,
                          "result_sha256":digest}
                         for s,state,rev,digest in entries]}

    def _bump(self, conn: sqlite3.Connection) -> None:
        prior = conn.execute("SELECT revision FROM workflows WHERE workflow_id=?",
                             (self.workflow_id,)).fetchone()[0]
        updated = conn.execute(
            "UPDATE workflows SET revision=? WHERE workflow_id=? AND revision=?",
            (prior+1,self.workflow_id,prior)).rowcount
        if updated != 1:
            raise WorkflowReplayDenied("workflow checkpoint CAS mismatch")

    def _reserve(self, request: OperationRequest, step_id: str) -> None:
        fp = _fingerprint(request)
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            collided = conn.execute(
                "SELECT operation_id FROM steps WHERE operation_id=? OR idempotency_key=? "
                "OR (workflow_id=? AND step_id=?)",
                (request.operation_id,request.idempotency_key,self.workflow_id,step_id),
            ).fetchone()
            if collided:
                raise WorkflowReplayDenied("workflow step already claimed; reconciliation required")
            conn.execute("""INSERT INTO steps VALUES (?,?,?,?,?,?,?,?)""",(
                self.workflow_id, step_id, request.operation_id, request.idempotency_key,
                fp, "IN_FLIGHT", 0, None))
            self._bump(conn)

    def _finish(self, request: OperationRequest, step_id: str,
                state: str, digest: str | None) -> None:
        if state not in STATES - {"IN_FLIGHT"}:
            raise ValueError("invalid checkpoint transition")
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT fingerprint,revision,state FROM steps "
                "WHERE workflow_id=? AND step_id=? AND operation_id=?",
                (self.workflow_id,step_id,request.operation_id)).fetchone()
            if not row or row[0] != _fingerprint(request) or row[2] != "IN_FLIGHT":
                raise WorkflowReplayDenied("workflow operation changed or already terminal")
            if conn.execute(
                "UPDATE steps SET state=?,revision=?,result_sha256=? "
                "WHERE workflow_id=? AND step_id=? AND revision=? AND state='IN_FLIGHT'",
                (state,row[1]+1,digest,self.workflow_id,step_id,row[1])).rowcount != 1:
                raise WorkflowReplayDenied("step checkpoint CAS mismatch")
            self._bump(conn)

    def reconcile(self, step_id: str) -> OperationResult | None:
        """On restart only: IN_FLIGHT -> UNCERTAIN, never auto-rerun."""
        if self.worker is not None:
            raise WorkflowReplayDenied("real workflow recovery requires central worker.advance/observe_activity")
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT operation_id,state,revision FROM steps WHERE workflow_id=? AND step_id=?",
                (self.workflow_id,step_id)).fetchone()
            if not row:
                return None
            operation, state, revision = row
            if state == "IN_FLIGHT":
                conn.execute(
                    "UPDATE steps SET state='UNCERTAIN',revision=? "
                    "WHERE workflow_id=? AND step_id=? AND revision=?",
                    (revision+1,self.workflow_id,step_id,revision))
                self._bump(conn)
                state = "UNCERTAIN"
            return OperationResult(operation,state)

    async def run_step(
        self, request: OperationRequest, *,
        step_id: str, effect: Callable[[], Awaitable[Mapping[str, Any]]],
        timeout: float = 3,
    ) -> DispatchOutcome:
        if self.worker is not None:
            raise WorkflowReplayDenied("real mode requires configured activity bindings; legacy effect injection disabled")
        if (not isinstance(step_id,str) or not 0 < len(step_id) <= 128
            or request.capability_id != "workflow:step"
            or request.principal_id != self.principal_id
            or request.work_item_id != self.work_item_id
            or request.machine_id != self.gate.machine.machine_id
            or request.arguments != {"workflow_id":self.workflow_id,
                                     "step_id":step_id,
                                     "checkpoint_version":SCHEMA_VERSION}
            or not 0 < timeout <= 60):
            return DispatchOutcome(OperationResult(request.operation_id,"FAILED",
                                                   error="subworkflow identity/scope mismatch"))
        if not (await self.gate.decision(request)).allowed:
            return DispatchOutcome(OperationResult(request.operation_id,"FAILED",
                                                   error="workflow grant denied"))
        # Reserve before effect. Duplicate and UNCERTAIN may not be rerun.
        self._reserve(request,step_id)
        result: DispatchOutcome | None = None
        try:
            result = await self.gate.execute(request,effect,timeout=timeout)
            digest: str | None = None
            if result.operation.state=="SUCCEEDED":
                try:
                    value = _bounded(result.payload)
                    if set(value) != {"worker","result"} or not isinstance(
                        value["worker"],str) or not isinstance(value["result"],str):
                        raise ValueError("invalid worker receipt")
                    digest = hashlib.sha256(json.dumps(value,sort_keys=True,
                                                        separators=(",",":")).encode()).hexdigest()
                except (ValueError,TypeError,InteropMappingDenied):
                    result = DispatchOutcome(OperationResult(request.operation_id,"UNCERTAIN",
                                                              error="unverifiable worker receipt"))
                    await self.gate.journal.finish(request,result.operation)
            self._finish(request,step_id,result.operation.state,digest)
            return result
        except asyncio.CancelledError:
            self._finish(request,step_id,"UNCERTAIN",None)
            raise
        except BaseException:
            self._finish(request,step_id,"UNCERTAIN",None)
            raise
