"""Host-side acceptance of an authenticated SENTRA peer task reference.

The incoming peer transport is never an authority. Acceptance checks local
WorkItem, principal, workspace, capability grant and the real Control Plane
durable operation gate. It only acknowledges a reference; it does not dispatch
a remote instruction, start a model or accept a remote result as completed.
"""
from __future__ import annotations

import asyncio
from contextlib import closing
import hashlib
import json

from sentra_mcp.services.authorization import AuthorizationService
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.central_authority import CentralDurableIntentAuthority
from sentra_runtime.contracts import (
    Capability, Machine, OperationRequest, OperationResult, PolicyDecision,
)
from sentra_runtime.durable_admission import DurableOperationGate
from sentra_runtime.executor import AuthorizationRequired

from .peer_work_wire import PeerWorkWire, PeerWireDenied

_CAP = "peer.task.accept"


def admit_pending_offer(
    *, canvas, wire: PeerWorkWire, workspace_id: str,
    sender: str, message_id: str, local_work_item_id: str,
) -> dict:
    """Record a locally approved peer reference against a *local* WorkItem.

    A local owner must first create a RUNNING WorkItem whose metadata includes
    the exact remote_peer_id and remote_subject_id of the received offer and
    explicitly grant peer.task.accept to its assignee. Incoming data cannot
    create a grant or decide an objective, role, or external execution effect.

    Any caller must be an authenticated local owner endpoint. This function
    must never be exposed directly as an untrusted agent/peer RPC.
    """
    if (not isinstance(wire, PeerWorkWire)
            or workspace_id != wire.workspace or sender not in wire.trust
            or not isinstance(message_id, str)
            or not isinstance(local_work_item_id, str)):
        raise PeerWireDenied("explicit trusted peer/workspace/work item required")
    canvas.store.workspace(workspace_id)
    with closing(wire._db()) as db:
        row = db.execute(
            "SELECT kind,state,subject_id,body_sha256 FROM peer_inbox "
            "WHERE workspace=? AND sender=? AND message_id=?",
            (workspace_id, sender, message_id),
        ).fetchone()
    if row is None or row[0] != "TASK_OFFER":
        raise PeerWireDenied("authenticated pending task offer required")
    if row[1] != "PENDING_LOCAL_ADMISSION":
        raise PeerWireDenied("offer already processed; reconcile its Operation")
    subject_id, evidence_sha = row[2], row[3]
    runtime = canvas._runtime()
    run = runtime.run(workspace_id)
    work = runtime.governance.work_item_info(local_work_item_id, runtime.owner)
    metadata = work.get("metadata") or {}
    if (run["state"] != "RUNNING" or work["run_id"] != run["run_id"]
            or work["state"] != "RUNNING"
            or metadata.get("workspace_id") != workspace_id
            or metadata.get("remote_peer_id") != sender
            or metadata.get("remote_subject_id") != subject_id
            or _CAP not in work.get("required_capabilities", ())
            or not work.get("assignee_agent_id")):
        raise PeerWireDenied("locally admitted WorkItem mapping required")

    agent_id = work["assignee_agent_id"]
    # The local WorkItem assignee must exist in the local Canvas ownership
    # store: arbitrary peer-supplied principal strings are not accepted.
    canvas.store.resource("agents", agent_id, workspace_id)
    machine = Machine(
        "peer-inbox-" + workspace_id, "read-only-peer-admission",
        runtime.owner, (Capability(_CAP, "Accept peer metadata only"),),
    )
    op_id = "peer-admit-" + hashlib.sha256(
        (workspace_id + "|" + sender + "|" + message_id).encode()
    ).hexdigest()[:32]
    request = OperationRequest(
        operation_id=op_id, principal_id=agent_id,
        machine_id=machine.machine_id, capability_id=_CAP,
        work_item_id=local_work_item_id, idempotency_key=op_id,
        arguments={"remote_peer_id": sender, "remote_subject_id": subject_id,
                   "signed_envelope_sha256": evidence_sha,
                   "workspace_id": workspace_id},
    )
    policy = BoundWorkItemPolicy(
        owner=runtime.owner, principal_type="agent",
        governance=runtime.governance,
        authorization=AuthorizationService(canvas.state_dir.parent),
    )
    decision = policy(request)
    if not isinstance(decision, PolicyDecision) or decision.allowed is not True:
        raise AuthorizationRequired("SENTRA local peer admission grant denied")

    async def record_reference_only(req):
        return OperationResult(
            req.operation_id, "SUCCEEDED",
            {"reference_admitted": True, "remote_work_executed": False},
        )

    gate = DurableOperationGate(
        CentralDurableIntentAuthority(runtime.durable), policy, machine=machine,
    )
    result = asyncio.run(gate.submit(
        run_id=run["run_id"], owner=runtime.owner,
        request=request, effect=record_reference_only,
    ))
    if result.state != "SUCCEEDED":
        raise PeerWireDenied("admission uncertain; reconcile existing Operation")
    with closing(wire._db()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute(
            "UPDATE peer_inbox SET state='ADMITTED_LOCAL_NO_EFFECT' "
            "WHERE workspace=? AND sender=? AND message_id=? "
            "AND kind='TASK_OFFER' AND state='PENDING_LOCAL_ADMISSION'",
            (workspace_id, sender, message_id),
        ).rowcount
        if changed != 1:
            raise PeerWireDenied("inbox changed during local admission")
    return {"state": "ADMITTED_LOCAL_NO_EFFECT", "operation_id": op_id,
            "work_item_id": local_work_item_id, "remote_task_executed": False,
            "receipt_is_work_completion": False}
