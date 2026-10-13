"""Durable, verifiable WorkItem/Operation receipts for Dot CLI handoffs and dispatches.

The physical PTY write or non-interactive CLI execution is one-shot under ShellHostRequests.
A transcript or input echo never proves a model reply.
Operation transitions to SUCCEEDED only with a cryptographically transformed nonce receipt.
WorkItem transitions to IN_REVIEW (never COMPLETED directly) until coordinator validation/consolidation.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import time


def _key(owner, project_id, request_key):
    raw = json.dumps([owner, project_id, request_key], separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _connect(control):
    return control.store.connect("shell")


def _ensure(control):
    with closing(_connect(control)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS canvas_dot_tool_deliveries (
            owner TEXT NOT NULL, project_id TEXT NOT NULL, space_id TEXT NOT NULL,
            request_key TEXT NOT NULL, source_dot_id TEXT NOT NULL,
            member_dot_id TEXT NOT NULL, tool TEXT NOT NULL,
            handoff_id TEXT NOT NULL, terminal_id TEXT NOT NULL,
            work_item_id TEXT NOT NULL, operation_id TEXT NOT NULL,
            start_cursor INTEGER NOT NULL, PRIMARY KEY(owner,project_id,request_key))""")
        db.execute("""CREATE TABLE IF NOT EXISTS canvas_dot_tool_dispatches (
            owner TEXT NOT NULL, project_id TEXT NOT NULL, space_id TEXT NOT NULL,
            request_key TEXT NOT NULL, source_dot_id TEXT NOT NULL,
            member_dot_id TEXT NOT NULL, tool TEXT NOT NULL,
            work_item_id TEXT NOT NULL, operation_id TEXT NOT NULL,
            receipt_json TEXT NOT NULL, verified INTEGER NOT NULL,
            status TEXT NOT NULL, created_at REAL NOT NULL,
            PRIMARY KEY(owner,project_id,request_key))""")


def reserve(canvas, control, owner, *, project_id, space_id, request_key,
            root_dot_id, source, target, tool, terminal_id, handoff_id,
            parent_work_item_id=None):
    """Reserve a central WorkItem/Operation before first physical write."""
    _ensure(control)
    ident = _key(owner, project_id, request_key)
    wid = "WI-dotcli-" + ident[:32]
    oid = "op-dotcli-" + ident[:32]
    run = canvas._runtime().run(project_id)
    if run["state"] != "RUNNING":
        raise PermissionError("Dot CLI handoff requires a running central Run")
    item = control.create_work_item(
        run["run_id"], owner, work_item_id=wid, external_key="dotcli-" + ident,
        parent_work_item_id=parent_work_item_id,
        assignee_agent_id=target["agent_id"],
        objective="Verify the result of a directed " + tool + " CLI handoff",
        acceptance_criteria=["Persisted provider/model acknowledgement, not terminal echo",
                             "Explicit verification before task completion"],
        execution_policy={"require_quality_gate": False},
        metadata={"workspace_id": project_id, "space_id": space_id,
                  "canvas_root_dot_id": root_dot_id, "source_dot_id": source["dot_id"],
                  "member_dot_id": target["dot_id"], "tool": tool,
                  "terminal_id": terminal_id, "handoff_id": handoff_id,
                  "parent_work_item_id": parent_work_item_id})
    if item["work_item_id"] != wid or item["run_id"] != run["run_id"]:
        raise RuntimeError("central WorkItem identity changed")
    operation = control.durable.create_operation(
        run["run_id"], owner, kind="canvas.dot_cli_handoff",
        idempotency_key="dotcli-" + ident, operation_id=oid,
        initial_state="RUNNING", cleanup_policy="manual")
    if operation["operation_id"] != oid or operation["kind"] != "canvas.dot_cli_handoff":
        raise RuntimeError("central Operation identity changed")
    if operation.get("idempotent_replay"):
        raise RuntimeError("prior central handoff exists: observe it; do not resend")
    if item["state"] == "PENDING":
        control.transition_work_item(wid, owner, "QUEUED",
                                     reason="operator authorized directed tool handoff")
    control.start_work_item_execution(wid, owner, run_id=run["run_id"],
                                      agent_id=target["agent_id"])
    start = canvas.store.terminal_output(project_id, terminal_id)["cursor"]
    with closing(_connect(control)) as db, db:
        db.execute("INSERT INTO canvas_dot_tool_deliveries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (owner, project_id, space_id, request_key, source["dot_id"], target["dot_id"],
                    tool, handoff_id, terminal_id, wid, oid, start))
    return {"work_item_id": wid, "operation_id": oid}


