# Exact daemon input receipts — 23 October 2026

## Source behavior

The authenticated local daemon now advertises `correlated_input_receipts: 1`.
New PTYs have a random input generation returned by creation and inventory;
reopening the broker reattaches the same generation and PID. The existing base
protocol remains version 1. This additive capability is not complete daemon
upgrade/version negotiation.

An exact selector binds the effect key, workspace, terminal, daemon runtime,
input generation and SHA-256 of the input bytes. `write_correlated` validates
that binding before dispatch. Its selector and possible-effect reservation
commit atomically before the PTY call. A duplicate key cannot write twice;
changed contents or scope are refused. Failed/aborted writes remain uncertain.

`input_effect` observes a selector without input text, reservation, creation or
write. Unknown effects remain unknown. A delivered receipt reports
`delivered_to_process`, never task completion. Historical definite receipts
remain observable after a daemon restart without recreating their process.
Old in-flight records become uncertain and cannot be replayed.

The physical key derives from owner, workspace, terminal and caller key. It
does not include the broker's temporary input target. That target still fences
dispatch, but reopening a broker or restoring an older outer journal cannot
give the same caller key a second identity in the surviving daemon.

The owner desktop input path protects the selector in its existing host intent
before dispatch. If confirmation is lost, inspection consults the existing
daemon and commits only an exact definite receipt. It does not call
connect-or-start, send another input or infer delivery from output text. A new
broker can inspect the old input target after reattaching the original PTY.
Late callback success/failure cannot replace an observed receipt or resurrect
its retired contents. Existing ACK, pending revisions and retention continue.

Selector growth is charged against the protected host admission budget before
the physical-effect boundary. The daemon permits at most 250,000 correlated
selector records; at capacity it refuses new correlated input while preserving
observation and deduplication. This is a record bound, not a total SQLite/WAL,
filesystem or legacy-daemon-journal byte limit. No journal was compacted in the
owner's installed application.

Legacy daemons retain the previous owner path and its weaker observation
guarantees. Calling the new correlated client API without the advertised
capability fails explicitly and never falls back to a write. A host claiming
the capability without an exact generation also fails before dispatch.

## Accepted-handler drain

The daemon's HTTP server now joins accepted handlers before closing its journal
and releasing ownership. Previously daemon threads could outlive `server_close`
and access a closed database. Socket reads keep their existing deadline.
The barrier does not terminate active PTYs or constitute an executable upgrade.

## Evidence

These scopes overlap; their case counts must not be added:

- **93 passed**, `daemon-consolidated40.xml`: daemon selectors, host recovery,
  real Windows ConPTY/broker recovery, protected retention, lease foundation,
  history, checkpoints, live-observation isolation and startup deadlines.
- **19 passed**, `host-compat41.xml`: late success/failure with and without ACK
  retirement, generic host-request compatibility and message status.
- **27 passed**, `receipt-bounds38.xml`: exact selector scope, capacity refusal,
  atomic reservation rollback and recovery of old uncertain receipts.
- Real source soak with correlated owner input: **passed**, three terminals,
  321 reads, nine advancing checkpoints and two broker reopens. One actual daemon
  reply was deliberately lost; three pending confirmations were recovered and
  acknowledged. Worker PIDs remained unchanged and each duplicate test input
  was consumed once. The owned daemon closed normally. This requested 30 seconds
  of workload and took 38.9 seconds overall: `source-correlated39/report.json`.
- Drain regression mutant: restoring the old daemon-thread behavior makes the
  barrier test fail and reproduces `Cannot operate on a closed database`.
  `drain-mutant37.log` is expected failing evidence, not a passing test run.
- Repeated source HTTP document workflows: nine scenarios / 75 requests passed,
  slowest request 1.078 seconds, `workflow-repeat38/result.json`. This does not
  establish the cause of the earlier hosted-runner timeouts.
- Enforced typed-core gate remains **0 / maximum 0**. Desktop bundle validation
  verifies 124 output files; these backend changes do not rebuild the full Setup.
- Physical-key follow-up: **3 passed**, `stable-physical43.xml`. The real Windows
  test additionally models a restored outer journal missing its request, changes
  the broker target and verifies the same daemon selector/receipt is reused.
  Only the disposable test journal is modified.

An isolated frozen Canvas was built from snapshot
`9613f1bc8e1034b036b44ceb5adb936751d0b9b75090d9318131d99f2e0ed9ce`
at base `6865fc0`, SHA-256
`7c776df52637d2b6e32f630cf5b3ce3357aee2911f5065af9fbe4003303e1dab`.
This preliminary component build predates the physical-key follow-up above;
it is not a new complete Setup, installed acceptance or qualification of the
later source. Its result remains `correlated-frozen42-result.json`.

## Still open

The central terminal-possession foundation can now call correlated writes under
its physical boundary, but it is still not integrated across all desktop,
mobile, agent and federation input paths. Exact owner receipts do not establish
global exclusive possession. Existing agent/mobile paths keep their central
admission; they must receive their own end-to-end correlation and reconciliation.

Complete installed-package acceptance, prolonged real model/TUI workloads,
physical phones/VPN, real daemon executable upgrade and clean signed Windows
distribution remain open. The owner's installed application and public release
assets were not replaced by this source milestone.
