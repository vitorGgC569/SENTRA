# SENTRA Commander Threat Model

## Assets

Protected assets include local files, terminal/process authority, Git workspaces,
browser sessions, OMA evidence, OAuth identities, device credentials and remote job results.

## Trust boundaries

1. MCP client ↔ Cloud MCP: OAuth 2.1 bearer/resource-server boundary.
2. Cloud MCP ↔ relay database: server-side authorization and user/device ownership.
3. Relay ↔ device agent: outbound HTTPS plus device credential.
4. Agent ↔ local MCP: local policy boundary and allowed roots.
5. Browser ↔ external sites: SSRF/private-network boundary.
6. Candidate ↔ source workspace: filesystem sandbox and deterministic verification boundary.

## Primary threats and mitigations

Credential theft: device secrets are random, expire, rotate, revoke and are stored by hash.
OAuth tokens are validated by external introspection and audience/resource configuration.

Cross-user device access: every device/job lookup is bound to user_id; foreign access is denied.

Tool escalation: device allowlists are checked before jobs are queued. Local MCP applies a
second policy layer.

Replay after disconnect: jobs become UNCERTAIN once execution may have started and are never
blindly resent. Only provably pre-execution leases may be requeued, once.

Result corruption: large results use per-chunk SHA-256 and a final payload digest.

SSRF: browser navigation resolves hostnames and blocks loopback/private/link-local/reserved ranges;
request routing applies the same guard to subresources.

Filesystem escape: existing SENTRA traversal, symlink/junction and private-path guards remain authoritative.

PID abuse: only managed owner-scoped processes can be killed through process tools.

Privilege configuration: MCP may change only bounded runtime limits. Roots, command policy and
remote exposure changes create a pending request that requires local CLI approval and restart.

Public transport downgrade: non-loopback relay requires TLS; non-loopback MCP requires OAuth
issuer/resource/introspection configuration and HTTPS resource/issuer URLs.

Supply chain: release bundles have SHA-256 manifests and optionally Authenticode signatures.
Updater rejects digest mismatch and can pin the signer thumbprint.

## Residual risks

A compromised local user account can read that user's agent token and operate within granted roots.
OAuth/IdP security depends on the selected external provider. Browser click/type can perform actions
with the logged-in browser user's authority; grant browser tools narrowly. A filesystem sandbox is
not an OS sandbox; untrusted command execution should use SENTRA's Docker execution backend.
