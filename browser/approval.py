"""Deny-only observed approval ledger for Web model pages.

The ChatGPT page may present a human approval card (connector/tool approval)
while a turn is pending. SENTRA must *observe* that state — show
WAITING_APPROVAL in Canvas/CLI/shell and refuse new sends — but NEVER click,
accept or dismiss the card programmatically. This module stores those
observations as data; the durable consent gate (Pacto) and the operator remain
the only approval authority.
"""
from __future__ import annotations

import time

from sentra_mcp.services.chat_access import _ID, _PRINCIPAL, _validate

APPROVAL_STATES = frozenset({"pending", "cleared", "unknown"})
MAX_TOOL_NAME = 200


class ApprovalLedger:
    """Per-conversation approval observations in the chat_access database."""

    def __init__(self, store) -> None:
        self.store = store
        db = self.store.connect("chat_access")
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS browser_approval_observations(
                    principal TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    state TEXT NOT NULL, tool_name TEXT,
                    observed REAL NOT NULL,
                    PRIMARY KEY(principal,conversation_id));
            """)
        finally:
            db.close()

    def observe(self, *, principal: str, conversation_id: str,
                state: str, tool_name: str | None = None) -> dict:
        """Record a page-observed approval state. Never performs approval."""
        _validate("principal", principal, _PRINCIPAL)
        _validate("conversation identity", conversation_id, _ID)
        if state not in APPROVAL_STATES:
            raise ValueError("unknown approval observation state")
        if tool_name is not None:
            if not isinstance(tool_name, str) or not 1 <= len(tool_name) <= MAX_TOOL_NAME:
                raise ValueError("approval tool name must be 1..200 characters")
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO browser_approval_observations VALUES(?,?,?,?,?) "
                       "ON CONFLICT(principal,conversation_id) DO UPDATE SET "
                       "state=excluded.state,tool_name=excluded.tool_name,observed=excluded.observed",
                       (principal, conversation_id, state, tool_name, time.time()))
            db.commit()
            return {"state": state, "tool_name": tool_name,
                    "effect_performed": False, "grants_created": False}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def status(self, principal: str, conversation_id: str,
               *, max_age_s: float = 120.0) -> dict:
        """Conservative approval view. Stale or missing observations fail closed."""
        _validate("principal", principal, _PRINCIPAL)
        _validate("conversation identity", conversation_id, _ID)
        if not isinstance(max_age_s, (int, float)) or max_age_s <= 0 or max_age_s > 3600:
            raise ValueError("invalid approval freshness window")
        db = self.store.connect("chat_access")
        try:
            row = db.execute("SELECT state,tool_name,observed FROM browser_approval_observations "
                             "WHERE principal=? AND conversation_id=?",
                             (principal, conversation_id)).fetchone()
        finally:
            db.close()
        if row is None:
            return {"state": "unverified", "send_blocked": False,
                    "evidence_present": False}
        age = max(0.0, time.time() - float(row["observed"]))
        blocked = row["state"] == "pending" or age > max_age_s
        return {"state": str(row["state"]), "tool_name": row["tool_name"],
                "age_s": round(age, 2), "send_blocked": bool(blocked),
                "evidence_present": True, "effect_performed": False}
