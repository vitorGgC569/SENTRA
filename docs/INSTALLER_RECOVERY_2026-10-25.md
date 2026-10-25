# Setup recovery and clean installation — 25 October 2026

The owner reported Setup 1.0.4 configuration exit code 2 on a computer with
previous failed installations. Its precise failure remains unconfirmed without
that computer's logs. Local fixtures reproduced corrupt legacy shortcuts,
unowned desktop launchers, damaged settings/markers, active-installation refusal
and a port occupied by a different MCP identity.

## Implementation for 1.0.5

Native Setup offers two explicit, initially unchecked choices:

- **Clean installation:** verify the complete payload and credential protection,
  confirm the installation has no active processes, and move previous SENTRA
  program components to a unique sibling `.sentra-clean-*` backup. Install fresh
  components while preserving unrelated files, projects, conversations, account
  credentials, private state and desktop ownership evidence. Valid installation
  identity is retained; corrupted/missing identity can be replaced only through
  this explicit recovery choice. No previous component backup is auto-deleted.
- **Recover damaged local settings:** retain the invalid `desktop.json` by a
  same-directory rename and start with Safe/workspace permissions. Clean
  installation also enables this recovery for invalid settings. Valid settings
  are retained. Recovery does not reconstruct or increase permissions from a
  guessed default or an old backup.

System roots, home/data roots, Git project roots, directory links and private
state overlapping a program component are rejected. Active processes and
unverifiable process ownership remain blocking conditions; Setup does not kill
sessions or take over an occupied service port.

An unowned desktop `SENTRA.exe` is retained. A numbered launcher is created and
tracked instead; repair reuses that launcher and uninstall removes only its
verified bytes. Damaged ownership receipts are backed up. A corrupt legacy
`SENTRA.lnk` is preserved, and migration of a verified old link occurs only after
the new launcher has been published. Publication refuses a conflicting file
that appears during staging.

The historical web-only `gpt-6` setting is migrated by the installer into its
explicit Web namespace. Ordinary model validation stays strict and native
provider configuration is not edited. UTF-8 BOM settings and markers are accepted.

The worker emits a bounded credential-free reason and localized text. Native
Setup displays that text instead of a generic runtime exception, preserves a
nonzero exit status on failure and shows backup/recovery notices on success.
The manual switches are `/SENTRA-CLEAN-INSTALL` and `/SENTRA-RECOVER-SETTINGS`;
users can choose the equivalent options in the wizard without a terminal.

## Verification before packaging

- 134 focused installer, Windows Shell, settings, account-connection and bundle
  tests passed, with one existing `msilib` deprecation warning.
- Actual Windows COM tests cover corrupt links, unowned executables, repeat
  repair, owned-only removal and a desktop publication race.
- Private filesystem fixtures cover clean backups, preserved data/identity,
  failed preparation recovery, process refusal and verification before movement.
- Inno Setup 7.1.0 compiled the recovery page and localized message reader using
  a tiny compile-only fixture; that fixture was not executed.
- One intermediate run encountered WinError 5 in the existing deep-path update
  rollback fixture. Its focused rerun and the subsequent complete related suite
  passed. No cause is inferred and unrelated update code was not changed.

Full 1.0.5 Setup packaging, installed residue-recovery qualification and
publication are pending at this source checkpoint. This record does not claim
acceptance on the owner's failed PC or a clean Windows OS.


## Packaged follow-up

The complete Setup, clean residue recovery, same-version repair, frozen shortcut
probe and installed model turn subsequently passed. See the [1.0.5 acceptance
record](RELEASE_1_0_5_ACCEPTANCE_2026-10-25.md) for exact published identities and
remaining limits.
