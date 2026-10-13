"""Real Temporal and LangGraph runtime adapters, subordinate to Run/WorkItem.

These are configurable SDK/worker bindings, not semantic analogies and not
a second scheduler or authority:

- The host injects a real, already-authenticated SDK client object
  (a ``temporalio`` client or a ``langgraph`` compiled graph/worker) at
  :meth:`configure`. The adapter verifies the client surface and SDK
  version, pins server/namespace/task-queue/graph, definition and worker
  versions, and persists external identities (Temporal workflow/run IDs,
  LangGraph thread/checkpoint IDs) as local projections.
- Every effect (``start``/``advance``/``signal``/``interrupt``/``resume``/
  ``cancel``) requires a *current* central physical-effect admission whose
  receipt matches the bound Run/owner, exactly like the existing ConPTY and
  workflow transports. Reads (``observe``) need no admission but perform
  no effect either.
- Outcomes reuse the classified semantics of ``workflow_temporal`` and
  ``workflow_langgraph``. Ambiguous loss becomes UNCERTAIN and is never
  replayed; reconciliation consults the provider before any new intent.
- When no SDK client/server is configured, every operation fails
  explicitly with :class:`RuntimeUnavailable`. Nothing is simulated.

Required signature per contract: ``configure`` / ``start`` / ``advance`` /
``signal`` / ``cancel`` / ``observe`` / ``reconcile`` (plus ``interrupt`` /
``resume`` / ``fork`` where the provider supports them).
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .workflow_contracts import digest, ident
from .workflow_checkpoint import namespace


class RuntimeUnavailable(RuntimeError):
    pass


class RuntimeScopeConflict(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeScope:
    owner: str
    run_id: str
    work_item_id: str
    principal_id: str
    machine_id: str = ""
    workspace_id: str = ""


def _scope_key(scope: RuntimeScope) -> str:
    for value in (scope.owner, scope.run_id, scope.work_item_id,
                  scope.principal_id):
        if not isinstance(value, str) or not value:
            raise ValueError("bounded runtime scope required")
    return hashlib.sha256("|".join(
        (scope.owner, scope.run_id, scope.work_item_id,
         scope.principal_id)).encode()).hexdigest()[:32]


class SubordinateRuntimeAdapter:
    """Shared subordinate plumbing: config pins, admission gate, projections."""

    PROVIDER = "base"
    REQUIRED_CLIENT_ATTRS: tuple[str, ...] = ()

    def __init__(self, database: str, *, workspace: str,
                 clock=time.time, control=None) -> None:
        root, target = Path(workspace).resolve(), Path(database).resolve()
        if target == root or not target.is_relative_to(root):
            raise ValueError("runtime projection outside workspace")
        from .workflow_storage import projection_path
        self.control = control
        self.database = projection_path(database, workspace, control=control)
        self.clock = clock
        self._client: Any = None
        self._config: dict[str, Any] | None = None
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS rt_bindings(
                binding_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
                owner TEXT NOT NULL, run_id TEXT NOT NULL,
                work_item_id TEXT NOT NULL, principal_id TEXT NOT NULL,
                server TEXT NOT NULL, scope_name TEXT NOT NULL,
                target_name TEXT NOT NULL, sdk_name TEXT NOT NULL,
                sdk_version TEXT NOT NULL, worker_version TEXT NOT NULL,
                compatible_versions TEXT NOT NULL,
                definition_id TEXT NOT NULL, definition_version TEXT NOT NULL,
                config_sha256 TEXT NOT NULL, external_namespace TEXT NOT NULL,
                created REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS rt_external_ids(
                binding_id TEXT NOT NULL, local_workflow_id TEXT NOT NULL,
                local_namespace TEXT NOT NULL, external_id TEXT NOT NULL,
                external_run TEXT, admitted_operation_id TEXT NOT NULL,
                state TEXT NOT NULL, updated REAL NOT NULL,
                PRIMARY KEY(binding_id, local_workflow_id, local_namespace))""")

    @contextmanager
    def _db(self):
        from .workflow_storage import projection_db
        with projection_db(self.database, control=self.control) as conn:
            yield conn

    # -- configuration -------------------------------------------------
    def configure(self, *, owner: str, scope: RuntimeScope,
                  server: str, scope_name: str, target_name: str,
                  sdk_client: Any, sdk_name: str, sdk_version: str,
                  worker_version: str, compatible_versions=(),
                  definition_id: str, definition_version: str,
                  operator_approved: bool = False) -> dict[str, Any]:
        """Pin a real SDK client to this Run/WorkItem scope.

        ``sdk_client`` is the host-provisioned, authenticated client object.
        ``sdk_version`` is the exact client library version the host
        provisioned (verified against the client's own version attribute
        when it exposes one). No connection is opened here beyond the
        client's own constructor; every later effect still needs central
        admission.
        """
        if operator_approved is not True:
            raise PermissionError("host owner approval required to configure runtime")
        _scope_key(scope)
        if scope.owner != owner:
            raise RuntimeScopeConflict("runtime scope belongs to another owner")
        if sdk_client is None:
            raise RuntimeUnavailable(
                f"no {self.PROVIDER} SDK client configured; provision an "
                "authenticated client and server before configuring the runtime")
        missing = [attr for attr in self.REQUIRED_CLIENT_ATTRS
                   if not callable(getattr(sdk_client, attr, None))]
        if missing:
            raise RuntimeUnavailable(
                f"{self.PROVIDER} client misses required surface: "
                + ",".join(sorted(missing)))
        reported = getattr(sdk_client, "sdk_version", None) or getattr(
            sdk_client, "__version__", None) or sdk_version
        if not isinstance(sdk_version, str) or not sdk_version:
            raise ValueError("exact SDK version pin required")
        if isinstance(reported, str) and reported and reported != sdk_version:
            raise RuntimeScopeConflict("provisioned SDK version differs from pin")
        ident(worker_version)
        ident(definition_id)
        ident(definition_version)
        if not isinstance(server, str) or not server or len(server) > 512:
            raise ValueError("explicit runtime server address required")
        for value in (scope_name, target_name):
            if not isinstance(value, str) or not 1 <= len(value) <= 256:
                raise ValueError("bounded runtime scope/target name required")
        compat = sorted(set(compatible_versions) | {worker_version})
        for version in compat:
            ident(version)
        config = {"provider": self.PROVIDER, "server": server,
                  "scope_name": scope_name, "target_name": target_name,
                  "sdk_name": sdk_name, "sdk_version": sdk_version,
                  "worker_version": worker_version,
                  "compatible_versions": compat,
                  "definition_id": definition_id,
                  "definition_version": definition_version}
        config_sha = digest(config)
        binding_id = "rt-" + hashlib.sha256("|".join(
            (owner, scope.run_id, scope.work_item_id, self.PROVIDER,
             server, scope_name, target_name)).encode()).hexdigest()[:32]
        record = {"binding_id": binding_id, "provider": self.PROVIDER,
                  "owner": owner, "run_id": scope.run_id,
                  "work_item_id": scope.work_item_id,
                  "principal_id": scope.principal_id, **config,
                  "config_sha256": config_sha,
                  "external_namespace": scope_name, "created": self.clock()}
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM rt_bindings WHERE binding_id=?",
                             (binding_id,)).fetchone()
            if old is not None and (
                    old["config_sha256"] != config_sha
                    or old["principal_id"] != scope.principal_id):
                raise RuntimeScopeConflict(
                    "runtime binding already configured differently")
            db.execute("INSERT OR IGNORE INTO rt_bindings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (binding_id, self.PROVIDER, owner, scope.run_id,
                        scope.work_item_id, scope.principal_id, server,
                        scope_name, target_name, sdk_name, sdk_version,
                        worker_version, ",".join(compat), definition_id,
                        definition_version, config_sha, scope_name,
                        record["created"]))
        self._client, self._config = sdk_client, record
        return record

    def _bound(self) -> tuple[Any, dict[str, Any]]:
        if self._client is None or self._config is None:
            raise RuntimeUnavailable(
                f"{self.PROVIDER} runtime not configured; configure an "
                "authenticated SDK client and server first")
        return self._client, self._config

    def _admission(self, scope: RuntimeScope):
        """Require a current central admission matching this Run/owner."""
        from sentra_runtime.effect_boundary import (
            CentralEffectContext, current_effect_context)
        context = current_effect_context.get()
        if not isinstance(context, CentralEffectContext):
            raise PermissionError(
                f"no current central durable {self.PROVIDER} effect admission")
        receipt, request = context.receipt, context.request
        if (receipt.owner != scope.owner or receipt.run_id != scope.run_id
                or request.work_item_id != scope.work_item_id
                or request.principal_id != scope.principal_id
                or (scope.machine_id and request.machine_id != scope.machine_id)):
            raise PermissionError(
                f"{self.PROVIDER} effect intent does not match durable operation")
        if not request.capability_id.startswith("runtime:"+self.PROVIDER+":") or request.arguments.get("binding_id") != self._bound()[1]["binding_id"]:
            raise PermissionError("runtime effect capability/binding differs")
        context.checkpoint()
        return context

    def _record_external(self, *, binding_id: str, local_workflow_id: str,
                         local_namespace: str, external_id: str,
                         external_run: str | None, operation_id: str,
                         state: str) -> None:
        ident(local_workflow_id)
        namespace(local_namespace)
        with self._db() as db:
            db.execute(
                "INSERT INTO rt_external_ids VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(binding_id,local_workflow_id,local_namespace) "
                "DO UPDATE SET external_id=excluded.external_id,"
                "external_run=COALESCE(excluded.external_run,rt_external_ids.external_run),"
                "admitted_operation_id=excluded.admitted_operation_id,"
                "state=excluded.state,updated=excluded.updated",
                (binding_id, local_workflow_id, local_namespace, external_id,
                 external_run, operation_id, state, self.clock()))

    def _reserve_start(self, scope, workflow_id, occurrence, external_id):
        context = self._admission(scope)
        ident(occurrence)
        config = self._bound()[1]
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT 1 FROM rt_external_ids WHERE binding_id=? AND "
                "local_workflow_id=? AND local_namespace=?",
                (config["binding_id"], workflow_id, occurrence)).fetchone()
            if old:
                raise RuntimeScopeConflict("occurrence exists or is uncertain; reconcile without replay")
            db.execute("INSERT INTO rt_external_ids VALUES(?,?,?,?,?,?,?,?)",
                (config["binding_id"], workflow_id, occurrence, external_id, None,
                 context.receipt.operation_id, "PREPARED", self.clock()))

    def external_ids(self, binding_id: str) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM rt_external_ids WHERE binding_id=? "
                              "ORDER BY local_workflow_id,local_namespace",
                              (binding_id,)).fetchall()
        return [dict(row) for row in rows]


