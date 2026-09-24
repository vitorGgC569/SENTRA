# SENTRA Desktop architecture

## Product boundary

SENTRA Desktop is a Windows-first local control plane around the existing SENTRA
MCP, OMA orchestration, principal-Edge bridge and optional Remote Agent.

The installed product keeps executable code and private runtime state separate:

```text
%LOCALAPPDATA%\SENTRA\Commander   signed executables + Edge extension
%USERPROFILE%\.sentra             credentials, policy, jobs, audit, snapshots
<user workspaces>                   user-approved project data only
```

A workspace never needs to contain SENTRA credentials or relay state.
## Processes

- `sentra-desktop.exe` — GUI, tray, onboarding and process supervisor.
- `sentra-mcp.exe` — loopback Streamable HTTP MCP server.
- `sentra-browser-relay.exe` — loopback authenticated Edge extension relay.
- `tunnel-client.exe` — official OpenAI outbound Secure MCP Tunnel client.
- `sentra-oma.exe` — queued autonomous engineering execution.
- `sentra-agent.exe` — optional outbound Remote Agent.
- `sentra-update-helper.exe` — transactional update/rollback helper.
- `sentra-diagnostics.exe` and `sentra-admin.exe` — local support/approval utilities.

The Desktop supervises child processes and writes only PID/status/log metadata
under the private state directory.
## Security profiles

**Safe** combines three independent controls: read-only workspace grants,
registration-time tool allowlisting and Docker process sandboxing.

**Developer** enables normal engineering mutation inside explicitly permitted
workspaces with the default MCP surfaces.

**Full** exposes all tool surfaces. It does not disable path validation, tunnel
authentication, local privileged-change approval or remote-device ACLs.

Custom per-tool allowlists are enforced while tools are registered. A tool that
is outside the allowlist is not discoverable by MCP clients.

## Workspace model

Installed workspaces are persisted as locally approved grants in
`.sentra/workspaces.json` with explicit `read`, `write` and `execute`
permissions. The MCP's configured root is an isolated default workspace rather
than the private SENTRA state directory.
## Browser model

The Edge bridge listens only on loopback and uses a high-entropy local relay
token. The installed relay token lives in `.sentra/browser/relay-token`.

ChatGPT automation uses the principal Microsoft Edge profile and adopts an
existing ChatGPT tab. The normal extension path does not call
`chrome.tabs.create`, `chrome.tabs.remove` or `chrome.windows.create`.

## Update model

Update manifests are fetched only over HTTPS (loopback HTTP is permitted for
tests), packages are SHA-256 verified and stable automatic updates require a
matching Authenticode signer thumbprint.

The update helper runs outside the install directory. It preserves the previous
installation, replaces the current version, verifies the setup result and
restores the previous tree if installation fails. The Desktop also exposes an
explicit previous-version rollback action.
## Release artifacts

Every stable Windows release is designed to publish:

- signed `SENTRA-Setup-<version>.exe`;
- signed per-user `SENTRA-Desktop-<version>-x64.msi`;
- signed update ZIP containing Setup + update helper;
- `SHA256SUMS.txt`;
- CycloneDX JSON SBOM;
- signed release manifest containing the trusted signer thumbprint.

The release workflow fails closed on a stable tag when Authenticode credentials
are not configured.
