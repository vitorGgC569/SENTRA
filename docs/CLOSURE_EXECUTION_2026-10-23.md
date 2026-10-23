# Closure execution — 23 October 2026

This is the continuing execution of the owner's nine-part attachment, not a
declaration of completion. Base revision: `9ed4341`. Results below distinguish
working-source changes, frozen artifacts, installed acceptance and physical
devices. Older reports remain historical; their unchecked boxes are not evidence
that a subsequently implemented feature is absent.

## Requirements and acceptance ledger

| Requirement | Evidence required to close it | Current disposition |
|---|---|---|
| CI failures and full run | Actual required checks passing on the delivered commit, with all collected cases and skips explained | All required jobs passed on `ee73a52` (run 40006505644), including exact partition coverage. The later `b38b213` run failed: a documents timeout/retained-worker failure in partition 0 and two post-effect revocation boundary timeouts in partition 1. Current source is not CI-qualified. See the follow-up below. |
| Long-running PTY/checkpoints | Successful prolonged run of the exact frozen/installed daemon under concurrent output, reconnect and uncertain input | Source and frozen 1,800-second runs passed. The exact correlated-input frozen follow-up on `b38b213` also passed: three terminals/reopens, 534 advancing checkpoint observations, one physical duplicate consumption. Complete installed-package and prolonged real-model/TUI acceptance still open. Earlier frozen failure remains historical. |
| Renderer recovery and memory | Watchdog/heap enforcement, preserved resource/view identity, no input replay, actual renderer qualification | Source watchdog and allocation admission delivered and tested; actual total V8/Chromium heap, installed acceptance and physical devices still unqualified. |
| Global input ownership and conflict recovery | Conflicting desktop/mobile origins and devices, lease loss, pending-intent recovery, no late/repeated effect | Central lease foundation has six tests, including durable uncertainty after a failed write. It is explicitly not wired to desktop/mobile/agent/daemon paths; global arbitration remains open. Multiple desktop pending selectors have their own partial acceptance below. |
| Multiple pending inputs | Independent observation/ACK, uncertainty preserved, old projection fencing and no resend | Desktop/host implementation and HTTP/ConPTY/Node/React tests delivered. Exact owner daemon correlation and broker-reopen recovery now have source acceptance; mobile/global arbitration and installed acceptance remain open. See the recovery and daemon receipt reports. |
| Journal retention | Bounded protected-content retention preserving unresolved effects and permanent deduplication | Terminal ACK/retirement, permanent tombstones and transactional owner admission budgets implemented. Generic operations retain complete content pending ACK integration; inactive stores need explicit maintenance. |
| Unified subscriptions | Versioned sequenced events, resumption/gap behavior and shared desktop/mobile consumers | Shared conversation projection transport now has source implementation and encrypted-client acceptance. Workspace inventory, approvals and terminal output still use their existing bounded read paths; complete unified subscriptions remain open. |
| Daemon upgrade | Actual version negotiation, explicit drain and update with active process preservation | Open; accepted HTTP handlers now drain before database closure. Handshake, additive receipt capabilities and drain commands do not qualify executable replacement. |
| MSI | Actual administrative extraction and independent install/update/uninstall of exact package and cabinets | Corrected external-media candidate passed real administrative extraction and 7,886 file checks; release callers now preserve/bind external media. Independent install/update/uninstall/signing remain open. Published preview is unchanged. |
| Windows stable distribution | Clean independent Windows, previous-version upgrade, rollback, uninstall inspection, component execution, trusted signing, reviewed exact hashes | Open; current unsigned Setup is experimental. Local update ZIP is not an enabled stable channel. |
| Workspace/editor/Git | Installed pane/orphan/layout recovery, device conflicts, visual editor/long content and authorized advanced merge/rebase/new/binary destructive flows | Existing source and targeted tests are partial evidence; complete acceptance open. |
| Guest/VM files | Real scoped remote editing, bidirectional synchronization and reviewed back-publication | Open; current snapshot import is one-way and does not make the host editor a guest filesystem. |
| Full Dot journey | Real installed conversation delegates authorized work, deliberate interruption/close, reopen, recovery, verified results without technical user intervention | Real ACP/OpenCode and three worktree workers already passed their recorded scopes; complete installed UI journey remains open. |
| Browser/computer and visual | Installed/mobile input and profile recovery; themes/focus/accessibility/reduced motion/narrow screens/attachments/dialogs/long documents; monitor topology/scaling; owner visual acceptance | Existing Chromium/Electron fixtures are partial evidence, not blanket acceptance. |
| Android/VPN | Actual phone installation/pairing/Windows approval/chat/terminal/background/reconnect/revoke/release, plus real private VPN route/address change | Open; automated encrypted clients are not physical phones. |
| iPhone | Valid signing/provisioning/build/distribution channel, then physical device acceptance | Open external prerequisite: no owner Apple Developer account or signing channel supplied. Source/export is not an installable app. |
| SSH/GitHub/Linear | Real configured identities/accounts/services; guided setup, authorized remote files and issues/PR operations | Partial adapters exist; native Linear and complete guided provider workflows remain open. |
| Additional Coucou integrations | Actual CLI observation adapters, reversible hooks and biometric approvals | Separate unimplemented backlog included in the attachment; existing visual adaptation does not prove these features. |
| Documentation/release closure | Reconciled current checklist, exact artifact provenance and recovery/update/limitations documentation | This ledger starts reconciliation; final release evidence is still required. |

