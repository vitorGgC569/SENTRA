# SENTRA validation progress — 26 October 2026

This is a development record, not a stable-release acceptance. The changes
described here are in the working tree; they are not evidence that the Setup,
APK, installed application or public downloads contain them.

## Changes under validation

- Clean installation moves only files identified in the existing SENTRA
  ownership marker. Conflicting unowned files stop the operation rather than
  being overwritten. A recovery receipt records the backup before moves.
- After an installation failure, missing files can be recovered without
  overwriting files created in the meantime. Existing conflicting files require
  manual recovery. Recovery uses a fully written temporary file and an atomic
  no-replace link; a failed copy does not expose a partial original file. The
  backup is retained. This is not a guarantee of automatic full rollback.
- The LAN pairing dialog retains action errors independently of periodic
  status refreshes. Mobile reconnection checks the pinned host and client
  identity and does not automatically replay an uncertain operation.
- Gateway request audit failures no longer interrupt the model request. Native
  models remain outside the Web-only gateway.
- The older Windows wrapper calls the Inno installer with its supported flags;
  diagnostics and unit fixtures have been brought into line with current
  packaging contracts. The desktop UI bundle was rebuilt from source.

The recovery and connection work takes inspiration from studying Cindy's
selective update, failure reporting and connection lifecycle. It does not embed
the Cindy application or its cloud relay. No source files from Cindy are
claimed as copied by this record; any future direct reuse must retain its
applicable license, notices and pinned provenance.

## Evidence

- Installer and recovery tests: 83 passed before the final atomic-copy change;
  34 targeted installer, wrapper and distribution tests passed afterwards.
- UI, gateway and mobile acceptance fixtures: 13 passed, two physical-network
  tests skipped. Desktop and execution tests: 55 passed, one skipped, including
  a real local Windows ConPTY case.
- Mobile transport: 25 passed, one optional multicast test skipped; app tests:
  seven passed; both TypeScript typechecks passed.
- The scoped mypy gate reported zero errors in its five configured source files.
  This is not a repository-wide typing result.
- An additional targeted suite covering PTY service behavior, input receipts,
  recovery, worktree management and coordinator authorization passed 85 tests.
  These tests do not establish clean-machine or installed-daemon acceptance.
- The current Android JavaScript bundle was exported locally. This is not an
  APK; producing the native package also requires an Android SDK and JDK.

## Still required

Build new Windows and Android packages from the reviewed tree, then verify their
contents and upgrade paths. Validate installation on a genuinely clean Windows
system, update, rollback and reboot; real installed account onboarding and
model response; interruption and recovery of multi-Dot work without duplicate
effects; and installed daemon concurrency and recovery. Pair and exercise
Android on a physical LAN/VPN, including camera, backgrounding and remote input.
An installable iPhone build requires Apple signing and distribution. Complete
the broader UI/accessibility and workspace qualification, and rerun the full
required test suites. Previous public preview releases remain separate from
these unshipped changes.
