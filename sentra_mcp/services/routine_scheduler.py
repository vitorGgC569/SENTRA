"""Durable routine scheduler built on normal SENTRA WorkItems."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from contextlib import contextmanager


def _parse_field(field: str, minimum: int, maximum: int) -> set[int]:
    field = str(field).strip()
    if not field:
        raise ValueError("empty cron field")
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError("empty cron list entry")
        step = 1
        if "/" in part:
            base, raw_step = part.split("/", 1)
            step = int(raw_step)
            if step < 1:
                raise ValueError("cron step must be positive")
        else:
            base = part
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            raw_start, raw_end = base.split("-", 1)
            start, end = int(raw_start), int(raw_end)
        else:
            start = end = int(base)
        if start < minimum or end > maximum or start > end:
            raise ValueError("cron field is out of range")
        values.update(range(start, end + 1, step))
    return values


def _cron_matches(spec: str, ts: float) -> bool:
    parts = str(spec or "").split()
    if len(parts) != 5:
        raise ValueError("cron must have five fields: minute hour day month weekday")
    minute, hour, day, month, weekday = (
        _parse_field(parts[0], 0, 59),
        _parse_field(parts[1], 0, 23),
        _parse_field(parts[2], 1, 31),
        _parse_field(parts[3], 1, 12),
        _parse_field(parts[4], 0, 7),
    )
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    # Cron Sunday may be 0 or 7. Python Monday is 0.
    cron_weekday = (dt.weekday() + 1) % 7
    weekday_ok = cron_weekday in weekday or (
        cron_weekday == 0 and 7 in weekday
    )
    return (
        dt.minute in minute
        and dt.hour in hour
        and dt.day in day
        and dt.month in month
        and weekday_ok
    )


def _parse_at(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        raise ValueError("schedule at value is required")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


class RoutineSchedule:
    """Deterministic UTC schedule evaluator for one-shot, interval and cron triggers."""

    @staticmethod
    def next_due(trigger_spec: dict[str, Any], after: float) -> float | None:
        spec = dict(trigger_spec or {})
        if "at" in spec:
            at = _parse_at(spec["at"])
            return at if at > after else None

        interval = spec.get("every_seconds", spec.get("interval_seconds"))
        if interval is not None:
            seconds = float(interval)
            if not 1 <= seconds <= 31_536_000:
                raise ValueError("routine interval must be 1..31536000 seconds")
            anchor = float(spec.get("anchor_at", 0.0) or 0.0)
            if anchor <= 0:
                return after + seconds
            if after < anchor:
                return anchor
            elapsed = after - anchor
            steps = int(elapsed // seconds) + 1
            return anchor + steps * seconds

        cron = spec.get("cron")
        if cron:
            # Search by minute boundary for at most 400 days. Cron is intentionally
            # UTC unless a future timezone-aware trigger adapter is supplied.
            cursor = int(after // 60) * 60 + 60
            limit = cursor + 400 * 24 * 60 * 60
            while cursor <= limit:
                if _cron_matches(str(cron), float(cursor)):
                    return float(cursor)
                cursor += 60
            raise ValueError("cron has no matching occurrence within 400 days")

        raise ValueError(
            "schedule trigger_spec requires one of at, every_seconds/interval_seconds, cron"
        )

    @classmethod
    def occurrences_until(
        cls,
        trigger_spec: dict[str, Any],
        first_due: float,
        now: float,
        *,
        limit: int,
    ) -> list[float]:
        if limit < 1:
            return []
        out: list[float] = []
        due: float | None = float(first_due)
        while due is not None and due <= now and len(out) < limit:
            out.append(due)
            due = cls.next_due(trigger_spec, due)
        return out


class RoutineScheduleTZ:
    """Timezone/DST-aware schedule evaluation over :class:`RoutineSchedule`.

    ``trigger_spec`` may additionally carry:

    - ``timezone``: IANA name (e.g. ``America/Sao_Paulo``). Cron fields are
      then matched against local wall time. DST gaps are skipped (a wall
      minute that never occurs fires nothing); ambiguous wall minutes fire
      only on the first occurrence (fold 0). Unknown zones and missing
      tzdata fail explicitly instead of silently using UTC.
    - ``calendar_exclusions``: list of ``YYYY-MM-DD`` local dates to skip.
    - ``every_after_completion_seconds``: interval measured from the last
      *completed* occurrence (distinct modality from cron and from
      anchor-based intervals). Due computation needs the completion
      ledger; use :meth:`next_due_after_completion`.

    Specs without these keys delegate exactly to :class:`RoutineSchedule`.
    """

    @staticmethod
    def _exclusions(trigger_spec: dict[str, Any]) -> set[str]:
        raw = trigger_spec.get("calendar_exclusions", [])
        if not raw:
            return set()
        if (not isinstance(raw, list) or len(raw) > 3660
                or any(not isinstance(entry, str) for entry in raw)):
            raise ValueError("calendar_exclusions must be a bounded date list")
        excluded = set()
        for entry in raw:
            try:
                parsed = datetime.strptime(entry.strip(), "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("calendar exclusion must be YYYY-MM-DD")
            excluded.add(parsed.isoformat())
        return excluded

    @staticmethod
    def _tz_next_due(trigger_spec: dict[str, Any], after: float) -> float:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        zone_name = trigger_spec.get("timezone", "UTC")
        if not isinstance(zone_name, str) or not 1 <= len(zone_name) <= 64:
            raise ValueError("bounded IANA timezone name required")
        try:
            tz = ZoneInfo(zone_name)
        except ZoneInfoNotFoundError:
            raise ValueError(
                f"unknown timezone {zone_name!r}; install tzdata/provision "
                "the zone instead of silently using UTC")
        cron = trigger_spec.get("cron")
        if not cron:
            raise ValueError("timezone-aware schedules require cron")
        parts = str(cron).split()
        if len(parts) != 5:
            raise ValueError("cron must have five fields")
        minute, hour, day, month, weekday = (
            _parse_field(parts[0], 0, 59), _parse_field(parts[1], 0, 23),
            _parse_field(parts[2], 1, 31), _parse_field(parts[3], 1, 12),
            _parse_field(parts[4], 0, 7))
        excluded = RoutineScheduleTZ._exclusions(trigger_spec)
        cursor = int(after // 60) * 60 + 60
        limit = cursor + (400 * 24 * 60 + 240) * 60
        while cursor <= limit:
            loc = datetime.fromtimestamp(cursor, tz=tz)
            naive = loc.replace(tzinfo=None)
            # DST gap: wall minute that round-trips on neither fold.
            first = naive.replace(tzinfo=tz, fold=0)
            first_ok = (first.astimezone(timezone.utc).astimezone(tz)
                        .replace(tzinfo=None) == naive)
            second = naive.replace(tzinfo=tz, fold=1)
            second_ok = (second.astimezone(timezone.utc).astimezone(tz)
                         .replace(tzinfo=None) == naive)
            if not first_ok and not second_ok:
                cursor += 60
                continue
            ambiguous = (first_ok and second_ok
                         and first.utcoffset() != second.utcoffset())
            if ambiguous and cursor != int(first.timestamp()):
                # Repeated wall minute: fire only the first occurrence.
                cursor += 60
                continue
            cron_weekday = (loc.weekday() + 1) % 7
            weekday_ok = cron_weekday in weekday or (
                cron_weekday == 0 and 7 in weekday)
            if (loc.minute in minute and loc.hour in hour
                    and loc.day in day and loc.month in month and weekday_ok
                    and loc.date().isoformat() not in excluded):
                return float(cursor)
            cursor += 60
        raise ValueError("cron has no matching occurrence within 400 days")

    @staticmethod
    def next_due(trigger_spec: dict[str, Any], after: float) -> float | None:
        spec = dict(trigger_spec or {})
        if "every_after_completion_seconds" in spec:
            raise ValueError("after-completion schedules need completion state; "
                             "use next_due_after_completion")
        if spec.get("timezone") is not None or spec.get("calendar_exclusions"):
            return RoutineScheduleTZ._tz_next_due(spec, after)
        return RoutineSchedule.next_due(spec, after)

    @staticmethod
    def next_due_after_completion(trigger_spec: dict[str, Any],
                                  completed_at: float | None,
                                  fallback: float) -> float:
        spec = dict(trigger_spec or {})
        interval = spec.get("every_after_completion_seconds")
        if interval is None:
            raise ValueError("not an after-completion schedule")
        seconds = float(interval)
        if not 1 <= seconds <= 31_536_000:
            raise ValueError("after-completion interval must be 1..31536000 seconds")
        base = float(completed_at) if completed_at is not None else float(fallback)
        return base + seconds

    @staticmethod
    def occurrences_until(trigger_spec: dict[str, Any], first_due: float,
                          now: float, *, limit: int) -> list[float]:
        if limit < 1:
            return []
        spec = dict(trigger_spec or {})
        if "every_after_completion_seconds" in spec:
            # Single occurrence per completion: never catch up a backlog.
            return [float(first_due)] if float(first_due) <= now else []
        out: list[float] = []
        due: float | None = float(first_due)
        while due is not None and due <= now and len(out) < limit:
            out.append(due)
            due = RoutineScheduleTZ.next_due(spec, due)
        return out


class RoutinePolicyStore:
    """Failure guard, cost ledger and completion tracking for routines.

    Lives in the governance database (same connection the scheduler
    already uses) as Pulso-owned ``pulso_routine_state`` projections.
    Never reserves Operations or Grants itself; pausing uses the existing
    governance enable flag. Costs are reservations against caps configured
    in routine metadata (``_pulso_cost_cap_usd``); the central budget
    authority remains the host's budget service.
    """

    def __init__(self, connect: Callable, *, clock: Callable[[], float] = time.time):
        self._connect = connect
        self.clock = clock
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pulso_routine_state(
                routine_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                paused INTEGER NOT NULL DEFAULT 0,
                paused_reason TEXT,
                awaiting_completion INTEGER NOT NULL DEFAULT 0,
                last_completed_at REAL, last_state TEXT,
                spent_micro_usd INTEGER NOT NULL DEFAULT 0,
                updated REAL NOT NULL)""")

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, routine_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM pulso_routine_state WHERE routine_id=?",
                             (routine_id,)).fetchone()
        return dict(row) if row is not None else None

    def _ensure(self, db: Any, routine_id: str, owner: str) -> None:
        previous=db.execute("SELECT owner FROM pulso_routine_state WHERE routine_id=?",(routine_id,)).fetchone()
        if previous and previous["owner"]!=owner:
            raise PermissionError("routine policy owner changed")
        db.execute("INSERT OR IGNORE INTO pulso_routine_state VALUES(?,?,0,0,NULL,0,"
                   "NULL,NULL,0,?)", (routine_id, owner, self.clock()))

    def set_paused(self, routine_id: str, owner: str, paused: bool,
                   reason: str | None) -> None:
        if reason is not None and (not isinstance(reason, str) or len(reason) > 500):
            raise ValueError("bounded pause reason required")
        with self._db() as db:
            self._ensure(db, routine_id, owner)
            db.execute("UPDATE pulso_routine_state SET paused=?,paused_reason=?,"
                       "updated=? WHERE routine_id=?",
                       (1 if paused else 0, reason, self.clock(), routine_id))

    def set_awaiting(self, routine_id: str, owner: str, awaiting: bool) -> None:
        with self._db() as db:
            self._ensure(db, routine_id, owner)
            db.execute("UPDATE pulso_routine_state SET awaiting_completion=?,updated=? "
                       "WHERE routine_id=?",
                       (1 if awaiting else 0, self.clock(), routine_id))

    def note_completion(self, routine_id: str, owner: str, *,
                        completed_at: float | None = None,
                        terminal_state: str, cost_usd: float = 0.0, operation_id: str | None = None) -> dict[str, Any]:
        """Record a terminal routine outcome (called by the host/composer).

        ``terminal_state`` is one of SUCCEEDED/FAILED/CANCELLED. Success
        resets the consecutive-failure counter; failure increments it.
        """
        if terminal_state not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            raise ValueError("terminal routine state required")
        if (type(cost_usd) not in (int, float) or cost_usd != cost_usd
                or cost_usd < 0 or cost_usd > 1_000_000):
            raise ValueError("bounded non-negative routine cost required")
        micro = round(float(cost_usd) * 1_000_000)
        now = self.clock()
        completed = float(completed_at) if completed_at is not None else now
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS pulso_routine_receipts(owner TEXT NOT NULL,operation_id TEXT NOT NULL,routine_id TEXT NOT NULL,state TEXT NOT NULL,micro_usd INTEGER NOT NULL,PRIMARY KEY(owner,operation_id))")
            db.execute("BEGIN IMMEDIATE")
            self._ensure(db, routine_id, owner)
            if operation_id is not None:
                old=db.execute("SELECT * FROM pulso_routine_receipts WHERE owner=? AND operation_id=?",(owner,operation_id)).fetchone()
                if old:
                    if (old["routine_id"],old["state"],old["micro_usd"])!=(routine_id,terminal_state,micro):
                        raise ValueError("immutable routine receipt changed")
                    return dict(db.execute("SELECT * FROM pulso_routine_state WHERE routine_id=?",(routine_id,)).fetchone())
                db.execute("INSERT INTO pulso_routine_receipts VALUES(?,?,?,?,?)",(owner,operation_id,routine_id,terminal_state,micro))
            if terminal_state == "SUCCEEDED":
                db.execute("UPDATE pulso_routine_state SET consecutive_failures=0,"
                           "awaiting_completion=0,last_completed_at=?,last_state=?,"
                           "spent_micro_usd=spent_micro_usd+?,updated=? "
                           "WHERE routine_id=?",
                           (completed, terminal_state, micro, now, routine_id))
            else:
                db.execute("UPDATE pulso_routine_state SET consecutive_failures="
                           "consecutive_failures+1,awaiting_completion=0,"
                           "last_completed_at=?,last_state=?,"
                           "spent_micro_usd=spent_micro_usd+?,updated=? "
                           "WHERE routine_id=?",
                           (completed, terminal_state, micro, now, routine_id))
        row = self.get(routine_id)
        assert row is not None
        return row

    def check_before_fire(self, routine: dict[str, Any]) -> str | None:
        """Return a pause reason when firing must be skipped, else None."""
        metadata = dict(routine.get("metadata") or {})
        state = self.get(routine["routine_id"])
        if state is not None and state["paused"]:
            return str(state["paused_reason"] or "manually paused")
        if state is not None and state["awaiting_completion"]:
            return "awaiting previous completion (strict non-overlap)"
        cap = metadata.get("_pulso_cost_cap_usd")
        if cap is not None:
            try:
                cap_micro = round(float(cap) * 1_000_000)
            except (TypeError, ValueError):
                return "invalid cost cap metadata"
            spent = state["spent_micro_usd"] if state else 0
            if spent >= cap_micro:
                return f"routine cost cap reached ({spent / 1_000_000:.6f} USD spent)"
        return None

    def maybe_auto_pause(self, governance: Any, routine: dict[str, Any]) -> str | None:
        """Auto-pause on configured consecutive failures or cost cap."""
        metadata = dict(routine.get("metadata") or {})
        state = self.get(routine["routine_id"])
        if state is None:
            return None
        max_failures = metadata.get("_pulso_max_consecutive_failures", 0)
        try:
            max_failures = int(max_failures)
        except (TypeError, ValueError):
            max_failures = 0
        reason: str | None = None
        if max_failures > 0 and state["consecutive_failures"] >= max_failures:
            reason = (f"auto-paused after {state['consecutive_failures']} consecutive "
                      "failures; review before resuming")
        else:
            reason = self.check_before_fire(routine)
            if reason is not None and "cost cap reached" not in reason:
                reason = None
        if reason is not None and not state["paused"]:
            self.set_paused(routine["routine_id"], routine["owner"], True, reason)
            try:
                governance.set_routine_enabled(
                    routine["routine_id"], routine["owner"], enabled=False)
            except (FileNotFoundError, PermissionError):
                pass
            return reason
        return reason if state["paused"] else None


