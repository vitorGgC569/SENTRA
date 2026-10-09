# SENTRA OS / CRIT-003 / Gate-5 — Reference host & Canvas opt-in plan

> **NOT ACTIVATED.** This is a design and test reference, not a production host,
> database driver, new login screen, or instruction to modify existing Canvas
> files. Ownership remains `sentra_collab/`, `sentra_canvas/static/sentra-collab.js`,
> and `tests/unit/test_sentra_collab_*.py`. No other files must be changed by CRIT-003.

## Reference callback contract

`reference_host.mjs` exports `ReferenceHost` solely for local, deterministic tests.
It holds ephemeral maps, a serialized mock transaction, membership with monotonic
grant epochs, SHA-256 token digests, a nonce ledger, and versioned Yjs snapshots.
Do not import or instantiate it in the SENTRA process. The sidecar's required
production boundary is an **application host** implementing the same callback
names from real authoritative services:

| Host callback | Input | Required production behavior |
|---|---|---|
| `resolveGrant` | `{token,workspaceId}` | Authenticate scoped short-lived one-time token; return `{workspaceId,principalId,permission,epoch,expiresAt}` or deny |
| `checkGrant` | grant context + `action:read/write` | Check live principal membership, workspace, epoch, expiry and write scope, every message; no JWT-only cached approval |
| `consumeNonce` | `{fingerprint,workspaceId,principalId,epoch,expiresAt}` | Atomically insert unique token fingerprint in **shared durable** store, return true only once, false on repeat |
| `loadSnapshot` | `{workspaceId}` | Return committed, versioned `{revision,snapshot}`; snapshot `Uint8Array` or null, revision safe non-negative integer |
| `commitSnapshot` | workspace, principal, epoch, context, expectedRevision, validated candidate bytes | In **one** DB transaction: recheck current epoch and write rights; compare stored revision; commit validated snapshot; return `{revision:expectedRevision+1}` |

A safe production transaction must linearize authorization and snapshot revision
together (e.g. serializable transaction plus row lock/CAS); separating the
permission query from the write introduces a TOCTOU race. Store revision,
scope, audit hash and nonce consumption server-side; never put those states in
Yjs. On a mismatch, reject rather than automatically retry stale writes.

### Controlled simulation (test-only, never deployment)

```js
import { ReferenceHost } from "./reference_host.mjs";
import { createCollabServer } from "./server.mjs";

const store = new ReferenceHost();           // in-memory deterministic fixture
store.setAccess("demoWS", "alice", "write");
const token = store.issueCredential("demoWS", "alice");
// Give token only to an explicitly named local test peer; do not log it.
const sidecar = createCollabServer({
  ...store.callbacks, allowedOrigins: [], port: 0, recheckMs: 500
});
// Tests explicitly call await sidecar.listen() and finally await sidecar.destroy().
// NO automatic startup, app registration, authentication page or network exposure.
```

`ReferenceHost.faultAfterCommitOnce("demoWS")` creates a **deterministic
ambiguous commit**: snapshot/revision are updated, then the acknowledgement is
lost. The pre-commit gate rejects that WebSocket update and does NOT broadcast
it; the durable fixture may nevertheless contain the change. On restart the
sidecar reloads committed state. This simulates ambiguity, not a distributed
database guarantee. `setAccess` and `revoke` bump the workspace/principal
epoch, so unused credentials issued in an old epoch also fail.

## Failure and security boundaries

- **Never enable real multi-writer deployment using the reference store**:
  memory vanishes with process death and local promises do not synchronize hosts.
  Production requires shared transaction/CAS, durable replay table, coherent
  snapshot loading after crashes, replay-aware reconnect and monitoring.
- **Ambiguous commit**: after a timeout, the host MUST distinguish committed
  from rejected using the authoritative revision, reconcile the document, and
  use idempotency/fencing. Retrying a different Yjs payload blindly can fork
  the view. A crash after commit but before `readUpdate` broadcasts leaves
  temporary peer divergence until re-sync.
- **Revocation**: check grant before WS use and in the **same atomic transaction**
  as the snapshot write. The heartbeat only eventually closes idle sockets;
  it is not the authorization boundary.
- **Identity / nonce**: tokens are short-lived and workspace-bound; never
  render tokens, nonce IDs, grants or audit details in the Canvas or awareness.
  Reject token reuse on the same or another sidecar, including after restart.
- **Only Yjs roots** `layout`, `nodes`, `notes`. No Run, Operation,
  PolicyDecision, Grant, Lease, account, credentials, CLI instructions, secret
  vault, terminal output or executable edges may be encoded into the CRDT.
  Server-side strict schema, length limits and read-only checks remain mandatory.
- **Awareness** is a separate ephemeral channel, not a source of claims. Only
  server-stamped principal ID and bounded cursor/selection survive; arbitrary
  user fields such as tokens or grants are discarded.
- **Yjs threat model** explicitly warns that an authenticated write peer can
  still inject destructive CRDT history; schema projection is not a general
  sandbox or secure conflict resolver. Only trusted writers receive write access;
  untrusted suggestions must use separate fork/review. Plaintext user notes
  are not a secret vault — reject secrets upstream with an approved DLP policy.
- **Transport**: loopback listener only; browser access through reviewed WSS
  reverse proxy, strict Origin policy plus real auth, CSRF protection, rate
  limits, binary parser hardening and log redaction. Missing Origin must not
  confer any privileges.

## Canvas opt-in mounting — coordinator-owned, not implemented here

1. In the existing Canvas host, introduce a **disabled-by-default capability
   flag** and a user-controlled *Collaboration* control. Keep existing
   `native.js`, `native.html` and CSS unchanged in CRIT-003 scope.
