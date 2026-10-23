# Changelog

All notable user-facing changes to SENTRA are recorded here.

## 1.0.1 — 2026-10-22 (preview qualification)

### Added

- Scoped workspace recovery, layout conflict choices, edge splits and keyboard navigation.
- Protected editor drafts and centrally authorized Git review, commit, fast-forward merge, publication and cleanup.
- Browser Design Mode and opt-in, owner-protected login profiles.
- Protected mobile drafts, foreground refresh, pinned-host LAN discovery and recoverable credential rotation.
- Scoped remote keyboard chords and drag gestures with input release on interruption.

### Fixed

- Host catalog reads blocking concurrent terminal and worker operations.
- Windows worktree provisioning at deep paths and protected draft cleanup races.
- HTTP SSE dechunking, truncated response detection, federation socket cleanup and A2A stream shutdown.
- Budget rejection incorrectly retaining a quote for a later task step.
- Installer login validation, exact loopback host checks and all findings in the enforced Python typing gate.
- Windows snapshot publication sharing failures without replaying validations, provider calls or task effects.
- Clean terminal packaging now seals the patched xterm dependency files before staging or starting its worker.
- Android preview certificate verification recognizes the actual build-tools scheme labels while preserving the original signing identity.

### Qualification

- Preview builds retain separate device, native package and signing acceptance gates.
- The complete Windows setup rebuild and prolonged final suite are deferred; this source preview does not claim a newly qualified Windows installer.
- Android/iPhone physical operation and private VPN behavior require device acceptance; no signed iOS distribution is claimed.
- Stable Windows publication requires independent clean-install, upgrade, uninstall and signature evidence bound to the actual artifacts.

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
