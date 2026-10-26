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
  conflicts or unverifiable copies block subsequent installation attempts and
  preserve the backup. Hashes allow recovery to resume idempotently after a
  second interruption. A verified temporary marker can be quarantined on
  Windows without replacing an unknown file. Multiple unresolved generations
  or unverified conflicts require manual recovery. An unrecognized marker is
  preserved and blocks replacement. Recovered files are checked again before
  completion; this cannot prevent a later write by another process.
- The LAN pairing dialog retains action errors independently of periodic
  status refreshes. Mobile reconnection checks the pinned host and client
  identity and does not automatically replay an uncertain operation.
- The mobile client also attempts bounded foreground transport recovery after a
  connection loss. It stops on revocation or a changed identity and does not
  retry business operations. Backgrounding and device changes cancel the loop.
- A mobile request that times out while its socket remains open now closes the
  suspect transport; outstanding operations remain uncertain and are not
  replayed. The reconnect loop can then reopen the pinned session.
- Paired-device authentication failures use a fixed error code, carried by the
  encrypted gateway. They close only the matching session; an operation denied
  by its scope leaves the device session connected.
- Credential rotation fences concurrent requests and stale responses while the
  new credential is stored. The durable rotation receipt supports recovery.
- Canvas shutdown performs a bounded drain of machine-host readers and active
  calls, fencing new admissions while dependencies are being closed. If the
  timeout expires, resources remain owned and an in-process caller may retry.
  Once the HTTP server is closed, its endpoint is removed even if shutdown
  fails; there is no remote retry through a closed endpoint.
- Physical thread work remains tracked even if an awaiting coroutine times out.
  Completed shutdown stages are not repeated, and an uncertain teardown stage
  stays fenced rather than being repeated without proof. Physical locks remain
  owned through teardown and, after an uncertain failure, for the lifetime of
  the host. Process exit still releases operating-system locks. RustDesk and
  Daytona retain references and report uncertainty if their owned processes or
  local connections cannot be confirmed closed. On Windows, RustDesk starts
  suspended, enters its Job before resuming, and retains its handles until the
  Job reports no active processes.
- Browser shutdown reports failed context, browser or driver closure as
  uncertain and retains references. It checks the main browser process has
  exited, but does not yet prove that all browser descendants have exited.
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
- After adding recovery on the next installer start, 105 targeted installer,
  recovery and distribution tests passed. One test exits a private worker
  process during its first file move and verifies recovery on the next start.
- UI, gateway and mobile acceptance fixtures: 13 passed, two physical-network
  tests skipped. Desktop and execution tests: 55 passed, one skipped, including
  a real local Windows ConPTY case.
- Mobile transport: 25 passed, one optional multicast test skipped; app tests:
  seven passed; both TypeScript typechecks passed.
- After the reconnect, lifecycle, timeout and rotation changes, 33 mobile
  transport tests and seven app tests passed, one optional multicast test was
  skipped, and both typechecks passed. These are not physical-device results.
- Seven mobile acceptance tests passed with real local Canvas HTTP, the Node
  gateway and encrypted clients, covering broker restart, scope denial and
  device revocation. These do not validate a physical phone or actual VPN.
- The scoped mypy gate reported zero errors in its five configured source files.
  This is not a repository-wide typing result.
- An additional targeted suite covering PTY service behavior, input receipts,
  recovery, worktree management and coordinator authorization passed 85 tests.
  These tests do not establish clean-machine or installed-daemon acceptance.
- Sixty-five targeted backend, machine-host, shutdown, federation, turn-memory and terminal
  possession tests passed after the
  thread-drain changes. They include timed-out physical work and a held lock;
  they do not prove the continuity of a model process after broker shutdown or
  verify Daytona and RustDesk against live external services.
- Thirty-five tests covering uncertain model turns and terminal possession
  passed with the current host-drain changes.
- Sixty-five additional host and executor tests passed, six service-dependent
  tests were skipped and four subtests passed. These include a real Windows
  Job with a child process; they do not establish a real RustDesk or Daytona
  service session.
- Browser shutdown tests include simulated closure failures and a real local
  process handle. Tests requiring a real Playwright browser were skipped; the
  browser process tree and an installed interactive session remain unverified.
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
- A later source-mode three-Dot interruption attempt did not reach a verified
  result. Durable records showed three creations and three delegations, with
  one user message per worker, but all worker turns were `UNCERTAIN` and no
  execution worktrees were recorded. Shutdown raised while catalog readers
  remained active. The temporary fixture initially failed to persist its
  report when cleanup also failed; it has since been corrected. This does not
  prove any duplicate or the absence of effects outside the recorded scope.
- A follow-up source-mode attempt recorded all three worker turns as `RUNNING`
  before broker interruption and confirmed that the broker reopened. The first
  worker status checked afterwards was `UNCERTAIN`; the fixture stopped without
  replay and closed its owned processes. This is a failed continuity test, not
  a completed multi-Dot task. Evidence:
  `.tmp/goal-dots-inflight-retry-20261026/report.json`.
- Android candidate APK: GitHub Actions run `40402687334`, commit
  `618d5401e104b0fdd3122732e89f733d9956f7c8`, package
  `app.sentra.mobile.preview`, versionCode 16. The build verified its v2
  signature against the existing preview certificate. SHA-256:
  `93c83976513ac38d44d3265714bed44d66921498de45cdb78e5eefc1446e1ddd`.
  It was downloaded to `.tmp/android-candidate-618d540/app-release.apk`; this
  is not proof of a successful physical-device test. The structured revocation
  response also requires a compatible desktop gateway.
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
