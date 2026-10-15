"""Optional connectors, skills, plugins and the local marketplace.

Nothing in this package mints a Grant. Deny-only does not close a
capability. External content stays data. A missing package is explicit
unavailability, not a download.
"""
from __future__ import annotations

from .catalog import LocalMarketplace
from .connectors import KNOWN_CONNECTORS, connector_status, invoke_connector
from .content_fence import fence_external_content
from .gate import EffectUncertain, HostBinding, OptionalCapabilityGate, PackagePin, Subject
from .policy import AllowPolicy, DenyOnlyPolicy
from .skills_data import disclose_skill, read_skill_text

__all__ = [
    "AllowPolicy",
    "DenyOnlyPolicy",
    "EffectUncertain",
    "HostBinding",
    "KNOWN_CONNECTORS",
    "LocalMarketplace",
    "OptionalCapabilityGate",
    "PackagePin",
    "Subject",
    "connector_status",
    "disclose_skill",
    "fence_external_content",
    "invoke_connector",
    "read_skill_text",
]
