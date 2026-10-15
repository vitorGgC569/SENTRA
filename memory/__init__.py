"""Selo memory package: durable projection store (never an authority).

Memory keeps recallable notes linked to existing Run/WorkItem/Operation ids.
It never creates runs, grants, leases or effects. All writes are owner-scoped
with digest + CAS and bounded retention.
"""
from .store import MemoryStore
from .costs import CostLedger
from .dot_scope import DotScopedStore

__all__ = ["MemoryStore", "CostLedger", "DotScopedStore"]
