# Terminal consumers — October 22, 2026

## Source changes

The Desktop terminal pool now admits at most eight concurrent reads, with one
read per consumer and a FIFO waiting budget of 128 identities. A credit remains
held across HTTP, checkpoint decoding and xterm's write acknowledgement. An old
release callback cannot debit a replacement read. Waiting rows contain no output.

This adapts ORCA's queued/in-flight accounting principle to SENTRA's pull protocol.
It does not give a viewer authority to pause or restart a producer. ConPTY,
history, Grants and WorkItems keep their existing ownership and admission.

Only connected, nonzero-size surfaces in the active project are observed. Modern
Desktop runtimes also use IntersectionObserver to suspend surfaces outside the
paintable viewport. Document suspension, removal and project changes invalidate
the view generation, queued input epoch and read controller. A late HTTP or render
callback cannot advance the cursor or re-enable stdin for the suspended view.

Suspension during an unacknowledged write marks the view uncertain. The next
observation restores its checkpoint; without one, a reset is labelled as a partial
image. Disposing the emulator releases its held render acknowledgement after
disposal. Temporary suspension does not falsely free a still-running renderer.
No physical terminal is closed or created by this consumer lifecycle.

Canvas now normalizes live, daemon and historical output to 16,000 Unicode scalar
characters per response. Cursors advance only through the returned prefix;
`head`/`has_more` preserve the outstanding suffix. Incremental frames are bounded
to 64,000 UTF-8 bytes and checkpoint decoding retains its existing 1 MiB ceiling.
The eight credits bound concurrent frame payloads, not total browser heap or all
xterm scrollback. Nonempty backlog is consumed without the normal idle delay;
empty frames do not spin while persistence is pending.

## Evidence

- 25 Python tests passed: frame boundaries and rejection, authenticated HTTP
  recovery of a 40,000-character supplementary-Unicode transcript without skips,
  quiet-session independence, real disposable Windows ConPTY/daemon reconnection,
  protected history and terminal observation authorization regressions.
- 169 Desktop Node tests passed, including nine new consumer tests and existing
  real-xterm checkpoint restoration. Pool scheduling tests inject HTTP/parser/DOM
  boundaries explicitly; they are not visual or browser-layout qualification.
- Source provenance revalidated eight copied transport modules, 28 copied terminal
  files and twelve adaptations against the pinned ORCA Git blobs. The updated
  dependency inventory contains 979 lockfile records, including development and
  optional-platform packages.

Reports: `.tmp/consumer-flow-host-final.xml` and
`sentra_canvas/desktop_ui/.tmp/consumer-flow-regression.log`.

Origin: `src/main/daemon/daemon-stream-backpressure.ts` at
`70b2197c97b164b16c618736a107967295e5af92`, blob SHA-256
`c20b25185f72e396515cf098ce74f8d52636c2db470a33cd527c0c54fa5c580f`.
MIT notices and the target adaptation remain in `vendor/orca/provenance.json`.

## Still open

The macro P0 is not complete. Desktop and mobile now have renderer watchdogs and
bounded aggregate emulator allocations (see the October 23 supplement below).
Bounded input queues were subsequently delivered separately. Prolonged TUI/real-model
CLI acceptance and installed daemon qualification remain. Unified sequenced subscriptions across
desktop/mobile also remain; bounded pull reads are not presented as that protocol.
Physical Android/iPhone and interactive visual checks are still pending.

No bundle, setup, tag or installed application was updated in this round. The
existing Windows preview and earlier validation outputs retain their own source
identities; this is a source implementation checkpoint.

## October 23 supplement: renderer recovery and allocation admission

Desktop inventory rows no longer allocate xterm instances. Only mounted, visible
surfaces allocate an emulator. A shared budget admits at most eight instances and
64 MiB of modeled buffer allocations, with 2,000 scrollback rows, both screen
buffers, 32 bytes per cell and 1 MiB per instance. Resize and checkpoint geometry
reserve before allocation. Pressure parks hidden least-recently-used emulators;
visible emulators are not silently displaced. A refused view explains its state
and is retried when an existing view is detached or a resource is removed.

Parking retains session identity, ownership, input receipt selectors and blocked
input state. Restoring requests a protected checkpoint and never starts a PTY or
resends input. Scroll position is restored within the available checkpoint range;
older scrollback remains explicitly limited by the host checkpoint.

The allocation count is an admission model, not a measurement or hard ceiling of
V8/Chromium process heap. Renderer fonts, DOM, GPU, extended cells and strings add
memory outside this reservation. Those process-level limits require separate
measurement and are not claimed as closed by the cell budget.

Mobile has one emulator with a 16 MiB allocation budget and 500 scrollback rows.
Missing render ACK, WebView load timeout and native renderer termination replace
only the view, with at most two automatic attempts per selected session. Further
failures request explicit observation restart. Stale view callbacks are fenced;
process actions and uncertain input are never replayed. No WebView onData channel
exists.

Evidence for this source checkpoint:
- Full Desktop Node suite: 253 passed (including real-xterm checkpoint tests).
- Mobile app Node suite: 7 passed; TypeScript check passed.
- Offline mobile document exercised in isolated Electron: 1 passed; actual Unicode,
  colors, normal/alternate buffers, saved register, CSP and read-only input checked.
- Cross-language Desktop source seal suite: 12 passed; imported shared emulator
  modules now invalidate stale bundles.

These are source and disposable-renderer checks, not physical Android/iPhone or
installed runtime qualification. The Desktop assets and mobile offline document
were regenerated; no installed application, setup, tag or account was changed.
