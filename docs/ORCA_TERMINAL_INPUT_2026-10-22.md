# Terminal input checkpoint — 22 October 2026

Source implementation; the existing Windows preview installer has not been rebuilt.

## Implemented

- The renderer input queue is bounded: 256 KiB aggregate, 64 KiB per terminal,
  16 KiB per packet, 512 aggregate entries and 128 per terminal. Active work and
  a 256-byte metadata allowance per entry count against the budget.
- UTF-8 packets are split into at most 1,024 Unicode scalars / 4,096 bytes for
  HTTP. A failed write cancels its queued suffix. Hiding or replacing a view
  discards queued input, including a trailing Enter; it cannot undo dispatched input.
- A same-origin Web Lock prevents two windows interleaving a queued packet.
  Missing coordination support leaves the new viewer read-only.
- Every new viewer input has a stable request key, exact session incarnation and
  fingerprint. Selectors persist before dispatch; the original input stays in
  the existing encrypted host journal. This adds no independent execution authority.
- The host records the possible-effect boundary before writing to ConPTY. Lost
  acknowledgements are inspected, never automatically replayed. A receipt for
  delivery to the process explicitly has `task_completion_verified: false`.
- A metadata-only pending index restores selectors even when the broker port
  changes. ACK removes the pending projection, not the consumed original key.
- Recovery appears inside the terminal: **Consultar confirmação**, then
  **Continuar digitando** after review. Resumption permits only new input.

## Evidence

The combined host regression report `.tmp/coucou-terminal-host-clean.xml` has
51 passing cases: six real HTTP/Windows ConPTY input cases, bounded output,
daemon recovery, authorization, workspace request recovery and 17 companion IDs.
The first run also passed its 51 cases but exited with a pytest temporary-folder
cleanup PermissionError; the clean rerun used an exclusive local test directory
and exited successfully. It is not counted twice.

The six input cases cover encrypted intent, exact deduplication, post-effect lost
HTTP ACK, recovery after rebinding a new HTTP port, post-write uncertainty,
incarnation mismatch, cross-terminal/unauthenticated access and invalid payloads.
The port-change case reuses the live app/ConPTY; it does not prove a full broker
process restart or a real model turn.

The combined desktop Node report has 231 passing cases, including queue limits,
Unicode, lost ACK, pending-selector adoption, two-window coordination, hidden
paste cancellation and unsupported-host behavior. Parser/HTTP/DOM boundaries in
pool tests are injected. Eleven JSX sources parsed in memory; no new bundle was
generated during this final review. See the Coucou integration report for the
additional approval cases and the limits of inherited screenshots.

## Remaining P0 work

This checkpoint does not finish P0. Cross-origin/global input possession, recovery
of multiple conflicting pending inputs, protected-journal retention, renderer
watchdog, aggregate emulator heap, prolonged real-model/TUI acceptance, installed
daemon qualification and unified sequenced subscriptions remain open.

The legacy authenticated owner input entry remains for existing clients. Agent
and mobile actions retain central machine admission. This checkpoint does not
claim that every owner keystroke now goes through a new Grant flow. Session
incarnations are deliberately changed on reconstruction; restored history cannot
be mistaken for continuity of a process.
