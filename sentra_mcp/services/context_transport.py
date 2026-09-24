"""Transient delivery adapters for SENTRA Context Bus.

The transport is deliberately non-authoritative. Durable context is committed to
SQLite/Postgres-class storage first; transport failures never roll back durable
knowledge. Consumers recover from the durable cursor after reconnect.
"""
from __future__ import annotations

import json
from typing import Any, Protocol


class ContextTransport(Protocol):
    def publish(self, event: dict[str, Any]) -> None: ...
    def close(self) -> None: ...


class NullContextTransport:
    def publish(self, event: dict[str, Any]) -> None:
        return None

    def close(self) -> None:
        return None


class InMemoryContextTransport:
    """Deterministic transport used by tests/local embedding."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(dict(event))

    def close(self) -> None:
        return None


class RedisStreamsContextTransport:
    """Best-effort Redis Streams fan-out using an injected compatible client.

    No redis package is imported here. The client only needs an xadd method.
    Redis is delivery acceleration only, never the durable source of truth.
    """

    def __init__(
        self,
        client: Any,
        *,
        prefix: str = "sentra",
        maxlen: int = 100_000,
    ) -> None:
        self.client = client
        self.prefix = str(prefix or "sentra").strip(":")
        self.maxlen = max(1000, int(maxlen))

    def publish(self, event: dict[str, Any]) -> None:
        run_id = str(event.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("context transport event requires run_id")
        key = f"{self.prefix}:run:{run_id}:context"
        payload = json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.client.xadd(
            key,
            {"event": payload},
            maxlen=self.maxlen,
            approximate=True,
        )

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()
