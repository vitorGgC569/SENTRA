# SENTRA Canvas Collaboration (opt-in)

A Hocuspocus v4 / Yjs collaboration boundary integrated into native Canvas. The owner enables it with the collaboration button; the Canvas supervises a loopback process and issues one-use tickets through the real ControlPlane grants. Browser dependencies are built with `npm ci` and `npm run build:browser` in this directory. Importing the modules does not start a server.

## Authority split

- **CRDT data:** root maps `layout`, `nodes`, `notes` only. Geometry (`x`, `y`, `width`, `height`), viewport and plain-text notes.
- **Ephemeral awareness:** server-stamped principal ID, optional cursor and selected node. Never an authorization claim.
- **Excluded from CRDT:** Run, Operation, PolicyDecision, Grant, Lease, terminal contents, CLI commands, credentials, audit evidence and other control-plane states.
- New nodes and links are **not created** by receiving CRDT updates. The authoritative graph remains in SENTRA; only display-only geometry and notes synchronize.
- This module does **not** issue grants, own accounts, or read browser tokens. Host must supply `resolveGrant`, live `checkGrant`, atomic persistent `consumeNonce`, versioned `loadSnapshot`, and fenced `commitSnapshot`. All callbacks fail closed.
- `loadSnapshot({workspaceId})` must return `{snapshot: Uint8Array | null, revision: nonnegativeInteger}`. `commitSnapshot({workspaceId, principalId, epoch, context, expectedRevision, snapshot})` must atomically verify the current grant and epoch, compare the stored revision, durably persist the candidate, and return `{revision: expectedRevision + 1}`. `consumeNonce({fingerprint,workspaceId,principalId,epoch,expiresAt})` must atomically consume the nonce fingerprint in durable/shared storage. No insecure in-process fallback is permitted.

## Run and test

Node.js 24+ is required for the optional service and built-in SQLite reference; install dependencies **only in this directory**:

```sh
npm install --prefix sentra_collab --ignore-scripts
npm test --prefix sentra_collab
```

Start only from an explicitly authorized coordinator host: import `createCollabServer` from `sentra_collab/server.mjs`; supply all five host callbacks, a strict `allowedOrigins` list, and call `listen()`. The listener is bound to **127.0.0.1**; do not expose the WS port directly to the network. For remote peers, integrate behind a reviewed TLS/auth reverse proxy with server-side workspace policy. Service stops via `destroy()`.

Client uses `window.SentraCollab.connect({workspaceId, url, getToken, Y, HocuspocusProvider, onChange, onPresence, onError})` only after the coordinator has loaded the approved dependencies; `getToken` must mint a **fresh one-use short-lived** session credential for each connection. This adapter does not modify the existing DOM automatically.

## Security and limits

Reject unknown root types/keys and non-display state. Write updates are validated on a shadow Y.Doc before applying. Per-update 64 KiB, document 1 MiB, bounded maps (512 node geometries, 128 notes), notes max 12k characters, strict numeric ranges. One-use credentials, live read/write checks, origin allowlist (where Origin is supplied), max documents and pre-auth message limits. Revocation removes the blocked session without granting CRDT authority. Local-memory replay cache and in-process snapshot callbacks are **not** a distributed multi-instance authorization solution; production needs shared nonce/replay storage, persistent snapshots, host rate limits and a monitored TLS boundary.

Tests include native WebSocket two-client synchronization, denied client, replay, workspace isolation, forbidden Run/Operation root, reconnection and live-session revocation. **No end-to-end two-machine Canvas UI test was performed.**

## Phase 2: safe coordinator handoff

1. Connect `resolveGrant` to the **authoritative SENTRA control plane**, never to a Yjs map. Mint a fresh random 32-byte (or stronger) one-use credential tied to a single workspace, principal, `read`/`write` scope, policy epoch and expiry (maximum 15 minutes). Reject attempts to reuse an existing token.
2. Implement `checkGrant` as **live deny-by-default** for `read` and `write`. Re-evaluate the current workspace membership, grant epoch, revocation and expiry, not merely a cached JWT claim. Reject revoked users on incoming frames and on subsequent persistence. Set an appropriate `recheckMs` (minimum 250 ms) for idle connected clients.
3. Implement versioned `loadSnapshot` and **atomic fenced `commitSnapshot`** together with live SENTRA grant/epoch validation and storage transaction. The callback must reject stale revision or revoked grant *before* writing. Treat any exception as a failed commit and never acknowledge it as persisted. Precommit does not make an untrusted or non-atomic host callback transactional.
4. Use a reviewed TLS reverse proxy and strict browser `allowedOrigins`; the sidecar binds only to `127.0.0.1`. Missing `Origin` is possible from non-browser clients, so Origin is not an authentication mechanism. Enforce caller principal/workspace at the authorization callbacks.
5. After coordinator review, package and explicitly load `sentra_canvas/static/sentra-collab.js` and pinned Yjs/Hocuspocus provider. Instantiate by user-initiated opt-in only; no automatic existing Canvas DOM mutation. On workspace switch, call `disconnect()` and obtain a new scoped credential. Treat incoming geometry as a view projection, never a command to create/execute nodes.
6. Validate with two independently authenticated real devices, reconnect after actual backend restart, revoked read/write grants, persistence failure and multi-instance replay. These validations are **not completed here**.

