# Multiple terminal input confirmations — 23 October 2026

## Delivered source behavior

The terminal can recover more than one pending input selector. Its compact
notice offers a batch check and an expandable list with individual checks.
Selectors from another connection remain inspectable against the original
terminal, request fingerprint and input incarnation. No command text is stored
in browser storage or displayed by this recovery control.

Each definite receipt is acknowledged and removed independently. An uncertain
or missing receipt stays pending and input remains blocked. The user can resume
only after all pending entries are resolved and the terminal is writable. A
delivery receipt is never presented as verified task completion. Batch checking
does not resend an input packet or grant permission.

## Ordering, restart and bounds

The existing protected host journal remains authoritative. A transactional
projection revision increments when pending selectors are inserted or removed.
The pending-list snapshot and revision are read in the same database snapshot.
The ACK returns its committed revision; browser windows share a locked revision
floor so an older response cannot restore a selector already acknowledged.

A random broker epoch separates revision domains across broker restarts and
restored database snapshots. A lower revision from a new broker does not hide
its pending entries. This epoch is presentation metadata, not execution
permission or proof that a process survived.

The host's existing per-terminal admission bound is 16 pending inputs. The local
selector journal allows 32 records and 32 KiB of serialized metadata, allowing a
local reservation to coexist with recovered host entries. Batches are bounded
to 16. Invalid identities, conflicting fingerprints and capacity failures
preserve the existing records and block further input. If an older/corrupt host
reports overflow, known rows remain consultable; further host rows can appear
after confirmed entries are acknowledged. Overflow cannot enable writing.

Old one-row browser journals are read without deleting or rewriting their
selectors. Hosts without the new revision/epoch metadata retain legacy
observation compatibility, without the new ordered-projection guarantee. Older
desktop code which rejects a multi-row journal remains read-only rather than
silently dropping its contents. No new Grant or permission authority was added.

## Validation and limits

- HTTP/Windows ConPTY and retention scope: **27 passed**, including three real
  pending writes, two independently acknowledged receipts, one post-write
  uncertainty, unchanged physical write count on inspection and no replay.
- Focused Node journal/pool scope: **36 passed**, including old projections,
  another browser window, changed broker epoch, multiple targets and budget
  refusal without data loss.
- Final full desktop Node suite: **258 passed** (`desktop-input26.log`).
- After rebuilding, host/retention and desktop source provenance: **39 passed**
  (`input26.xml`). The later canonical-line-ending regression scope also passed.
- Real Electron/React fixture: theme switching, narrow layout, readable button
  contrast, keyboard activation of batch inspection, retained uncertainty and
  explicit resume passed. The fixture backend is synthetic/read-only; it does
  not qualify physical terminal execution or operating-system keyboard routing.

Evidence: `.tmp/closure-root/multiple-input21.xml`, `multiple-input21-node.log`,
`multiple-input-renderer25/result.json` and the matching captures. Earlier
renderer trials are retained: they exposed a missing theme wrapper and the need
to focus a hidden fixture and wait for enabled controls, not successful keyboard
acceptance. They are not counted as final passes.

Global terminal possession, exact physical-effect correlation through the daemon,
mobile reconciliation and installed-package acceptance remain separate open
requirements. This source milestone does not close them.

Subsequent source continuation: [exact owner daemon receipts](TERMINAL_DAEMON_RECEIPTS_2026-10-23.md)
now qualifies the owner path under deliberate reply loss and broker restart.
Global possession, mobile and installed acceptance remain open.
