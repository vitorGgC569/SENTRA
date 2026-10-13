"""Granular Setup/Doctor state distinctions (Vitra-owned, pure projections).

Setup must distinguish each axis independently instead of collapsing them
into a single ready flag:

- local-ready: local MCP healthy with verified registration-time policy.
- tunnel-online: secure tunnel configured AND healthz/readyz reachable.
- account-app-observed: ChatGPT plugin install observed via authenticated
  tool proof (never inferred from tunnel liveness alone).
- tools-authorized: workspace grants + policy surfaces verified.
- version-current: installed version equals the newest verified release
  manifest (stale/unknown otherwise, never assumed).
- extension: installed / paired / login / revoked as separate states.

All functions are pure over verified health dicts; they never start
processes, inspect secrets, or assert account installation without proof.
"""
from __future__ import annotations

from typing import Any


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def describe_setup_states(status: dict[str, Any], *, current_version: str = "",
                          newest_version: str = "") -> dict[str, Any]:
    """Map verified product health into independent setup axes."""
    status = _dict(status)
    mcp = _dict(status.get("mcp"))
    tunnel = _dict(status.get("tunnel"))
    plugin_proof = _dict(status.get("plugin_proof"))
    credentials = _dict(status.get("credential_storage"))
    edge = _dict(status.get("edge"))
    relay = _dict(status.get("relay"))

    local_ready = bool(mcp.get("ok"))
    tunnel_online = bool(tunnel.get("configured") and tunnel.get("ok") and not tunnel.get("reauth_required"))
    tunnel_reauth = bool(tunnel.get("reauth_required"))
    storage_healthy = credentials.get("ok") is True

    # Account-app observation requires an authenticated tool call proof, not
    # just a live tunnel. Names mirror onboarding.chatgpt_plugin_install_plan.
    mcp_tool_observed = plugin_proof.get("mcp_tool_observed") is True
    authenticated_tool_observed = plugin_proof.get("authenticated_tool_observed") is True
    if authenticated_tool_observed:
        account_app = "observed"
    elif mcp_tool_observed:
        account_app = "tool-observed-unverified"
    else:
        account_app = "unobserved"

    policy = mcp.get("policy") if isinstance(mcp.get("policy"), dict) else None
    allowed_roots = status.get("allowed_roots")
    roots_count = len(allowed_roots) if isinstance(allowed_roots, list) else 0
    if local_ready and policy is not None and roots_count > 0:
        tools_authorized: str = "authorized"
    elif local_ready:
        tools_authorized = "pending"
    else:
        tools_authorized = "unverified"

    if current_version and newest_version:
        if current_version.strip() == newest_version.strip():
            version_current: str = "current"
        else:
            version_current = "stale"
    else:
        version_current = "unknown"

    extension = _describe_extension(edge, relay)
    return {
        "schema": 1,
        "local": {"ready": local_ready},
        "tunnel": {
            "online": tunnel_online,
            "configured": bool(tunnel.get("configured")),
            "reauth_required": tunnel_reauth,
            "credential_storage_healthy": storage_healthy,
        },
        "account_app": {
            "state": account_app,
            "mcp_tool_observed": mcp_tool_observed,
            "authenticated_tool_observed": authenticated_tool_observed,
            "note": "ChatGPT installation is account-owned; never inferred from tunnel liveness.",
        },
        "tools": {"state": tools_authorized, "workspace_count": min(roots_count, 1000)},
        "version": {"state": version_current, "installed": current_version, "newest": newest_version},
        "extension": extension,
    }


def _describe_extension(edge: dict[str, Any], relay: dict[str, Any]) -> dict[str, Any]:
    """Extension lifecycle as separate states: installed/paired/login/revoked."""
    manifest_present = bool(edge.get("manifest_present"))
    if not manifest_present:
        # Fall back to install-dir presence hint when the caller provides it.
        manifest_present = edge.get("installed") is True
    paired = bool(relay.get("ok") or edge.get("ok"))
    login_observed = bool(edge.get("login_observed") or edge.get("authenticated"))
    revoked = bool(edge.get("revoked") or edge.get("pairing_revoked"))
    workers = edge.get("workers") if isinstance(edge.get("workers"), list) else []
    if revoked:
        state = "revoked"
    elif login_observed and paired:
        state = "login"
    elif paired:
        state = "paired"
    elif manifest_present:
        state = "installed"
    else:
        state = "absent"
    return {
        "state": state,
        "installed": manifest_present,
        "paired": paired,
        "login_observed": login_observed,
        "revoked": revoked,
        "detail": str(edge.get("detail") or relay.get("detail") or ""),
        "workers": min(len(workers), 64),
    }
