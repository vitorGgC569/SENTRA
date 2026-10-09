# Governance Control Plane

This document defines the product/control-plane layer that sits above SENTRA's
Durable Run/Operation kernel. The design borrows proven control-plane patterns
from agent-management systems while keeping SENTRA's existing authority model:
the Control Plane is authoritative, the Context Bus is knowledge, and model
consensus is never a release signal.

## Canonical hierarchy

```text
Workspace / Project
        |
       Goal
        |
     WorkItem
        |
        +-- assignment / checkout
        +-- ExecutionPolicy
        +-- RetryPolicy
        +-- BudgetPolicy
        |
       Run ---------------- Agent ---------------- Chat/Session
        |
    Operation
        |
 ExecutionWorkspace
        |
 WorkProduct / Evidence / CostEvent / Decision
```

A physical chat is transport. A logical Agent remains stable when ChatGPT,
Gemini, Codex or another provider conversation must be replaced. A WorkItem is
the durable unit of product work between a Goal and its executor Run.

## WorkItem authority

`GovernanceService` stores WorkItems in `governance.sqlite3`. A WorkItem
carries its objective, acceptance criteria, parent, blockers, dependencies,
assignee, required capabilities, target files, resource locks, side-effect
scope, execution policy, retry policy, budget, checkout Run, executor Run and
failure chain.

Checkout and execution ownership are separate. Compare-and-clear operations
only clear a lock owned by the expected Run. A stale Run may be reconciled, but
a live successor cannot be displaced by an older worker.

The legacy `DurableTaskLedger` remains the scheduler/OMA ledger. WorkItem is
the product/control-plane object; the two deliberately share the same
ControlPlaneStore boundary instead of pretending that scheduler tasks and
product work have identical semantics.

## Validation, review and approval are different

The promotion path is intentionally staged:

```text
implementation
     |
     v
deterministic Quality Gate
     | fail
     +-------> REPAIRING
     |
     | pass
     v
VALIDATING
     |
     v
agent review (optional)
     |
     v
human approval (optional)
     |
     v
READY_FOR_PROMOTION
```

`ExecutionPolicy.require_quality_gate` defaults to true. A WorkItem cannot
enter review, approval or promotion until a deterministic Quality Gate result
has been recorded. Returning to RUNNING or REPAIRING invalidates the previous
gate result, so changes requested by a reviewer require fresh validation before
resubmission.

The Quality Gate remains deterministic and separate from model consensus. The
governance layer records the validated result and evidence references; it does
not let a reviewer or approver replace deterministic checks.

## Recovery authority

Recovery is not synonymous with permission to continue modifying deliverables.
A WorkItem can enter one of these recovery classes:

```text
OBSERVE_ONLY
STATUS_REPAIR
RESOURCE_CLEANUP
CONVERSATION_REATTACH
SOURCE_CONTINUATION
SIDE_EFFECT_RETRY
```

Each class grants a bounded maximum capability set. The default recovery path
therefore cannot silently turn an observation or status-repair operation into
new source changes. Ambiguous side effects remain subject to Durable Core
UNCERTAIN/reconcile semantics.

## Retry policy

Retry state is durable and survives process/server restart. A RetryPolicy
contains maximum attempts, backoff, retryable error classes, same-agent/session
requirements, side-effect replay policy and the exhausted action.

Side-effect replay is fail-closed. `RECONCILE_FIRST` is the normal default;
`NEVER` blocks replay; `SAFE_ONLY` is only appropriate when the caller can
establish that replay is safe. Exhaustion can block, escalate, reconcile,
create follow-up work or require the operator.

## Activity, cost and budget

Governance writes a cross-cutting Activity stream that correlates actor,
Workspace, Goal, WorkItem, Run, Operation, Agent, action, outcome and evidence.

Cost events track three independent dimensions:

```text
actual_cost   = marginal billed cost observed by SENTRA
market_cost   = normalized/equivalent market cost
quota_usage   = provider/subscription quota consumption
```

They are never collapsed into one number. This prevents subscription usage from
appearing economically free merely because a particular call had no marginal
API charge.

BudgetPolicy supports instance, workspace, goal, WorkItem, agent and provider
scopes. Hard-stop policies are checked before WorkItem execution and before
cost recording. Warning policies report but do not grant authority. A hard-stop
never becomes advisory merely because an agent wants to continue.

## Versioned secrets

