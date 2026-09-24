# Durable execution and recovery

SENTRA treats a connector timeout as a loss of observation, not as proof that work stopped. Long-running work is modeled independently of any single chat or MCP request.

## Identity model

The runtime keeps these identities separate:

- **Run**: the durable mission/program instance.
- **Agent**: a logical worker assigned to a role/task.
- **Chat**: a replaceable provider conversation bound to an Agent.
- **Operation**: one side-effecting or long-running action.
- **Resource**: an observed process, session, worker or other runtime object.
- **Artifact**: immutable evidence/result metadata with SHA-256.
- **Lease**: temporary ownership of a resource plus a fencing token.

Changing a conversation ID does not change the Agent or Run. Rebinding a chat is recorded as an event and preserves role/task history.

## Durable state

State lives below the configured SENTRA state directory in durable/durable.sqlite3 plus runs/<run_id>/events.jsonl and state.json.

SQLite is the materialized durable store. events.jsonl is append-only evidence, and state.json is the current projection useful for handoff/inspection.

Run records include desired state, observed state, capability snapshot, used capabilities, operations, agents, chats, resources, processes, progress, artifacts and leases. `processes[]` and `progress[]` are direct projections of the underlying process resources and operation state, so a resumed chat does not need to reconstruct them manually.

## Idempotent operations

Every side effect that can outlive a request should have an operation_id and an idempotency key. sentra_start_process accepts run_id, idempotency_key, cleanup_policy and readiness_probe.

Repository Jobs (TEST/LINT/TYPECHECK/BUILD/BENCH) are correlated automatically to a Durable Run/Operation and expose run_id/operation_id alongside the legacy job_id. Research uses its research run_id as the Universal Run ID and exposes a durable operation_id for the long-running execution. Persistent Search keeps its legacy search_id but also carries run_id/operation_id/idempotency_key, emits bounded progress events, and becomes UNCERTAIN rather than being replayed when a restart interrupts an active scan. Their wait calls report OPERATION_STILL_RUNNING instead of implying that a connector timeout aborted the underlying work.

Repeating the same idempotency key does not blindly spawn another process/job/research execution. SENTRA returns the known execution/operation when possible. If the original effect may have started but cannot be proven, the operation becomes UNCERTAIN and is not automatically replayed.

## Progress and readiness

Process creation is not considered product readiness. Optional readiness probes can require one or more observable signals:

- loopback TCP port listening;
- loopback HTTP endpoint responding;
- a bounded stdout/stderr marker.

Progress is persisted as events. Readiness can advance through PROCESS_STARTED, PORT_LISTENING, TRANSPORT_CONNECTED and PRODUCT_READY.

sentra_operation(action=wait) waits only for the requested connector-friendly window. If it times out while work continues, the response carries OPERATION_STILL_RUNNING; the operation remains queryable through status.

## Reconciliation

sentra_run(action=reconcile) compares desired and observed state. It uses multiple evidence sources instead of a single timeout: real process PID liveness, resource state, recent artifacts, fresh leases, Agent heartbeat and Chat heartbeat.

If evidence still shows progress, reconciliation takes no destructive action. If an operation is stale and has no supporting evidence, it is marked UNCERTAIN, linked chats/agents are marked for recovery where appropriate, and the Run enters RECOVERING. Automatic replay is deliberately disabled for ambiguous side effects.

## Leases and fencing

A lease returns a monotonically increasing fencing_token. A writer must present the current token when updating protected state. A stale generation is rejected with STALE_FENCE, preventing an old/zombie worker from overwriting state after recovery transferred ownership.

## Contract negotiation

The live MCP server exposes a canonical tool-schema hash, server build identity and capability manifest. sentra_session_open includes the live contract so clients can detect a cached/outdated schema.

Clients can use sentra_run(action=contract_manifest) and sentra_run(action=contract_negotiate) before depending on optional behavior.

Important semantic errors include SCHEMA_MISMATCH, PROTOCOL_MISMATCH, CAPABILITY_MISMATCH, CAPABILITY_MISSING, PLUGIN_STALE, REMOTE_AGENT_STALE, SESSION_WRONG_PLACE, OPERATION_STILL_RUNNING, STALE_FENCE and STATE_CONFLICT. The current stable list is also published in the live capability contract.

The Edge bridge also publishes extension version/build identity and source hashes. A live worker with a mismatched or missing required identity fails closed rather than being treated as compatible.

Remote Agents use the same principle. Every heartbeat publishes a nested live SENTRA manifest with server version, protocol/capability versions, build ID, source/executable identity, schema hash, tool count and tool inventory. Gateway-submitted jobs persist `contract_required=1`: the gateway rejects submission when the advertised contract is incompatible, and the RemoteStore refuses to grant a lease if the Agent becomes stale after enqueue. Pairing/heartbeat itself remains available for diagnosis, so a stale device is inspectable without being allowed to execute side effects.

## Process ownership and cleanup

sentra_operation(action=process_tree) shows managed process roots and discovered children together with Run/Operation ownership, readiness, command, workspace and cleanup policy.

Cleanup policies are explicit:

- terminate_on_run_end — default for Run-owned work;
- preserve — leave the process running;
- manual — operator-controlled cleanup.

A terminal Run transition invokes Run-scoped cleanup for processes using the default policy.

## Binary and image evidence

Binary files no longer need to be forced through text. sentra_artifact(action=read_binary) reads a registered artifact by opaque artifact_id and returns a bounded base64 page with MIME type, total bytes, next offset and SHA-256. Registered Run artifacts use an unpredictable 128-bit capability ID exposed through sentra://artifact/<artifact_id>; SHA-256 is stored separately and verified before reading.

List-like inspection APIs expose a common items/page envelope with offset, limit, returned, total and next_offset. Legacy aliases such as entries/results remain where needed for compatibility.

## Browser fallback policy

For ChatGPT, SENTRA remains principal-Edge-only. A stale plugin, wrong target, missing capability or unavailable controller is a semantic failure. SENTRA does not silently launch another browser/profile.

For other browser paths, invasive/native fallback must be explicitly opted into with allow_invasive_fallback=true; the default is fail-closed.

## Operator recovery

A new conversation can recover a Run without reconstructing context from chat history:

    sentra.exe run resume <run_id>
    sentra.exe run status <run_id>
    sentra.exe run events <run_id>
    sentra.exe run reconcile <run_id>

The same operations are available over the compact MCP sentra_run surface.

For OMA conversation hygiene, main.py --clear removes managed remote chats after a run (or for an existing --job-id). --chat-project binds newly created logical chats to a supplied ChatGPT Project and managed chats receive stable titles such as [SENTRA] <run_id> - <role>.

## Safety invariants

1. A timeout is never interpreted as an abort.
2. Ambiguous side effects are never silently replayed.
3. Old fencing generations cannot commit new state.
4. Physical chat replacement cannot erase Agent/Run identity.
5. A plugin/schema mismatch is discovered before relying on the mismatched capability.
6. Readiness requires an observable signal, not merely a spawned PID.
7. Invasive fallback is explicit and never silent.
8. Durable recovery does not bypass deterministic quality, workspace or promotion policy.