The browser adapter checks Hocuspocus `scope` before permitting local edits and permits awareness in `readonly` mode. For writes, `PrecommitGate` serializes each workspace document, validates the candidate shadow Y.Doc and its quotas, awaits host `commitSnapshot`, and only then permits the Hocuspocus `readUpdate`/broadcast. The `afterHandleMessage` hook releases the per-document lock. `onStoreDocument` does not perform deferred storage.

### Remaining blocked items

- No approved integration yet with SENTRA's real workspace membership, grant/epoch revocation API or durable snapshot store; the E2E tests inject fixture callbacks only.
- The earlier post-broadcast store race is mitigated **within this sidecar** by a pre-apply gate. A deterministic barrier test revokes a user while commit is pending and proves the peer receives no update. **No end-to-end transacionality is claimed:** the host must atomically combine revision CAS, current grant/epoch check and durable persistence, and must handle ambiguous timeouts, crash recovery, concurrent processes and reattach. A process crash after a successful commit but before the in-memory Yjs update may leave peers temporarily stale until they reconnect.
- Persistent `consumeNonce` is now **mandatory**; the local cache is supplemental only. The fixture demonstrates replay denial across a sidecar restart using shared simulated nonce storage; a real database transaction and global workspace admission policy remain unintegrated.
- Hocuspocus logs rejected protocol frames with library stack traces; production log filtering/redaction at the host is required. No temporary `TEST_MAP`, `TEST_SHADOW_REASON` or similar debugging logs remain.
- This phase did not run a two-machine browser UI E2E, TLS/Origin proxy test, prolonged soak or automatic deployment; none may be claimed as complete.

## Gate-3 race study and deterministic regression

**Previous vulnerable ordering:** the Hocuspocus `readUpdate` mutates and broadcasts the Y.Doc synchronously, whereas its debounced `onStoreDocument` runs later. Under revocation between these events the peer has already observed uncommitted data, even if `storeSnapshot` refuses the save. Authorization at `onStoreDocument` alone is insufficient.

**Current local ordering:** `beforeSync` acquires a per-document mutex, confirms live workspace permission, applies the proposed Yjs update to a temporary shadow document, enforces root allowlists and quotas, and awaits `commitSnapshot`. Only a fenced successful commit releases Hocuspocus to apply the accepted update and broadcast it. `afterHandleMessage` releases the mutex. Deferred Hocuspocus `onStoreDocument` validates but does not write.

**Deterministic negative test:** `gate.test.mjs` pauses an in-flight `commitSnapshot` at a controlled barrier after writer authentication and before storage. While paused, peer state and storage are both verified empty. The policy then revokes the writer and resumes the commit, which is refused. The peer still sees no update, and storage remains empty. No arbitrary sleep creates the race; the barrier establishes its order.

**Cross-process limitations:** local mutexes guard only one sidecar process. Correct multi-instance operation requires an atomic database `compare-and-swap(workspace_revision)`, an *atomic* current-principal/epoch check in the same commit and a durable idempotency/nonce table shared across all processes. In the fixture, Maps imitate these properties; this is **not evidence** of production-grade transactional storage. An ambiguous commit timeout, host bug, process crash between durable commit and in-memory application, or another instance's concurrent updates require host-level reconciliation and potentially reloading the workspace Y.Doc. Do not turn on multiple writers until these are implemented and verified. Never issue a credential or expose a login UI from this sidecar.

**Gate-3 coverage:** read-only scope, invalid state and oversize quotas, Run/Grant/Lease denial, nonce replay after restart, authenticated workspace switch, sanitized awareness without secrets, fenced precommit no-leak race and serialized concurrent writers. Tests use real Hocuspocus/Yjs loopback WebSockets and local fixture callbacks, **not** external agent, production host or two-machine integration.

