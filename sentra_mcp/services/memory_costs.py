"""Selo: Memory/Costs service facade for central composition."""
from __future__ import annotations


def build_client(**trusted_host_configuration):
    from .selo_composition import build_client as compose
    return compose(**trusted_host_configuration)

from pathlib import Path
from typing import Any

from memory.store import MemoryStore
from memory.costs import CostLedger


class MemoryCostsService:
    def __init__(self, state_root: Path | str) -> None:
        self.root = Path(state_root).resolve()
        self.memory = MemoryStore(self.root)
        self.costs = CostLedger(self.root)

    def memory_put(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.memory.put(owner, **kwargs)

    def memory_get(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.memory.get(owner, **kwargs)

    def memory_delete(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.memory.delete(owner, **kwargs)

    def memory_list(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.memory.list(owner, **kwargs)

    def cost_record(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.costs.record(owner, **kwargs)

    def cost_budget(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.costs.set_budget(owner, **kwargs)

    def cost_totals(self, owner: str, **kwargs: Any) -> dict[str, Any]:
        return self.costs.totals(owner, **kwargs)
