"""Concurrent admission budgets with persistent reservations and honest accounting."""
from __future__ import annotations

import uuid
from dataclasses import dataclass


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
        self.task_limits, self.task_used, self.reservations = {}, {}, {}
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
