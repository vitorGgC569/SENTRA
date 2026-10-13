"""Host-only outbox crash recovery (Rastro).

Observation only: classifies every durable Web delivery as
not_sent/pending/unconfirmed/sent and every relay job as
QUEUED/LEASED/COMPLETED/FAILED. Unconfirmed deliveries are NEVER
retransmitted here; they require receipt reconciliation or an explicit
human decision. Provenance: feder-cr/invisible_dots outbox/receipt
pattern + Chat On Steroids P0 outbox (`src/main/session/input.ts`,
`recorder.ts`, `store.ts`).
"""
from __future__ import annotations

from typing import Any


def _job_rows(jobs) -> list[dict[str, Any]]:
    with jobs.lock:
        rows = jobs.db.execute(
            "SELECT id,state,worker,deadline,phase,requeues,may_have_sent,created,updated "
            "FROM jobs ORDER BY updated").fetchall()
        return [dict(row) for row in rows]


def recover_outbox(jobs, *, control=None) -> dict[str, Any]:
    """Return a crash-recovery report without sending anything."""
    items: list[dict[str, Any]] = []
    for row in _job_rows(jobs):
        job_id = row["id"]
        try:
            delivery = jobs.delivery_status(job_id)
        except Exception:
            delivery = None
        relay_state = row.get("state")
        delivery_state = (delivery or {}).get("state")
        uncertain = bool(delivery_state in {"pending", "unconfirmed"} or row.get("may_have_sent"))
        if delivery_state == "sent":
            action = "reconcile_receipt"
            needs_operator = False
        elif delivery_state == "unconfirmed" or (uncertain and relay_state in {"LEASED", "FAILED"}):
            action = "operator_decision"
            needs_operator = True
        elif delivery_state == "pending":
            action = "wait_worker"
            needs_operator = False
        elif relay_state == "QUEUED":
            action = "wait_worker"
            needs_operator = False
        elif relay_state in {"COMPLETED", "FAILED"} and delivery_state in {None, "not_sent"}:
            action = "none"
            needs_operator = False
        else:
            action = "operator_decision"
            needs_operator = True
        items.append({"job_id": job_id, "relay_state": relay_state,
                      "phase": row.get("phase") or "", "worker": row.get("worker") or "",
                      "requeues": int(row.get("requeues") or 0),
                      "may_have_sent": bool(row.get("may_have_sent")),
                      "delivery": delivery, "delivery_state": delivery_state,
                      "requires_operator_reconciliation": needs_operator,
                      "suggested_action": action, "automatic_resend": False})
    unconfirmed = sum(1 for item in items if (item["delivery_state"] or "") == "unconfirmed")
    return {"jobs": items, "total": len(items), "unconfirmed": unconfirmed,
            "automatic_resend": False,
            "note": "unconfirmed deliveries need receipt reconciliation, never automatic resend"}


def recover_continuations(control, owner: str) -> dict[str, Any]:
    """Reconcile open A->B continuations; never retries a send or rebind."""
    reconciled: list[dict[str, Any]] = []
    with control.session_checkpoints.store.connect("session_checkpoint") as db:
        rows = db.execute("SELECT continuation_id FROM session_continuations "
                          "WHERE owner=? AND state IN ('PREPARED','REBINDING','UNCERTAIN')",
                          (owner,)).fetchall()
    for row in rows:
        continuation_id = row["continuation_id"]
        try:
            status = control.reconcile_chat_continuation(owner, continuation_id)
            reconciled.append({"continuation_id": continuation_id,
                               "state": status.get("state"),
                               "requires_operator_reconciliation": bool(
                                   status.get("requires_operator_reconciliation")),
                               "automatic_resend": False})
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            reconciled.append({"continuation_id": continuation_id,
                               "state": "UNKNOWN", "error": str(exc)[:240],
                               "requires_operator_reconciliation": True,
                               "automatic_resend": False})
    return {"owner": owner, "open": reconciled, "automatic_resend": False}


def recover_web_sends(control, jobs, owner: str) -> dict[str, Any]:
    """Report durable WebSend intents; ANSWERED repair is observation-only."""
    from native_bridge.web_send import WebSendAuthority
    authority = WebSendAuthority(control, jobs)
    with control.session_checkpoints.store.connect("session_checkpoint") as db:
        rows = db.execute("SELECT job_id FROM web_send_intents WHERE owner=? "
                          "AND stage NOT IN ('ANSWERED','FAILED','REJECTED','CANCELLED')",
                          (owner,)).fetchall()
    intents: list[dict[str, Any]] = []
    for row in rows:
        job_id = row["job_id"]
        try:
            status = authority.status(owner, job_id)
            intents.append({"job_id": job_id, "state": status.get("state"),
                            "requires_operator_reconciliation": bool(
                                status.get("requires_operator_reconciliation")),
                            "automatic_resend": False})
        except (FileNotFoundError, ValueError, RuntimeError, PermissionError) as exc:
            intents.append({"job_id": job_id, "state": "UNKNOWN",
                            "error": str(exc)[:240],
                            "requires_operator_reconciliation": True,
                            "automatic_resend": False})
    return {"owner": owner, "intents": intents, "automatic_resend": False}