Public relay and relay-dependent push remain outside the owner's selected
LAN/private-VPN delivery. They are not silently counted as delivered.

## Working-source checkpoint correction

Live checkpoint observation previously acquired both the global archived-screen
reconstruction lock and SQLite writer lock. A deterministic before/after probe
held both locks: the base implementation did not respond during the hold, whereas
the working correction returned the last committed checkpoint immediately.
This proves lock coupling; it does **not** establish the exact cause of the old
1,430-second frozen failure.

The live projection holds only OS-protected, successfully committed frames,
follows committed quota pruning, preserves workspace identity and ordered
geometry, and cannot start a process. Archived reconstruction retains its own
serialized path. Failed transactions must not publish a newer frame.

Local evidence (overlapping runs are not summed):

- History/checkpoint/isolation scope: 25 passed; an initial run's pytest temporary
  cleanup failed, and a unique-directory repetition exited successfully.
- Daemon/checkpoint integration scope: 17 passed.
- Final projection scope, including actual quota eviction and failed-commit
  retention: 6 passed.
- Enforced mypy gate: zero findings / maximum zero.
- `checkpoint-lock-proof12.json` records the before/after probe.
- `source-projection-soak12/report.json`: source-only 1,800-second soak passed,
  17,883 output reads, 531 checkpoints, three broker reopens, unchanged worker
  PIDs and one physical execution of the intentionally duplicated input.

Evidence is retained under `.tmp/closure-root`; those private laboratory paths
are not distributed product inputs. A new frozen build, installed qualification
and full CI are still required after the source changes stabilize.

## Subsequent source/build evidence

- Peer handlers now drain before their shared authority can close. Canvas shutdown
  invokes this drain, retains failed session registrations and prevents a new
  listener during shutdown. Canvas wiring and shell-federation scope: 5 passed.
- Renderer recovery includes stale-ACK fencing and protected restoration without
  recreating the PTY. Desktop Node scope: 253 passed; mobile Node scope: 7 passed;
  Python renderer/provenance scope: 13 passed; mobile TypeScript passed. Allocation
  reservations are a conservative buffer model, **not** measured total heap.
- CI partition validation scope: 47 passed. Both partitions independently collect
  the full recursive suite; a mandatory gate rejects differing collections,
  omissions, duplicates, incomplete execution and source-revision disagreement.
- A new Canvas-only executable was built from immutable source snapshot
  `25a97f11a18ed16820d8eb142ace750cf165fa77710890860d498f4694d6e425`.
  Its SHA-256 is
  `c12a509668f3b2ba21f5129919afd1869be1fdf20e355944ec27587967d768d6`.
  The frozen 1,800-second acceptance passed under the same sealed source broker:
  18,561 output reads, 534 checkpoints, three broker reopens, unchanged worker
  PIDs, one physical duplicate-intent execution and graceful owned-daemon closure.
  Evidence: `frozen-projection-soak12/report.json`. These synthetic ANSI/Unicode
  workloads do not qualify prolonged real-model CLI/TUI behavior. The later
  stronger checkpoint-progress assertion separately passed a 30-second source
  run; it was not retroactively added to the already-running 1,800-second runs.
  This is not a new complete Setup or an update to the owner's installation.
- Retention: 19 final tests passed, including deterministic ACK/inspection/
  compaction races. Limits are per owner: 250,000 permanent keys and 256 MiB
  protected content plus admission reservations. Only acknowledged, definite
  terminal receipts are eligible after seven days; unresolved and asynchronous
  operations are not discarded. See [policy and limits](HOST_REQUEST_RETENTION_2026-10-23.md).
