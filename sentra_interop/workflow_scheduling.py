"""Durable enterprise binding between scheduled routines and workflows.

A routine firing (cron/interval/one-shot occurrence) becomes exactly one
workflow intent (create, advance/resume, or signal) with an idempotent
occurrence key derived from the schedule. The binding itself never executes
an effect: the host admits each intent as a distinct central operation
through ``CheckpointedWorkflowWorker`` and the governance routine service.

Human supervision is structural: binding a routine to a workflow and firing
a bound occurrence both require explicit ``operator_approved=True`` from the
host owner. This module only records the binding and builds exact intents.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .workflow_contracts import digest, ident
from .workflow_checkpoint import namespace


class WorkflowScheduleConflict(ValueError):
    pass


class RoutineWorkflowBinding:
    """Persist routine -> workflow intent templates with occurrence dedupe."""

    KINDS = frozenset({"create", "advance", "resume", "signal"})

    def __init__(self, database: str, *, workspace: str,
                 clock=time.time, control=None, definitions=()) -> None:
        self.definitions={(definition.definition_id,definition.version):definition for definition in definitions}
        self.control = control
        root, target = Path(workspace).resolve(), Path(database).resolve()
        if target == root or not target.is_relative_to(root):
            raise ValueError("schedule binding projection outside workspace")
        from .workflow_storage import projection_path
        projection_path(database, workspace, control=control)
        self.database, self.clock = str(target), clock
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS routine_workflow_bindings(
                routine_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                workflow_id TEXT NOT NULL, namespace TEXT NOT NULL,
                definition_id TEXT NOT NULL, definition_version TEXT NOT NULL,
                intent_kind TEXT NOT NULL, signal_name TEXT,
                updated REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS routine_workflow_occurrences(
                routine_id TEXT NOT NULL, occurrence_key TEXT NOT NULL,
                workflow_id TEXT NOT NULL, namespace TEXT NOT NULL,
                intent_kind TEXT NOT NULL, intent_sha256 TEXT NOT NULL,
                admitted_operation_id TEXT,
                PRIMARY KEY(routine_id, occurrence_key))""")

    @contextmanager
    def _db(self):
        from .workflow_storage import projection_db
        with projection_db(self.database, control=self.control) as conn:
            yield conn

    def bind(self, *, owner: str, routine_id: str, workflow_id: str,
             ns: str = "", definition_id: str, definition_version: str,
             intent_kind: str, signal_name: str | None = None,
             operator_approved: bool = False) -> dict:
        """Bind a governance routine to a workflow intent template."""
        if operator_approved is not True:
            raise PermissionError("host owner approval required to bind routine to workflow")
        if not isinstance(owner, str) or not owner:
            raise ValueError("owner scope required")
        ident(routine_id)
        ident(workflow_id)
        namespace(ns)
        ident(definition_id)
        ident(definition_version)
        if intent_kind not in self.KINDS:
            raise ValueError("unknown routine workflow intent kind")
        if intent_kind == "signal":
            ident(signal_name or "")
        elif signal_name is not None:
            raise ValueError("signal name only applies to signal intents")
        record = {"routine_id": routine_id, "owner": owner,
                  "workflow_id": workflow_id, "namespace": ns,
                  "definition_id": definition_id,
                  "definition_version": definition_version,
                  "intent_kind": intent_kind, "signal_name": signal_name,
                  "updated": self.clock()}
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM routine_workflow_bindings "
                             "WHERE routine_id=?", (routine_id,)).fetchone()
            if old is not None and (
                    old["owner"], old["workflow_id"], old["namespace"],
                    old["definition_id"], old["definition_version"],
                    old["intent_kind"], old["signal_name"]) != (
                    owner, workflow_id, ns, definition_id,
                    definition_version, intent_kind, signal_name):
                raise WorkflowScheduleConflict(
                    "routine already bound to a different workflow intent")
            db.execute("INSERT INTO routine_workflow_bindings VALUES(?,?,?,?,?,?,?,?,?) "
                       "ON CONFLICT(routine_id) DO UPDATE SET updated=excluded.updated",
                       (routine_id, owner, workflow_id, ns, definition_id,
                        definition_version, intent_kind, signal_name, record["updated"]))
        return record

    def unbind(self, *, owner: str, routine_id: str,
               operator_approved: bool = False) -> None:
        if operator_approved is not True:
            raise PermissionError("host owner approval required to unbind routine")
        with self._db() as db:
            row = db.execute("SELECT owner FROM routine_workflow_bindings "
                             "WHERE routine_id=?", (routine_id,)).fetchone()
            if row is None:
                raise FileNotFoundError("routine workflow binding not found")
            if row["owner"] != owner:
                raise PermissionError("routine binding belongs to another owner")
            db.execute("DELETE FROM routine_workflow_bindings WHERE routine_id=?",
                       (routine_id,))

    def intent_for_occurrence(self, *, owner: str, routine_id: str,
                              occurrence_key: str,
                              signal_payload: dict | None = None) -> dict:
        """Build the exact central intent for one schedule occurrence.

        Idempotent: the same occurrence key always yields the same intent and
        never stages a second admission. Re-firing after a lost reply must
        reconcile the recorded admission, not build a new identity.
        """
        if not isinstance(occurrence_key, str) or not occurrence_key:
            raise ValueError("bounded occurrence key required")
        with self._db() as db:
            binding = db.execute("SELECT * FROM routine_workflow_bindings "
                                 "WHERE routine_id=?", (routine_id,)).fetchone()
        if binding is None:
            raise FileNotFoundError("routine has no workflow binding")
        if binding["owner"] != owner:
            raise PermissionError("routine binding belongs to another owner")
        kind = binding["intent_kind"]
        workflow_id, ns = binding["workflow_id"], binding["namespace"]
        if kind == "create":
            definition=self.definitions.get((binding["definition_id"],binding["definition_version"]))
            if definition is None:
                raise WorkflowScheduleConflict("scheduled workflow definition pins unavailable")
            workflow_id="scheduled-"+digest([owner,routine_id,workflow_id,occurrence_key])[:48]
            arguments = {"workflow_id": workflow_id,
                         "definition_id": binding["definition_id"],
                         "definition_version": binding["definition_version"],
                         "definition_sha256": definition.fingerprint,
                         "input_sha256": digest(signal_payload or {})}
            capability = "workflow:create"
        elif kind in {"advance", "resume"}:
            arguments = {"workflow_id": workflow_id, "namespace": ns}
            capability = "workflow:" + kind
        else:
            if not isinstance(signal_payload, dict):
                raise ValueError("signal intent requires a JSON mapping payload")
            signal_id = "sched-" + hashlib.sha256(
                f"{routine_id}|{occurrence_key}".encode()).hexdigest()[:32]
            arguments = {"workflow_id": workflow_id, "namespace": ns,
                         "name": binding["signal_name"], "signal_id": signal_id,
                         "payload_sha256": digest(signal_payload)}
            capability = "workflow:signal"
        intent_sha = digest({"capability": capability, "arguments": arguments})
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM routine_workflow_occurrences "
                             "WHERE routine_id=? AND occurrence_key=?",
                             (routine_id, occurrence_key)).fetchone()
            if old is not None:
                if (old["workflow_id"], old["namespace"], old["intent_kind"],
                        old["intent_sha256"]) != (workflow_id, ns, kind, intent_sha):
                    raise WorkflowScheduleConflict(
                        "occurrence already admitted with a different intent")
                return {"capability_id": capability, "arguments": arguments,
                        "occurrence_key": occurrence_key,
                        "already_admitted": old["admitted_operation_id"] is not None}
            db.execute("INSERT INTO routine_workflow_occurrences VALUES(?,?,?,?,?,?,NULL)",
                       (routine_id, occurrence_key, workflow_id, ns, kind, intent_sha))
        return {"capability_id": capability, "arguments": arguments,
                "occurrence_key": occurrence_key, "already_admitted": False}

    def execute_occurrence(self, *, owner, routine_id, occurrence_key, ctx, resolver, signal_payload=None):
        if self.control is None or not callable(resolver) or ctx["owner"]!=owner:
            raise WorkflowScheduleConflict("configured central workflow resolver required")
        intent=self.intent_for_occurrence(owner=owner,routine_id=routine_id,
            occurrence_key=occurrence_key,signal_payload=signal_payload)
        arguments=dict(intent["arguments"])
        kind=intent["capability_id"].split(":")[1]
        if kind=="create":
            arguments.pop("definition_sha256")
            arguments.pop("input_sha256")
            arguments["inputs"]=dict(signal_payload or {})
        elif kind=="signal":
            arguments.pop("payload_sha256")
            arguments["payload"]=dict(signal_payload)
        arguments["intent_kind"]=kind
        from .workflow_shell_host import server_operation_id
        trusted={**ctx,"request_key":"schedule-"+digest([owner,routine_id,occurrence_key])}
        operation_id=server_operation_id(trusted,intent["capability_id"])
        self.mark_admitted(routine_id=routine_id,occurrence_key=occurrence_key,operation_id=operation_id)
        result=resolver("execute",trusted,arguments)
        if not isinstance(result,dict) or result.get("operation_id")!=operation_id or result.get("state") is None:
            raise WorkflowScheduleConflict("schedule resolver did not return its executed central receipt")
        return result

    def mark_admitted(self, *, routine_id: str, occurrence_key: str,
                      operation_id: str) -> None:
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("central operation identity required")
        with self._db() as db:
            updated = db.execute(
                "UPDATE routine_workflow_occurrences SET admitted_operation_id=? "
                "WHERE routine_id=? AND occurrence_key=? "
                "AND (admitted_operation_id IS NULL OR admitted_operation_id=?)",
                (operation_id, routine_id, occurrence_key, operation_id)).rowcount
            if updated != 1:
                raise ValueError("unknown occurrence or conflicting admission")

    def occurrences(self, routine_id: str, limit: int = 100) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("occurrence page limit must be 1..1000")
        with self._db() as db:
            rows = db.execute("SELECT * FROM routine_workflow_occurrences "
                              "WHERE routine_id=? ORDER BY occurrence_key DESC LIMIT ?",
                              (routine_id, limit)).fetchall()
        return [dict(row) for row in rows]