## Gate-4 awareness regression: policy and leakage review

The Hocuspocus v4 `MessageReceiver` decodes awareness into a temporary
`Awareness` whose `getStates()` includes a **synthetic empty local entry**.
A policy that treats that entry as the incoming peer's identity may incorrectly
bind `claim.clientId` and then deny the actual client's legitimate state.
The corrected policy removes empty synthetic states before binding. It also
drops non-owned tombstones, rejects multiple non-empty client states per
message, rejects reassignment of a bound client ID, and retains the per-document
`awarenessOwners` constraint across sockets. Only `user.id` (from the
authenticated server context), validated `cursor` and validated `selection`
are ever re-encoded to peers; arbitrary `user`, `token`, `secret`,
`grant` and other client-controlled fields are excluded. If any
non-whitelisted value fails validation, the incoming frame is rejected;
no wider authorization or scope is inferred from awareness.

The real WebSocket test asserts that a viewer receives the sender's sanitized
presence without its forged `admin` identity, token, secret or grant fields.
The unit test also covers multi-ID spoofing, non-owned tombstone attempts and
strict output field names. The sidecar does **not** expose credentials or a
login form. Rejected test frames may still generate Hocuspocus library stack
traces; a production log-redaction policy remains a host-owned blocking item.

## Gate-5 reference host and design handoff

See **[INTEGRATION_GATE5.md](./INTEGRATION_GATE5.md)** for the concrete five-callback
contract, mock epoch/revision/nonce transaction design, ambiguous commit
reconciliation, two-peer/restart tests, Yjs and awareness trust boundaries,
and the minimal SENTRA Canvas opt-in proposal (including static SVG cables
with damped spring/Verlet physics). Source comparison covers the cloned
Yjs, y-protocols, Hocuspocus, xyflow and OpenHands trees.

`reference_host.mjs` is **test-only in-memory simulation**. It deliberately
does not start a service, issue real SENTRA credentials, persist to disk,
export an authentication UI, or claim distributed ACID guarantees. The
precommit sidecar is not wired to the production host or current Canvas.

## Sprint 3x3 / CRIT-003: three executable local integrations

For the tested additions (Yjs real two-peer geometry/viewport/notes sync,
SQLite durable WAL + **real two-process** CAS/nonce/epoch and crash recovery,
and y-protocols raw-aware tombstone authorization) see
**[SPRINT_3X3_LOCAL.md](./SPRINT_3X3_LOCAL.md)**.

Important: `reference_host.mjs` remains a **Map-only simulation**.
The new `sqlite_host.mjs` persists local SQLite data and shares atomic
transactions across processes using one local database file, but is also
**a reference implementation, NOT the live SENTRA host**. There is no
authenticated integration with the actual product's identity, workspace
policy or production database. The existing Canvas still never loads
`sentra-collab.js` automatically. Do not deploy or enable this sidecar
for users from these tests. The complete SQLite-enhanced suite was run
with Node.js 24.19.0 on Windows; the original base sidecar can remain
Node 22+, but `node:sqlite` availability is required for the new tests.

Security repair: Hocuspocus' intermediate `scratch.getStates()` cannot
represent remote null tombstones; the added `awareness_guard.mjs`
authenticates the raw frame and commits *only the connection owner's*
removal to actual server awareness. Foreign removals and client-ID
impersonation are rejected before broadcast.

## Sprint 3×3 Phase 2 — new slices (not enabled)

See **[SPRINT_3X3_PHASE2.md](./SPRINT_3X3_PHASE2.md)** for three additional
tested capabilities: authoritative-graph-only native SVG physical cables;
read-only SQLite ambiguous-commit reconciliation plus bounded precommit
quarantine/timeout; and opt-in client workspace lifecycle with cleanup of
providers, presence, display data and scoped tokens. This phase also restores
the previous negative WebSocket regression tests: quarantine blocks mutating
updates, **not** innocent peer no-op sync. None of these features auto-loads
or enables the SENTRA native Canvas; production integration remains blocked.

## Sprint 3x3 Phase 3 (opt-in laboratory)

See [SPRINT_3X3_PHASE3.md](./SPRINT_3X3_PHASE3.md) for the native SVG
keyboard/accessibility graph overlay, canonical verified read-only Yjs snapshot
preview, and per-process Hocuspocus quota/health controls. None of the new
modules mounts native Canvas, exposes a public health route or restores
ControlStore. Separate authoritative SENTRA host and production integration
remain required.