- New MSI external-media laboratory: actual `msiexec /a` returned zero and all
  7,886 extracted files were verified. The exact same artifacts failed at a
  longer laboratory target path; shorter-path administrative acceptance does
  not qualify arbitrary path lengths, registered installation or clean Windows.
  The application payload remains the earlier frozen `8b24da4`; this trial
  qualifies the revised packaging arrangement only. Details and exact media
  hashes: `.tmp/closure-msi/full-result3.json`.

## Consolidated verification before commit

- Selected CI/packaging/retention/PTY/Canvas shutdown suites: **127 passed**,
  `.tmp/closure-root/consolidated15.xml`.
- Additional release/security/runtime/provenance scope: **78 passed**,
  `.tmp/closure-root/release-expanded16.xml`.
- Central terminal-possession foundation: **6 passed**,
  `.tmp/closure-root/possession-foundation16.xml`. This is not transport integration:
  the daemon does not yet supply `input_generation` or `write_correlated`, and
  existing input paths do not call this module. No UI is advertised as globally
  arbitrated on this evidence.
- Source contract passed; enforced mypy remains **0 / maximum 0**. A complete
  remote CI on the resulting commit is still required.
- Release-caller changes preserve external CABs through temporary staging,
  include their inventory in manifest/checksums/SBOM, require trusted CAB
  signatures and Installer trust-table inscription for stable releases, and
  bind VM acceptance to the exact external-media inventory. The pipeline is
  prepared; genuine certificate/Insignia/independent VM qualification is not
  claimed by the local unsigned laboratory.

The interrupted delegated implementation left global terminal ownership at a
tested foundation. Its remaining execution-path integration is retained in the
ledger; it must not be inferred from the module's presence or its unit tests.

## Multiple pending input continuation

[Recovery report](TERMINAL_INPUT_RECOVERY_2026-10-23.md): pending selectors now
recover individually or in a batch. The host publishes a transactional revision
and broker epoch; shared browser floors reject obsolete projections without
losing selectors when the broker restarts. Known receipts can be acknowledged
independently while uncertain entries continue blocking input. No physical
write is retried. This does not complete global input arbitration.

The first remote run of `8477de1` stopped at the whitespace gate; its new MSI
helper contained an extra blank line at EOF. Follow-up `c99869c` corrected that
without weakening the gate. CI run `40000592432` is the full remote qualification
of that base, not of these subsequent uncommitted recovery changes.

## Complete remote CI result and follow-up

Run `40000592432` on `c99869c` finished with **nine failing unit cases**,
4,262 passing cases and 65 skips across the two partitions. Integration,
failure, Windows/Edge, pinned Web Models/Electron and source-contract jobs passed.
The mandatory coverage and aggregate jobs correctly rejected the failing run.
This is not a green complete CI.

- Four packaging/provenance cases: the shared imports need LF checkout rules,
  the sealed checkout fixture must copy those imports, and the snapshot test
  must compare canonical repository paths. One existing desktop source had CRLF
  bytes although Git stores LF; the bundle was rebuilt after normalization.
  Node and Python now refuse to seal noncanonical source line endings instead
  of producing an artifact which fails after checkout.
- Telemetry startup: a concurrent first WAL transition can fail immediately
  with `SQLITE_BUSY`. Only idempotent WAL setup is retried within the existing
  five-second budget; event bodies are not retried. Deterministic busy/non-busy
  regression cases and real concurrent publisher tests pass locally.
- The Docker test's six-second availability probe timed out on the hosted
  Windows runner. An unavailable optional backend is explicitly skipped, not
  reported as a passing sandbox restart. Set `SENTRA_REQUIRE_SANDBOX_RESTART=1`
  for mandatory qualification; then absent/timed-out/non-Linux backends fail.
  The actual restart test passed locally in the 99-case scope below.
- Two workflow timeouts and one post-effect federation revocation timeout did
  not reproduce in focused local runs. Their ten-second deadlines and effect
  assertions remain unchanged. Timeout diagnostics now preserve server stacks;
  passing reruns do not establish that the historical causes are fixed.

Current local scopes (overlap; do not add together):

- Desktop Node: **258 passed**, `desktop-input26.log`.
- Host/retention/source provenance: **39 passed**, `input26.xml`.
- Packaging/source seals/telemetry/release/sandbox restart: **99 passed**,
  `ci-regression30.xml`, including actual Git checkout and real sandbox restart.
