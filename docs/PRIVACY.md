# SENTRA Commander Privacy

## Data model

SENTRA Commander is designed so machine data remains on the paired device unless a
specific MCP tool result is requested. The relay stores device metadata, tool ACLs,
job arguments/results and execution state needed to deliver remote calls.

The relay must not receive browser cookies, OAuth client secrets, local process
environment secrets or device credentials in plaintext storage.

## Credentials

OAuth access tokens authenticate MCP users to the cloud resource server.
Device tokens authenticate agents to the relay. They are distinct credentials.
The relay stores only a SHA-256 digest of each device token. Rotation replaces the
digest immediately; revocation invalidates the device.

Local agent config contains a protected form of the device token and must still be treated as sensitive.
On Windows, SENTRA protects the token with current-user DPAPI. On non-Windows systems,
new credentials are stored in the operating-system credential backend through `keyring`;
a legacy `portable:` encoding is accepted only for migration and is never written by current code.
Installer location is the current user's profile and the config should not be shared.

## Audit

Local MCP audit logs redact known authorization/API key/token/password fields.
Audit logs may contain file paths, tool names, timestamps and non-secret metadata.
Operators should set retention policies appropriate to their environment.

## Browser

Browser operations may expose page text or screenshots when explicitly requested.
Persistent login state is managed by the existing browser layer and is not uploaded
to the relay as a credential artifact. Remote browser use should be granted only to
devices/tool ACLs that require it.

## Telemetry

sentra_usage_stats and audit query operate on local redacted audit data. SENTRA does
not require third-party analytics for Commander operation.
