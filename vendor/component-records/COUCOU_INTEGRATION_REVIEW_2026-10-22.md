# Coucou integration review — 22 October 2026

## Scope closed in source

Reviewed and completed the visual front handed off by DeepSeek: animated original
Dots, the optional presence island, compact conversation presence/ticker, decision
cards, the Oxta hub and file-drop presentation. Existing SENTRA navigation and the
ORCA workspace remain. The hub observes existing data; the existing attachment
adapter handles uploads. No Coucou executor, permission service, mobile transport,
hooks or Mochi assets were introduced. No dependency was added.

The island is enabled by default in the delivered implementation, persisted as
`sentra_shell_island=on/off`, and can be hidden in its panel. On narrow windows it
opens from the topbar sparkle button. This supersedes the earlier document's
wording that it was opt-in. The main Home structure and Canvas navigation remain;
the companion renderer and this optional presence chrome are the intended changes.

## Corrections made during final review

1. **Inspection really is read-only.** The original central decision card sent
   `coordinator_approval_reply` again when asked to consult. It now uses
   `conversation_permission_status` with the original fingerprint/key and exact
   project/Space/conversation. Pending selectors survive reopening, including when
   the approval has already disappeared from the pending list. Uncertain decisions
   are not reconstructed or replayed. The existing protected journal owns results.
2. **Two-window decisions are coordinated.** Persistence precedes dispatch and
   uses the existing selector journal plus a Web Lock. Unknown transport errors
   keep the selector. A terminal receipt must confirm the original request before
   the selector is removed. Invalid/unavailable persistence prevents dispatch.
3. **Delivery is not verified task completion.** A receipt ID, a nonempty textual
   verification field or a file list alone no longer triggers success. Current
   failure, cancellation, uncertainty and active execution defeat stale success
   flags. Explicit host verification is required by the conversation and hub.
4. **Event targets are guarded.** The inherited screenshot report recorded two
   `event.target.closest is not a function` errors. Shell guards now handle events
   originating on Document or text nodes without losing modal guards.
5. **Presentation cleanup.** Hub copy is shorter, redundant observation badges
   are hidden and project state is human-readable. Expired decision countdowns
   disable approval locally; backend admission remains authoritative.
6. **Attribution and source inventory.** The inspected Coucou pin and complete
   MIT notice are preserved in `vendor/coucou`. The source manifest lists the new
   modules; it was not regenerated against stale output bundles.

## Validation and its limits

- **231 desktop Node cases passed**, including five new decision-journal cases,
  completion counterexamples and event-target handling.
- **51 host cases passed** in `.tmp/coucou-terminal-host-clean.xml`, including
  terminal receipts and the 17 mascot identifiers.
- **Five additional host cases passed** in `.tmp/coucou-approval-host-final.xml`:
  existing inline permission/approval admission plus a new real HTTP case for
  recovering a decision after its pending card disappears. Inspection is forced
  to fail if it tries to mark a decision again; cross-conversation access is denied.
- Eleven JSX source files parsed in memory without emitting a bundle.
- The handed-off Electron workspace fixture reports success for restoration,
  keyboard navigation, narrow layout and inline lost-ACK recovery. Its report is
  `sentra_canvas/desktop_ui/.tmp/workspace-ux-out/result.json`.
- The inherited screenshot report has ten completed scenarios but **two functional
  console errors**, corrected in source above. Screenshots were inspected as saved
  artifacts; they are not a clean rerun of the latest changes. Some captures named
  “island-open” show only the pill, so those names alone do not prove an open panel.
- Fresh interactive verification is pending: local browser control is disabled
  in Work settings. The earlier automatic approval rejection of a disposable
  Electron launch was not bypassed. Dark/light, narrow layouts, reduced motion,
  open island focus and upload behavior need a clean interactive rerun.

No new setup, tag, commit or push was made in this final review. Previously
generated static desktop assets from the handoff were preserved; they precede
these last corrections and must not be described as the latest validated bundle.

## Separate backlog

This closes the handed-off visual implementation and its source review, with
interactive acceptance explicitly outstanding. It does not close the ORCA macro
migration. Coucou CLI observation adapters, reversible hook installation, biometric
mobile approvals and its other audited ideas remain separate, unimplemented
backlog. Physical Android/iPhone, relay and signed distribution are still pending.
