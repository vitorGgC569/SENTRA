# SENTRA 1.0.4 acceptance — 25 October 2026

## Published downloads

- [Windows Setup 1.0.4](https://github.com/vitorGgC569/SENTRA/releases/tag/installer-preview-20261025-2): unsigned onedir + Inno Setup 7.1.0 preview,
  9 verified assets including three setup parts. Full Setup SHA-256:
  `81e9b48304e2480cd3112927c4b85af34eec8532d9d7af460d78056028a126cc` (2,857,576,510 bytes).
- [Android preview v11](https://github.com/vitorGgC569/SENTRA/releases/tag/mobile-preview-20261025-11): standalone ARM64 APK, version code 11,
  SHA-256 `e7c9e5902141431db4214c60d9cf4841490f461c9912e1740c6da5c5ea4c7842`. The dedicated preview signer is unchanged.
- [Download site](https://vitorggc569.github.io/SENTRA/). iOS remains unavailable.

Application and installer source: `6c98ae16cd0800f805fe66d0ab370c069cfb2e42`.
The sealed source snapshot and individual release asset hashes are in the release
metadata. Android source is `7fbabed2db5d200242148537d248341d4f6aee8b`, workflow
`40208015155`; its mobile tree is unchanged in the Windows
source commit. Emulator-only x86_64 artifacts are not phone downloads.

## Automated and local checks

109 focused onboarding/installer tests passed, with one Python `msilib`
deprecation warning. Website validation passed 23 Python and eight Node tests.
A first attempt at the Python run hit a permission error during pytest's cleanup
of a pre-existing temporary symlink; rerunning with a fresh isolated base directory
completed successfully. No product failure was inferred from that runner error.

The complete native Setup installed into an empty private folder and repaired the
same version, retaining a draft sentinel and synthetic native-provider configuration.
Its onedir support files were present. An unowned destination was refused with
a nonzero exit code, retaining its file. Payload checks ran with a minimal PATH.
The user's installed application, live profiles and provider routes were preserved.
System registration was disabled in this isolated qualification, so shortcuts and
automatic startup are not qualified by that test.

The installed frozen 1.0.4 Canvas received a real `sentra/chatgpt-web/auto` response
with a confirmed receipt and one physical user message. There was no automatic
replay. The check reused the already authorized private account profile, through a
source gateway and the newly installed browser/MCP components. This does not claim
every provider/model or the complete frozen Setup account wizard was exercised.
During the run, the source gateway logged idle HTTP keep-alive connection resets
while reading subsequent request lines. The original response and receipt were
confirmed, and the owned frozen broker closed; the message was not replayed.

## Integrated account connection

The source coordinator and packaged Chromium reused the exact owner-authorized
validation app and proved the roundtrip using a fresh one-use MCP health challenge.
The app was not recreated. The bounded embedded protocol prepared the read-only
probe; generic script/keyboard access was not introduced. Draft and app mentions
are preserved. Account inventory hydration is awaited before creation is considered.

New-app preparation supports the observed tunnel textbox and legacy selector and
the explicit no-second-OAuth choice. Login, account safety consent and submission
remain owner actions. An app's name alone cannot verify its tunnel or host. An
existing app targeting another host is not silently retargeted.

## Android checks

The native Origin correction is present in both new Windows host and phone APK.
Host identity pinning, encrypted frames, replay rejection, approval and scopes
remain enforced. The prior x86_64 emulator qualification from the same mobile
source passed pairing, inventory, draft retention after force-stop, background
return, gateway reconnection with retained identity and device revocation.
See the [earlier account/emulator record](LIVE_ACCOUNT_AND_EMULATOR_2026-10-25.md)
for its exact artifact identities and scope.

## Still open

- Clean Windows OS installation, cross-version upgrade, rollback and reboot.
  The official Microsoft evaluation ISO was downloaded and its published hash
  verified. Automatic approval review rejected creation of the disposable VM with
  `blocked by policy`; no specific reason was supplied. No host security setting
  was changed. Empty-folder installation on this PC does not replace this gate.
- Full frozen Setup account-wizard end-to-end acceptance and all provider models.
- Physical Android/iPhone LAN/VPN, camera and remote-control qualification:
  explicitly deferred by the owner in favor of automated tests for now.
- Native iOS distribution: no Apple Developer account or signing channel exists.
- Publisher signing and stable-release acceptance. These are unsigned previews;
  no signature, update-admission or Windows protection gate was disabled.

Machine-readable evidence: [windows-1.0.4-2026-10-25.json](release-evidence/windows-1.0.4-2026-10-25.json).
