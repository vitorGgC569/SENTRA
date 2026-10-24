# Mobile preview and GitHub Pages delivery

The public page is built from `site/` by `.github/workflows/pages.yml`.
Images are actual renderer captures of disposable demonstration fixtures; their
origin and hashes are in `site/assets/provenance.json`. No installed account or
conversation was captured. The page never connects to the user's local host.

## Android

Dispatch `SENTRA Android preview` on the reviewed source commit. The workflow
checks types/contracts, prebuilds the Expo native Android project, creates a
standalone ARM64 release APK and verifies its signature. It publishes a GitHub
prerelease with APK, SHA-256, metadata and installation notes. Package identity
`app.sentra.mobile.preview` is separate from future production distribution.

The dedicated preview signing key is held in GitHub Actions secrets. Its local
recovery copy is DPAPI-protected outside the repository in the user's SENTRA
signing directory. No secret or private signing file belongs in Git. Preserve
this key for upgrade continuity; do not generate a replacement on each CI run.

The page enables Android downloads only when GitHub's asset digest, size and
release tag match `mobile-downloads.json`. Publishing a build does not establish
physical-device qualification. Release tests must still cover LAN pairing,
reconnect, background suspension, revocation and remote input on real hardware.

## iPhone

The owner has no Apple Developer account. There is no published iOS installation channel yet. The page explicitly states
that status. An Apple distribution certificate/provisioning profile and a valid
TestFlight or other permitted signed distribution channel are needed before an
installation button can be enabled. An unsigned IPA or a simulator bundle is
not presented as a phone download. Mac-like visual style is independent of
which operating system the user owns.

## Windows and migration

The page links to Windows release notes without claiming that an earlier setup
contains later local changes. The local installed Canvas patch has its own
build identity. Stable Windows publication retains the existing independent QA
and signing gate. No stable release is created by the mobile preview workflow.

## Direct LAN / VPN

The owner selected direct connectivity, not a public relay. The desktop gateway
is explicitly enabled from Devices and binds a local private interface. Automatic
selection prefers physical LAN; private overlay VPN interfaces must be selected
by their reachable IPv4 address. RFC1918 and 100.64.0.0/10 addresses are supported.
A VPN must be configured separately on both peers; no public port forwarding,
cloud account or public relay is required. E2EE identity pinning, expiring QR,
owner confirmation, scoped device permissions and revocation still apply.
A passing local protocol test is not evidence of routing on a physical VPN.

The full workspace migration remains open: interactive browser/computer surfaces,
orphan recovery/layout synchronization qualification,
SSH/connectors, physical devices and final signed distribution.

Current acceptance, pinned ACP and concurrent worktree evidence: [delivery report](DELIVERY_ACCEPTANCE_2026-10-22.md).
