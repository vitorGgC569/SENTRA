"""Read-only reconciliation after crash, canvas close, relay loss or reboot.

The plan never resubmits an effect. UNCERTAIN, in-flight and IN_REVIEW records
stay observable. Terminal records are preserved. Calling the planner twice
with the same inputs returns the same digest and writes nothing.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


INCIDENTS = frozenset({"crash", "canvas_closed", "relay_down", "reboot"})

_OBSERVE_OPERATION = {"UNCERTAIN", "RUNNING", "QUEUED", "WAITING_EXTERNAL"}
_TERMINAL_OPERATION = {"SUCCEEDED", "FAILED", "CANCELLED"}
_TERMINAL_WORK = {"COMPLETED", "FAILED", "CANCELLED"}
_BLOCK_CONVERSATION = {
    "uncertain", "queued", "running", "in_flight", "blocked",
    "IN_FLIGHT", "UNCERTAIN", "BLOCKED", "QUEUED", "RUNNING",
}
_PRESERVE_CONVERSATION = {"completed", "confirmed", "CONFIRMED", "COMPLETED", "CLEARED"}
_GRANT_OBSERVE = {"claimed", "uncertain", "CLAIMED", "UNCERTAIN"}
_BLOCK_RELAY = {"QUEUED", "LEASED", "IN_FLIGHT", "RUNNING", "BLOCKED"}


def _digest(plan: dict[str, Any]) -> str:
    body = {key: value for key, value in plan.items() if key != "digest"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class UncertainRecovery:
    def __init__(self, incident: str):
        if incident not in INCIDENTS:
            raise ValueError("incident must be crash, canvas_closed, relay_down or reboot")
        self.incident = incident

    def reconcile(
        self,
        *,
        operations: Iterable[dict[str, Any]] = (),
        conversations: Iterable[dict[str, Any]] = (),
        grants: Iterable[dict[str, Any]] = (),
        work_items: Iterable[dict[str, Any]] = (),
        relay_jobs: Iterable[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        items = []
        items.extend(self._rows("operation", operations, self._operation))
        items.extend(self._rows("conversation", conversations, self._conversation))
        items.extend(self._rows("grant", grants, self._grant))
        items.extend(self._rows("work_item", work_items, self._work_item))
        items.extend(self._rows("relay_job", relay_jobs, self._relay))
        items.sort(key=lambda item: (item["kind"], item["id"]))
        plan = {
            "incident": self.incident,
            "effects_executed": 0,
            "may_resend": False,
            "automatic_retry": False,
            "second_effect": False,
            "promoted_work_items": 0,
            "items": items,
            "counts": {
                "observe": sum(item["disposition"] == "observe" for item in items),
                "preserve": sum(item["disposition"] == "preserve" for item in items),
                "blocked": sum(item["disposition"] == "blocked" for item in items),
            },
        }
        plan["digest"] = _digest(plan)
        return plan

    def reconcile_durable(
        self,
        control: Any,
        owner: str,
        run_id: str,
        *,
        conversations: Iterable[dict[str, Any]] = (),
        grants: Iterable[dict[str, Any]] = (),
        work_items: Iterable[dict[str, Any]] = (),
        relay_jobs: Iterable[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        """Read central operations and plan. Does not transition or resend them."""
        operations = []
        offset = 0
        while True:
            page = control.durable.list_operations(run_id, owner, offset=offset, limit=1000)
            for item in page["items"]:
                operations.append({"id": item["operation_id"], "state": item["state"]})
            nxt = page.get("page", {}).get("next_offset")
            if nxt is None or nxt == offset:
                break
            offset = nxt
        return self.reconcile(
            operations=operations,
            conversations=conversations,
            grants=grants,
            work_items=work_items,
            relay_jobs=relay_jobs,
        )

    def _rows(self, kind: str, rows: Iterable[dict[str, Any]], classify) -> list[dict[str, Any]]:
        items = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{kind} entry must be an object")
            ident = row.get("id")
            state = row.get("state")
            if not isinstance(ident, str) or not ident:
                raise ValueError(f"{kind} id required")
            if not isinstance(state, str) or not state:
                raise ValueError(f"{kind} state required")
            items.append({
                "kind": kind,
                "id": ident,
                "state": state,
                "disposition": classify(row),
                "may_resend": False,
                "action": "none",
            })
        return items

    @staticmethod
    def _operation(row: dict[str, Any]) -> str:
        state = row["state"]
        if state in _TERMINAL_OPERATION:
            return "preserve"
        return "observe"

    @staticmethod
    def _conversation(row: dict[str, Any]) -> str:
        state = row["state"]
        if state in _BLOCK_CONVERSATION:
            return "blocked"
        if state in _PRESERVE_CONVERSATION:
            return "preserve"
        return "observe"

    @staticmethod
    def _grant(row: dict[str, Any]) -> str:
        if row["state"] in _GRANT_OBSERVE or row.get("revoked") == "uncertain":
            return "observe"
        return "preserve"

    @staticmethod
    def _work_item(row: dict[str, Any]) -> str:
        if row["state"] in _TERMINAL_WORK:
            return "preserve"
        return "observe"

    @staticmethod
    def _relay(row: dict[str, Any]) -> str:
        state = row["state"]
        if state == "COMPLETED":
            return "preserve"
        if state in _BLOCK_RELAY:
            return "blocked"
        return "observe"
