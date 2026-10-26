# Native Canvas turn binding: design prerequisites

This is a design contract, not a completed implementation or an authorization
to promote an uncertain operation. Closing or restarting the current Canvas
broker still terminates its owned native model processes. No provider or tool
call may be repeated merely to populate this record.

## Current evidence and gap

`canvas_shell_queue` and `canvas_shell_provider_bindings` bind a Canvas
operation to its conversation, agent and WorkItem before the CLI is launched.
The CLI independently creates a random journal turn in `begin_turn`; the
protected journal messages do not carry that Canvas operation identity.
`provider_context` can associate a provider call with a turn and a supplied
scope, but it does not independently prove that a final assistant message is
the response to that exact operation. A matching prompt or latest assistant
message cannot supply this proof.

The host capsule in `prepare_provider_binding` is currently created for the
PostgreSQL backend only; SQLite receives no such capsule. A child-supplied
environment variable or raw turn identifier must therefore not become proof
of an authoritative result. The shell actor verifies a live process, scope,
operation, WorkItem and token, but its records and endpoint are volatile, and
that validation alone does not establish that a claimed journal message is
final, belongs to the turn, or survived a broker restart.

## Required contract before using a binding as proof

1. The host reserves one unpredictable turn identity for the admitted Canvas
   operation before starting the child, durably recording owner, principal,
   project, workspace, Space, conversation, Run, WorkItem, agent and operation.
   A conflicting reservation fails closed; a repeat only reads the same one.
2. The journal atomically associates that reserved identity with the newly
   created turn and original input, using a host-authenticated protocol with
   equivalent protections for SQLite and PostgreSQL. It must reject foreign,
   stale, duplicate or already consumed bindings. The child's raw claim is not
   an independent authority decision.
3. Each response records its journal sequence, turn identity, content hash,
   role, provenance and finality in the same transaction as the response and
   turn state. Intermediate model messages, tool directives, drafts, errors
   and interrupted turns cannot be promoted as final.
4. A host-side reconciliation checks the exact original protected request,
   reservation and final receipt, the current cancellation/revocation policy,
   Run and WorkItem authority, and independently records any task verification.
   It uses a conditional central transition so cancellation or a competing
   reconciliation cannot be overwritten. A missing, conflicting or ambiguous
   proof stays `UNCERTAIN`. Publication must be idempotent, scoped and must not
   call the provider or replay a tool.
5. Restart tests must interrupt before and after every durable boundary, verify
   exactly one physical submission, reject forged/foreign/stale identities and
   delayed old completions, and demonstrate no resend on repeated inspection.
   The installed Windows broker and physical model transport need separate
   qualification; these tests alone would not prove process continuity.

The existing receipt-only Web recovery and publication of already confirmed
`SUCCEEDED` native turns remain distinct from this proposed capability.
