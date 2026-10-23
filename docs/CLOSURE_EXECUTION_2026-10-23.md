# Closure execution — 23 October 2026

This is the continuing execution of the owner's nine-part attachment, not a
declaration of completion. Base revision: `9ed4341`. Results below distinguish
working-source changes, frozen artifacts, installed acceptance and physical
devices. Older reports remain historical; their unchecked boxes are not evidence
that a subsequently implemented feature is absent.

## Requirements and acceptance ledger

| Requirement | Evidence required to close it | Current disposition |
|---|---|---|
| CI failures and full run | Actual required checks passing on the delivered commit, with all collected cases and skips explained | Focused contract/drain corrections passed; two whole-file unit jobs and mandatory exact-coverage verification implemented. Original timeout causes remain unproven; new complete CI still required. |
| Long-running PTY/checkpoints | Successful prolonged run of the exact frozen/installed daemon under concurrent output, reconnect and uncertain input | New source and frozen 1,800-second runs passed with three terminals, three broker reopens and unchanged worker PIDs. Complete installed-package and prolonged real-model/TUI acceptance still open. Earlier frozen failure remains historical. |
| Renderer recovery and memory | Watchdog/heap enforcement, preserved resource/view identity, no input replay, actual renderer qualification | Source watchdog and allocation admission delivered and tested; actual total V8/Chromium heap, installed acceptance and physical devices still unqualified. |
| Global input ownership and conflict recovery | Conflicting desktop/mobile origins and devices, lease loss, pending-intent recovery, no late/repeated effect | Central lease foundation has six tests, including durable uncertainty after a failed write. It is explicitly not wired to desktop/mobile/agent/daemon paths; global arbitration and multi-pending recovery remain open. |
| Journal retention | Bounded protected-content retention preserving unresolved effects and permanent deduplication | Terminal ACK/retirement, permanent tombstones and transactional owner admission budgets implemented. Generic operations retain complete content pending ACK integration; inactive stores need explicit maintenance. |
| Unified subscriptions | Versioned sequenced events, resumption/gap behavior and shared desktop/mobile consumers | Open; bounded polling is not this acceptance. |
| Daemon upgrade | Actual version negotiation, explicit drain and update with active process preservation | Open; handshake and existing drain commands alone do not qualify an update. |
| MSI | Actual administrative extraction and independent install/update/uninstall of exact package and cabinets | Corrected external-media candidate passed real administrative extraction and 7,886 file checks. Release-caller integration and independent install/update/uninstall/signing remain open. Published preview is unchanged. |
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