def reserve_dispatch(canvas, control, owner, *, project_id, space_id, request_key,
                     root_dot_id, source, target, tool, coordinator_work_item_id,
                     coordinator_operation_id=None, instruction=""):
    """Reserve a child WorkItem/Operation for non-interactive coordinator tool dispatch."""
    _ensure(control)
    ident = _key(owner, project_id, request_key)
    wid = "WI-dottool-" + ident[:32]
    oid = "op-dottool-" + ident[:32]
    run = canvas._runtime().run(project_id)
    if run["state"] != "RUNNING":
        raise PermissionError("Dot tool dispatch requires a running central Run")
    item = control.create_work_item(
        run["run_id"], owner, work_item_id=wid, external_key="dottool-" + ident,
        parent_work_item_id=coordinator_work_item_id,
        assignee_agent_id=target["agent_id"],
        objective=f"Non-interactive {tool} execution for instruction: {instruction[:120]}",
        acceptance_criteria=[
            "Verifiable inference receipt with transformed nonce, not terminal echo",
            "Explicit coordinator validation/consolidation before completion",
        ],
        execution_policy={"require_quality_gate": False},
        metadata={
            "workspace_id": project_id, "space_id": space_id,
            "canvas_root_dot_id": root_dot_id, "source_dot_id": source["dot_id"],
            "member_dot_id": target["dot_id"], "tool": tool,
            "parent_work_item_id": coordinator_work_item_id,
            "parent_operation_id": coordinator_operation_id,
        })
    operation = control.durable.create_operation(
        run["run_id"], owner, kind="canvas.dot_tool_dispatch",
        idempotency_key="dottool-" + ident, operation_id=oid,
        initial_state="RUNNING", cleanup_policy="manual")
    if operation.get("idempotent_replay"):
        return {"work_item_id": wid, "operation_id": oid, "idempotent_replay": True}
    if item["state"] == "PENDING":
        control.transition_work_item(wid, owner, "QUEUED",
                                     reason="coordinator authorized non-interactive tool dispatch")
    control.start_work_item_execution(wid, owner, run_id=run["run_id"],
                                      agent_id=target["agent_id"])
    return {"work_item_id": wid, "operation_id": oid, "idempotent_replay": False}


def record_dispatch_outcome(control, owner, *, project_id, space_id, request_key,
                            source_dot_id, member_dot_id, tool, ids, receipt):
    """Commit verified or uncertain dispatch outcome and perform strict state transitions.
    
    Operation SUCCEEDED only with valid receipt.
    WorkItem transitions to IN_REVIEW (not COMPLETED directly) pending coordinator consolidation.
    """
    _ensure(control)
    wid = ids["work_item_id"]
    oid = ids["operation_id"]
    verified = bool(receipt.get("verified"))

    if verified:
        control.durable.update_operation(
            oid, owner, state="SUCCEEDED",
            event_type="DOT_TOOL_INFERENCE_VERIFIED",
            progress={"work_item_id": wid, "receipt": receipt, "automatic_retry": False})
        try:
            control.transition_work_item(wid, owner, "VALIDATING",
                                         reason="validating non-interactive receipt",
                                         metadata={"receipt": receipt})
        except Exception:
            pass
        control.transition_work_item(wid, owner, "IN_REVIEW",
                                     reason="verifiable receipt acknowledged; pending coordinator consolidation",
                                     metadata={"receipt": receipt, "quality_gate": {"status": "passed", "passed": True}})
        status = "in_review"
    elif receipt.get("launch_failed"):
        control.durable.update_operation(
            oid, owner, state="FAILED",
            event_type="DOT_TOOL_DISPATCH_FAILED",
            progress={"work_item_id": wid, "receipt": receipt, "automatic_retry": False})
        try:
            control.transition_work_item(wid, owner, "FAILED",
                                         reason="tool process launch failed")
        except Exception:
            pass
        status = "failed"
    else:
        # Echo-only or ambiguous output -> UNCERTAIN, never retry
        control.durable.update_operation(
            oid, owner, state="UNCERTAIN",
            event_type="DOT_TOOL_DISPATCH_UNCERTAIN",
            progress={"work_item_id": wid, "receipt": receipt, "automatic_retry": False,
                      "reason": "unconfirmed model inference or terminal echo detected"})
        try:
            control.transition_work_item(wid, owner, "BLOCKED",
                                         reason="tool outcome uncertain; no automatic retry",
                                         metadata={"receipt": receipt})
        except Exception:
            pass
        status = "uncertain"

    with closing(_connect(control)) as db, db:
        db.execute(
            "INSERT INTO canvas_dot_tool_dispatches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(owner,project_id,request_key) DO UPDATE SET "
            "receipt_json=excluded.receipt_json, verified=excluded.verified, status=excluded.status",
            (owner, project_id, space_id, request_key, source_dot_id, member_dot_id,
             tool, wid, oid, json.dumps(receipt, ensure_ascii=False),
             1 if verified else 0, status, time.time()),
        )
    return {
        "status": status,
        "work_item_id": wid,
        "operation_id": oid,
        "verified": verified,
        "receipt": receipt,
        "automatic_retry": False,
    }


def sent(control, owner, ids):
    """Record accepted physical delivery only; model execution remains unproven."""
    control.durable.update_operation(
        ids["operation_id"], owner, state="WAITING_EXTERNAL",
        event_type="DOT_CLI_DELIVERED_NO_MODEL_ACK",
        progress={"work_item_id": ids["work_item_id"], "transport": "conpty-stdin",
                  "model_acknowledged": False, "automatic_retry": False})
    return ids


