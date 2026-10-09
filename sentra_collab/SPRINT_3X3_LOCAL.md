# SENTRA OS / CRIT-003 / Sprint 3x3 — local implementation evidence

> **Local validation only. Production NOT integrated. Nothing auto-starts.**
> Scope: `sentra_collab/`, the optional `sentra_canvas/static/sentra-collab.js`
> adapter, and `tests/unit/test_sentra_collab_*.py`. No native JS/HTML/CSS,
> core policy, secrets, terminals or other agent's work was modified.

## [VALIDAÇÃO LOCAL REAL] 1. Yjs — display-only state and opt-in adapter

Executable modules: `policy.mjs`, `precommit.mjs`, `server.mjs`,
`sentra_canvas/static/sentra-collab.js`. Two actual Hocuspocus WebSocket
providers connected via `ws://127.0.0.1:<ephemeral-port>` for:
- viewport `layout.viewport = {x,y,zoom}`; `nodes[id]` geometry
  `{x,y,width,height}`; `notes[id]` bounded plain text;
- peer-to-peer synchronization through server, independent concurrent
  additions to notes, convergence and persisted Yjs snapshots;
- reload from **disk-backed** SQLite after sidecar destroy/recreate;
- isolated workspaces and fresh scope-specific tokens on reconnect;
- negative tests rejecting `runs`, `operations`, `grants`, `leases`,
  unknown roots, invalid geometry, oversized updates and read-only writes.

The **actual optional adapter** is executed in a Node single-realm integration
test with real server, actual Yjs and HocuspocusProvider; verifies both
`onChange` and `onPresence` across two authenticated peers, strict read-only
writes and appropriate cleanup. It is **not injected into native.html**.
The `nodes` root represents geometry only: it must NEVER create an
executable SENTRA node or change the authoritative graph.

## [VALIDAÇÃO LOCAL REAL] 2. Hocuspocus — SQLite store/fencing

Executable module: `sqlite_host.mjs` (`SQLiteHost`, Node.js 24 tested).
It is a **local, opt-in example host**, NOT integrated with SENTRA's actual
identity/membership service. Requires a caller-provided absolute SQLite file
path; never starts a server or generates auth UI automatically.
It creates four tables (members, issued token hashes, consumed nonces,
versioned binary snapshots) with WAL, synchronous FULL and busy timeout.

Five host callback methods:
- `resolveGrant({token, workspaceId})` returns scoped principal, read/write
  permission, policy epoch and expiry using SHA-256 fingerprint lookup.
- `checkGrant({...context, action})` live-rechecks current membership epoch,
  expiry, workspace and write scope; fails closed.
- `consumeNonce({fingerprint,...})` uses a unique-key `INSERT OR IGNORE`
  guarded by live grant/epoch checks inside **BEGIN IMMEDIATE**; consumed
  fingerprints survive storage instance and Node child-process restart.
- `loadSnapshot({workspaceId})` loads a revision plus checked Yjs binary
  snapshot from disk, not an in-memory Map.
- `commitSnapshot({workspaceId,principalId,epoch,context,expectedRevision,
  snapshot})` rejects unauthorized or out-of-schema bytes, executes live
  epoch/permission check and expected-revision CAS inside the **same SQLite
  write transaction**, committing before `beforeSync` accepts/broadcasts.

Test isolation: every test creates/removes its **own disposable temporary
SQLite database**; no permanent host files, real accounts or credentials.
`test/sqlite_worker.mjs` runs in separate Node child processes with IPC
test inputs (no token in command-line/URLs). Deterministic tests prove:
- two **real processes** racing the same nonce: one succeeds, one denied;
- two **real processes** racing `expectedRevision=0`: exactly one snapshot
  committed; stale writer denied;
- revocation from process A prevents process B from committing an old epoch;
- fault **after SQLite write but before COMMIT** produces a rollback;
- actual child process exits abruptly with code 77 **inside** the transaction;
  reopening the database shows no phantom revision and accepts a fresh commit;
- injected storage error on the **real WebSocket precommit path** closes
  writer, prevents peer broadcast, then reopens/reconciles SQLite.

