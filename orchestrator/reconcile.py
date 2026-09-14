"""Operator reconciliation for blocked conversation seats.

A seat stuck IN_FLIGHT/UNCERTAIN/BLOCKED halts its run by design (an uncertain
send is never auto-replayed: it might already be posted in the user's chat).
Only an explicit operator decision unblocks it, and only by DISCARDING the
uncertain intent — the next send opens a FRESH chat. Reconciliation never
resumes or replays the ambiguous delivery itself.

Paths follow the --status convention: run_dir is workspace/runs/<job-id>.

Forensics come from the relay's own SQLite (read-only) plus the seat record:
- no relay job for (task_id, window)  -> the send never dispatched: safe discard
- job QUEUED/LEASED (stale lease)     -> worker died or abandoned it: safe discard
- job COMPLETED with result           -> answer exists; operator reviews it manually
- anything else                       -> keep blocked, investigate further
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

from .conversation_pool import FixedConversationRouter, inspect_conversations


def relay_jobs_for_task(db_path, task_id: str, since_ts: float = 0.0) -> List[Dict[str, Any]]:
    """Read-only lookup of relay jobs for a task. Never writes, never locks
    for writing (immutable URI). Returns [] when the database is absent."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    uri = f"file:{db_path}?mode=ro"
    found = []
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    except Exception:
        return []
    try:
        rows = conn.execute(
            "SELECT id, payload, state, worker, lease_until, updated FROM jobs").fetchall()
    except Exception:
        conn.close()
        return []
    for jid, payload, state, worker, lease_until, updated in rows:
        try:
            data = json.loads(payload or "{}")
        except Exception:
            continue
        if data.get("task_id") != task_id:
            continue
        if updated and updated < since_ts:
            continue
        found.append({"job_id": jid, "state": state, "worker": worker or "",
                      "lease_until": lease_until, "updated": updated})
    conn.close()
    return sorted(found, key=lambda r: r["updated"] or 0.0)


def blocked_seats(run_dir) -> List[Dict[str, Any]]:
    """Seats currently blocking their run, with evidence, newest last."""
    run_dir = Path(run_dir)
    info = inspect_conversations(run_dir, run_dir.name)
    out = []
    for key in info.get("blocked_seats", []):
        entry = (info.get("seats", {}) or {}).get(key, {})
        out.append({"seat": key, "state": entry.get("state"),
                    "task_id": entry.get("task_id"),
                    "updated": entry.get("updated"),
                    "request_sha256": entry.get("request_sha256", "")[:16]})
    return out


def drop_seat(run_dir, seat: str, reason: str) -> Dict[str, Any]:
    """Operator-explicit discard of a stuck seat intent. The seat entry is
    removed (next send opens a fresh chat) and the decision is journaled.
    Refuses non-blocking seats: nothing ambiguous, nothing to reconcile."""
    run_dir = Path(run_dir)
    # Same validation as the pool: no symlinks, same run, known seat.
    pool = FixedConversationRouter(None, run_dir.name, run_dir)
    current = pool.seats().get(seat)
    if current is None:
        raise ValueError(f"unknown seat '{seat}' for run '{run_dir.name}'")
    if current.get("state") not in {"IN_FLIGHT", "UNCERTAIN", "BLOCKED"}:
        raise ValueError(f"seat '{seat}' is {current.get('state')}; only stuck seats may be dropped")
    del pool._map[seat]
    pool._save()
    record = {"ts": time.time(), "run_id": run_dir.name, "seat": seat,
              "action": "drop-stale-intent", "reason": reason,
              "dropped_state": current.get("state"),
              "dropped_task_id": current.get("task_id"),
              "operator": "cli --drop-seat (explicit, no auto-replay)"}
    audit = run_dir / "reconciliations.jsonl"
    with open(audit, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
