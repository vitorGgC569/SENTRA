# SENTRA OS / CRIT-003 / Sprint 3x3 Phase 3 — local handoff

**[VALIDAÇÃO LOCAL REAL]** Three new isolated laboratory integrations, all opt-in. Nothing auto-starts or touches native.js, native.html, CSS, core, production identity or credentials.

## 1. Native SVG graph accessibility overlay

- Module: graph_a11y.mjs. API: projectAccessibleGraph(readGraph); mountGraphAccessibility({svg,readGraph,readViewport,onSelect,onZoom,reducedMotion}).
- The reader MUST be injected from the authoritative graph; Yjs and presence are NOT sources of executable node/link truth.
- Whitelist exactly id,label,x,y,width,height; frozen projection; 256 node cap, safe geometry, unique identifiers and bounded text. Run/Grant/Lease and other keys rejected.
- Explicit SVG groups, aria-label, aria-pressed, keyboard arrows/Home/End, Enter/Space visual-only selection, +/- bounded zoom request. Host remains sole authority for whether viewport requests are applied.
- Reduced-motion disables transitions. Refresh and dispose clean owned nodes/listeners. No DOM mutation on import; test is DOM/SVG fixture, not a native Canvas browser acceptance test.

## 2. Verified read-only Yjs snapshot exchange

- Module: verified_snapshot.mjs. exportVerifiedSnapshot({workspaceId,authorizeRead,loadSnapshot}) and inspectVerifiedSnapshot({bytes,workspaceId,minRevision,trustedSha256}).
- Canonical version 1 JSON envelope: format SENTRA_DISPLAY_ONLY; version, workspaceId, revision, payloadSha256 and payloadBase64. Whole-envelope SHA256 independent of payload hash.
- Import preview requires an independently **trusted** SHA256 from an authenticated host, exact canonical JSON bytes, workspace/revision floor, 1 MiB binary size and 1.4 MB envelope cap. Extra keys, stale/foreign workspaces, tampering and non-display roots rejected.
- The preview contains frozen plain layout/nodes/notes, restoreAllowed=false. It NEVER returns a mutable Y.Doc, overwrites SQLite, restores a ControlStore or grants privileges.
- SHA256 alone is NOT a signature/authentication guarantee: digest must come from a separate trusted control channel. Restore would require explicit approved host CAS and audit, not a CRDT import.
- Node tests include two real Hocuspocus WS peers, persisted SQLite export, server restart/disk reload, byte identical export and negative verification checks.

## 3. Local Hocuspocus quotas, backpressure, health

- Module local_admission.mjs integrated into server.mjs through opt-in quotas config. Configurable maxPerPrincipal (default 4), maxPerWorkspace (24), maxTotal (128), maxFramesPerWindow (120), windowMs (1000), maxFrameBytes (81920).
- Admission runs after AccessGate authentication and durable one-use nonce consumption. A quota-rejected credential is spent; next connect requires a new scoped grant.
- onDisconnect releases per-socket counters. Authenticated frames are metered; over-budget socket is rejected without closing innocent peers. destroy() clears local tracker/sessions/heartbeat.
- createCollabServer().localHealth() is only a direct local method, NOT an HTTP route. Safe numeric output: activeSessions, activeWorkspaces, accepted, rejected, framesRejected, admissionLatencyP95Ms, closed. No tokens, principal IDs or workspace names; max 256 latency samples.
- Real WS tests cover two peers/read-only, cross-workspace principal and workspace caps, one-use replay rejection, fresh-grant reconnect, heartbeat revocation, backpressure, and clean shutdown.
- Window and admission counts are process-local only, NOT multi-host quotas or network DDoS defense. Local test latency is not a production SLO.

## Activation gate / [PRODUÇÃO NÃO INTEGRADA]

Coordinator/native Canvas owner must manually opt in only after authoritative graph projection and real accessibility audits; verified digest delivered over authenticated host transport; real SENTRA identity + permissions; WSS/TLS/Origin; log redaction; cluster-aware admission, Hocuspocus document replication and recovery; browser E2E and load testing.
Nothing in this sprint alters the native Canvas UI, starts a listener, uses real credentials or replaces ControlStore.

## Verification commands (Windows)

npm test --prefix C:\Users\vitor\OneDrive\Desktop\SENTRA\sentra_collab
python -m pytest -q C:\Users\vitor\OneDrive\Desktop\SENTRA\tests\unit\test_sentra_collab_boundary.py -o cache_dir=C:\Users\vitor\OneDrive\Desktop\SENTRA\sentra_collab\.pytest_cache