This proves local SQLite transaction behavior on one machine/local filesystem,
not remote HA, network-filesystem coordination, durable replicated sessions
or product-wide database guarantees. No real SENTRA grant service has been
connected. A **committed** snapshot followed by crash before Hocuspocus
broadcast may leave peers divergent until reloaded. Cross-process WS
fan-out, reconnect reconciliation while an older server stays live, durable
audit and distributed transaction ownership require separate work.

## [VALIDAÇÃO LOCAL REAL] 3. y-protocols — sanitized awareness

Executable modules: `policy.mjs` and **new**
`awareness_guard.mjs`, integrated into `server.mjs`.

The cloned Hocuspocus v4 `MessageReceiver.ts` decodes inbound awareness into
a **scratch Awareness**. A null tombstone disappears from
`scratch.getStates()`, so sanitizing only the high-level map is insufficient
to authenticate removals. We discovered this with a failing **real WS** test.
The server now pre-decodes the exact incoming aware frame in
`beforeHandleMessage` and allows an offline tombstone **only if** the
socket's earlier bound clientId matches, that socket still owns the ID,
and its presence is currently live. Legitimate removal is applied to the
server's awareness with the authenticated connection origin and broadcasts
normally. Malicious foreign null/clientID spoof frames fail closed and the
offending connection is evicted.

Non-null presence still passes `sanitizeAwareness`, which stamps
`user.id=authenticatedPrincipal`, allows only bounded `cursor` and
`selection`, strips `secret`, `token`, `grant`, `lease`,
and prevents cross-socket identity reassignment. WebSocket tests verify:
two peers, a read-only viewer sending safe presence, cross-workspace
isolation, forged admin/credentials excluded, legitimate owner tombstone
removing remote presence, malicious foreign tombstone denied, forged non-null
victim ID denied, innocent peer remains online.

**Fail-closed trade-off:** maximum one clientId per incoming awareness
frame; batched multi-ID awareness frames are denied. No client may use an
unauthenticated awareness frame to remove another peer.

## Browser handoff (not activated)

Only the coordinator owning the native Canvas may enable explicit opt-in:
1. Add a disabled-by-default feature flag and visible user consent control;
   do **not** auto-load the sidecar from `native.html` or `native.js`.
2. Bind the five host callbacks to authenticated SENTRA services, *not* to
   `SQLiteHost` (which has a fake grant issuer). Require fresh one-time
   short-lived workspace-specific grants from the real host.
3. Under a reviewed TLS/WSS ingress, strict Origin allowlist and real
   user session, bundle pinned Yjs + HocuspocusProvider and explicitly
   load `sentra-collab.js`; call
   `SentraCollab.connect({workspaceId,url,getToken,Y,HocuspocusProvider,
   onChange,onPresence,onError})`.
4. Pass received geometry only to already-authorized graph nodes; allow
   no executable graph edges, no Run/Operation/PolicyDecision/Grant/Lease,
   terminal contents or credentials into Yjs or awareness.
5. On backend/workspace switch, revoked grant, logout or feature disable,
   dispose the adapter and sockets; reissue token before reconnect.
   Redact logs, enforce rate limits, run real cross-machine TLS tests.

### Product blockers / truth boundary

**[PRODUÇÃO NÃO INTEGRADA]** Actual SENTRA identity membership, grant,
epoch and token issuance; TLS certificate/reverse proxy; WebSocket cross-
process broker and shared Hocuspocus Y.Doc replication; production admission
and rate limits; node runtime graph; full Canvas rendering; multi-machine UI
E2E; distributed or cloud DB; secret scanning/DLP; real recovery/HA runbooks.
The precommit and SQLite CAS hold locally on a single SQLite file, NOT across
independent database replicas or servers with separate CRDT states.
Do not enable multiple production WS writers or claim production-grade E2E.

### Validation commands

```powershell
npm test --prefix "C:\Users\vitor\OneDrive\Desktop\SENTRA\sentra_collab"
python -m pytest -q "C:\Users\vitor\OneDrive\Desktop\SENTRA\tests\unit\test_sentra_collab_boundary.py" -o cache_dir="C:\Users\vitor\OneDrive\Desktop\SENTRA\sentra_collab\.pytest_cache"
```

Node.js **24.19.0** and its built-in `node:sqlite` were verified on the
authorized Windows device. SQLite tests require a Node build exposing
`node:sqlite`/`DatabaseSync`. The optional original sidecar does not
require SQLite unless `sqlite_host.mjs` is explicitly selected.
