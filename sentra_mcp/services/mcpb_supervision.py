"""Host-only MCPB supervision: inventory, health and crash-recovery tickets.

Read-mostly facade over the existing MCPB authorities (bundle catalog,
Docker ownership ledger, MCP HTTP sessions). It starts no subprocess,
sends no network request, mints no grant and performs no ``docker rm``:
cleanup tickets carry exact container IDs for the coordinator's centrally
fenced effect (``MCPBDockerOwnership.reconcile_stopped_owned``), and stale
HTTP sessions are reconciled through the existing
``MCPHttpRegistry.reconcile_abandoned`` UNCERTAIN marking.
"""
from __future__ import annotations

import time
from pathlib import Path


class MCPBSupervisionService:
    """Supervision projections bound to one central ControlPlaneService."""

    def __init__(self, control):
        self.control = control
        self.store = control.store

    def _same_authority(self, other_store) -> None:
        from .pacto_authority import require_same_store
        require_same_store(self.store, other_store)

    def status(self, owner, workspace):
        """Inventory and health counts; never asserts remote liveness."""
        root = str(Path(workspace).resolve(strict=True))
        with self.store.connect("plugin_bundle") as db:
            try:
                bundles = db.execute(
                    "SELECT enabled, COUNT(*) AS n FROM plugin_bundles "
                    "WHERE owner=? AND workspace=? GROUP BY enabled",
                    (owner, root)).fetchall()
            except Exception:
                bundles = []
            try:
                registrations = db.execute(
                    "SELECT status, COUNT(*) AS n FROM plugin_bundle_registrations "
                    "WHERE owner=? AND workspace=? GROUP BY status",
                    (owner, root)).fetchall()
            except Exception:
                registrations = []
            try:
                claims = db.execute(
                    "SELECT state, COUNT(*) AS n FROM mcpb_docker_ownership "
                    "WHERE owner=? AND workspace=? GROUP BY state",
                    (owner, root)).fetchall()
            except Exception:
                claims = []
            try:
                sessions = db.execute(
                    "SELECT state, COUNT(*) AS n FROM mcp_http_session_attempts "
                    "WHERE owner=? AND workspace=? GROUP BY state",
                    (owner, root)).fetchall()
            except Exception:
                sessions = []
        return {
            "workspace": root,
            "staged_bundles": {str(r[0]): r[1] for r in bundles},
            "registrations": {str(r[0]): r[1] for r in registrations},
            "docker_claims": {str(r[0]): r[1] for r in claims},
            "http_sessions": {str(r[0]): r[1] for r in sessions},
            "remote_liveness_proved": False,
            "grants_created": False,
            "worker_started": False,
        }

    def sweep(self, owner, workspace, *, min_age_seconds=60, approved_by_host=None):
        """Crash-recovery sweep returning exact-ID tickets, never performing rm.

        - Stale HTTP session attempts become UNCERTAIN via the existing
          registry reconciliation (no network resend).
        - Docker claims older than ``min_age_seconds`` whose central
          Operation is terminal are returned as cleanup tickets for the
          coordinator's fenced exact-ID effect. PREPARED claims without a
          bound container ID are reported, not ticketed.
        ``approved_by_host`` must be a host callable returning True; model
        or browser booleans never authorize the sweep.
        """
        if type(min_age_seconds) is not int or min_age_seconds < 30:
            raise ValueError("minimum stale sweep age is 30 seconds")
        if not callable(approved_by_host):
            raise PermissionError("MCPB supervision sweep requires host operator approval")
        try:
            approved = approved_by_host(owner, workspace)
        except TypeError:
            # Zero-arg host callbacks (e.g. a bearer-route closure over its
            # own workspace) are accepted with identical standing.
            approved = approved_by_host()
        if approved is not True:
            raise PermissionError("MCPB supervision sweep requires host operator approval")
        root = str(Path(workspace).resolve(strict=True))
        http = self.control.mcp_http.reconcile_abandoned(
            owner, root, min_age_seconds=max(min_age_seconds, 30))
        tickets, reported, now = [], [], time.time()
        with self.store.connect("plugin_bundle") as db:
            try:
                rows = db.execute(
                    "SELECT operation_id,container_id,state,created_at,updated_at "
                    "FROM mcpb_docker_ownership WHERE owner=? AND workspace=? "
                    "AND state IN ('PREPARED','BOUND') AND created_at<?",
                    (owner, root, now - min_age_seconds)).fetchall()
            except Exception:
                rows = []
        for row in rows:
            operation_id = row["operation_id"]
            try:
                operation = self.control.durable.operation_status(operation_id, owner)
            except Exception:
                reported.append({"operation_id": operation_id,
                                 "reason": "central operation receipt unavailable"})
                continue
            if operation.get("state") not in {"SUCCEEDED", "FAILED", "CANCELLED", "UNCERTAIN"}:
                continue
            if row["state"] != "BOUND" or not row["container_id"]:
                reported.append({"operation_id": operation_id,
                                 "reason": "claim without bound container cannot be ticketed"})
                continue
            tickets.append({
                "source_operation_id": operation_id,
                "container_id": row["container_id"],
                "operation_state": operation.get("state"),
                "requires_fresh_inspect": True,
                "authorized_cleanup": False,
                "performed": False,
            })
        return {"workspace": root, "http_reconciliation": http,
                "cleanup_tickets": tickets, "reported_claims": reported,
                "containers_removed": 0, "effects_replayed": 0,
                "note": "tickets require a separately granted exact-ID cleanup Operation"}
