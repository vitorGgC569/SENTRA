"""Provider-neutral split-phase conversation turn scheduler."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Iterable

from .rate_governor import ProviderRateGovernor


class ConversationTurnScheduler:
    """Dispatch short START turns, then collect them without resending prompts."""

    def __init__(
        self,
        *,
        start: Callable[[Any], Awaitable[dict[str, Any]]],
        collect: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        governor: ProviderRateGovernor | None = None,
        provider_of: Callable[[Any], str] | None = None,
        collect_concurrency: int = 8,
    ) -> None:
        if collect_concurrency < 1:
            raise ValueError("collect_concurrency must be positive")
        self.start = start
        self.collect = collect
        self.governor = governor
        self.provider_of = provider_of or (
            lambda item: str(
                item.get("provider", "chatgpt") if isinstance(item, dict) else "chatgpt"
            )
        )
        self.collect_concurrency = collect_concurrency

    async def _start_one(self, item: Any) -> dict[str, Any]:
        provider = self.provider_of(item)
        if self.governor is not None:
            await self.governor.wait(provider)
            self.governor.record_dispatch(provider)
        try:
            started = await self.start(item)
        except Exception as exc:
            return {
                "_scheduler_error": str(exc)[:2000],
                "_scheduler_phase": "start",
                "_scheduler_item": item,
                "provider": provider,
            }
        result = dict(started)
        result.setdefault("provider", provider)
        result["_scheduler_item"] = item
        return result

    async def _collect_one(
        self, started: dict[str, Any], semaphore: asyncio.Semaphore
    ) -> dict[str, Any]:
        if started.get("_scheduler_error"):
            return started
        async with semaphore:
            try:
                result = dict(await self.collect(started))
            except Exception as exc:
                return {
                    **started,
                    "_scheduler_error": str(exc)[:2000],
                    "_scheduler_phase": "collect",
                }
            result.setdefault("provider", started.get("provider"))
            result.setdefault("conversation_url", started.get("conversation_url"))
            result.setdefault("conversation_id", started.get("conversation_id"))
            result["_scheduler_item"] = started.get("_scheduler_item")
            return result

    async def run_batch(self, items: Iterable[Any]) -> list[dict[str, Any]]:
        # START is deliberately sequential: one physical controller, many remote
        # generations. It is never retried here; replay safety belongs to Durable
        # Operations and the delivery_state recorded by the caller.
        started = []
        for item in list(items):
            started.append(await self._start_one(item))
        semaphore = asyncio.Semaphore(self.collect_concurrency)
        return list(
            await asyncio.gather(
                *(self._collect_one(item, semaphore) for item in started)
            )
        )
