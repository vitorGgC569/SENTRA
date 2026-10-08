"""Durable routine scheduler built on normal SENTRA WorkItems."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Callable


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


class RoutineSchedulerService:
    """Turns due schedule routines into idempotent normal WorkItems."""

    def __init__(
        self,
        control_plane: Any,
        *,
        clock: Callable[[], float] = time.time,
        poll_interval_s: float = 5.0,
    ) -> None:
        self.control = control_plane
        self.governance = control_plane.governance
        self.clock = clock
        self.poll_interval_s = max(0.2, float(poll_interval_s))
        self._stop = asyncio.Event()

    def _scheduled_rows(self) -> list[dict[str, Any]]:
        with self.governance._connect() as db:
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
        base = float(routine.get("last_fired_at") or routine.get("created_at") or self.clock())
        next_due = RoutineSchedule.next_due(routine["trigger_spec"], base)
        return self.governance.update_routine_clock(
            routine["routine_id"], routine["owner"], next_due_at=next_due
        )

    def tick(self, *, now: float | None = None) -> dict[str, Any]:
        current = self.clock() if now is None else float(now)
        results: list[dict[str, Any]] = []
        for raw in self._scheduled_rows():
            try:
                routine = self._initialize_due(raw)
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
                occurrences = RoutineSchedule.occurrences_until(
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
                        fired.append({
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
                            "error": str(exc)[:2000],
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
                next_due = RoutineSchedule.next_due(
                    routine["trigger_spec"], last_occurrence
                )
                while next_due is not None and next_due <= current:
                    next_due = RoutineSchedule.next_due(
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
                    "error": str(exc)[:2000],
                })
        return {"checked_at": current, "items": results}

    async def run(self) -> None:
        self._stop.clear()
        while not self._stop.is_set():
            self.tick()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval_s)
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()
