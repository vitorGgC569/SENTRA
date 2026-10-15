"""Local-use policy for SENTRA. It does not charge and it does not lock local use.

Commercial documents describe this policy. They do not create a paywall, a
second authority, or a Grant. Hosted extras may be absent. That absence does
not turn off the CLI, the desktop, the local Canvas, the REPL, or loopback MCP.
"""
from __future__ import annotations

from typing import Any


LOCAL_SURFACES = ("cli", "desktop", "mcp_loopback", "canvas_local", "repl")


class LocalUsePolicy:
    """Pinned open-local policy. Paywall, charge, and block flags cannot be set."""

    def __init__(
        self,
        *,
        charge_user: bool = False,
        paywall: bool = False,
        block_local_use: bool = False,
        license_spdx: str = "MIT",
    ) -> None:
        if charge_user is not False or paywall is not False or block_local_use is not False:
            raise ValueError("local use stays open; no paywall and no charge")
        if license_spdx != "MIT":
            raise ValueError("SENTRA license pin is MIT")
        self.charge_user = False
        self.paywall = False
        self.block_local_use = False
        self.license_spdx = "MIT"
        self.commercial_homologated = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "license_spdx": self.license_spdx,
            "charge_user": self.charge_user,
            "paywall": self.paywall,
            "block_local_use": self.block_local_use,
            "commercial_homologated": self.commercial_homologated,
            "local_surfaces": list(LOCAL_SURFACES),
            "authorizes_effect": False,
        }


def evaluate_access(
    policy: LocalUsePolicy,
    *,
    surface: str,
    authenticated_account: bool = False,
) -> dict[str, Any]:
    """Decide presentation access. This does not issue a Grant or admit an effect."""
    if not isinstance(policy, LocalUsePolicy):
        raise TypeError("LocalUsePolicy required")
    if type(authenticated_account) is not bool:
        raise ValueError("authenticated_account must be a boolean")
    if surface in LOCAL_SURFACES:
        return {
            "allowed": True,
            "surface": surface,
            "charge": False,
            "paywall": False,
            "account_required": False,
            "blocks_local": False,
            "authorizes_effect": False,
            "reason": "local use remains open",
        }
    if surface == "hosted_optional":
        return {
            "allowed": False,
            "surface": surface,
            "charge": False,
            "paywall": False,
            "account_required": False,
            "blocks_local": False,
            "authorizes_effect": False,
            "reason": "optional hosted surface is not part of local use",
        }
    raise ValueError("unknown surface")


def support_bundle() -> dict[str, Any]:
    """Redacted support facts. No tokens, prompts, or credential paths."""
    from sentra_version import PRODUCT_VERSION, SERVER_VERSION

    return {
        "product": "SENTRA",
        "product_version": PRODUCT_VERSION,
        "server_version": SERVER_VERSION,
        "license": "MIT",
        "charge_user": False,
        "paywall": False,
        "local_use_blocked": False,
        "commercial_homologation": "not_homologated",
        "collect": [
            "product_version",
            "command",
            "test_result",
            "uncertain_state_without_resend",
        ],
        "never_collect": [
            "tokens",
            "auth.json",
            "api_keys",
            "full_prompts",
            "credentials",
            "cookies",
        ],
        "authorizes_effect": False,
    }