class TemporalRuntimeAdapter(SubordinateRuntimeAdapter):
    """Real Temporal client binding, subordinate to the central journal.

    Compatible with the ``temporalio`` Python client surface
    (``start_workflow`` / ``get_workflow_handle`` with ``signal`` /
    ``query`` / ``cancel`` / ``describe`` / ``fetch_history_events``).
    Workflow IDs embed the SENTRA scope and the occurrence digest with
    reject-duplicate reuse, so one occurrence is one Temporal workflow.
    """

    PROVIDER = "temporal"
    REQUIRED_CLIENT_ATTRS = ("start_workflow", "get_workflow_handle")

    def _temporal_id(self, scope: RuntimeScope, workflow_id: str,
                     occurrence: str) -> str:
        ident(workflow_id)
        occurrence_digest = hashlib.sha256(
            f"{workflow_id}|{occurrence}".encode()).hexdigest()[:16]
        return "sentra-" + digest([_scope_key(scope), workflow_id, occurrence])

    def _handle(self, client, scope, workflow_id, occurrence):
        config = self._bound()[1]
        with self._db() as db:
            row = db.execute("SELECT external_id,external_run FROM rt_external_ids WHERE binding_id=? AND local_workflow_id=? AND local_namespace=?",
                (config["binding_id"], workflow_id, occurrence)).fetchone()
        if row is None:
            raise RuntimeScopeConflict("runtime occurrence has not been admitted")
        return client.get_workflow_handle(row["external_id"], first_execution_run_id=row["external_run"])

    async def start(self, scope: RuntimeScope, *, workflow_id: str,
                    occurrence: str, inputs: dict) -> dict[str, Any]:
        client, config = self._bound()
        context = self._admission(scope)
        if not isinstance(inputs, dict):
            raise ValueError("Temporal workflow inputs must be a mapping")
        digest(inputs)
        temporal_id = self._temporal_id(scope, workflow_id, occurrence)
        operation_id = context.receipt.operation_id
        from temporalio.common import WorkflowIDReusePolicy, RetryPolicy
        from datetime import timedelta
        self._reserve_start(scope, workflow_id, occurrence, temporal_id)
        try:
            context.checkpoint()
            handle = await client.start_workflow(
                config["target_name"], inputs, id=temporal_id,
                task_queue=config["scope_name"],
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=timedelta(seconds=config.get("execution_timeout_seconds", 3600)),
                memo={"sentra_run_id": scope.run_id,
                      "sentra_work_item_id": scope.work_item_id,
                      "sentra_definition": config["definition_id"] + "@"
                      + config["definition_version"],
                      "sentra_worker_version": config["worker_version"]})
        except Exception as exc:
            return {"workflow_id": workflow_id, "temporal_id": temporal_id,
                    "status": "UNCERTAIN", "failure_type": type(exc).__name__,
                    "operation_id": operation_id, "replayed_effect": False}
        run_id = getattr(handle, "result_run_id", None) or getattr(handle, "first_execution_run_id", None) or getattr(handle, "run_id", None)
        self._record_external(
            binding_id=config["binding_id"], local_workflow_id=workflow_id,
            local_namespace=occurrence, external_id=temporal_id,
            external_run=run_id if isinstance(run_id, str) else None,
            operation_id=operation_id, state="STARTED")
        return {"workflow_id": workflow_id, "temporal_id": temporal_id,
                "temporal_run_id": run_id, "status": "STARTED",
                "operation_id": operation_id, "replayed_effect": False}

    async def advance(self, scope: RuntimeScope, *, workflow_id: str,
                      occurrence: str, payload: dict | None = None) -> dict[str, Any]:
        return await self.signal(scope, workflow_id=workflow_id,
                                 occurrence=occurrence, name="sentra_advance",
                                 payload=payload or {})

    async def signal(self, scope: RuntimeScope, *, workflow_id: str,
                     occurrence: str, name: str,
                     payload: dict) -> dict[str, Any]:
        from .workflow_contracts import digest as _digest
        client, config = self._bound()
        context = self._admission(scope)
        ident(name)
        if not isinstance(payload, dict):
            raise ValueError("Temporal signal payload must be a mapping")
        _digest(payload)
        handle = self._handle(client, scope, workflow_id, occurrence)
        try:
            context.checkpoint()
            await handle.signal(name, payload)
        except Exception as exc:
            return {"workflow_id": workflow_id, "status": "UNCERTAIN",
                    "failure_type": type(exc).__name__, "replayed_effect": False,
                    "operation_id": context.receipt.operation_id}
        self._record_external(
            binding_id=config["binding_id"], local_workflow_id=workflow_id,
            local_namespace=occurrence, external_id=self._temporal_id(
                scope, workflow_id, occurrence),
            external_run=None, operation_id=context.receipt.operation_id,
            state="SIGNALLED")
        return {"workflow_id": workflow_id, "signal": name, "status": "SIGNALLED",
                "operation_id": context.receipt.operation_id,
                "replayed_effect": False}

    async def interrupt(self, scope: RuntimeScope, *, workflow_id: str,
                        occurrence: str, reason: str) -> dict[str, Any]:
        if not isinstance(reason, str) or not 1 <= len(reason) <= 512:
            raise ValueError("bounded interrupt reason required")
        return await self.signal(scope, workflow_id=workflow_id,
                                 occurrence=occurrence, name="sentra_interrupt",
                                 payload={"reason": reason})

    async def resume(self, scope: RuntimeScope, *, workflow_id: str,
                     occurrence: str, payload: dict) -> dict[str, Any]:
        return await self.signal(scope, workflow_id=workflow_id,
                                 occurrence=occurrence, name="sentra_resume",
                                 payload=payload)

    async def cancel(self, scope: RuntimeScope, *, workflow_id: str,
                     occurrence: str) -> dict[str, Any]:
        client, config = self._bound()
        context = self._admission(scope)
        handle = self._handle(client, scope, workflow_id, occurrence)
        try:
            context.checkpoint()
            await handle.cancel()
        except Exception as exc:
            return {"workflow_id": workflow_id, "status": "UNCERTAIN",
                    "failure_type": type(exc).__name__,
                    "note": "cancellation requests cooperative stop; started "
                            "external effects are never rolled back",
                    "operation_id": context.receipt.operation_id}
        self._record_external(
            binding_id=config["binding_id"], local_workflow_id=workflow_id,
            local_namespace=occurrence, external_id=self._temporal_id(
                scope, workflow_id, occurrence),
            external_run=None, operation_id=context.receipt.operation_id,
            state="CANCEL_REQUESTED")
        return {"workflow_id": workflow_id, "status": "CANCEL_REQUESTED",
                "operation_id": context.receipt.operation_id}

    async def observe(self, scope: RuntimeScope, *, workflow_id: str,
                      occurrence: str) -> dict[str, Any]:
        """Read Temporal status/history. Read-only: never starts an effect."""
        from .workflow_temporal import classify_temporal_failure
        client, config = self._bound()
        _scope_key(scope)
        if (config["owner"], config["run_id"], config["work_item_id"], config["principal_id"]) != (scope.owner, scope.run_id, scope.work_item_id, scope.principal_id):
            raise RuntimeScopeConflict("observe scope differs from binding")
        handle = self._handle(client, scope, workflow_id, occurrence)
        context = self._admission(scope)
        try:
            context.checkpoint()
            description = await handle.describe()
        except Exception as exc:
            return {"workflow_id": workflow_id, "status": "UNCERTAIN",
                    "failure_type": type(exc).__name__}
        context.checkpoint()
        memo = await description.memo()
        expected = {"sentra_run_id":scope.run_id,"sentra_work_item_id":scope.work_item_id,
            "sentra_definition":config["definition_id"]+"@"+config["definition_version"]}
        if any(memo.get(key)!=value for key,value in expected.items()) or memo.get("sentra_worker_version") not in config["compatible_versions"] or description.task_queue!=config["scope_name"]:
            return {"workflow_id":workflow_id,"status":"UNCERTAIN","failure_type":"PROVIDER_IDENTITY_PIN_MISMATCH","replayed_effect":False}
        status = getattr(description, "status", None)
        status_name = getattr(status, "name", None) or str(status)
        history: list[dict[str, Any]] = []
        fetch = getattr(handle, "fetch_history_events", None)
        if callable(fetch):
            try:
                context.checkpoint()
                iterator=fetch().__aiter__()
                for _ in range(200):
                    context.checkpoint()
                    try:
                        event=await iterator.__anext__()
                    except StopAsyncIteration:
                        break
                    event_type=getattr(event,"event_type",None)
                    from temporalio.api.enums.v1 import EventType
                    name=EventType.Name(event_type)
                    history.append({"event":name})
            except Exception:
                return {"workflow_id": workflow_id,
                        "temporal_status": status_name, "status": "UNCERTAIN",
                        "note": "history unreadable; reconcile before acting"}
        failure_types = [entry["event"] for entry in history
                         if "FAILED" in entry["event"] or "TIMED_OUT" in entry["event"]]
        verdict = classify_temporal_failure(
            failure_type=failure_types[-1] if failure_types else None,
            effect_state="UNKNOWN" if status_name not in {
                "RUNNING", "COMPLETED", "FAILED", "CANCELED", "TERMINATED",
                "CONTINUED_AS_NEW", "TIMED_OUT"} else "COMPLETED")
        terminal = {"COMPLETED": "SUCCEEDED", "FAILED": "FAILED",
                    "CANCELED": "CANCELLED", "TERMINATED": "CANCELLED"}
        return {"workflow_id": workflow_id, "temporal_status": status_name,
                "history_events": len(history),
                "failure_class": verdict,
                "status": terminal.get(status_name, "UNCERTAIN"
                                       if verdict == "UNCERTAIN" else "RUNNING")}

    async def reconcile(self, scope: RuntimeScope, *, workflow_id: str,
                        occurrence: str) -> dict[str, Any]:
        """Consult the provider; ambiguous stays UNCERTAIN, never replays."""
        observed = await self.observe(scope, workflow_id=workflow_id,
                                      occurrence=occurrence)
        if observed["status"] == "UNCERTAIN":
            return {**observed, "replayed_effect": False,
                    "action": "await provider; do not resubmit"}
        return {**observed, "replayed_effect": False}

    def retry_kwargs(self) -> dict[str, Any]:
        """Constructor kwargs for a Temporal RetryPolicy of the pinned SDK.

        Returns plain values the host passes to
        ``temporalio.common.RetryPolicy`` (or the provisioned equivalent);
        non-retryable application types mirror ``workflow_temporal``.
        """
        from .workflow_temporal import TERMINAL_APPLICATION_TYPES
        _, config = self._bound()
        policy = {"maximum_attempts": 3, "initial_interval_seconds": 1.0,
                  "maximum_interval_seconds": 60.0, "backoff_coefficient": 2.0,
                  "maximum_interval_expiration_seconds": 3600.0,
                  "non_retryable_error_types": sorted(TERMINAL_APPLICATION_TYPES)}
        _ = config
        return policy


