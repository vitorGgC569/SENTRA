# SENTRA Windows 1.0.5 acceptance — 25 October 2026

[Published Setup](https://github.com/vitorGgC569/SENTRA/releases/tag/installer-preview-20261025-3) · [download site](https://vitorggc569.github.io/SENTRA/).
Unsigned preview; 9 verified assets, including three installer parts.
Complete Setup: 2,857,654,405 bytes. SHA-256:
`7767c72b7f2ed157b650ad586e580a5e114665397f59207650fc27f31d6a54da`.
Application and installer source: `24e293b7d52360643859f497d3faea28cb815213`. Exact sealed snapshot
and part identities are in the release metadata. Android remains preview v11;
this Windows-only recovery change does not rebuild or reidentify the phone APK.

## Recovery choices

After destination selection, native Setup offers **Clean installation** and
**Recover damaged local settings**, both initially unchecked. Clean installation
verifies the payload first, refuses active sessions and preserves previous
program components in a unique sibling backup before reinstalling. Unrelated
files, projects, private state, conversations and account credentials are retained.
Valid installation identity and settings are retained. Backups are not auto-deleted.

Invalid local settings require explicit recovery or clean-install selection.
Their original bytes are retained and local configuration is recovered in
Safe/workspace mode. Native provider configurations are not redirected. Backup
locations and recovery notices appear on completion and in the local report.

Corrupt legacy desktop shortcuts and unowned desktop executables no longer
prevent creating a valid launcher. Unknown files are retained; a numbered,
tracked launcher is used when needed. Repair reuses it and uninstall checks its
identity before removing it. The frozen native Windows Shell probe covers these
residue cases without touching the owner's real desktop.

Setup now displays a bounded localized cause for damaged markers/settings,
unidentified destinations, occupied ports, active processes and failed local
service/display checks. A failed worker returns a nonzero exit status without
the old generic native runtime-exception dialog or an apparent success launch.
Recovery rejects protected directories, Git project roots and directory links.

## Verified

- 134 focused installer, actual Windows Shell, settings, account-connection and
  bundle tests passed. One existing Python msilib deprecation warning remains.
- Inno Setup 7.1.0 compiled the recovery choices and localized message reader.
- The actual complete Setup was run with explicit clean installation over private
  residue fixtures: an old executable, broken marker and stale runtime file.
  Those bytes were backed up; unrelated notes, a project and an account fixture
  stayed intact. The stale runtime file was absent from the fresh program tree.
- A damaged desktop.json was retained byte for byte and recovered with Safe
  workspace permissions. The synthetic native-provider config stayed unchanged.
- Same-version repair preserved a draft sentinel and the recovered settings.
  Default installation into an unowned destination still returned failure and
  retained its existing file; recovery is an explicit owner's choice.
- The installed frozen Windows Shell probe passed corrupt-link and unowned-EXE
  recovery, repeated repair and owned-only removal, entirely in private folders.
- The installed frozen Canvas received a real sentra/chatgpt-web/auto response,
  with a confirmed receipt and one physical user message, without replay. That
  test reused an owner-authorized private account state through a source gateway.
- A separate real private frozen-broker observation confirmed that the offline
  installation guard refuses an active broker. Its owned test process closed.

The [implementation record](INSTALLER_RECOVERY_2026-10-25.md) explains scope and
the retained intermediate Windows filesystem test failure. Machine-readable
[acceptance evidence](release-evidence/windows-1.0.5-2026-10-25.json) binds this
release to the tested bytes.

## Open acceptance

The owner's failed PC has not been retested with this package. Its exact 1.0.4
failure remains unconfirmed without its local diagnostics. Fixture success does
not identify that remote cause or establish a clean Windows OS qualification.
System registration was disabled in the private Setup run; the packaged Windows
Shell probe independently used private shortcut folders.

Clean Windows OS, cross-version update/rollback/reboot, complete frozen account
wizard, all provider models and broad long-running runtime acceptance remain
separate gates. Automatic approval review previously blocked VM creation; no
host security configuration was weakened. Physical Android/iPhone LAN/VPN,
camera and remote-control tests were deferred by the owner. iOS distribution
and publisher signing remain unavailable. This is not a stable signed update.
