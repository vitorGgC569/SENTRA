"""Bind Lume channel triggers to the real central workflow.

Lume's ``ChannelService`` owns connectors, the encrypted inbox, claim/ack
and provider send. This module is Pulso's trigger side of that contract:

- :meth:`ChannelWorkflowTrigger.poll` projects ``pending_inbound``.
- :meth:`ChannelWorkflowTrigger.claim_for_workflow` claims one inbox event
  (CAS on ``expected_revision``; an already-claimed event is never
  reassigned here — reconcile instead) and builds the exact
  ``workflow:signal`` intent keyed by Lume's ``dispatch_idempotency_key``
  (``channel:<connector>:<event>``) for the host to admit as a distinct
  central operation under existing owner grants/admission. The facade
  performs no effect.
- :meth:`ChannelWorkflowTrigger.ack_claim` acknowledges through Lume's
  ``ack``, which marks ACKNOWLEDGED only on Durable Operation SUCCEEDED
  in the same WorkItem/project, else UNCERTAIN.
- No channel inherits ChatTrust: signal payloads carry a bounded
  provenance reference (connector/event/dispatch key); message text is
  resolved server-side from the encrypted inbox by the host's payload
  resolver and the external sender identity never confers a grant.

Route table ``bind_route`` (host action with owner approval) pins which
workflow/signal a connector feeds. Shell/route callers never select the
workflow.
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


class ChannelTriggerConflict(ValueError):
    pass


class ChannelWorkflowTrigger:
    """Claim inbox events and bind them to workflow signal intents."""

    def __init__(self, database: str, *, workspace: str,
                 channel_service: Any = None, control: Any = None,
                 clock=time.time) -> None:
        root, target = Path(workspace).resolve(), Path(database).resolve()
        if target == root or not target.is_relative_to(root):
            raise ValueError("trigger projection outside workspace")
        from .workflow_storage import projection_path
        projection_path(database, workspace, control=control)
        self.database, self.clock = str(target), clock
        self.channel_service = channel_service
        self.control = control
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS channel_workflow_routes(
                connector_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                workflow_id TEXT NOT NULL, namespace TEXT NOT NULL,
                signal_name TEXT NOT NULL, updated REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS channel_dispatch_intents(
                dispatch_key TEXT PRIMARY KEY, owner TEXT NOT NULL,
                connector_id TEXT NOT NULL, event_id TEXT NOT NULL,
                claim_id TEXT NOT NULL, workflow_id TEXT NOT NULL,
                namespace TEXT NOT NULL, signal_name TEXT NOT NULL,
                signal_id TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                admitted_operation_id TEXT, created REAL NOT NULL)""")

    @contextmanager
    def _db(self):
        from .workflow_storage import projection_db
        with projection_db(self.database, control=self.control) as conn:
            yield conn

    def _service(self, owner: str):
        service = self.channel_service
        if service is None:
            raise ChannelTriggerConflict(
                "Lume ChannelService not composed; host must inject it")
        if getattr(service, "owner", owner) != owner:
            raise PermissionError("channel service bound to another owner")
        return service

    # -- routing -------------------------------------------------------
    def bind_route(self, *, owner: str, connector_id: str, workflow_id: str,
                   ns: str = "", signal_name: str,
                   operator_approved: bool = False) -> dict[str, Any]:
        """Pin a connector to a workflow signal (host action, approved)."""
        if operator_approved is not True:
            raise PermissionError("host owner approval required to bind channel route")
        if not isinstance(owner, str) or not owner:
            raise ValueError("owner scope required")
        ident(connector_id)
        ident(workflow_id)
        namespace(ns)
        ident(signal_name)
        record = {"connector_id": connector_id, "owner": owner,
                  "workflow_id": workflow_id, "namespace": ns,
                  "signal_name": signal_name, "updated": self.clock()}
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM channel_workflow_routes "
                             "WHERE connector_id=?", (connector_id,)).fetchone()
            if old is not None and (
                    old["owner"], old["workflow_id"], old["namespace"],
                    old["signal_name"]) != (
                    owner, workflow_id, ns, signal_name):
                raise ChannelTriggerConflict(
                    "connector already routed to a different workflow signal")
            db.execute("INSERT INTO channel_workflow_routes VALUES(?,?,?,?,?,?) "
                       "ON CONFLICT(connector_id) DO UPDATE SET updated=excluded.updated",
                       (connector_id, owner, workflow_id, ns, signal_name,
                        record["updated"]))
        return record

    def route(self, owner: str, connector_id: str) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute("SELECT * FROM channel_workflow_routes "
                             "WHERE connector_id=?", (connector_id,)).fetchone()
        if row is None:
            raise ChannelTriggerConflict(
                "connector has no bound workflow route; host must bind_route first")
        if row["owner"] != owner:
            raise PermissionError("channel route belongs to another owner")
        return dict(row)

    # -- trigger flow --------------------------------------------------
    def poll(self, owner: str, *, connector_id: str, project_id: str,
             limit: int = 100) -> list[dict[str, Any]]:
        return self._service(owner).pending_inbound(
            connector_id=connector_id, project_id=project_id, limit=limit)

    @staticmethod
    def _signal_id(dispatch_key: str) -> str:
        return "ch-" + hashlib.sha256(dispatch_key.encode()).hexdigest()[:32]

    def claim_for_workflow(self, owner: str, *, connector_id: str,
                           event_id: str, consumer_id: str,
                           expected_revision: int,
                           lease_seconds: int = 60) -> dict[str, Any]:
        """Claim one inbox event and bind it to the routed workflow intent.

        Returns the Lume claim plus the exact ``workflow:signal`` intent
        (capability + arguments) for the host to admit as a distinct
        central operation. Performs no effect itself. Repeating the same
        dispatch key replays the recorded intent; a conflicting intent is
        refused. Expired claims are never reassigned here.
        """
        service = self._service(owner)
        route = self.route(owner, connector_id)
        claim = service.inbound_claim(connector_id=connector_id, event_id=event_id, consumer_id=consumer_id)
        if claim is None:
            claim = service.claim(connector_id=connector_id, event_id=event_id,
                              consumer_id=consumer_id,
                              expected_revision=expected_revision,
                              lease_seconds=lease_seconds)
        dispatch_key = claim["dispatch_idempotency_key"]
        if dispatch_key != f"channel:{connector_id}:{event_id}":
            raise ChannelTriggerConflict("channel dispatch key shape changed")
        signal_id = self._signal_id(dispatch_key)
        # Provenance reference only: text resolves server-side from the
        # encrypted inbox via the host payload resolver. No ChatTrust.
        payload = {"channel_event": {"connector_id": connector_id,
                                     "event_id": event_id},
                   "dispatch_key": dispatch_key,
                   "project_id": claim["project_id"],
                   "workspace_id": claim["workspace_id"],
                   "message": service.claimed_payload(connector_id=connector_id, event_id=event_id, claim_id=claim["claim_id"]),
                   "chat_trust_inherited": False}
        payload_sha = digest(payload)
        arguments = {"workflow_id": route["workflow_id"],
                     "namespace": route["namespace"],
                     "name": route["signal_name"], "signal_id": signal_id,
                     "payload_sha256": payload_sha}
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM channel_dispatch_intents "
                             "WHERE dispatch_key=?", (dispatch_key,)).fetchone()
            if old is not None:
                if (old["owner"], old["claim_id"], old["workflow_id"],
                        old["namespace"], old["signal_name"],
                        old["payload_sha256"]) != (
                        owner, claim["claim_id"], route["workflow_id"],
                        route["namespace"], route["signal_name"], payload_sha):
                    raise ChannelTriggerConflict(
                        "dispatch key already bound to a different intent")
                return self._intent(dict(old), claim)
            db.execute("INSERT INTO channel_dispatch_intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (dispatch_key, owner, connector_id, event_id,
                        claim["claim_id"], route["workflow_id"],
                        route["namespace"], route["signal_name"], signal_id,
                        payload_sha, None, self.clock()))
            row = db.execute("SELECT * FROM channel_dispatch_intents "
                             "WHERE dispatch_key=?", (dispatch_key,)).fetchone()
            return self._intent(dict(row), claim)

    def _intent(self, row: dict, claim: dict) -> dict[str, Any]:
        return {"claim_id": row["claim_id"], "event_id": row["event_id"],
                "connector_id": row["connector_id"],
                "project_id": claim["project_id"],
                "workspace_id": claim["workspace_id"],
                "revision": claim["revision"],
                "dispatch_idempotency_key": row["dispatch_key"],
                "capability_id": "workflow:signal",
                "arguments": {"workflow_id": row["workflow_id"],
                              "namespace": row["namespace"],
                              "name": row["signal_name"],
                              "signal_id": row["signal_id"],
                              "payload_sha256": row["payload_sha256"]},
                "signal_payload_reference": {
                    "channel_event": {"connector_id": row["connector_id"],
                                      "event_id": row["event_id"]},
                    "resolve_via": "host payload resolver from encrypted inbox"},
                "admit_via": "central operation journal",
                "effects_started": False,
                "already_admitted": row["admitted_operation_id"] is not None}

    def signal_payload(self, owner, dispatch_key):
        with self._db() as db:
            row = db.execute("SELECT * FROM channel_dispatch_intents WHERE dispatch_key=? AND owner=?",
                (dispatch_key, owner)).fetchone()
        if row is None:
            raise FileNotFoundError("channel dispatch not found")
        service = self._service(owner)
        claim = service.inbound_claim(connector_id=row["connector_id"], event_id=row["event_id"])
        payload = {"channel_event": {"connector_id": row["connector_id"], "event_id": row["event_id"]},
            "dispatch_key": dispatch_key, "project_id": claim["project_id"], "workspace_id": claim["workspace_id"],
            "message": service.claimed_payload(connector_id=row["connector_id"], event_id=row["event_id"], claim_id=row["claim_id"]),
            "chat_trust_inherited": False}
        if digest(payload) != row["payload_sha256"]:
            raise ChannelTriggerConflict("claimed signal payload changed")
        return payload

    def mark_admitted(self, *, dispatch_key: str, operation_id: str) -> None:
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("central operation identity required")
        with self._db() as db:
            updated = db.execute(
                "UPDATE channel_dispatch_intents SET admitted_operation_id=? "
                "WHERE dispatch_key=? AND (admitted_operation_id IS NULL "
                "OR admitted_operation_id=?)",
                (operation_id, dispatch_key, operation_id)).rowcount
            if updated != 1:
                raise ValueError("unknown dispatch key or conflicting admission")

    def ack_claim(self, owner: str, *, claim_id: str, work_item_id: str,
                  operation_id: str, receipt_id: str | None = None) -> dict[str, Any]:
        """Acknowledge through Lume ack (SUCCEEDED-only, else uncertain)."""
        if self.control is None:
            raise ChannelTriggerConflict("central control required for acknowledgement")
        with self._db() as db:
            row = db.execute("SELECT * FROM channel_dispatch_intents WHERE owner=? AND claim_id=?",
                (owner, claim_id)).fetchone()
        operation = self.control.durable.operation_status(operation_id, owner)
        progress = operation.get("progress") or {}
        if row is None or row["admitted_operation_id"] != operation_id or progress.get("capability_id") != "workflow:signal" or progress.get("work_item_id") != work_item_id:
            raise ChannelTriggerConflict("acknowledgement must reference the exact admitted workflow signal")
        from sentra_runtime.contracts import OperationRequest
        from .gate import _fingerprint
        request = OperationRequest(operation_id, progress["principal_id"], progress["machine_id"],
            "workflow:signal", work_item_id, "pulso:" + row["dispatch_key"],
            {"workflow_id": row["workflow_id"], "namespace": row["namespace"], "name": row["signal_name"],
             "signal_id": row["signal_id"], "payload_sha256": row["payload_sha256"]})
        with self.control.durable.lock:
            recorded = self.control.durable._operation_row(operation_id, owner)["intent_sha256"]
        if recorded != _fingerprint(request):
            raise ChannelTriggerConflict("central workflow signal fingerprint mismatch")
        return self._service(owner).ack(claim_id=claim_id, work_item_id=work_item_id,
            operation_id=operation_id, receipt_id=receipt_id)

    def attach_control(self, control: Any) -> None:
        """Attach the Control Plane for SUCCEEDED-gated confirmation."""
        self.control = control

    def confirm_dispatch(self, owner: str, *, dispatch_key: str,
                         work_item_id: str, operation_id: str,
                         receipt_id: str | None = None) -> dict[str, Any]:
        """Complete claim→signal→ack with zero new grants.

        The host admitted the signal intent (built by
        :meth:`claim_for_workflow`) as a distinct central operation under
        existing workflow grants. This method verifies the admitted
        operation is SUCCEEDED in the same WorkItem (durable read), then
        acknowledges through Lume's ``ack``. Any other outcome returns
        ``uncertain`` WITHOUT acking, leaving the claim for reconcile.
        """
        if self.control is None:
            raise ChannelTriggerConflict(
                "control plane not attached; host must attach_control first")
        with self._db() as db:
            row = db.execute("SELECT * FROM channel_dispatch_intents "
                             "WHERE dispatch_key=?", (dispatch_key,)).fetchone()
        if row is None:
            raise FileNotFoundError("channel dispatch intent not found")
        if row["owner"] != owner:
            raise PermissionError("dispatch intent belongs to another owner")
        if row["admitted_operation_id"] != operation_id:
            raise ChannelTriggerConflict(
                "operation does not match the admitted dispatch")
        operation = self.control.durable.operation_status(operation_id, owner)
        progress = operation.get("progress") if isinstance(
            operation.get("progress"), dict) else {}
        if progress.get("work_item_id") != work_item_id:
            raise ChannelTriggerConflict(
                "operation bound to another WorkItem")
        if operation["state"] != "SUCCEEDED" or operation.get("run_id") is None:
            return {"dispatch_key": dispatch_key, "status": "uncertain",
                    "operation_state": operation["state"],
                    "action": "reconcile; claim left unacknowledged"}
        acked = self.ack_claim(owner, claim_id=row["claim_id"],
                               work_item_id=work_item_id,
                               operation_id=operation_id,
                               receipt_id=receipt_id)
        return {"dispatch_key": dispatch_key, "status": acked.get("status"),
                "claim_id": row["claim_id"], "operation_id": operation_id,
                "receipt_id": acked.get("receipt_id")}