2. Have the authenticated authoritative host issue a new ephemeral scoped
   credential for each explicit connection/reconnection. A token endpoint must
   require the user's existing authenticated session; it must not open a new
   login form nor expose credentials to document, telemetry or URLs.
3. Bundle audited/pinned Yjs and HocuspocusProvider for the optional view and
   explicitly load the existing new `sentra-collab.js` adapter only after
   review. Connect with `SentraCollab.connect({workspaceId,url,getToken,Y,
   HocuspocusProvider,onChange,onPresence,onError})`. Treat `onChange` as a
   display-only projection into authorized node positions/viewport/notes.
4. Fetch **which nodes and links exist**, their identities and execution
   statuses only from the authoritative SENTRA graph; never create, grant,
   execute or delete a runtime node in response to CRDT content.
5. On workspace switch, logout, policy change, unmount or backend replacement:
   dispose/detach all listeners, call `disconnect()`, wipe local presence,
   and acquire a **fresh** workspace-bound token. Never rescope an existing
   provider or reuse a credential.
6. Validate two physical peers, backend restart, race injection, Origin/WSS,
   revocation, replay across multiple instances, tenant isolation, impaired
   networks and accessibility **before** any product enablement.

All those host/Canvas changes are **blocked on coordinator ownership**.
This slice does not ship a React app, enable Hocuspocus, register a startup
task, or expose a login to users.


## Minimalist layout and cables with visual physics (design-only)

**Intended visual language**: a restrained native-feeling dark graphite
workbench, substantial negative space, crisp typography and subtle glass
layers with low-contrast 1px strokes. One calm canvas with compact floating
controls; status appears on demand rather than duplicated in every panel.
Keep affordances obvious: connected, waiting, paused and denied must differ
by icon/label and accessible text, not color or animation alone. A low-contrast
fractal grid can live behind the *authorized graph* and must not encode any
private data. Nodes are compact resizable cards with focused terminal details
only after explicit inspection, not always-visible walls of text.

**Cables/edges**: obtain the graph's approved source/target handles from the
SENTRA host. Render lightweight SVG paths layered beneath nodes, using
XYFlow-style `getBezierPath` semantics: start/end at connector handles,
curvature determined by orientation/distance, independent invisible hit path
for keyboard/mouse targeting and small labels on demand. Do not mirror React
Flow's entire React graph; its `BaseEdge` and `BezierEdge` are *design
references* for a small native SVG path overlay.

**Physics**: treat the rope as view state, never as execution state. On a node
drag, sample the moving endpoints and update 8–16 interpolated cable points
with a fixed-time-step damped spring/Verlet solver:

- `velocity += (target - point) * stiffness * dt; velocity *= damping`;
  `point += velocity * dt` (or Verlet using previous positions).
- Pin first/last points to connection anchors; enforce maximum stretch and
  bounded displacement, then fit a smooth cubic path through the sampled
  points. Use 60 FPS only while moving, then stop animating when settled.
- Keep `position`, drag targets, velocities, rope samples, pointer events and
  per-frame animation **out of Yjs**. Sync at most coalesced validated node
  positions/viewport to peers; peers locally recompute the same style.
- Prefer compositor-friendly SVG/Canvas with `requestAnimationFrame`;
  cap edges and visual effects, drop subdivisions at low zoom, and stop on
  hidden tabs. Respect `prefers-reduced-motion` with static curves; provide
  nonanimated keyboard equivalents and perceptible focus indicators.
- Cable *creation, deletion and route permission* must remain backed by the
  host's authoritative graph/PolicyDecision. A rendered connection cannot
  invoke a Run, Grant, Lease, command or terminal action.

### Incorporation comparison (actual cloned source reviewed)

| Source reviewed | Adopt / emulate | Explicitly DO NOT adopt |
|---|---|---|
| `third_party/yjs` (`THREAT_MODEL.md`, root map APIs) | Display-only CRDT maps, binary update snapshots, bounded state | Yjs as access control, shared runtime commands, untrusted editor rights; Yjs notes as secret storage |
| `third_party/y-protocols` (`PROTOCOL.md`) | SyncStep1/SyncStep2/Update semantics, presence lifecycle/tombstone handling | Trust client-supplied awareness identity, or promote CRDT presence into authorization |
| `third_party/hocuspocus` (`MessageReceiver.ts`, Server hooks) | Optional socket transport, `beforeSync` admission, sanitized scratch awareness and graceful cleanup | Debounced `onStoreDocument` as a transaction, external listener without WSS/auth, indiscriminate stateless broadcasts |
| `third_party/xyflow` (`BezierEdge.tsx`, `BaseEdge.tsx`) | SVG Bezier geometry, source/target anchors, invisible interaction path, focused edge labels | React Flow-wide rewrite of SENTRA native Canvas, or Yjs ownership of executable links |
| `third_party/openhands` (`specs/canvas-extensions.md`, `canvas-extensions-runtime.tsx`) | Capability-gated opt-in, explicit enable/disable, lifecycle disposers, backend switch cleanup | Import full React frontend; assume same-realm extensions are sandboxes; grant ambient browser credentials to untrusted plugins |

OpenHands' own extension specification explicitly notes that same-realm
extensions are **trusted code**, not sandboxed. An isolated optional Canvas
adapter must therefore be reviewed/pinned and explicitly loaded; UI isolation
is not equivalent to a security boundary.

**Status:** Visual physics and application opt-in are architecture proposals
only, not attached to the running Canvas, and not validated in a browser
integration test. The executable Gate-5 deliverable is the isolated
reference host + real-loopback security tests.
