"""Canonical, hash-linked local audit evidence for SENTRA executor operations.

This is *tamper-evident relative to a trusted head*. It is NOT a durable,
complete or independently witnessed log by itself. Production must persist
events before side effects and anchor signed heads externally (e.g. Tessera).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


def canonical(event: Mapping[str, Any]) -> bytes:
    if not isinstance(event, Mapping):
        raise TypeError("audit event must be an object")
    try:
        encoded = json.dumps(dict(event), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("audit event is not canonicalizable") from exc
    return encoded.encode("utf-8")


def _hash(prev: str, entry: bytes) -> str:
    return hashlib.sha256(b"SENTRA/AUDIT/V1\x00" + bytes.fromhex(prev)
                          + len(entry).to_bytes(8, "big") + entry).hexdigest()


GENESIS = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    event: Mapping[str, Any]
    previous: str
    digest: str


class AuditChain:
    """In-memory prototype only; caller must persist/anchor an external head."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    @property
    def head(self) -> str:
        return self._entries[-1].digest if self._entries else GENESIS

    @property
    def entries(self) -> tuple[AuditEntry, ...]:
        return tuple(self._entries)

    def append(self, event: Mapping[str, Any]) -> AuditEntry:
        # Freeze a canonical JSON projection, not the caller's mutable dict.
        stable = json.loads(canonical(event))
        previous = self.head
        entry = AuditEntry(seq=len(self._entries) + 1, event=stable,
                           previous=previous, digest=_hash(previous, canonical(stable)))
        self._entries.append(entry)
        return entry

    @staticmethod
    def verify(entries: Sequence[AuditEntry], *, expected_head: str | None = None) -> bool:
        current = GENESIS
        for index, entry in enumerate(entries, 1):
            if entry.seq != index or entry.previous != current:
                return False
            try:
                hashed = _hash(current, canonical(entry.event))
            except (TypeError, ValueError, OverflowError):
                return False
            if hashed != entry.digest:
                return False
            current = hashed
        return expected_head is None or current == expected_head
