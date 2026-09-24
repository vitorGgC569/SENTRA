# Changelog

All notable user-facing changes to SENTRA are recorded here.

## 1.0.0 — 2026-09-22

### Added

- SENTRA Desktop Windows control center and system tray.
- Operational status for MCP, Secure Tunnel, Edge Bridge, sandbox, Git and Remote Agent.
- Start, stop, restart and Doctor controls without PowerShell.
- Safe, Developer and Full security profiles with registration-time tool policy.
- Visual workspace allowlist with read, write and execute permissions.
- Persistent OMA task queue with real execution and logs.
- Git diff viewer, audit viewer, workspace snapshots and rollback.
- OpenAI Secure MCP Tunnel onboarding with DPAPI-protected Runtime API key.
- Optional Remote Agent pairing from the Desktop UI.
- Self-contained Windows Setup executable.
- Per-user Windows MSI package.
- Pinned and SHA-256-verified OpenAI tunnel-client acquisition.
- Transactional signed automatic updates with previous-version rollback.
- CycloneDX SBOM and release SHA-256 checksums.
- Principal-Edge-only ChatGPT browser bridge with existing-tab adoption.

### Security

- Product runtime state is separated from user workspaces.
- Runtime credentials remain outside Git.
- Stable tagged releases require Authenticode signing.
- Safe profile combines read-only workspace grants, tool allowlisting and Docker sandboxing.
