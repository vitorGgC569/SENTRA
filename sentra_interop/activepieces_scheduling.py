"""Activepieces schedule/webhook triggers bound to SENTRA routines.

The owned SDK worker reports ``setSchedule`` intents and trigger events, but
it must not create a global scheduler or admit central tasks by itself. This
module is the host-side counterpart:

- :meth:`ActivepiecesScheduleBridge.schedule_handler` is the callback the
  host passes as ``schedule_handler`` to ``OwnedPieceSDKBackend``. It
  associates an AP schedule request with a governance routine subscription
  and refuses to invent scheduler state.
- :meth:`ActivepiecesScheduleBridge.webhook_handler` ingests trigger webhook
  events with ``_dedupe_key`` claims and delegates task admission to the
  host's existing central admission callback.

Both paths fail explicitly when the host has not configured the referenced
routine subscription or admission callback.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from .workflow_contracts import digest, ident


class ActivepiecesScheduleConflict(ValueError):
    pass


class ActivepiecesScheduleBridge:
    """Bind AP piece schedules and webhooks to routine subscriptions."""

    def __init__(self, database: str, *, workspace: str,
                 trigger_admitter: Callable | None = None,
                 trigger_lookup: Callable | None = None,
                 clock=time.time, control=None) -> None:
        self.control = control
        root, target = Path(workspace).resolve(), Path(database).resolve()
        if target == root or not target.is_relative_to(root):
            raise ValueError("AP schedule projection outside workspace")
        from .workflow_storage import projection_path
        projection_path(database, workspace, control=control)
        self.database = str(target)
        self.trigger_admitter, self.trigger_lookup = trigger_admitter, trigger_lookup
        self.clock = clock
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS ap_schedule_bindings(
                subscription_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                routine_id TEXT NOT NULL, piece TEXT NOT NULL,
                version TEXT NOT NULL, member TEXT NOT NULL,
                connection_id TEXT, schedule_sha256 TEXT NOT NULL,
                enable_operation_id TEXT NOT NULL, updated REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS ap_webhook_claims(
                subscription_id TEXT NOT NULL, event_key TEXT NOT NULL,
                event_sha256 TEXT NOT NULL, work_item_id TEXT,
                PRIMARY KEY(subscription_id, event_key))""")

    @contextmanager
    def _db(self):
        from .workflow_storage import projection_db
        with projection_db(self.database, control=self.control) as conn:
            yield conn

    def bind_schedule(self, *, owner: str, subscription_id: str,
                      routine_id: str, piece: str, version: str,
                      member: str, connection_id: str | None,
                      schedule: dict, enable_operation_id: str,
                      operator_approved: bool = False) -> dict:
        """Pin an AP schedule request to a governance routine subscription."""
        if operator_approved is not True:
            raise PermissionError("host owner approval required to bind AP schedule")
        ident(subscription_id)
        ident(routine_id)
        if not isinstance(schedule, dict) or not schedule:
            raise ValueError("AP schedule descriptor required")
        digest(schedule)
        if not isinstance(enable_operation_id, str) or not enable_operation_id:
            raise ValueError("central enable operation identity required")
        record = {"subscription_id": subscription_id, "owner": owner,
                  "routine_id": routine_id, "piece": piece, "version": version,
                  "member": member, "connection_id": connection_id,
                  "schedule_sha256": digest(schedule),
                  "enable_operation_id": enable_operation_id,
                  "updated": self.clock()}
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM ap_schedule_bindings "
                             "WHERE subscription_id=?", (subscription_id,)).fetchone()
            if old is not None and (
                    old["owner"], old["routine_id"], old["piece"],
                    old["version"], old["member"], old["connection_id"],
                    old["schedule_sha256"]) != (
                    owner, routine_id, piece, version, member,
                    connection_id, record["schedule_sha256"]):
                raise ActivepiecesScheduleConflict(
                    "AP schedule subscription already bound differently")
            db.execute(
                "INSERT INTO ap_schedule_bindings VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(subscription_id) DO UPDATE SET updated=excluded.updated",
                (subscription_id, owner, routine_id, piece, version, member,
                 connection_id, record["schedule_sha256"],
                 enable_operation_id, record["updated"]))
        return record

    def _enabled_binding(self, subscription_id, request=None):
        if self.control is None:
            raise PermissionError("configured central control required")
        with self._db() as db:
            binding = db.execute("SELECT * FROM ap_schedule_bindings WHERE subscription_id=?", (subscription_id,)).fetchone()
        if binding is None:
            raise PermissionError("AP subscription not bound")
        enable = self.control.durable.operation_status(binding["enable_operation_id"], binding["owner"])
        if enable["state"] != "SUCCEEDED" or enable.get("progress", {}).get("capability_id") != "activepieces:trigger_enable":
            raise PermissionError("AP enable has no successful central receipt")
        if request is not None:
            source = self.control.work_item_info(request.work_item_id, binding["owner"])
            enabled = self.control.work_item_info(enable["progress"]["work_item_id"], binding["owner"])
            if source["run_id"] != enable["run_id"] or source.get("metadata", {}).get("workspace_id") != enabled.get("metadata", {}).get("workspace_id"):
                raise PermissionError("AP trigger outside enabled Run/project")
        return binding

    def schedule_handler(self, request: Any, schedule: dict) -> dict:
        """Callback for ``OwnedPieceSDKBackend(schedule_handler=...)``.

        The SDK worker invokes this with the piece schedule request and the
        originating intent ``request``. Only a previously bound
        ``subscription_id`` may fire, and firing only returns the pinned
        routine reference for the host scheduler to drive through
        ``RoutineSchedulerService``; it never enqueues work itself.
        """
        subscription_id = (getattr(request, "arguments", {}) or {}).get("subscription_id")
        if not isinstance(subscription_id, str):
            raise ValueError("AP schedule intent carries no subscription scope")
        if not isinstance(schedule, dict) or not schedule:
            raise ValueError("AP schedule descriptor required")
        with self._db() as db:
            binding = db.execute("SELECT * FROM ap_schedule_bindings "
                                 "WHERE subscription_id=?", (subscription_id,)).fetchone()
        if binding is None:
            raise PermissionError("AP schedule subscription is not bound to a routine")
        if digest(schedule) != binding["schedule_sha256"]:
            raise ActivepiecesScheduleConflict("AP schedule descriptor changed")
        from sentra_runtime.effect_boundary import current_effect_context
        context = current_effect_context.get()
        if context is None or context.request != request or context.receipt.owner != binding["owner"]:
            raise PermissionError("AP schedule outside admitted hook")
        routine = self.control.governance.routine_info(binding["routine_id"], binding["owner"])
        trigger_spec = ({"cron": schedule["cronExpression"], "timezone": schedule.get("timezone", "UTC")}
            if "cronExpression" in schedule else {"every_seconds": schedule["intervalMs"] / 1000})
        if any(routine["trigger_spec"].get(key) != value for key, value in trigger_spec.items()):
            raise ActivepiecesScheduleConflict("SDK schedule differs from configured central routine")
        context.checkpoint()
        return {"subscription_id": subscription_id,
                "routine_id": binding["routine_id"],
                "owner": binding["owner"],
                "schedule_sha256": binding["schedule_sha256"],
                "drive_via": "RoutineSchedulerService.tick",
                "enqueued_here": False}

    def webhook_handler(self, *, subscription_id: str,
                        events: list[dict]) -> list[dict]:
        """Ingest AP webhook/polling events into central task admission.

        Each event carries ``_dedupe_key`` (or a content digest when absent)
        and an event payload mapping. New keys claim first, then call the
        host's ``trigger_admitter``; repeats reuse the recorded WorkItem.
        """
        ident(subscription_id)
        if self.trigger_admitter is None:
            raise PermissionError(
                "no central trigger admission callback configured; "
                "webhook ingestion refuses to invent tasks")
        if not isinstance(events, list) or not 1 <= len(events) <= 100:
            raise ValueError("webhook event batch must be 1..100 items")
        with self._db() as db:
            binding = db.execute("SELECT * FROM ap_schedule_bindings "
                                 "WHERE subscription_id=?", (subscription_id,)).fetchone()
        if binding is None:
            raise PermissionError("AP webhook subscription is not bound")
        from sentra_runtime.effect_boundary import current_effect_context
        context = current_effect_context.get()
        if context is None or context.receipt.owner != binding["owner"] or context.request.capability_id != "activepieces:trigger_ingest" or context.request.arguments.get("subscription_id") != subscription_id or context.request.arguments.get("events_sha256") != digest(events):
            raise PermissionError("webhook events require their exact central ingestion intent")
        binding = self._enabled_binding(subscription_id, context.request)
        outcomes = []
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("invalid webhook event envelope")
            payload = event.get("payload", event)
            if not isinstance(payload, dict):
                raise ValueError("webhook event payload must be a mapping")
            raw_key = event.get("_dedupe_key")
            event_key = (raw_key if isinstance(raw_key, str) and raw_key
                         else hashlib.sha256(digest(payload).encode()).hexdigest()[:32])
            if not isinstance(event_key,str) or not 1<=len(event_key)<=256 or any(char in event_key for char in "\0\r\n"):
                raise ValueError("bounded webhook dedupe key required")
            event_sha = digest(payload)
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                old = db.execute("SELECT * FROM ap_webhook_claims "
                                 "WHERE subscription_id=? AND event_key=?",
                                 (subscription_id, event_key)).fetchone()
                if old is not None:
                    if old["event_sha256"] != event_sha:
                        raise ActivepiecesScheduleConflict(
                            "webhook event key bound to different content")
                    outcomes.append({"event_key": event_key, "status": "REUSED" if old["work_item_id"] else "UNCERTAIN",
                                     "work_item_id": old["work_item_id"]})
                    continue
                db.execute("INSERT INTO ap_webhook_claims VALUES(?,?,?,NULL)",
                           (subscription_id, event_key, event_sha))
            context.checkpoint()
            admitted = self.trigger_admitter(subscription_id, event_key, payload)
            if not isinstance(admitted, dict) or not admitted.get("work_item_id"):
                raise ValueError("central trigger admission returned no WorkItem")
            item = self.control.work_item_info(admitted["work_item_id"], binding["owner"])
            origin = self.control.work_item_info(context.request.work_item_id, binding["owner"])
            if item["run_id"] != origin["run_id"] or item.get("metadata", {}).get("workspace_id") != origin.get("metadata", {}).get("workspace_id"):
                raise ActivepiecesScheduleConflict("trigger callback admitted a task outside source scope")
            with self._db() as db:
                db.execute("UPDATE ap_webhook_claims SET work_item_id=? "
                           "WHERE subscription_id=? AND event_key=?",
                           (admitted["work_item_id"], subscription_id, event_key))
            outcomes.append({"event_key": event_key, "status": "ADMITTED",
                             "work_item_id": admitted["work_item_id"]})
        return outcomes

    def reconcile_webhook(self, *, subscription_id: str,
                          event_key: str) -> dict | None:
        """Recover a claim whose admission reply was lost (lookup only)."""
        if self.trigger_lookup is None:
            raise PermissionError("no central trigger lookup configured")
        with self._db() as db:
            claim = db.execute("SELECT * FROM ap_webhook_claims "
                               "WHERE subscription_id=? AND event_key=?",
                               (subscription_id, event_key)).fetchone()
        if claim is None:
            return None
        if claim["work_item_id"] is not None:
            return {"event_key": event_key, "status": "ADMITTED",
                    "work_item_id": claim["work_item_id"]}
        found = self.trigger_lookup(subscription_id, event_key)
        if isinstance(found, dict) and found.get("work_item_id"):
            binding = self._enabled_binding(subscription_id)
            item = self.control.work_item_info(found["work_item_id"], binding["owner"])
            enable = self.control.durable.operation_status(binding["enable_operation_id"], binding["owner"])
            if item["run_id"] != enable["run_id"]:
                raise ActivepiecesScheduleConflict("recovered webhook task outside original Run")
            with self._db() as db:
                db.execute("UPDATE ap_webhook_claims SET work_item_id=? "
                           "WHERE subscription_id=? AND event_key=?",
                           (found["work_item_id"], subscription_id, event_key))
            return {"event_key": event_key, "status": "RECOVERED",
                    "work_item_id": found["work_item_id"]}
        return {"event_key": event_key, "status": "PENDING"}
