"""Concurrent admission budgets with persistent reservations and honest accounting."""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from .process_lock import exclusive_file_lock


class BudgetExceeded(RuntimeError):
    pass


def estimate_input_tokens(messages) -> int:
    """Reserva na MESMA unidade da liquidação (tokens, não bytes).

    Antes: sum(bytes)+128 reservava ~4x o consumo real em ASCII contra limites
    em tokens, negando chamadas legítimas (e 4x pior com validadores
    concorrentes). Convenção do projeto: len//4.
    """
    total = sum(len((m.get("content") or "")) + 32 for m in messages) + 128
    return max(1, total // 4)


@dataclass
class Reservation:
    id: str
    bucket: str
    task_id: str
    amount: int


class TokenBudget:
    def __init__(self, master: int, secondary: int, save=None, state=None):
        if min(master, secondary) <= 0:
            raise ValueError("token budgets must be positive")
        self.limits = {"master": master, "secondary": secondary}
        self.used = {"master": 0, "secondary": 0}
        self.task_limits: dict[str, int] = {}
        self.task_used: dict[str, int] = {}
        self.reservations: dict[str, Reservation] = {}
        self.save = save
        self.accounting = {"provider": 0, "estimated": 0, "uncertain": 0}
        if state:
            self.limits = {key: min(value, state.get("limits", {}).get(key, value))
                           for key, value in self.limits.items()}
            self.used.update(state.get("used", {}))
            self.task_limits.update(state.get("task_limits", {}))
            self.task_used.update(state.get("task_used", {}))
            self.accounting.update(state.get("accounting", {}))
            # A crashed remote call may still have consumed its reserved tokens.
            for entry in state.get("reservations", {}).values():
                self.used[entry["bucket"]] += entry["amount"]
                tid = entry["task_id"]
                self.task_used[tid] = self.task_used.get(tid, 0) + entry["amount"]
                self.accounting["uncertain"] += entry["amount"]
            self._save()

    def register_task(self, task_id: str, limit: int):
        if limit <= 0:
            raise ValueError("task token budget must be positive")
        self.task_limits[task_id] = min(limit, self.task_limits.get(task_id, limit))
        self._save()

    def reserve(self, role: str, task_id: str, input_bound: int, output_limit: int) -> Reservation:
        if input_bound < 0 or output_limit <= 0:
            raise ValueError("invalid reservation bounds")
        bucket = "master" if role.split(".")[0] == "master" else "secondary"
        amount = input_bound + output_limit
        reserved_bucket = sum(r.amount for r in self.reservations.values() if r.bucket == bucket)
        reserved_task = sum(r.amount for r in self.reservations.values() if r.task_id == task_id)
        if self.used[bucket] + reserved_bucket + amount > self.limits[bucket]:
            raise BudgetExceeded(f"{bucket} token admission budget exhausted")
        if (task_id in self.task_limits and self.task_used.get(task_id, 0) + reserved_task + amount
                > self.task_limits[task_id]):
            raise BudgetExceeded(f"task {task_id} token admission budget exhausted")
        reservation = Reservation(uuid.uuid4().hex, bucket, task_id, amount)
        self.reservations[reservation.id] = reservation
        self._save()
        return reservation

    def settle(self, reservation: Reservation, usage=None, *, uncertain=False):
        if self.reservations.pop(reservation.id, None) is None:
            raise ValueError("reservation already settled")
        if uncertain or usage is None:
            amount, source = reservation.amount, "uncertain"
        else:
            amount = max(0, usage.input_tokens) + max(0, usage.output_tokens) + max(0, usage.reasoning_tokens)
            source = "provider" if usage.accounting == "provider" else "estimated"
        self.used[reservation.bucket] += amount
        self.task_used[reservation.task_id] = self.task_used.get(reservation.task_id, 0) + amount
        self.accounting[source] += amount
        self._save()
        if amount > reservation.amount:
            raise BudgetExceeded("provider exceeded reserved output budget; further work must stop")

    def remaining(self, bucket: str | None = None, task_id: str | None = None):
        reserved_by_bucket = {
            name: sum(r.amount for r in self.reservations.values() if r.bucket == name)
            for name in self.limits
        }
        remaining_by_bucket = {
            name: max(0, self.limits[name] - self.used.get(name, 0) - reserved_by_bucket[name])
            for name in self.limits
        }
        if task_id is not None:
            limit = self.task_limits.get(task_id)
            if limit is None:
                return None
            reserved = sum(r.amount for r in self.reservations.values() if r.task_id == task_id)
            return max(0, limit - self.task_used.get(task_id, 0) - reserved)
        if bucket is not None:
            if bucket not in remaining_by_bucket:
                raise ValueError(f"unknown budget bucket: {bucket}")
            return remaining_by_bucket[bucket]
        return remaining_by_bucket

    def exhausted(self, bucket: str | None = None, task_id: str | None = None) -> bool:
        remaining = self.remaining(bucket=bucket, task_id=task_id)
        if isinstance(remaining, dict):
            return all(value <= 0 for value in remaining.values())
        if remaining is None:
            return False
        return remaining <= 0

    def to_dict(self):
        return {"limits": self.limits, "used": self.used, "task_limits": self.task_limits,
                "task_used": self.task_used, "accounting": self.accounting,
                "remaining": self.remaining(),
                "reservations": {key: vars(value) for key, value in self.reservations.items()}}

    def _save(self):
        if self.save:
            self.save(self.to_dict())


_SURFACES = ("canvas", "terminal", "vm")
_DOT_BUDGET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


@dataclass
class ResourceReservation:
    id: str
    dot_id: str
    surface: str
    ram_mb: int
    cpu_percent: float


class HostResourceBudget:
    """Admission budget for host RAM and CPU. It does not kill or renice.

    Reservations survive a new instance on the same ``state_path``. They count
    until ``release``, including after a crash, so a restart cannot admit the
    same RAM twice. The snapshot for one Dot omits every other Dot's id.
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        *,
        total_mb: int,
        reserve_mb: int = 2048,
        max_cpu_percent: float = 85.0,
        surface_ram_mb: dict | None = None,
        save=None,
        state=None,
        state_path: Path | str | None = None,
    ):
        if type(total_mb) is not int or type(reserve_mb) is not int:
            raise ValueError("memory totals must be ints")
        if reserve_mb < 512 or reserve_mb >= total_mb:
            raise ValueError("reserve must leave the host usable room")
        if isinstance(max_cpu_percent, bool) or not isinstance(max_cpu_percent, (int, float)):
            raise ValueError("max_cpu_percent must be a number")
        if not 1 <= float(max_cpu_percent) <= 95:
            raise ValueError("cpu ceiling must stay inside 1..95 so the host keeps headroom")
        if state is not None and state_path is not None:
            raise ValueError("pass state or state_path, not both")
        caps = {"canvas": 2048, "terminal": 1024, "vm": 8192}
        if surface_ram_mb is not None:
            if not isinstance(surface_ram_mb, dict):
                raise TypeError("surface_ram_mb must be an object")
            unknown = set(surface_ram_mb) - set(caps)
            if unknown:
                raise ValueError("unknown surface: " + ", ".join(sorted(unknown)))
            for key, value in surface_ram_mb.items():
                if type(value) is not int or value < 128:
                    raise ValueError(f"{key} ram ceiling must be an int >= 128")
                caps[key] = value
        self.total_mb = total_mb
        self.reserve_mb = reserve_mb
        self.max_cpu_percent = float(max_cpu_percent)
        self.surface_ram_mb = caps
        self.save = save
        self.state_path = Path(state_path).resolve() if state_path else None
        self.reservations: dict[str, ResourceReservation] = {}
        self._lock = threading.RLock()
        if state is not None:
            self._apply_reservations(state)
        elif self.state_path is not None and self.state_path.is_file():
            self._apply_reservations(self._read_file())

    def _guard(self):
        if self.state_path is None:
            return nullcontext()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        return exclusive_file_lock(self.state_path.with_name(self.state_path.name + ".lock"))

    @staticmethod
    def _check_identity(dot_id: str, surface: str) -> None:
        if not isinstance(dot_id, str) or not _DOT_BUDGET_ID.fullmatch(dot_id):
            raise ValueError("invalid dot_id")
        if surface not in _SURFACES:
            raise ValueError("unknown surface")

    def _apply_reservations(self, data: dict) -> None:
        if not isinstance(data, dict) or data.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("invalid host resource budget state")
        raw = data.get("reservations")
        if not isinstance(raw, dict):
            raise ValueError("invalid host resource reservations")
        loaded: dict[str, ResourceReservation] = {}
        for key, entry in raw.items():
            if not isinstance(entry, dict):
                raise ValueError("invalid reservation")
            dot_id = entry.get("dot_id")
            surface = entry.get("surface")
            self._check_identity(str(dot_id or ""), str(surface or ""))
            ram = entry.get("ram_mb")
            cpu = entry.get("cpu_percent")
            if type(ram) is not int or ram < 0:
                raise ValueError("invalid reserved ram")
            if isinstance(cpu, bool) or not isinstance(cpu, (int, float)) or float(cpu) < 0:
                raise ValueError("invalid reserved cpu")
            reservation_id = str(entry.get("id") or key)
            if reservation_id != str(key):
                raise ValueError("reservation id mismatch")
            loaded[reservation_id] = ResourceReservation(
                reservation_id, str(dot_id), str(surface), ram, float(cpu)
            )
        self.reservations = loaded

    def _read_file(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("invalid host resource budget state") from exc
        if not isinstance(data, dict):
            raise ValueError("invalid host resource budget state")
        return data

    def _ram_used(self, surface: str | None = None) -> int:
        return sum(
            item.ram_mb for item in self.reservations.values()
            if surface is None or item.surface == surface
        )

    def _cpu_used(self) -> float:
        return sum(item.cpu_percent for item in self.reservations.values())

    def remaining_ram(self) -> int:
        return max(0, self.total_mb - self.reserve_mb - self._ram_used())

    def overcommitted(self) -> bool:
        if self._ram_used() + self.reserve_mb > self.total_mb:
            return True
        if self._cpu_used() > self.max_cpu_percent + 1e-9:
            return True
        return any(
            self._ram_used(surface) > cap
            for surface, cap in self.surface_ram_mb.items()
        )

    def reserve(self, dot_id: str, surface: str, ram_mb: int, cpu_percent: float) -> ResourceReservation:
        self._check_identity(dot_id, surface)
        if type(ram_mb) is not int or ram_mb < 0:
            raise ValueError("ram_mb must be a non-negative int")
        if isinstance(cpu_percent, bool) or not isinstance(cpu_percent, (int, float)):
            raise ValueError("cpu_percent must be a number")
        cpu_percent = float(cpu_percent)
        if cpu_percent < 0 or cpu_percent > self.max_cpu_percent:
            raise ValueError("cpu_percent exceeds the host ceiling")
        if ram_mb == 0 and cpu_percent == 0:
            raise ValueError("reservation must ask for ram or cpu")
        with self._lock:
            with self._guard():
                if self.state_path is not None and self.state_path.is_file():
                    self._apply_reservations(self._read_file())
                if self._ram_used() + ram_mb + self.reserve_mb > self.total_mb:
                    raise BudgetExceeded("host RAM reserve would be exhausted")
                if self._ram_used(surface) + ram_mb > self.surface_ram_mb[surface]:
                    raise BudgetExceeded(f"{surface} RAM ceiling reached")
                if self._cpu_used() + cpu_percent > self.max_cpu_percent + 1e-9:
                    raise BudgetExceeded("host CPU ceiling reached")
                reservation = ResourceReservation(
                    uuid.uuid4().hex, dot_id, surface, ram_mb, cpu_percent
                )
                self.reservations[reservation.id] = reservation
                try:
                    self._save()
                except Exception:
                    self.reservations.pop(reservation.id, None)
                    raise
                return reservation

    def release(self, reservation_id: str) -> None:
        with self._lock:
            with self._guard():
                if self.state_path is not None and self.state_path.is_file():
                    self._apply_reservations(self._read_file())
                previous = self.reservations.pop(str(reservation_id), None)
                if previous is None:
                    raise ValueError("reservation already released")
                try:
                    self._save()
                except Exception:
                    self.reservations[previous.id] = previous
                    raise

    def snapshot_for_dot(self, dot_id: str) -> dict:
        self._check_identity(dot_id, "canvas")
        with self._lock:
            own = [item for item in self.reservations.values() if item.dot_id == dot_id]
        return {
            "dot_id": dot_id,
            "reservations": [vars(item) for item in own],
            "host_ram_reserved_mb": self._ram_used(),
            "host_ram_remaining_mb": self.remaining_ram(),
            "host_cpu_reserved_percent": self._cpu_used(),
            "authorizes_effects": False,
            "kills_processes": False,
            "changes_priority": False,
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "reservations": {key: vars(value) for key, value in self.reservations.items()},
            "ram_reserved_mb": self._ram_used(),
            "cpu_reserved_percent": self._cpu_used(),
            "authorizes_effects": False,
            "kills_processes": False,
            "changes_priority": False,
        }

    def _save(self) -> None:
        payload = self.to_dict()
        if self.save:
            self.save(payload)
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(
            prefix=".host-budget-", suffix=".tmp", dir=str(self.state_path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.state_path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
