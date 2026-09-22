# SENTRA Desktop — 5-minute quickstart

## 1. Install

Download the signed `SENTRA-Setup-<version>.exe` from the GitHub Release and run it.

The installer is per-user by default. It installs under:

```text
%LOCALAPPDATA%\SENTRA\Commander
```

Private runtime state is stored separately under:

```text
%USERPROFILE%\.sentra
```

No API key or device credential is stored in the installation directory or Git repository.
## 2. Choose a workspace and profile

In Setup, select the project directory SENTRA may access.

Choose a profile:

- **Safe** — read-only workspace permissions, explicit tool allowlist and Docker sandbox.
- **Developer** — read/write/execute workspace permissions with core developer/browser tools.
- **Full** — all SENTRA MCP surfaces; intended for a trusted local operator.

You can change individual workspace permissions later in **Workspaces & Policy**.

## 3. Connect OpenAI Secure MCP Tunnel

In OpenAI Platform, create/select a tunnel and a Restricted Runtime API key with
**Tunnels: Read + Use**. Paste the `tunnel_...` ID and Runtime API key into Setup
or the Desktop **Onboarding** tab.

The Runtime API key is immediately protected with Windows DPAPI.
## 4. Enable the Edge bridge

Open **Onboarding → Open edge://extensions**.

1. Enable **Developer mode**.
2. Choose **Load unpacked**.
3. Select the installed `edge_extension` folder shown by SENTRA Desktop.
4. Open the extension Options page.
5. Paste the relay token shown in SENTRA Desktop.

The bridge adopts an existing eligible ChatGPT tab. It does not create or close
ChatGPT tabs in the normal principal-Edge path.

## 5. Confirm Ready

The Status page should show:

```text
MCP      ✓ Ready
Tunnel   ✓ Ready
Edge     ✓ Ready
Sandbox  ✓ Ready   (when Docker Desktop is available)
Git      ✓ Ready
Remote   ✓ Ready   (only after optional Remote Agent pairing)
```
Use **Doctor** whenever a component is not ready. The error panel shows recent
service errors without exposing Runtime API keys or device tokens.

## Next steps

- Add/remove workspaces and edit read/write/execute permissions.
- Queue an OMA task in **Jobs & Queue**.
- Inspect the current Git diff before changes.
- Create a snapshot before risky work; use rollback when required.
- Pair the optional Remote Agent only when another SENTRA relay/device workflow is needed.

For the full tunnel setup and OpenAI Platform permission model, see
`docs/SECURE_MCP_TUNNEL.md`.
