# SENTRA Commander Deployment

## 1. Cloud components

Deploy two HTTPS services:
1. SENTRA Cloud MCP (streamable HTTP /mcp).
2. SENTRA Relay (agent outbound API).

The MCP service and relay may share a private database/network, but agent endpoints and MCP OAuth
endpoints have separate authentication domains.

## 2. OAuth

SENTRA is an OAuth resource server, not an authorization server. Configure an external OAuth/OIDC
provider that supports token introspection (RFC 7662), bearer tokens, the MCP resource/audience and
your required scopes.

Required environment:

    SENTRA_MCP_TRANSPORT=streamable-http
    SENTRA_MCP_HOST=0.0.0.0
    SENTRA_MCP_ALLOW_NON_LOOPBACK=true
    SENTRA_OAUTH_ISSUER_URL=https://idp.example.com/
    SENTRA_OAUTH_RESOURCE_URL=https://mcp.example.com/mcp
    SENTRA_OAUTH_INTROSPECTION_URL=https://idp.example.com/oauth2/introspect
    SENTRA_OAUTH_CLIENT_ID=...
    SENTRA_OAUTH_CLIENT_SECRET=...
    SENTRA_OAUTH_REQUIRED_SCOPES=sentra:mcp

The SDK exposes RFC 9728 protected-resource metadata. Reverse proxies must preserve Authorization
and WWW-Authenticate headers.

Recommended additional scopes:
- sentra:devices:read
- sentra:devices:write
- sentra:execute
- sentra:admin

## 3. Relay TLS

The relay refuses non-loopback binding without a TLS certificate/key. Run behind a hardened reverse
proxy or provide a TLS server certificate directly. Agents must use HTTPS except for loopback tests.

## 4. Pairing

From an authenticated MCP client call sentra_pair_device with a minimal allowlist.
On the device run:

    sentra-agent.exe pair --relay https://relay.example.com --code XXXX-XXXX-XXXX --name "Office PC" --allowed-root C:\work --process-mode workspace

The pairing code is one-use and short-lived. The device stores its returned credential locally.

## 5. Windows install/startup

Use installer/windows/install.ps1 from a release bundle. It copies signed executables under
%LOCALAPPDATA%\SENTRA\Commander, optionally pairs the device, persists the
selected process privilege ceiling (`sandbox|workspace|unrestricted`, default
`workspace`), registers a logon Scheduled Task with restart settings, and
falls back to the Startup folder.

## 6. Updates

Host release-manifest.json and the release ZIP over HTTPS. The updater verifies SHA-256 and,
when signer_thumbprint is present, verifies each executable's Authenticode signer before allowing
installation.

## 7. Registry

server.json follows the official MCP Registry schema. Before public publication, render a manifest
with a namespace you control and a real MCP_REMOTE_URL. The release workflow validates metadata
with mcp-publisher and publishes only when MCP_REMOTE_URL is configured.

## 8. Production requirements outside source code

A production deployment still needs operator-owned external assets:
- DNS names;
- TLS certificates;
- OAuth/OIDC tenant/application and scopes;
- hosted database/backup policy;
- public relay/MCP hosting;
- code-signing certificate if signed Windows binaries are desired;
- verified Registry namespace.

These are deployment credentials/infrastructure, not values that should be committed to source.

The repository includes a Dockerfile, Compose definition and `.dockerignore`. `docker compose config`
is part of the release validation. A real image build additionally requires a running Docker engine;
production images should be built by CI or a controlled build host rather than relying on a developer desktop daemon.


## 9. MCP 2026-07-28 conversation identity

The 2026-07-28 Streamable HTTP wire is single-exchange and does not provide a
cross-request `Mcp-Session-Id`. Clients that use SENTRA stateful resources
must call `sentra_session_open` once per conversation and pass the returned
signed `session_token` to process/search/browser/sandbox/job/research calls.
The token is bound to the authenticated OAuth subject when OAuth is enabled,
has an expiry, survives HTTP reconnects, and must not be logged or committed.
