"""Optional Code Mode tools. Deny-only does not close the surface.

An empty allow list closes use. A deny-only list does not: it raises
instead of returning an empty map that would look like a closed surface.
A tool cannot carry a Grant for itself.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from sentra_marketplace.packages import claims_self_grant
from sentra_marketplace.policy import AllowPolicy, DenyOnlyPolicy

_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")


class OptionalSurfaceRefused(PermissionError):
    """The optional tool surface was refused. The capability stays unclosed."""

    def __init__(self, reason: str, receipt: dict[str, Any]):
        super().__init__(reason)
        self.reason = reason
        self.receipt = receipt


def resolve_optional_tools(policy, declared: Mapping[str, Any]) -> dict[str, Any]:
    """Return the opted-in handlers' names, or refuse a deny-only policy."""
    if isinstance(policy, DenyOnlyPolicy):
        receipt = {
            "mode": "deny-only",
            "reason": "DENY_ONLY_DOES_NOT_CLOSE",
            "capability_closed": False,
            "enabled": [],
            "closed": [],
            "unavailable": [],
            "grants_created": False,
            "homologated": False,
            "denied_listed": sorted(policy.denied),
        }
        raise OptionalSurfaceRefused(str(receipt["reason"]), receipt)
    if not isinstance(policy, AllowPolicy):
        raise ValueError("allow or deny-only exposure required")
    if not isinstance(declared, Mapping):
        raise ValueError("declared tools must be a map")
    for name, handler in declared.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError("tool name outside allowlist charset: " + str(name)[:80])
        if _claims(handler):
            receipt = {
                "mode": "allow",
                "reason": "PLUGIN_SELF_GRANT",
                "capability_closed": False,
                "enabled": [],
                "tool": name,
                "grants_created": False,
                "homologated": False,
            }
            raise OptionalSurfaceRefused(str(receipt["reason"]), receipt)
    enabled = []
    closed = []
    for name, handler in declared.items():
        if name in policy.allowed:
            if not callable(handler):
                raise ValueError("host tool handler required for: " + name)
            enabled.append(name)
        else:
            closed.append(name)
    unavailable = sorted(name for name in policy.allowed if name not in declared)
    opened = bool(enabled)
    return {
        "mode": "allow",
        "reason": "opted_in" if opened else "NOT_OPTED_IN",
        "capability_closed": not opened,
        "enabled": enabled,
        "closed": closed,
        "unavailable": unavailable,
        "grants_created": False,
        "homologated": False,
    }


def _claims(handler) -> bool:
    if isinstance(handler, Mapping) and claims_self_grant(dict(handler)):
        return True
    return bool(getattr(handler, "self_grant", False))
