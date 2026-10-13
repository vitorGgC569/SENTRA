"""LangGraph checkpoint/store semantics mapped onto SENTRA checkpoints.

NOT a LangGraph runtime, graph server or operations authority. This module
ports the exact parent-checkpoint lineage, pending-write staging and
progress/idle-timeout semantics inspected in the pinned LangGraph clone
(``libs/checkpoint/langgraph/checkpoint/base``,
``libs/langgraph/langgraph/pregel/_retry.py``,
``libs/checkpoint/langgraph/store/base``) onto
``WorkflowCheckpointStore`` projections.

Pending writes become usable only after the host's central journal confirms
the associated operation; this module only stages and reconciles them.
"""
from __future__ import annotations

import math
import time
from typing import Any

from .workflow_checkpoint import WorkflowCheckpointStore, namespace
from .workflow_contracts import ident


class LangGraphCheckpointBridge:
    """Parent-checkpoint lineage and pending-write staging on the real store."""

    def __init__(self, store: WorkflowCheckpointStore, *,
                 idle_timeout_seconds: float = 60.0,
                 clock=time.time) -> None:
        if not isinstance(store, WorkflowCheckpointStore):
            raise TypeError("real workflow checkpoint store required")
        if (type(idle_timeout_seconds) not in (int, float)
                or not math.isfinite(idle_timeout_seconds)
                or not 0 < idle_timeout_seconds <= 86400):
            raise ValueError("bounded idle timeout required")
        self.store, self.idle_timeout, self.clock = store, float(idle_timeout_seconds), clock
        self._progress: dict[tuple[str, str, str], float] = {}

    def checkpoint_lineage(self, request: Any, *, workflow_id: str,
                           ns: str = "") -> list[dict[str, Any]]:
        """Walk ``parent_namespace`` chain to the root, newest first."""
        ident(workflow_id)
        namespace(ns)
        lineage = []
        current: str | None = ns
        while current is not None:
            loaded = self.store.load(workflow_id, current, request)
            lineage.append({"namespace": current,
                            "checkpoint_id": loaded["id"],
                            "revision": loaded["revision"],
                            "status": loaded["state"].get("status"),
                            "parent_namespace": loaded["instance"]["parent_namespace"]})
            current = loaded["instance"]["parent_namespace"]
        return lineage

    def stage_pending_write(self, *, workflow_id: str, ns: str,
                            step_id: str, attempt: int,
                            operation_id: str, value: Any) -> None:
        """Stage a pending write exactly like a LangGraph pending-write entry.

        Usable only after central acknowledgement; the worker's own
        confirmation path (``advance``/``observe``) promotes it.
        """
        ident(workflow_id)
        namespace(ns)
        ident(step_id)
        if type(attempt) is not int or attempt < 1:
            raise ValueError("attempt must be >= 1")
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("central operation identity required")
        self.store.put_write(workflow_id, ns, step_id, attempt, operation_id, value)

    def heartbeat(self, *, workflow_id: str, ns: str, step_id: str) -> float:
        """Record real progress; only genuine binding/transport heartbeats renew."""
        ident(workflow_id)
        namespace(ns)
        ident(step_id)
        now = self.clock()
        self._progress[(workflow_id, ns, step_id)] = now
        return now

    def idle_expired(self, *, workflow_id: str, ns: str, step_id: str,
                     now: float | None = None) -> bool:
        """True when no real heartbeat arrived within the idle timeout."""
        ident(step_id)
        current = self.clock() if now is None else float(now)
        last = self._progress.get((workflow_id, ns, step_id))
        if last is None:
            return False
        return (current - last) >= self.idle_timeout


class LangGraphNamespaceStore:
    """Namespace-scoped TTL memory projection over the checkpoint store.

    Mirrors the LangGraph store base semantics (hierarchical namespace,
    lexical scan of descendant namespaces, TTL expiry) without installing
    embeddings or authorizing another namespace.
    """

    def __init__(self, store: WorkflowCheckpointStore, *,
                 clock=time.time) -> None:
        if not isinstance(store, WorkflowCheckpointStore):
            raise TypeError("real workflow checkpoint store required")
        self.store, self.clock = store, clock

    def put(self, *, workflow_id: str, ns: str, key: str, value: Any,
            ttl_seconds: float | None = None) -> None:
        if not isinstance(key, str) or not 1 <= len(key) <= 256:
            raise ValueError("bounded memory key required")
        ident(workflow_id)
        namespace(ns)
        self.store.memory_put(workflow_id, ns, key, value, ttl_seconds=ttl_seconds)

    def scan(self, request: Any, *, workflow_id: str, ns_prefix: str,
             query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        """Lexical scan of the namespace and its descendants."""
        ident(workflow_id)
        namespace(ns_prefix)
        if not isinstance(query, str) or len(query) > 1024:
            raise ValueError("bounded memory query required")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("scan limit must be 1..100")
        namespaces = [ns_prefix]
        # Descendant namespaces share the prefix; the checkpoint store owns
        # the instance index, so scan stays within the same workflow.
        with self.store.db() as db:
            rows = db.execute("SELECT DISTINCT namespace FROM wf_instances "
                              "WHERE workflow_id=?", (workflow_id,)).fetchall()
        for row in rows:
            candidate = row["namespace"]
            if candidate != ns_prefix and candidate.startswith(
                    ns_prefix + "/" if ns_prefix else ""):
                namespaces.append(candidate)
        results: list[dict[str, Any]] = []
        for candidate in sorted(namespaces):
            try:
                self.store.load(workflow_id,candidate,request)
                items = self.store.memory_search(
                    workflow_id, candidate, query=query, limit=limit)
            except (FileNotFoundError, PermissionError, ValueError):
                continue
            for entry in items:
                results.append({**entry, "namespace": candidate})
                if len(results) >= limit:
                    return results
        return results
