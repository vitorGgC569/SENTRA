"""Opt-in policy for optional connectors, skills and plugins.

A deny-only list does not close a capability. Closing use requires an
explicit allow entry. Wildcards are rejected so a subject cannot widen
its own surface.
"""
from __future__ import annotations

from typing import Iterable


class AllowPolicy:
    """Exact opt-in. Absence from the set closes that use."""

    mode = "allow"

    def __init__(self, allowed: Iterable[str]):
        items = tuple(allowed)
        if any(type(item) is not str or not item or "*" in item or "?" in item
               or any(ch.isspace() for ch in item) or len(item) > 256
               for item in items):
            raise ValueError("optional allow list is exact and rejects wildcards")
        self.allowed = frozenset(items)

    def decide(self, capability: str) -> tuple[bool, str, bool]:
        if capability in self.allowed:
            return True, "opted_in", False
        return False, "NOT_OPTED_IN", True


class DenyOnlyPolicy:
    """A denial list is not a closure of the capability.

    Listed or unlisted, the outcome is the same: the policy does not open
    the capability and does not count as having closed it.
    """

    mode = "deny-only"

    def __init__(self, denied: Iterable[str] = ()):
        self.denied = frozenset(denied)

    def decide(self, capability: str) -> tuple[bool, str, bool]:
        del capability
        return False, "DENY_ONLY_DOES_NOT_CLOSE", False
