# Shared conversation observations — 23 October 2026

## Delivered source scope

Desktop and mobile now import the same `ProjectFeed` and projection reducer from
[component source inventory](../THIRD_PARTY_NOTICES.md). The desktop
module is a re-export, not a second implementation. Both observe the existing
protected `ShellStreamJournal`; no replacement authority, conversation or model
transport is introduced.

The mobile gateway opens an authenticated **loopback POST** SSE observation on
`/api/mobile/stream` and carries frames inside the existing paired E2EE WebSocket.
Device credentials remain in encrypted requests and private loopback bodies,
never URLs. The host derives access from the existing `message_list` capability,
checks current project/Space/Dot/conversation membership, and rechecks device
revocation and resource scope before every emitted frame and idle observation
cycle. Project-wide resets/events are filtered before leaving the host. Mobile
cannot use its project cursor to read a different Dot's conversation or head.

`presentation_head` is a read-only gateway method. `subscribe_presentation` and
`unsubscribe_presentation` attach/detach viewers; they never create, resend,
cancel, approve or complete work. Closing a view does not close a resource.

## Version, cursor and recovery

Frames and subscription acceptance carry protocol version 1. An owner-scoped
journal epoch is generated once in the existing SQLite store. It survives
normal reopen; a replaced journal has a different epoch. New clients send both
the last project sequence and epoch on reconnection. An epoch mismatch, compacted
cursor or future cursor causes an explicit reset and a fresh scoped head read.

The project resume cursor differs from the visible conversation's delta base.
Events for other conversations advance the host cursor but do not expose their
content or descriptors. Heartbeats advance a filtered viewer's resume cursor.
A reset can legitimately lower a visible sequence after restoration; generation
fencing prevents a late head from the former projection from winning. The prior
preview remains visible while observation repairs itself. Frames are always
partial and non-authoritative; a preview cannot authorize effects or prove final
completion.

RPC requests and stream frames share the existing ordered authenticated cipher
session. A broker destination update aborts only read subscriptions. `ProjectFeed`
reopens observation with its last cursor and repairs gaps through head reads;
it never retries a message, terminal input or any other effectful request.
Revoked credentials terminate observation with 401/403. Unsupported endpoints or
subscription protocols produce an explicit unavailable state.

## Bounds and lifecycle

- At most 16 gateway connections and two read subscriptions per connection;
  existing host-wide 32 SSE slots remain shared with desktop readers.
- Existing request queue/rate and encrypted socket backpressure remain in force.
- The SSE parser admits bounded chunks and counts UTF-8 bytes, with a 2 MB frame
  budget, including multi-line and unterminated Unicode input.
- The Hermes observer queue retains at most 128 frames / 4 MB conservatively
  accounted bytes. Overflow fails explicitly and requires observation repair;
  it never silently drops an input or treats a gap as completion.
- Mobile uses async frame iteration without requiring browser `ReadableStream`
  or `TextDecoder` polyfills. The trusted Node gateway handles SSE decoding.
- App suspension/navigation detaches the selected conversation observer. Existing
  protected drafts remain independent. Credential rotation restarts the observer
  with the newly stored credential. A preview is bound to its selected conversation
  before rendering, avoiding content carryover during navigation.

The mobile conversation now updates its generating preview through events and
refreshes committed messages on observed operation/state transitions. Its
existing bounded history polling is reserved for an explicitly unavailable
presentation endpoint. **Workspace inventory, approval lists, terminal output,
and browser/computer observations still use their existing bounded read paths.**
This milestone does not close the requirement for all-channel unified events.

## Evidence and practical limits

Private lab evidence under `.tmp/closure-root` includes the following overlapping
scopes (counts are not added):

- `presentation-final65.xml`: **62 passed**, final consolidated scoped HTTP,
  protected replay/content, encrypted mobile acceptance, rotation/restart/input
  identity and desktop/mobile packaging provenance scopes.
- `presentation-desktop65.log`: **261 passed**; `presentation-transport65.log`:
  **22 passed / 1 skipped** (real multicast socket opt-in). The 15 parser cases
  are included in the desktop total.
- `presentation-mobile-export66.log`: final Android Metro/Hermes export completed;
  it does not produce or qualify an installable APK.
- Required CI now runs transport typecheck/tests and the real encrypted Canvas
  presentation test explicitly, preserving its separate JUnit evidence. A
  failure remains a required job failure; unit partition coverage is unchanged.

- `presentation-http71.xml`: **4 passed**, including a real desktop SSE reset
  when the prior epoch changes but the numeric cursor still matches.
- `ci-contract70.xml`: **40 passed**, required job guards and exact partition
  contracts; the new explicit encrypted observation lane cannot be optional.

Earlier supporting runs:

- `presentation-consolidated53.xml`: **41 passed**, actual scoped Canvas HTTP,
  protected stream replay/content, mobile permissions, real Node encrypted
  pairing/credential rotation, broker restart and input identity scopes.
- `presentation-real62.xml`: **3 passed**, current scope/epoch tests and actual
  production Canvas → Node gateway → encrypted mobile client. The latter checks
  a Unicode preview, exclusion of a second Dot, ciphertext on the wire, resume
  with the prior project cursor and epoch after broker retarget, and idle
  revocation. No physical phone, real LAN interface or VPN is claimed.
- `presentation-parser63.log`: **15 passed**, shared SSE/reducer/feed tests,
  including Unicode byte limits, restored lower cursors, stale head fencing,
  async mobile frames and revoked authority. These overlap the desktop suite.
- Desktop suite: **261 passed**; mobile app suite: **7 passed**. Transport suite:
  **22 passed / 1 skipped** (actual multicast socket opt-in not enabled).
- Both transport and mobile TypeScript checks passed. Android Metro/Hermes export
  completed (`presentation-mobile-export56.log`); this is not an APK build or
  installed device qualification.
- Desktop bundle rebuilt with the imported shared JS in both Node/Python source
  provenance manifests. Provenance/mobile-stage scope: **21 passed**. Typed-core
  baseline: **0 / maximum 0**.

Final delivered source must also receive its own complete required CI. The owner app/profile, published Setup,
Android APK and existing model cookies were not replaced by this milestone.
Android/iPhone physical tests, private VPN, complete installed UI acceptance,
and the remaining event channels are still open.