class LangGraphRuntimeAdapter(SubordinateRuntimeAdapter):
    """Real LangGraph graph binding, subordinate to the central journal.

    Compatible with a compiled ``langgraph`` graph surface (``ainvoke`` /
    ``astream`` / ``aget_state`` / ``aupdate_state``). Thread IDs embed the
    SENTRA scope and occurrence; checkpoints form parent lineage in the
    local projection while the provider remains the execution store.
    Forking creates a new thread from a checkpoint and never rewrites
    history. Cancellation is cooperative and never rolls back effects.
    """

    PROVIDER = "langgraph"
    REQUIRED_CLIENT_ATTRS = ("ainvoke", "aget_state", "aupdate_state")

    def __init__(self, database: str, *, workspace: str,
                 signal_channel: str = "sentra_signal", clock=time.time, control=None) -> None:
        super().__init__(database, workspace=workspace, clock=clock, control=control)
        ident(signal_channel)
        self.signal_channel = signal_channel
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS rt_langgraph_threads(
                binding_id TEXT NOT NULL, local_workflow_id TEXT NOT NULL,
                occurrence TEXT NOT NULL, thread_id TEXT NOT NULL,
                checkpoint_id TEXT, parent_checkpoint_id TEXT,
                state TEXT NOT NULL, updated REAL NOT NULL,
                PRIMARY KEY(binding_id, local_workflow_id, occurrence))""")

    async def _drive(self, client, value, config, context):
        import asyncio
        import time as monotonic_time
        limits = self._bound()[1]
        total = limits.get("execution_timeout_seconds", 3600)
        idle = limits.get("idle_timeout_seconds", 120)
        stream = getattr(client, "astream", None)
        if not callable(stream):
            raise RuntimeUnavailable("real graph update stream required for progress timeout")
        iterator = stream(value, config, stream_mode="updates").__aiter__()
        deadline = monotonic_time.monotonic() + total
        latest = None
        try:
            for _ in range(10000):
                remaining = deadline - monotonic_time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("graph total timeout")
                context.checkpoint()
                try:
                    latest = await asyncio.wait_for(iterator.__anext__(), min(idle, remaining))
                except StopAsyncIteration:
                    return latest
            raise RuntimeScopeConflict("graph progress event bound exceeded")
        finally:
            close = getattr(iterator, "aclose", None)
            if callable(close):
                await close()

    def _thread_id(self, scope: RuntimeScope, workflow_id: str,
                   occurrence: str) -> str:
        ident(workflow_id)
        occurrence_digest = hashlib.sha256(
            f"{workflow_id}|{occurrence}".encode()).hexdigest()[:16]
        return "sentra-" + digest([_scope_key(scope), workflow_id, occurrence])

    def _graph_config(self, thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    async def start(self, scope: RuntimeScope, *, workflow_id: str,
                    occurrence: str, inputs: dict) -> dict[str, Any]:
        from .workflow_checkpoint import namespace as check_ns
        client, config = self._bound()
        context = self._admission(scope)
        if not isinstance(inputs, dict):
            raise ValueError("LangGraph inputs must be a mapping")
        digest(inputs)
        check_ns("")
        thread_id = self._thread_id(scope, workflow_id, occurrence)
        self._reserve_start(scope, workflow_id, occurrence, thread_id)
        try:
            context.checkpoint()
            result = await self._drive(client, inputs, self._graph_config(thread_id), context)
        except Exception as exc:
            return {"workflow_id": workflow_id, "thread_id": thread_id,
                    "status": "UNCERTAIN", "failure_type": type(exc).__name__,
                    "replayed_effect": False,
                    "operation_id": context.receipt.operation_id}
        context.checkpoint()
        state = await client.aget_state(self._graph_config(thread_id))
        checkpoint_id = None
        state_config = getattr(state, "config", None)
        if isinstance(state_config, dict):
            candidate = state_config.get("configurable", {}).get("checkpoint_id")
            if isinstance(candidate, str):
                checkpoint_id = candidate
        if checkpoint_id is None:
            candidate = getattr(state, "checkpoint_id", None)
            if isinstance(candidate, str):
                checkpoint_id = candidate
        with self._db() as db:
            db.execute("INSERT INTO rt_langgraph_threads VALUES(?,?,?,?,?,?,?,?) "
                       "ON CONFLICT(binding_id,local_workflow_id,occurrence) "
                       "DO UPDATE SET checkpoint_id=excluded.checkpoint_id,"
                       "state=excluded.state,updated=excluded.updated",
                       (config["binding_id"], workflow_id, occurrence,
                        thread_id, checkpoint_id, None, "STARTED", self.clock()))
        self._record_external(
            binding_id=config["binding_id"], local_workflow_id=workflow_id,
            local_namespace=occurrence, external_id=thread_id,
            external_run=checkpoint_id,
            operation_id=context.receipt.operation_id, state="STARTED")
        return {"workflow_id": workflow_id, "thread_id": thread_id,
                "checkpoint_id": checkpoint_id, "status": "STARTED",
                "output_proven": False,
                "operation_id": context.receipt.operation_id,
                "replayed_effect": False}

    async def advance(self, scope: RuntimeScope, *, workflow_id: str,
                      occurrence: str, resume: dict | None = None) -> dict[str, Any]:
        """Continue the thread; resume values only with explicit approval."""
        client, config = self._bound()
        context = self._admission(scope)
        thread_id = self._thread_id(scope, workflow_id, occurrence)
        context.checkpoint()
        state = await client.aget_state(self._graph_config(thread_id))
        interrupts = [task for task in (getattr(state, "tasks", None) or [])
                      if getattr(task, "interrupts", None)]
        if interrupts and resume is None:
            return {"workflow_id": workflow_id, "thread_id": thread_id,
                    "status": "WAITING_INTERRUPT",
                    "interrupt_count": len(interrupts),
                    "note": "resume values require host owner approval"}
        if resume is not None and not interrupts:
            raise RuntimeScopeConflict("resume requires an existing interrupt checkpoint")
        try:
            if interrupts:
                from .workflow_contracts import digest as _digest
                _digest(resume)
                from langgraph.types import Command
                context.checkpoint()
                result = await self._drive(client, Command(resume=resume),
                                              self._graph_config(thread_id), context)
            else:
                context.checkpoint()
                result = await self._drive(client, None, self._graph_config(thread_id), context)
        except Exception as exc:
            return {"workflow_id": workflow_id, "thread_id": thread_id,
                    "status": "UNCERTAIN", "failure_type": type(exc).__name__,
                    "replayed_effect": False,
                    "operation_id": context.receipt.operation_id}
        return {"workflow_id": workflow_id, "thread_id": thread_id,
                "status": "ADVANCED",
                "output_proven": False,
                "operation_id": context.receipt.operation_id,
                "replayed_effect": False}

    async def signal(self, scope: RuntimeScope, *, workflow_id: str,
                     occurrence: str, payload: dict) -> dict[str, Any]:
        client, config = self._bound()
        context = self._admission(scope)
        if not isinstance(payload, dict):
            raise ValueError("LangGraph signal payload must be a mapping")
        digest(payload)
        thread_id = self._thread_id(scope, workflow_id, occurrence)
        try:
            context.checkpoint()
            await client.aupdate_state(self._graph_config(thread_id),
                                       {self.signal_channel: payload})
        except Exception as exc:
            return {"workflow_id": workflow_id, "thread_id": thread_id,
                    "status": "UNCERTAIN", "failure_type": type(exc).__name__,
                    "replayed_effect": False,
                    "operation_id": context.receipt.operation_id}
        return {"workflow_id": workflow_id, "thread_id": thread_id,
                "status": "SIGNALLED",
                "operation_id": context.receipt.operation_id,
                "replayed_effect": False}

    async def interrupt(self, scope: RuntimeScope, *, workflow_id: str,
                        occurrence: str, reason: str) -> dict[str, Any]:
        if not isinstance(reason, str) or not 1 <= len(reason) <= 512:
            raise ValueError("bounded interrupt reason required")
        return await self.signal(scope, workflow_id=workflow_id,
                                 occurrence=occurrence,
                                 payload={"interrupt": reason})

    async def resume(self, scope: RuntimeScope, *, workflow_id: str,
                     occurrence: str, values: dict,
                     operator_approved: bool = False) -> dict[str, Any]:
        if operator_approved is not True:
            raise PermissionError("resume values require host owner approval")
        if not isinstance(values, dict):
            raise ValueError("resume values must be a mapping")
        return await self.advance(scope, workflow_id=workflow_id,
                                  occurrence=occurrence, resume=values)

    async def cancel(self, scope: RuntimeScope, *, workflow_id: str,
                     occurrence: str) -> dict[str, Any]:
        """Cooperative cancellation flag; never rolls back started effects."""
        client, config = self._bound()
        context = self._admission(scope)
        thread_id = self._thread_id(scope, workflow_id, occurrence)
        try:
            context.checkpoint()
            await client.aupdate_state(
                self._graph_config(thread_id),
                {self.signal_channel: {"cancel_requested": True}})
        except Exception as exc:
            return {"workflow_id": workflow_id, "thread_id": thread_id,
                    "status": "UNCERTAIN", "failure_type": type(exc).__name__,
                    "operation_id": context.receipt.operation_id}
        with self._db() as db:
            db.execute("UPDATE rt_langgraph_threads SET state='CANCEL_REQUESTED',"
                       "updated=? WHERE binding_id=? AND local_workflow_id=? "
                       "AND occurrence=?",
                       (self.clock(), config["binding_id"], workflow_id,
                        occurrence))
        return {"workflow_id": workflow_id, "thread_id": thread_id,
                "status": "CANCEL_REQUESTED",
                "note": "cooperative stop; started effects are never rolled back",
                "operation_id": context.receipt.operation_id}

    async def fork(self, scope: RuntimeScope, *, workflow_id: str,
                   occurrence: str, new_occurrence: str,
                   checkpoint_id: str | None = None) -> dict[str, Any]:
        """Time travel that never rewrites history: a new thread from a checkpoint."""
        client, config = self._bound()
        context = self._admission(scope)
        source_thread = self._thread_id(scope, workflow_id, occurrence)
        target_thread = self._thread_id(scope, workflow_id, new_occurrence)
        if target_thread == source_thread or not checkpoint_id:
            raise ValueError("fork requires a distinct occurrence and pinned checkpoint_id")
        source_config = self._graph_config(source_thread)
        source_config["configurable"]["checkpoint_id"] = checkpoint_id
        context.checkpoint()
        source_state = await client.aget_state(source_config)
        source_checkpoint = (getattr(source_state, "config", {}) or {}).get(
            "configurable", {}).get("checkpoint_id")
        if source_checkpoint != checkpoint_id:
            raise RuntimeScopeConflict("fork checkpoint unavailable or changed")
        saver = getattr(client, "checkpointer", None)
        if saver is None or not callable(getattr(saver, "aget_tuple", None)):
            raise RuntimeUnavailable("durable graph checkpointer required for fork")
        context.checkpoint()
        snapshot = await saver.aget_tuple(source_config)
        if snapshot is None:
            raise RuntimeScopeConflict("fork checkpoint missing")
        self._reserve_start(scope, workflow_id, new_occurrence, target_thread)
        fork_checkpoint = getattr(saver, "afork_checkpoint", None)
        if not callable(fork_checkpoint):
            raise RuntimeUnavailable("checkpoint saver must preserve complete parent/write lineage")
        context.checkpoint()
        target_config = await fork_checkpoint(source_config, self._graph_config(target_thread))
        with self._db() as db:
            db.execute("INSERT INTO rt_langgraph_threads VALUES(?,?,?,?,?,?,?,?) "
                       "ON CONFLICT(binding_id,local_workflow_id,occurrence) "
                       "DO UPDATE SET thread_id=excluded.thread_id,"
                       "checkpoint_id=excluded.checkpoint_id,"
                       "parent_checkpoint_id=excluded.parent_checkpoint_id,"
                       "state=excluded.state,updated=excluded.updated",
                       (config["binding_id"], workflow_id, new_occurrence,
                        target_thread, None,
                        source_checkpoint if isinstance(source_checkpoint, str) else None,
                        "FORKED", self.clock()))
        return {"workflow_id": workflow_id, "thread_id": target_thread,
                "parent_checkpoint_id": source_checkpoint,
                "history_rewritten": False, "status": "FORKED",
                "operation_id": context.receipt.operation_id}

    async def observe(self, scope: RuntimeScope, *, workflow_id: str,
                      occurrence: str) -> dict[str, Any]:
        """Read thread state/checkpoints. Read-only: never advances the graph."""
        client, config = self._bound()
        _scope_key(scope)
        if (config["owner"], config["run_id"], config["work_item_id"], config["principal_id"]) != (scope.owner, scope.run_id, scope.work_item_id, scope.principal_id):
            raise RuntimeScopeConflict("observe scope differs from binding")
        thread_id = self._thread_id(scope, workflow_id, occurrence)
        context = self._admission(scope)
        try:
            context.checkpoint()
            state = await client.aget_state(self._graph_config(thread_id))
        except Exception as exc:
            return {"workflow_id": workflow_id, "thread_id": thread_id,
                    "status": "UNCERTAIN", "failure_type": type(exc).__name__}
        tasks = getattr(state, "tasks", None) or []
        pending = [getattr(task, "name", "?") for task in tasks
                   if getattr(task, "result", None) is None]
        interrupts = [task for task in tasks if getattr(task, "interrupts", None)]
        history = getattr(client, "aget_state_history", None)
        revisions = 1
        if callable(history):
            try:
                count = 0
                context.checkpoint()
                async for _ in history(self._graph_config(thread_id), limit=200):
                    context.checkpoint()
                    count += 1
                revisions = count
            except Exception:
                pass
        next_step = getattr(state, "next", None)
        failures = [task for task in tasks if getattr(task,"error",None)]
        return {"workflow_id": workflow_id, "thread_id": thread_id,
                "next": list(next_step) if next_step else [],
                "pending_tasks": pending[:50],
                "waiting_interrupt": bool(interrupts),
                "checkpoint_revisions": revisions,
                "status": "FAILED" if failures else "WAITING_INTERRUPT" if interrupts
                          else "READY" if pending or next_step
                          else "SUCCEEDED" if (getattr(state, "config", {}) or {}).get("configurable", {}).get("checkpoint_id")
                          else "UNCERTAIN"}

    async def reconcile(self, scope: RuntimeScope, *, workflow_id: str,
                        occurrence: str) -> dict[str, Any]:
        observed = await self.observe(scope, workflow_id=workflow_id,
                                      occurrence=occurrence)
        if observed["status"] == "UNCERTAIN":
            return {**observed, "replayed_effect": False,
                    "action": "await provider; do not resubmit"}
        return {**observed, "replayed_effect": False}
