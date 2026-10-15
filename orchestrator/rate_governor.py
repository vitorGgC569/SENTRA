"""Shared provider pacing and platform-hold governor."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import time
from contextlib import nullcontext

from .process_lock import exclusive_file_lock
from pathlib import Path
from typing import Any, Callable


class ProviderRateGovernor:
    """Persisted, provider-isolated dispatch pacing.

    This component never authorizes replay. It only answers when a *new*,
    already-authorized send may be attempted.
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        minimum_intervals: dict[str, float] | None = None,
        *,
        state_path: Path | str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.minimum_intervals = {
            "chatgpt": 30.0,
            "gemini": 15.0,
            **{str(k): max(0.0, float(v)) for k, v in (minimum_intervals or {}).items()},
        }
        self.clock = clock
        self.state_path = Path(state_path).resolve() if state_path else None
        self._process_lock_path = (
            self.state_path.with_name(self.state_path.name + ".lock")
            if self.state_path else None
        )
        self._lock = threading.RLock()
        self._lanes: dict[str, dict[str, Any]] = {}
        self._load()

    def _lane(self, provider: str) -> dict[str, Any]:
        key = str(provider or "").strip().lower()
        if not key:
            raise ValueError("provider is required")
        return self._lanes.setdefault(
            key,
            {"last_dispatch": 0.0, "hold_until": 0.0, "reason": "", "failures": 0},
        )

    def _load(self) -> None:
        if not self.state_path or not self.state_path.is_file():
            return
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("invalid provider rate governor state")
        lanes = data.get("lanes") or {}
        if not isinstance(lanes, dict):
            raise ValueError("invalid provider rate lanes")
        self._lanes = {
            str(k): {
                "last_dispatch": float(v.get("last_dispatch", 0.0)),
                "hold_until": float(v.get("hold_until", 0.0)),
                "reason": str(v.get("reason", "")),
                "failures": int(v.get("failures", 0)),
            }
            for k, v in lanes.items() if isinstance(v, dict)
        }

    def _save(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(
            prefix=".provider-rate-", suffix=".tmp", dir=self.state_path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    {"schema_version": self.SCHEMA_VERSION, "lanes": self._lanes},
                    handle, indent=2, sort_keys=True,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.state_path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def _process_guard(self):
        return (
            exclusive_file_lock(self._process_lock_path)
            if self._process_lock_path is not None
            else nullcontext()
        )

    def _delay_for_locked(self, provider: str) -> float:
        lane = self._lane(provider)
        now = self.clock()
        interval = self.minimum_intervals.get(str(provider).lower(), 0.0)
        pacing_until = float(lane["last_dispatch"]) + interval
        return max(0.0, pacing_until - now, float(lane["hold_until"]) - now)

    def delay_for(self, provider: str) -> float:
        with self._lock:
            with self._process_guard():
                if self.state_path and self.state_path.is_file():
                    self._load()
                return self._delay_for_locked(provider)

    async def wait(self, provider: str) -> None:
        delay = self.delay_for(provider)
        if delay > 0:
            await asyncio.sleep(delay)

    def record_dispatch(self, provider: str) -> None:
        with self._lock:
            with self._process_guard():
                if self.state_path and self.state_path.is_file():
                    self._load()
                lane = self._lane(provider)
                lane["last_dispatch"] = self.clock()
                self._save()

    def hold(self, provider: str, seconds: float, *, reason: str) -> None:
        if seconds < 0:
            raise ValueError("hold seconds cannot be negative")
        with self._lock:
            with self._process_guard():
                if self.state_path and self.state_path.is_file():
                    self._load()
                lane = self._lane(provider)
                lane["hold_until"] = max(float(lane["hold_until"]), self.clock() + seconds)
                lane["reason"] = str(reason or "PLATFORM_HOLD")[:120]
                lane["failures"] = int(lane["failures"]) + 1
                self._save()

    def clear_hold(self, provider: str) -> None:
        with self._lock:
            with self._process_guard():
                if self.state_path and self.state_path.is_file():
                    self._load()
                lane = self._lane(provider)
                lane.update(hold_until=0.0, reason="", failures=0)
                self._save()

    def record_outcome(
        self, provider: str, outcome: str, *, retry_after_s: float | None = None
    ) -> None:
        normalized = str(outcome or "").strip().upper()
        if normalized in {"PLATFORM_HOLD", "RATE_LIMITED", "QUOTA_EXHAUSTED"}:
            with self._lock:
                with self._process_guard():
                    if self.state_path and self.state_path.is_file():
                        self._load()
                    lane = self._lane(provider)
                    failures = int(lane["failures"])
                    fallback = min(300.0, 15.0 * (2 ** min(failures, 4)))
                    seconds = max(fallback, float(retry_after_s or 0.0))
                    lane["hold_until"] = max(
                        float(lane["hold_until"]), self.clock() + seconds
                    )
                    lane["reason"] = normalized[:120]
                    lane["failures"] = failures + 1
                    self._save()
        elif normalized in {"AVAILABLE", "COMPLETED", "READY"}:
            self.clear_hold(provider)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            with self._process_guard():
                if self.state_path and self.state_path.is_file():
                    self._load()
                now = self.clock()
                return {
                    provider: {
                        **dict(lane),
                        "delay_s": self._delay_for_locked(provider),
                        "held": float(lane["hold_until"]) > now,
                    }
                    for provider, lane in self._lanes.items()
                }


class HostResourceGovernor:
    """Short, persisted pause while the host CPU or RAM is hot.

    ``observe`` records pressure and returns a delay. It does not sleep, renice,
    kill, or touch a VM. The delay never exceeds 2 seconds, including a value
    reloaded from disk, so a restart cannot stall the machine for minutes.
    """

    SCHEMA_VERSION = 1
    MAX_DELAY_S = 2.0

    def __init__(
        self,
        *,
        state_path: Path | str | None = None,
        clock: Callable[[], float] = time.time,
        max_delay_s: float = 2.0,
        ram_hot_percent: float = 85.0,
        cpu_hot_percent: float = 85.0,
    ) -> None:
        if isinstance(max_delay_s, bool) or not isinstance(max_delay_s, (int, float)):
            raise ValueError("max_delay_s must be a number")
        if not 0 < float(max_delay_s) <= self.MAX_DELAY_S:
            raise ValueError("max_delay_s must be within (0, 2]")
        for name, value in (("ram_hot_percent", ram_hot_percent), ("cpu_hot_percent", cpu_hot_percent)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 50 <= float(value) <= 95:
                raise ValueError(f"{name} must stay inside 50..95")
        self.max_delay_s = float(max_delay_s)
        self.ram_hot_percent = float(ram_hot_percent)
        self.cpu_hot_percent = float(cpu_hot_percent)
        self.clock = clock
        self.state_path = Path(state_path).resolve() if state_path else None
        self._process_lock_path = (
            self.state_path.with_name(self.state_path.name + ".lock")
            if self.state_path else None
        )
        self._lock = threading.RLock()
        self._hold_until = 0.0
        self._reason = ""
        self._load()

    def _process_guard(self):
        return (
            exclusive_file_lock(self._process_lock_path)
            if self._process_lock_path is not None
            else nullcontext()
        )

    def _load(self) -> None:
        if not self.state_path or not self.state_path.is_file():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("invalid host resource governor state") from exc
        if not isinstance(data, dict) or data.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("invalid host resource governor state")
        if "hold_until" not in data:
            raise ValueError("invalid host resource governor state")
        try:
            hold = float(data.get("hold_until") or 0.0)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid host resource governor state") from exc
        now = self.clock()
        if hold > now + self.max_delay_s:
            hold = now + self.max_delay_s
        self._hold_until = max(0.0, hold)
        self._reason = str(data.get("reason") or "")[:120]

    def _save(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(
            prefix=".host-pressure-", suffix=".tmp", dir=str(self.state_path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    {
                        "schema_version": self.SCHEMA_VERSION,
                        "hold_until": self._hold_until,
                        "reason": self._reason,
                    },
                    handle, indent=2, sort_keys=True,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.state_path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def _delay_locked(self) -> float:
        remaining = float(self._hold_until) - self.clock()
        if remaining <= 0:
            return 0.0
        return min(self.max_delay_s, remaining)

    def _hot(self, ram_percent: float, cpu_percent: float | None, available_mb: int | None) -> bool:
        if ram_percent >= self.ram_hot_percent:
            return True
        if cpu_percent is not None and cpu_percent >= self.cpu_hot_percent:
            return True
        return available_mb is not None and available_mb < 1024

    def observe(
        self,
        *,
        ram_percent: float,
        cpu_percent: float | None = None,
        available_mb: int | None = None,
    ) -> float:
        """Return the seconds a caller may wait. This method itself does not sleep."""
        if isinstance(ram_percent, bool) or not isinstance(ram_percent, (int, float)):
            raise ValueError("ram_percent must be a number")
        if not 0 <= float(ram_percent) <= 100:
            raise ValueError("ram_percent out of range")
        if cpu_percent is not None:
            if isinstance(cpu_percent, bool) or not isinstance(cpu_percent, (int, float)):
                raise ValueError("cpu_percent must be a number or null")
            if not 0 <= float(cpu_percent) <= 100:
                raise ValueError("cpu_percent out of range")
        if available_mb is not None and (type(available_mb) is not int or available_mb < 0):
            raise ValueError("available_mb must be a non-negative int")
        with self._lock:
            with self._process_guard():
                if self.state_path and self.state_path.is_file():
                    self._load()
                if self._hot(float(ram_percent), None if cpu_percent is None else float(cpu_percent), available_mb):
                    self._hold_until = min(
                        max(self._hold_until, self.clock() + self.max_delay_s),
                        self.clock() + self.max_delay_s,
                    )
                    self._reason = "host_pressure"
                self._save()
                return self._delay_locked()

    def delay(self) -> float:
        with self._lock:
            with self._process_guard():
                if self.state_path and self.state_path.is_file():
                    self._load()
                return self._delay_locked()

    def clear(self) -> None:
        with self._lock:
            with self._process_guard():
                self._hold_until = 0.0
                self._reason = ""
                self._save()

    async def wait(self) -> float:
        delay = self.delay()
        if delay > 0:
            await asyncio.sleep(delay)
        return delay

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            with self._process_guard():
                if self.state_path and self.state_path.is_file():
                    self._load()
                return {
                    "delay_s": self._delay_locked(),
                    "reason": self._reason,
                    "hold_until": self._hold_until,
                    "max_delay_s": self.max_delay_s,
                    "authorizes_effects": False,
                    "sleeps_in_observe": False,
                    "changes_priority": False,
                }