class RoutineSchedulerService:
    """Turns due schedule routines into idempotent normal WorkItems."""

    def __init__(
        self,
        control_plane: Any,
        *,
        clock: Callable[[], float] = time.time,
        poll_interval_s: float = 5.0,
        cost_resolver=None,
        occurrence_dispatcher=None,
    ) -> None:
        self.cost_resolver=cost_resolver
        self.occurrence_dispatcher=occurrence_dispatcher
        self.control = control_plane
        self.governance = control_plane.governance
        self.clock = clock
        self.poll_interval_s = max(0.2, float(poll_interval_s))
        self.policies = RoutinePolicyStore(
            self.governance._connect, clock=clock)
        self._stop = asyncio.Event()

    def _scheduled_rows(self) -> list[dict[str, Any]]:
        with self.policies._db() as db:
            rows = db.execute(
                "SELECT routine_id,owner FROM routines "
                "WHERE enabled=1 AND trigger_kind='schedule' ORDER BY updated_at"
            ).fetchall()
        return [
            self.governance.routine_info(str(row["routine_id"]), str(row["owner"]))
            for row in rows
        ]

    def _initialize_due(self, routine: dict[str, Any]) -> dict[str, Any]:
        if routine.get("next_due_at") is not None:
            return routine
        if "every_after_completion_seconds" in dict(routine.get("trigger_spec") or {}):
            # Completion-driven modality: the ledger owns the next due.
            return routine
        base = float(routine.get("last_fired_at") or routine.get("created_at") or self.clock())
        next_due = RoutineScheduleTZ.next_due(routine["trigger_spec"], base)
        return self.governance.update_routine_clock(
            routine["routine_id"], routine["owner"], next_due_at=next_due
        )

    def tick(self, *, now: float | None = None) -> dict[str, Any]:
        current = self.clock() if now is None else float(now)
        results: list[dict[str, Any]] = []
        for raw in self._scheduled_rows():
            try:
                routine = self._initialize_due(raw)
                gate_reason = self.policies.check_before_fire(routine)
                if gate_reason is not None:
                    auto = self.policies.maybe_auto_pause(self.governance, routine)
                    results.append({
                        "routine_id": routine["routine_id"],
                        "status": "PAUSED",
                        "reason": auto or gate_reason,
                    })
                    continue
                if "every_after_completion_seconds" in dict(
                        routine.get("trigger_spec") or {}):
                    results.append(self._tick_after_completion(routine, current))
                    continue
                due = routine.get("next_due_at")
                if due is None or float(due) > current:
                    continue

                metadata = dict(routine.get("metadata") or {})
                authority_run_id = str(
                    metadata.get("_runtime_authority_run_id") or ""
                ).strip()
                goal_id = str(metadata.get("_runtime_goal_id") or "").strip() or None
                if not authority_run_id:
                    results.append({
                        "routine_id": routine["routine_id"],
                        "status": "UNBOUND",
                        "reason": "scheduled routine has no runtime authority Run binding",
                    })
                    continue

                cap = (
                    int(routine["missed_cap"])
                    if routine["missed_policy"] == "enqueue_missed_with_cap"
                    else 1
                )
                occurrences = RoutineScheduleTZ.occurrences_until(
                    routine["trigger_spec"], float(due), current, limit=cap
                )
                fired: list[dict[str, Any]] = []
                failed = False
                for scheduled_at in occurrences:
                    occurrence_key = f"{scheduled_at:.6f}"
                    try:
                        outcome = self.control.fire_routine(
                            routine["routine_id"],
                            routine["owner"],
                            run_id=authority_run_id,
                            goal_id=goal_id,
                            source=f"schedule:{occurrence_key}",
                            occurrence_key=occurrence_key,
                        )
                        execution = None
                        if self.occurrence_dispatcher is not None and (outcome.get("work_item") or {}).get("metadata", {}).get("routine_occurrence_key") == occurrence_key:
                            execution = self.occurrence_dispatcher(routine, occurrence_key, outcome["work_item"])
                        fired.append({
                            "execution": execution,
                            "scheduled_at": scheduled_at,
                            "status": outcome.get("status"),
                            "work_item_id": (
                                (outcome.get("work_item") or {}).get("work_item_id")
                            ),
                        })
                    except Exception as exc:
                        failed = True
                        fired.append({
                            "scheduled_at": scheduled_at,
                            "status": "FAILED",
                            "error_type": type(exc).__name__,
                        })
                        break

                if failed:
                    results.append({
                        "routine_id": routine["routine_id"],
                        "status": "RETRY_PENDING",
                        "fires": fired,
                        "next_due_at": due,
                    })
                    continue

                # skip_missed fires one occurrence and skips backlog. Catch-up
                # advances occurrence-by-occurrence up to missed_cap, then skips
                # any remaining backlog to the first future occurrence.
                last_occurrence = occurrences[-1] if occurrences else float(due)
                next_due = RoutineScheduleTZ.next_due(
                    routine["trigger_spec"], last_occurrence
                )
                while next_due is not None and next_due <= current:
                    next_due = RoutineScheduleTZ.next_due(
                        routine["trigger_spec"], next_due
                    )
                self.governance.update_routine_clock(
                    routine["routine_id"],
                    routine["owner"],
                    next_due_at=next_due,
                    last_fired_at=last_occurrence,
                )
                results.append({
                    "routine_id": routine["routine_id"],
                    "status": "PROCESSED",
                    "fires": fired,
                    "next_due_at": next_due,
                })
            except Exception as exc:
                results.append({
                    "routine_id": raw.get("routine_id"),
                    "status": "ERROR",
                    "error_type": type(exc).__name__,
                })
        return {"checked_at": current, "items": results}

    def _tick_after_completion(self, routine: dict[str, Any],
                                 current: float) -> dict[str, Any]:
        """Fire one occurrence measured from the last *completed* run.

        Strict non-overlap: while the previous occurrence has no recorded
        terminal outcome the routine waits instead of enqueueing. A misfire
        (downtime) fires exactly one occurrence for the missed slot — no
        backlog catch-up — keeping occurrence identity unique.
        """
        routine_id, owner = routine["routine_id"], routine["owner"]
        metadata = dict(routine.get("metadata") or {})
        authority_run_id = str(
            metadata.get("_runtime_authority_run_id") or "").strip()
        goal_id = str(metadata.get("_runtime_goal_id") or "").strip() or None
        if not authority_run_id:
            return {"routine_id": routine_id, "status": "UNBOUND",
                    "reason": "scheduled routine has no runtime authority Run binding"}
        state = self.policies.get(routine_id)
        fallback = float(routine.get("created_at") or current)
        due = RoutineScheduleTZ.next_due_after_completion(
            routine["trigger_spec"],
            state["last_completed_at"] if state else None, fallback)
        if due > current:
            if routine.get("next_due_at") != due:
                self.governance.update_routine_clock(routine_id, owner, next_due_at=due)
            return {"routine_id": routine_id, "status": "PENDING", "next_due_at": due}
        occurrence_key = f"{due:.6f}"
        try:
            outcome = self.control.fire_routine(
                routine_id, owner, run_id=authority_run_id, goal_id=goal_id,
                source=f"schedule:{occurrence_key}", occurrence_key=occurrence_key)
        except Exception as exc:
            return {"routine_id": routine_id, "status": "RETRY_PENDING",
                    "fires": [{"scheduled_at": due, "status": "FAILED",
                               "error_type": type(exc).__name__}],
                    "next_due_at": routine.get("next_due_at")}
        work = outcome.get("work_item") or {}
        if work.get("work_item_id"):
            if self.occurrence_dispatcher is not None and work.get("metadata", {}).get("routine_occurrence_key") == occurrence_key:
                self.occurrence_dispatcher(routine, occurrence_key, work)
            # ENQUEUED or coalesced onto a live item: strict non-overlap
            # waits for that item's terminal outcome either way.
            self.policies.set_awaiting(routine_id, owner, True)
            self.governance.update_routine_clock(
                routine_id, owner, next_due_at=None, last_fired_at=due)
            return {"routine_id": routine_id, "status": "PROCESSED",
                    "fires": [{"scheduled_at": due, "status": outcome.get("status"),
                               "work_item_id": work["work_item_id"]}],
                    "next_due_at": None,
                    "awaiting_completion": True}
        cooldown = RoutineScheduleTZ.next_due_after_completion(
            routine["trigger_spec"], current, current)
        self.governance.update_routine_clock(
            routine_id, owner, next_due_at=cooldown, last_fired_at=due)
        return {"routine_id": routine_id, "status": "PROCESSED",
                "fires": [{"scheduled_at": due, "status": outcome.get("status"),
                           "work_item_id": None}],
                "next_due_at": cooldown}

    def set_paused(self, routine_id: str, owner: str, *, paused: bool,
                   reason: str | None = None,
                   operator_approved: bool = False) -> dict[str, Any]:
        """Manually pause/resume a schedule (host owner approval required)."""
        if operator_approved is not True:
            raise PermissionError("pausing a schedule requires host owner approval")
        self.governance.routine_info(routine_id, owner)
        default = "manually paused by host owner" if paused else None
        self.policies.set_paused(routine_id, owner, paused,
                                 reason if reason is not None else default)
        self.governance.set_routine_enabled(routine_id, owner, enabled=not paused)
        return {"routine_id": routine_id, "paused": paused,
                "reason": reason if reason is not None else default}

    def note_outcome(self, routine_id, owner, *, terminal_state, cost_usd=None, operation_id=None):
        """Only authoritative terminal WorkItem/Operation receipts count."""
        if operation_id is None:
            raise ValueError("central operation_id required for routine outcome")
        routine=self.governance.routine_info(routine_id,owner)
        operation=self.control.durable.operation_status(operation_id,owner)
        item_id=operation.get("progress",{}).get("work_item_id")
        item=self.control.work_item_info(item_id,owner)
        expected={"COMPLETED":"SUCCEEDED","FAILED":"FAILED","CANCELLED":"CANCELLED"}.get(item["state"])
        if (operation["state"]!=terminal_state or expected!=terminal_state or item.get("metadata",{}).get("routine_id")!=routine_id):
            raise PermissionError("routine completion requires the same terminal central WorkItem")
        if cost_usd is not None:
            raise PermissionError("caller cost cannot replace the central usage ledger")
        if self.cost_resolver is None:
            raise RuntimeError("central cost receipt resolver unavailable; completion remains unaccounted")
        micro=self.cost_resolver(owner=owner,operation_id=operation_id,work_item_id=item_id)
        if type(micro) is not int or not 0<=micro<=1_000_000_000_000:
            raise ValueError("central usage must return exact integer micro-USD")
        cost=micro/1_000_000
        state=self.policies.note_completion(routine_id,owner,terminal_state=terminal_state,
            cost_usd=cost,completed_at=operation["updated_at"],operation_id=operation_id)
        auto=self.policies.maybe_auto_pause(self.governance,routine)
        return {"routine_id":routine_id,"state":state,"auto_paused":auto,"operation_id":operation_id}

    async def run(self) -> None:
        self._stop.clear()
        while not self._stop.is_set():
            await asyncio.to_thread(self.tick)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval_s)
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()
