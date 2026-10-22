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

There is no published iOS installation channel yet. The page explicitly states
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

The full ORCA migration remains open: interactive browser/computer surfaces,
orphan recovery/layout synchronization, real ACP/three-worktree acceptance,
remote relay/SSH/connectors, physical devices and final signed distribution.