Secrets are metadata plus encrypted versions and bindings. Plaintext is
protected by the OS-backed secret mechanism and is resolved only for an
authorized runtime binding. Rotation creates a new version rather than
overwriting history. Access is recorded. Blueprints export requirements and
metadata, never plaintext values, DPAPI blobs, device tokens or session tokens.

## ExecutionWorkspace

ExecutionWorkspace is the durable logical wrapper around worktree, sandbox,
remote-device or future VM/cloud execution. Its lifecycle is:

```text
PROVISIONING -> READY -> LEASED -> DIRTY -> VALIDATING
                                      |          |
                                      |          v
                                      +----> PROMOTING -> PROMOTED

terminal alternatives: DISCARDED / FAILED
```

Physical ownership remains fenced by Durable leases. Promotion is never
implicit and must continue to respect the integration/Quality Gate boundary.

## Routines

A Routine is a producer of ordinary WorkItems, not a second scheduler model.
Schedule, webhook or API triggers create the same WorkItem used by manual work.
Active-run policy is one of `coalesce_if_active`, `skip_if_active` or
`always_enqueue`. Missed schedules are either skipped or replayed with a
bounded cap.

## Plugins

Third-party plugin workers execute out-of-process through the managed
ProcessService. Their manifests declare methods and required capabilities.
Effective capabilities are the intersection of declared, verified and
operator-narrowed grants.

Plugins cannot replace core authority: workspace authorization, secrets,
budgets, fencing, deterministic validation, promotion, audit and Control Plane
rules remain host-owned. UI code is not treated as a security sandbox.

## Skills, memory and context

These concepts remain separate:

```text
Memory  = evidence-backed lessons learned by SENTRA
Skill   = installable/versioned executable instruction or capability package
Context = knowledge for the current execution
Policy  = what a principal is allowed to do
```

The Context Bus remains non-authoritative even when many agents agree.

## Ordered distributed ingress

Remote Agent, Edge relay and plugin sources can use an ordered EventEnvelope
with `source_instance_id`, `source_epoch`, `source_seq`, event identity,
idempotency identity and payload hash. The receiver acknowledges
`highest_contiguous_source_seq`. Gaps are preserved instead of being silently
treated as delivered.

This is the replay/deduplication boundary for reconnecting distributed sources;
it complements leases/fencing rather than replacing them.

## Session checkpoints

A logical Chat may outlive one physical provider conversation. Formal session
checkpoints persist the resumable cursor and bounded provider/session state
against the logical `run_id + agent_id + chat_id`, together with
`source_instance_id + source_epoch + source_seq`.

Checkpoint replay is idempotent by source sequence and content hash. A reused
sequence with different content conflicts, and sequence numbers cannot move
backwards inside one source epoch. Obvious plaintext secret fields are rejected;
checkpoints must store secret references instead of credentials. Rebinding a
provider conversation therefore does not transfer authority and does not require
reconstructing session progress from chat text.

## Portable blueprints

Blueprint export/import scrubs machine-local authority. Exports may carry
agents, goals, WorkItems, routines, skills and policies, but never secret
values, local absolute paths, conversation IDs, machine IDs, session tokens or
device credentials. Import remaps local IDs and starts from a non-authoritative
state that must be validated before activation.

## Authorization

Authorization is resolved from Principal + Capability + Scope + Conditions.
A role may be a template that expands to grants; role state is never a second
authorization database. Local single-user mode can keep the simpler approved
workspace R/W/X model, while hosted/multi-user deployments can add grants
without changing the decision contract.

## Storage boundary

Desktop/single-node SENTRA uses `SQLiteControlPlaneStore` with WAL,
`synchronous=FULL`, foreign keys and bounded busy timeout. Governance,
authorization, budgets, ordered ingress, execution workspaces and scheduler
tasks consume the same store abstraction.

The abstraction deliberately fails closed for unknown backends. SENTRA does
not emulate PostgreSQL by blindly rewriting SQLite SQL. A hosted PostgreSQL
adapter must ship native schema/migrations and transaction/locking semantics
before it can be selected as authority.

## Non-goals

SENTRA does not encode a mandatory company/CEO org chart in the kernel. Company,
engineering team, research lab, game studio or audit team are templates over
Workspace/Goal/WorkItem/Agent.

SENTRA also does not make external chat systems authoritative. ChatGPT, Gemini,
Codex, Slack/Discord-style future adapters and browser tabs are transports and
presentation surfaces; durable identity, budgets, permissions, approvals,
artifacts and release authority stay in SENTRA.
