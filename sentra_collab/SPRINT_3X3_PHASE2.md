# SENTRA OS / CRIT-003 / Sprint 3x3 Phase 2

**[VALIDAÇÃO LOCAL REAL]** Only the optional `sentra_collab/` sidecar and
`sentra_canvas/static/sentra-collab.js` were changed. The current SENTRA
native Canvas is NOT connected, started or altered.

## 1. Physical native SVG cables — implemented

`physical_cables.mjs` is a standalone ES module. Pure
`authoritativeCables(readGraph)`, `bezierPath`,
`createCablePhysics`, `stepCable`, `ropePath` and optional
`mountCableLayer`. `readGraph` MUST come from the host's authoritative
read-only graph projection, never an untrusted collaborative Yjs document.
Endpoint coordinates are validated and frozen. Only `id,source,target` are
accepted for a connector; forbidden Run/Grant/Lease fields are rejected.
There are no side effects on import. SVG paths are non-interactive
(`pointer-events:none`) and cannot initiate executable links.

Solver bounds: at most 128 edges, 4–16 interpolated points per edge,
coordinate and sag bounds, clamped delta time, damped spring convergence
and pinned endpoints. Animation is ephemeral local-only (not persisted,
not sent via Yjs or awareness); requestAnimationFrame is injected by an
opt-in host. `reducedMotion:true` draws a static Bezier curve with no
animation. `dispose()` cancels RAF and removes owned SVG children.
Geometry/solver/unit SVG tests execute under Node with a controlled SVG
surface; a real Canvas browser rendering benchmark remains **unvalidated**.

Host handoff sketch (coordinator-owned; DO NOT auto-mount):

```js
import { mountCableLayer } from './physical_cables.mjs'
const layer = mountCableLayer({
  svg: /* reviewed dedicated SVG overlay, not current native.html */,
  readGraph: () => authoritativeSENTRAGraph.getApprovedConnectorEndpoints(),
  requestFrame: requestAnimationFrame,
  cancelFrame: cancelAnimationFrame,
  reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches
})
// On authoritative geometry changed, call layer.refresh(); on unmount layer.dispose().
```

This is a **native SVG** alternative to selected XYFlow Bezier and handle
geometry, not a React Flow migration or an execution graph editor.

## 2. SQLite crash/ambiguous recovery — implemented in local reference

`SQLiteHost` in `sqlite_host.mjs` continues to own the **one** local
database and its pre-existing four SQLite tables. No second store or replay
log is introduced. `reconcileCommit({workspaceId,expectedRevision,
candidateSnapshot})` only inspects the committed snapshot and returns
`committed` when exactly the next revision contains the same bytes,
`not-committed` when the expected revision is still current, and
`diverged` for all other situations. It **never writes** or retries an
uncertain operation; callers must only recover via authoritative reload.

`PrecommitGate` now marks a document quarantined on a host commit exception,
CAS denial or timeout (4-second default, bounded configurable
`commitTimeoutMs`). Mutating Yjs updates to that document remain blocked.
Harmless peer read/no-op handshake frames can finish, avoiding erroneous
disconnection of unrelated existing observers. Writer's failed update is
denied before live apply/broadcast, and the Hocuspocus connection closes.
`createCollabServer().inspectRecovery(workspaceId)` returns only
quarantine and revision metadata (never actual notes, tokens or secrets).
A fresh sidecar process reloads SQLite and reconciles committed bytes.
A late DB commit may still land after a timeout: quarantining prevents
subsequent updates but **cannot cancel a running host transaction**.
There is NO automatic replay, no authoritative rollback assumption.

**Deterministic evidence:** two actual Node child processes read the same
SQLite WAL and agree on a committed revision; nonce is consumed only once;
ambiguous commit followed by WS restart reopens the durable snapshot;
timeout injection rejects live apply; prior sprint checked CAS, rollback,
epoch and a killed worker mid-transaction.

**Not production HA:** one SQLite file shared on one trusted local filesystem
supports local atomic transactions; separate Hocuspocus in-memory Y.Docs
**DO NOT cross-process replicate**. Redis broker/distributed consensus,
multinode WSS, real host authentication, idempotency and crash fencing
are production blockers. **Never deploy multiple WS writers** from these
tests alone.

## 3. Workspace lifecycle adapter — real WebSocket tested

`sentra-collab.js` adds `SentraCollab.createWorkspaceSession()` as an
optional, explicit host entrypoint. Its lifecycle provides
`switchWorkspace(id)`, `revoke()`, `logout()`, `disconnect()`,
`status()`, read-only `snapshot()` and gated display/presence setters.
Switching workspace destroys the old Y.Doc/provider before starting
the next one; generation checks drop stale events AND stale async token
issuer results. The adapter clears all displayed state (`onChange(null)`)
and presence (`onPresence([])`) on switch, revocation or logout.
`onDisconnected` clears stale UI while a connection drops.

The **real WS test** has a writable peer and read-only peer, a local SQLite
host, two workspace switches, unique tokens per provider auth, display-only
geometry/notes and server-stamped presence. It verifies non-export of
Run/Grant/Lease methods, read-only denial, invalidated old session,
visibility isolation, cleanup of sockets on revocation and logout.

**Handoff to authorized Canvas owner:**
1. Add disabled-by-default opt-in to host-owned Canvas UI (not this scope).
2. Supply vetted Yjs + HocuspocusProvider bundles and a real session-bound
   `getToken({workspaceId})` issuer that returns a fresh one-use scoped
   grant on *every* authentication/reconnect. Never reuse browser account
   tokens as collab grants.
3. Feed `onChange({workspaceId,display})` only to already-approved
   authoritative nodes' viewport, notes and geometry. Do not create a
   node, run commands, grant leases or route execution via CRDT.
4. Feed `onPresence({workspaceId,peers})` into a purely visual overlay;
   rely only on stamped principal identities from sidecar. Clear overlays
   after revoke/logout/backend switch. Bind WSS, Origin, logout revocation,
   DLP, log redaction and rate limits before real users.
5. Keep the sidecar disabled until host identity, policy epochs, persistent
   multi-instance coordination and real browser tests are approved.

**[PRODUÇÃO NÃO INTEGRADA]** Real SENTRA auth, shared production DB,
multi-instance Yjs fanout, authenticated TLS, real Canvas mount, production
credentials, distributed recovery and browser UI end-to-end are absent.
None of the three features was automatically enabled.

## QA regression

The previous quarantine iteration disconnected innocent peers by rejecting
all sync frames after a failed commit. The regression was reproduced with
four failing existing cases (gate revoked writer, reference ambiguous ACK,
reference revoked epoch and SQLite write fault). Revised precommit logic
continues to reject every mutated candidate but permits *no-op* sync frames
after quarantine. The original negative tests remain intact and pass; no
change weakens nonce/epoch, CRDT allowlist or broadcast-before-commit checks.

Commands on the authorized Windows machine:

```powershell
npm test --prefix "C:\Users\vitor\OneDrive\Desktop\SENTRA\sentra_collab"
python -m pytest -q "C:\Users\vitor\OneDrive\Desktop\SENTRA\tests\unit\test_sentra_collab_boundary.py" -o cache_dir="C:\Users\vitor\OneDrive\Desktop\SENTRA\sentra_collab\.pytest_cache"
```
