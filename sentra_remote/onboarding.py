"""Shared first-run onboarding contract for installed SENTRA surfaces.

The local product is useful without a ChatGPT Secure MCP Tunnel. A tunnel is a
separately enabled integration; no plugin setup is allowed to block local use.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

OPENAI_TUNNELS_URL = "https://platform.openai.com/settings/organization/tunnels"
OPENAI_API_KEYS_URL = "https://platform.openai.com/settings/organization/api-keys"
CHATGPT_PLUGINS_HOME_URL = "https://chatgpt.com/"

TUTORIAL_MEDIA = {
    "tunnel": "mcp-create-tunnel.mp4",
    "connector": "mcp-connect-connector.mp4",
}


def tutorial_video_path(install_dir: "Path", step: str) -> "Path":
    """Find shipped tutorial videos, restricted to known bundled file names."""
    from pathlib import Path

    if step not in TUTORIAL_MEDIA:
        raise ValueError("unknown tutorial step")
    filename = TUTORIAL_MEDIA[step]
    installed = Path(install_dir) / "docs" / "onboarding_media" / filename
    source = Path(__file__).resolve().parents[1] / "docs" / "onboarding_media" / filename
    selected = installed if installed.is_file() else source
    if not selected.is_file():
        raise FileNotFoundError("SENTRA setup tutorial video is missing")
    return selected.resolve()



def chatgpt_plugin_install_plan(
    status: dict[str, Any], *, tunnel_id: str = ""
) -> dict[str, Any]:
    """A safe local preparation verdict; ChatGPT installation is account-owned.

    Does not request, expose, or return API keys or credentials.
    """
    mcp = _dict(status.get("mcp"))
    tunnel = _dict(status.get("tunnel"))
    configured = bool(tunnel.get("configured") or tunnel_id)
    online = bool(mcp.get("ok")) and bool(tunnel.get("ok"))
    if not configured:
        reason = "Set up a Secure MCP Tunnel and Runtime API key with All permissions first."
    elif not mcp.get("ok"):
        reason = "Local SENTRA MCP is not healthy; start or repair it before installing."
    elif not tunnel.get("ok"):
        reason = "Tunnel is configured but not online; reconnect and run Verify."
    else:
        reason = "SENTRA tunnel is online; finish plugin installation in ChatGPT."

    return {
        "ready_to_install": configured and online,
        "requires_account_authorization": True,
        "tunnel_id": tunnel_id if tunnel_id.startswith("tunnel_") else "",
        "chatgpt_url": CHATGPT_PLUGINS_HOME_URL,
        "reason": reason,
        "steps": (
            "Open ChatGPT web, then Plugins > + > Add custom MCP server.",
            "Enter name SENTRA and choose Tunnel; select your SENTRA tunnel.",
            "Choose the authentication required by the SENTRA server.",
            "Review safety prompts, create the plugin, then install it in ChatGPT.",
            "Return to SENTRA and verify an authorized tool call.",
        ),
    }


@dataclass(frozen=True, slots=True)
class OnboardingAction:
    id: str
    title: str
    detail: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class SurfaceState:
    id: str
    title: str
    ready: bool
    detail: str
    optional: bool = False


@dataclass(frozen=True, slots=True)
class OnboardingSnapshot:
    stage: str
    ready: bool
    title: str
    detail: str
    actions: tuple[OnboardingAction, ...]
    surfaces: tuple[SurfaceState, ...]
    optional_tools: tuple[SurfaceState, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _openai_actions(*, reauth: bool = False) -> tuple[OnboardingAction, ...]:
    return (
        OnboardingAction(
            "open_tunnels", "Open OpenAI Tunnels",
            "Create or select the Secure MCP Tunnel for this computer.",
            OPENAI_TUNNELS_URL,
        ),
        OnboardingAction(
            "open_api_keys", "Create Runtime API key with All permissions",
            "Select All permissions. Never paste this key in chat.",
            OPENAI_API_KEYS_URL,
        ),
        OnboardingAction(
            "connect_verify", "Reconnect & Verify" if reauth else "Connect & Verify",
            "Store the key using OS protection and check MCP/tunnel readiness.",
        ),
    )


def build_onboarding_snapshot(
    status: dict[str, Any], *, intent: str = "local"
) -> OnboardingSnapshot:
    """Map real health into an actionable first-run experience.

    intent='local' makes only the local MCP mandatory.
    intent='chatgpt' shows the guided OpenAI setup without changing local health.
    """
    if intent not in {"local", "chatgpt"}:
        raise ValueError("onboarding intent must be local or chatgpt")
    mcp = _dict(status.get("mcp"))
    tunnel = _dict(status.get("tunnel"))
    relay = _dict(status.get("relay"))
    edge = _dict(status.get("edge"))
    web = _dict(status.get("web_models"))
    credentials = _dict(status.get("credential_storage"))
    git = _dict(status.get("git"))
    sandbox = _dict(status.get("sandbox"))

    mcp_ready = bool(mcp.get("ok"))
    reauth = bool(tunnel.get("reauth_required"))
    credential_configured = bool(credentials.get("configured"))
    storage_healthy = credentials.get("ok") is True
    tunnel_configured = bool(tunnel.get("configured") and credential_configured)
    chatgpt_ready = bool(
        mcp_ready and tunnel_configured and storage_healthy
        and tunnel.get("ok") and not reauth
    )
    # A running relay alone does not prove the browser extension is connected.
    edge_ready = bool(edge.get("ok"))
    web_ready = bool(web.get("ready", web.get("ok")))

    surfaces = (
        SurfaceState(
            "terminal", "SENTRA Terminal", mcp_ready,
            "Local MCP and command-line tools are available."
            if mcp_ready else "Start the local MCP to use the complete runtime.",
        ),
        SurfaceState(
            "chatgpt", "ChatGPT / Secure MCP Tunnel", chatgpt_ready,
            "Secure MCP Tunnel is online. Complete or verify plugin installation and workspace access in ChatGPT." if chatgpt_ready
            else (
                "Runtime API key invalidated; create a new key with All permissions and reconnect."
                if reauth else (
                    "Credential storage needs repair; reconnect OpenAI with DPAPI protection."
                    if tunnel_configured and not storage_healthy else (
                        "Tunnel is configured but offline; use Connect & Verify or Doctor."
                        if tunnel_configured else
                        "Optional: connect a Tunnel ID and Runtime API key with All permissions."
                    )
                )
            ),
            optional=True,
        ),
        SurfaceState(
            "codex", "Codex / Web Models", web_ready,
            "Web Models gateway is available." if web_ready
            else "Optional: sign in to Web Models, then connect Codex.",
            optional=True,
        ),
        SurfaceState(
            "browser", "Edge / Browser plugin", edge_ready,
            "Extension and local relay are connected." if edge_ready
            else ("Relay running; browser extension not yet paired."
                  if relay.get("ok") else "Optional Edge extension is not connected."),
            optional=True,
        ),
    )
    optional_tools = (
        SurfaceState(
            "git", "Git", bool(git.get("ok")),
            str(git.get("detail") or "Detected or installed when requested."),
            optional=True,
        ),
        SurfaceState(
            "docker", "Docker sandbox", bool(sandbox.get("ok")),
            str(sandbox.get("detail") or "Required only for isolated tasks."),
            optional=True,
        ),
    )

    if intent == "chatgpt" and not chatgpt_ready:
        if reauth:
            detail = "The Runtime API key was invalidated. Create a new key with All permissions and reconnect."
        elif tunnel_configured and not storage_healthy:
            detail = "Configured credential storage is not healthy; reconnect OpenAI securely."
        elif not tunnel_configured:
            detail = ("Authorize automatic setup or create/select an OpenAI tunnel and a "
                      "Runtime API key with All permissions in OpenAI Platform.")
        else:
            detail = "Credentials are saved, but the secure tunnel is offline. Start and verify it."
        return OnboardingSnapshot(
            "CONNECT_OPENAI", False, "Connect ChatGPT", detail,
            _openai_actions(reauth=reauth),
            surfaces, optional_tools,
        )

    if not mcp_ready:
        return OnboardingSnapshot(
            "START_SENTRA", False, "Start SENTRA",
            "SENTRA is installed. Start local services and verify their health; OpenAI is optional.",
            (OnboardingAction("start_verify", "Start & Verify", "Start local MCP and relay; run Doctor."),),
            surfaces, optional_tools,
        )

    actions: list[OnboardingAction] = [
        OnboardingAction(
            "open_quickstart", "Start a task",
            "Open SENTRA Terminal or choose a project to work on.",
        )
    ]
    if not chatgpt_ready:
        actions.extend(_openai_actions(reauth=reauth))
    if not web_ready:
        actions.append(OnboardingAction(
            "connect_codex", "Enable Web Models",
            "Complete model sign-in and connect Codex when needed.",
        ))
    if not edge_ready:
        actions.append(OnboardingAction(
            "connect_edge", "Enable browser automation",
            "Install/enable the Edge extension only for browser tasks.",
        ))
    detail = (
        "SENTRA Terminal is ready. ChatGPT tunnel, Codex, and Edge can be enabled separately."
        if not chatgpt_ready
        else "SENTRA Terminal and ChatGPT Secure MCP Tunnel are ready. Codex and Edge are optional."
    )
    if reauth:
        detail += " ChatGPT requires a new Runtime API key with All permissions; local use is unaffected."
    elif tunnel_configured and not chatgpt_ready:
        detail += " ChatGPT connection needs attention; local use is unaffected."
    return OnboardingSnapshot(
        "READY", True, "SENTRA is ready", detail,
        tuple(actions), surfaces, optional_tools,
    )