- Post-effect federation revocation matrix: **8 passed**, `ci-timeouts29.xml`.
- Workflow documents: **3 passed**, `workflow30.xml`.
- Enforced typed-core gate: **0 errors / maximum 0**, `input26-mypy.log`.

A new complete CI on the resulting revision is still required. The complete
Windows setup, user's installed app, Android APK and iPhone distribution have
not been replaced by these source changes.

## Exact owner/daemon receipt continuation

The multiple-pending/CI source milestone was committed and pushed as `ee73a52`.
Its full remote qualification is run `40006505644`; the two unit jobs were still
running at the last observation. This does not qualify the later daemon changes.

[Exact daemon receipt report](TERMINAL_DAEMON_RECEIPTS_2026-10-23.md) records the
new capability, physical input generations, read-only effect observation and
protected host reconciliation. A real source daemon survived lost confirmation
and two broker reopens with one consumption per input. The HTTP shutdown barrier
now joins accepted handlers before closing SQLite; its old-behavior regression
mutant fails as expected. The 93-case consolidated scope and 19-case host
compatibility scope passed. Global possession and the remaining attachment
requirements are still active, not inferred complete from these improvements.

The daemon/host implementation was committed locally as `6865fc0`. The next
physical-key correction excludes the temporary broker target from the durable
daemon key; a real Windows journal-restore regression passed. Preliminary
component build 42 succeeded but predates that follow-up. Its exact hashes and
limits are recorded in the daemon report, not promoted to complete release QA.

## Hosted CI and host lifecycle follow-up

Run [40006505644](https://github.com/vitorGgC569/SENTRA/actions/runs/40006505644)
completed successfully on `ee73a52`, including integration, failure, both unit
partitions, Windows/Edge, pinned Web Models/Electron, exact partition coverage
and the required aggregate. Unit partition 0 recorded 1,975 passed / 37 skipped;
partition 1 recorded 2,300 passed / 29 skipped. The coverage verifier compared
4,341 collected cases in 514 files with partition sizes 2,012 and 2,329 and
proved the exact union. Seven subtests per partition are not extra collected
cases and are not added to those totals.

The 66 JUnit skip reasons were inspected, not treated as feature acceptance.
They concern explicit real-device/provider opt-ins, absent external tools or
source profiles, Docker/VM/remote credentials, and tests that specifically
exercise an unavailable provider. Eight Vite-dependent unit cases were skipped
in that Python environment; separate Canvas/Electron jobs passed their own
scopes. These do not qualify physical phones, native remote services or every
optional provider.

The later `b38b213` run
[40010182220](https://github.com/vitorGgC569/SENTRA/actions/runs/40010182220)
has a failing partition 0: 1,993 passed, 37 skipped and one failed documents
workflow. Its captured request deadline shows a physical document worker in
central authorization at output publication. Shutdown then refused to close a
host with an occupied physical I/O boundary. That refusal is retained. The
trace does not prove the cause of the original request delay. Partition 1 also
finished with two failed post-effect revocation boundary waits, 2,310 passed and
29 skipped. Their stacks include central authorization connection/commit work.
The exact-coverage job correctly refused failed partition manifests; it did not
accept a partial green suite.

A separate deterministic regression demonstrates that `MachineHost.close()`
previously left its default executor thread alive and event loop open after
stopping the host thread. The correction shuts down async generators and the
default executor on the owning loop, then closes the loop. The test failed on
the prior implementation and passed with the correction. Catalog-reader and
actual resource-lock guard tests confirm that busy hosts retain their runtime
instead of killing physical work. This fixes a demonstrated resource leak; it
does not retrospectively establish the hosted timeout's cause. Full CI on the
new delivered revision remains required.


## Shared conversation observations follow-up

Desktop and mobile now import the same read-only projection feed. The mobile
path authenticates an existing conversation through its current `message_list`
capability, filters project events at the host, and encrypts observations through
the existing paired WebSocket. Cursor+epoch resumption, gap repair, revocation,
bounded slow-reader queues and lower-sequence restoration have source tests.
The final consolidated scope records 62 passed; the desktop suite records 261
passed. These are overlapping test scopes, not an installed product claim.

See [shared observation contracts and evidence](SHARED_PRESENTATION_EVENTS_2026-10-23.md).
The CI now explicitly runs the actual encrypted Canvas path. Workspace inventory,
approvals and terminal output still use their existing read paths; all-channel
unified subscriptions, physical mobile acceptance and installed qualification
remain open. The existing public packages and owner sessions were preserved.
