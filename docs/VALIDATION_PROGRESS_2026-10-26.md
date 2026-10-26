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
- On a later installer start, a durable receipt from a clean installation
  interrupted during replacement is inspected under the installation lock.
  Missing previous files are recovered without overwriting conflicts; unresolved
  conflicts block subsequent installation attempts and preserve the backup.
  Multiple unresolved generations require manual recovery.
- The LAN pairing dialog retains action errors independently of periodic
  status refreshes. Mobile reconnection checks the pinned host and client
  identity and does not automatically replay an uncertain operation.
- The mobile client also attempts bounded foreground transport recovery after a
  connection loss. It stops on revocation or a changed identity and does not
  retry business operations. Backgrounding and device changes cancel the loop.
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
- After adding recovery on the next installer start, 88 targeted installer,
  recovery and distribution tests passed. One test exits a private worker
  process during its first file move and verifies recovery on the next start.
- UI, gateway and mobile acceptance fixtures: 13 passed, two physical-network
  tests skipped. Desktop and execution tests: 55 passed, one skipped, including
  a real local Windows ConPTY case.
- Mobile transport: 25 passed, one optional multicast test skipped; app tests:
  seven passed; both TypeScript typechecks passed.
- After the foreground reconnect and lifecycle fencing changes, 31 mobile
  transport tests and seven app tests passed, one optional multicast test was
  skipped, and both typechecks passed. These are not physical-device results.
- The scoped mypy gate reported zero errors in its five configured source files.
  This is not a repository-wide typing result.
- An additional targeted suite covering PTY service behavior, input receipts,
  recovery, worktree management and coordinator authorization passed 85 tests.
  These tests do not establish clean-machine or installed-daemon acceptance.
- A source-mode run of `tests/qa/dot_worktree_execution.py` passed with the real
  `sentra/codex/current` model. It created three workers and separate Git
  worktrees, verified their edits, checked compatible and conflicting reviews,
  and re-opened the broker after the edits. The report is in
  `.tmp/goal-three-dots-20261026/report.json`. It did not interrupt a running
  effect and did not validate the installed build.
- An earlier frozen Windows candidate passed a private crash test: a broker was
  stopped while a terminal command was running, the daemon retained the same
  worker, and the receipt was reconciled without resending. The command ran
  once. Evidence: `.tmp/candidate-20261026-frozen-crash/report.json`. This
  candidate predates the latest installer and mobile changes.
- Android candidate APK: GitHub Actions run `40394905514`, commit
  `4a90c2217429d9f56115b91f848cf854f055224e`, package
  `app.sentra.mobile.preview`, versionCode 12. The build verified its v2
  signature against the existing preview certificate. SHA-256:
  `cdc9e93c575473c4ae5d16cbe23c2c7983d4f45147f09ecc24efb78cc60c6aa3`.
  It was downloaded to `.tmp/android-candidate-20261026/app-release.apk`; this
  predates the foreground reconnect changes and is not proof of a successful
  physical-device test. A fresh build must include those changes.
- CI run `40394884595` reported that the MCP integration fixture did not open
  its loopback port within 15 seconds. The same integration test passed locally
  in 11.20 seconds, and a separate local cold-start observation reached the
  listener in 5.81 seconds. These observations do not identify the CI cause;
  the failed run remains evidence against full integration acceptance.

## Still required

The Windows candidate started before the interrupted-install recovery change;
it cannot establish that the new recovery is included in the next Setup.
Finish validating that candidate, then build the updated sources and verify their
contents and upgrade paths. Test the
Android candidate on an actual device. Validate installation on a genuinely clean Windows
system, update, rollback and reboot; real installed account onboarding and
model response; interruption and recovery of multi-Dot work without duplicate
effects; and installed daemon concurrency and recovery. Pair and exercise
Android on a physical LAN/VPN, including camera, backgrounding and remote input.
An installable iPhone build requires Apple signing and distribution. Complete
the broader UI/accessibility and workspace qualification, and rerun the full
required test suites. Previous public preview releases remain separate from
these unshipped changes.