class PulsoChannelSendExecutor:
    """Admit-and-execute driver for staged channel notifications.

    The host root resolves the staged text server-side
    (``resolve_send``), admits a distinct central operation with
    capability ``channel:send`` and arguments
    ``{connector_id, recipient, text_sha256}``, then calls
    :meth:`execute` with the admitted ``request``. Uses no new grants:
    authority is the admitted request; provider send stays Lume's.

    Final host resolver signature (for Nexo/Codex composition)::

        channel_resolver(action, ctx, params) -> dict
            action "resolve": params {dedupe_key}
                -> {connector_id, recipient, text} (server-side text)
            action "execute": params {request, connector_id, recipient, text}
                with request the admitted channel:send OperationRequest
                -> Lume send result dict
    """

    def __init__(self, *, channel_bridge: Any = None,
                 channel_service: Any = None) -> None:
        self.channel_bridge = channel_bridge
        self.channel_service = channel_service

    def resolve(self, owner: str, dedupe_key: str) -> dict[str, Any]:
        if self.channel_bridge is None:
            raise ChannelTriggerConflict("channel bridge not composed")
        return self.channel_bridge.resolve_send(owner, dedupe_key)

    async def execute(self, *, request: Any, connector_id: str,
                      recipient: str, text: str) -> dict[str, Any]:
        service = self.channel_service
        if service is None:
            raise ChannelTriggerConflict("Lume ChannelService not composed")
        result = service.send(request, connector_id=connector_id,
                              recipient=recipient, text=text)
        import inspect as _inspect
        if _inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict):
            raise ChannelTriggerConflict("channel send returned invalid result")
        return {"ok": True, "value": result}
