# Security Policy

## Supported releases

Security fixes are provided for the latest stable SENTRA Desktop release and,
when practical, the immediately previous stable release.

## Reporting a vulnerability

Do not publish credentials, exploit details, private tunnel identifiers, device
tokens, or sensitive logs in a public issue. Prefer GitHub Private Vulnerability
Reporting / Security Advisories for this repository. If that channel is not
available, contact the repository maintainer privately through GitHub before
sharing reproduction material.

Include the affected version, component, impact, minimal reproduction steps and
whether exploitation requires local, workspace, tunnel or remote-device access.
## Security boundaries

SENTRA treats local operator approval, workspace permissions, tool allowlists,
the process sandbox, the loopback Edge relay, Secure MCP Tunnel credentials and
Remote Agent device credentials as separate boundaries.

Runtime API keys and device credentials must never be committed. Windows builds
store supported local secrets with DPAPI. The `.sentra/` runtime directory is
excluded from Git.

Stable Windows releases must be Authenticode signed. The release workflow fails
closed for a stable tag when its signing certificate is unavailable.

## Update verification

Automatic updates require HTTPS, SHA-256 verification and a matching
Authenticode signer thumbprint. Update application is transactional: the
previous install is retained as a rollback point and restored if installation
fails.
