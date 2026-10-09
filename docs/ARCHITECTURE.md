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
permissions. Filesystem scope is independent from the execution profile:
`workspace` exposes only individually approved grants, `user` adds the current
user's home tree, and `computer` adds accessible local/mapped drives.
More-specific workspace grants take precedence over broader scope grants.

The MCP's configured root is an isolated default workspace rather than the
private SENTRA state directory. The optional Remote Agent uses that same
registry as its filesystem authority: Desktop policy sync writes profile,
scope, surfaces and tool allowlist into the Agent configuration, while actual
path permissions remain in `.sentra/workspaces.json`. Policy is synchronized
again before each Agent start so a previously paired device cannot silently
retain an older, broader Desktop policy. Safe remains read-only regardless of
filesystem scope.

## Durable multi-agent control plane

The product/governance layer above Durable Run/Operation is specified in
[`GOVERNANCE_CONTROL_PLANE.md`](GOVERNANCE_CONTROL_PLANE.md), including
WorkItem ownership, deterministic validation, retry/recovery policy, budgets,
secrets, routines, plugins, ordered ingress and portable blueprints.

SENTRA separates authoritative state from model conversation state. Durable
`Run`, `Goal`, `Agent`, `Chat`, `Operation`, lease/fencing and artifact
records remain in the Control Plane even when a physical ChatGPT or Gemini
conversation must be replaced. A `Chat` belongs to exactly one logical Agent;
cross-Agent rebinding fails closed.

The Context Bus transports typed knowledge, targeted agent messages, questions,
objections, results and evidence. It is non-authoritative: model consensus never
marks a Goal successful and never promotes a candidate.

`orchestrator/swarm_cycle.py` provides the persistent multi-provider cycle used
by `sentra swarm ...`. The balanced profile uses ChatGPT and Gemini specialists
over one Run/Goal, with the bounded phase sequence
`discover -> peer_questions -> cross_review -> implement -> test -> challenge -> synthesize`.
Peer questions are targeted rather than unrestricted all-to-all fanout.

When `--execute` is enabled, the swarm's compiled context is handed to the
existing OMA implementation path. OMA and deterministic validation retain
mutation/Quality-Gate authority. Browser sends are checkpointed: a known
`NOT_SENT` failure may be retried, while `IN_FLIGHT`/`UNCERTAIN` delivery is
never replayed automatically.

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