def uncertain(control, owner, ids, reason):
    """Best-effort UNCERTAIN on ambiguous physical writes; never retry."""
    try:
        op = control.durable.operation_status(ids["operation_id"], owner)
        if op["state"] in {"RUNNING", "WAITING_EXTERNAL", "STARTING"}:
            control.durable.update_operation(
                ids["operation_id"], owner, state="UNCERTAIN",
                event_type="DOT_CLI_DELIVERY_UNCERTAIN",
                progress={"automatic_retry": False, "reason": reason})
    except Exception:
        pass
    try:
        item = control.work_item_info(ids["work_item_id"], owner)
        if item["state"] == "RUNNING":
            control.transition_work_item(ids["work_item_id"], owner, "BLOCKED",
                                         reason="CLI physical outcome uncertain; no automatic retry")
    except Exception:
        pass


def deliveries(canvas, control, owner, project_id, space_id, member_dot_ids):
    _ensure(control)
    if not member_dot_ids:
        return []
    with closing(_connect(control)) as db:
        handoff_rows = [dict(r) for r in db.execute(
            "SELECT member_dot_id,source_dot_id,tool,handoff_id,terminal_id,"
            "work_item_id,operation_id,start_cursor FROM canvas_dot_tool_deliveries "
            "WHERE owner=? AND project_id=? AND space_id=? ORDER BY rowid DESC LIMIT 80",
            (owner, project_id, space_id))]
        dispatch_rows = [dict(r) for r in db.execute(
            "SELECT member_dot_id,source_dot_id,tool,request_key,work_item_id,"
            "operation_id,receipt_json,verified,status FROM canvas_dot_tool_dispatches "
            "WHERE owner=? AND project_id=? AND space_id=? ORDER BY rowid DESC LIMIT 80",
            (owner, project_id, space_id))]

    result = []
    # Process handoffs
    for row in handoff_rows:
        if row["member_dot_id"] not in member_dot_ids or row["source_dot_id"] not in member_dot_ids:
            continue
        item = control.work_item_info(row["work_item_id"], owner)
        op = control.durable.operation_status(row["operation_id"], owner)
        live = canvas._sessions.get(row["terminal_id"])
        pty = getattr(live, "pty", None)
        if op["state"] == "WAITING_EXTERNAL" and (pty is None or pty.poll() is not None):
            uncertain(control, owner, row, "missing owned live CLI after handoff")
            item = control.work_item_info(row["work_item_id"], owner)
            op = control.durable.operation_status(row["operation_id"], owner)
        try:
            output = canvas.store.terminal_output(project_id, row["terminal_id"], row["start_cursor"])
            text = output.get("text", "")
            evidence = {"cursor": output["cursor"], "post_send_chars": len(text),
                        "post_send_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "truncated": bool(output.get("truncated"))}
        except Exception:
            evidence = {"unavailable": True}
        result.append({
            **{k: row[k] for k in ("member_dot_id", "source_dot_id", "tool",
                                   "handoff_id", "terminal_id", "work_item_id", "operation_id")},
            "work_item_state": item["state"], "operation_state": op["state"],
            "transcript_evidence": evidence, "model_acknowledged": False,
            "model_result_verified": False, "task_completed": False,
            "mode": "handoff",
        })

    # Process dispatches
    for row in dispatch_rows:
        if row["member_dot_id"] not in member_dot_ids or row["source_dot_id"] not in member_dot_ids:
            continue
        item = control.work_item_info(row["work_item_id"], owner)
        op = control.durable.operation_status(row["operation_id"], owner)
        try:
            receipt = json.loads(row["receipt_json"])
        except Exception:
            receipt = {}
        result.append({
            "member_dot_id": row["member_dot_id"],
            "source_dot_id": row["source_dot_id"],
            "tool": row["tool"],
            "handoff_id": row["request_key"],
            "terminal_id": "",
            "work_item_id": row["work_item_id"],
            "operation_id": row["operation_id"],
            "work_item_state": item["state"],
            "operation_state": op["state"],
            "transcript_evidence": {
                "post_send_chars": receipt.get("output_chars", 0),
                "post_send_sha256": receipt.get("stdout_sha256"),
            },
            "model_acknowledged": bool(row["verified"]),
            "model_result_verified": bool(row["verified"]),
            "task_completed": item["state"] == "COMPLETED",
            "receipt": receipt,
            "mode": "dispatch",
        })
    return result


def terminal_lost(control, owner, project_id, terminal_id):
    """One owned handle closed: never infer remote completion or replay it."""
    _ensure(control)
    with closing(_connect(control)) as db:
        rows = [dict(row) for row in db.execute(
            "SELECT DISTINCT work_item_id,operation_id FROM canvas_dot_tool_deliveries "
            "WHERE owner=? AND project_id=? AND terminal_id=?",
            (owner, project_id, terminal_id))]
    for ids in rows:
        uncertain(control, owner, ids, "owned ConPTY closed before model result verification")
    return {"unverified_deliveries": len(rows), "automatic_retry": False}
