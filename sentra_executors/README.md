# SENTRA Machine Executors — bounded integration (EXEC-001)

This package is an **opt-in adapter layer**, not a Windows sandbox, a remote
desktop gateway, or a replacement for the SENTRA control plane.

## Integration contract

- Register a Machine with typed Capability entries in the real
  sentra_runtime.executor.ExecutorRegistry.
- Inject the **same trusted policy callback**, producing a real
  sentra_runtime.contracts.PolicyDecision, into both registry and adapter.
  An arbitrary object with an allowed attribute does not confer authorization.
- The v1 registry denies non-empty PolicyDecision.constraints even if
  this adapter can verify them. Do **not** bypass the registry to run a
  constrained grant; coordinate core enhancement in a separate milestone.
- Unknown machine, principal, capability, PID, HWND, action, UIA selector,
  Daytona sandbox or non-allowlisted command denies before dispatch.
- Reuse of an operation ID with changed validated intent or an idempotency
  key already consumed is rejected. Deduplication is only **process-local**:
  distributed retries require SENTRA durable journals, leases and fencing.
- Timeout, cancellation or post-dispatch policy revocation is UNCERTAIN,
  without automatic replay. A backend thread can continue after timeout
  or cancellation; no rollback is asserted.
- cleanup() follows the core protocol returning None and never kills a
  user process or deletes a remote sandbox.

## Windows UIA security limitations

WindowsUIAExecutor uses pywinauto UIA, attached to a pre-registered process,
window handle, exact title, action and selector. It cannot freely launch
programs, type arbitrary keys, elevate, or execute uncontrolled mouse actions.

**PID/HWND checks are not OS isolation**. Accessibility providers may expose
other desktop surfaces, PIDs and window handles may be reused, and code may
run with the privilege level of the host user. External actions can race with
revocation. Real untrusted automation requires a dedicated low-privilege
Windows user or disposable VM plus OS-enforced controls. This package does
not implement hcsshim/Windows containers, gVisor, or Guacamole.

## Daytona limitations

DaytonaExecutor loads the SDK only when used, and targets an *existing*
sandbox by exact ID. It demands public=False, network_block_all=True, and
state=started before an allowlisted exact command. Evidence contains only
exit code, output length and output SHA-256, not logs or credentials.

SDK properties are not independent remote attestation. A separate opt-in
DaytonaSandboxLifecycle now supports explicit approval-controlled provision,
discover, status and idempotent cleanup of **manager-created** sandboxes;
it never substitutes for durable ControlStore leases or admin authorization.
No general snapshot administration, credential management, public service
or unapproved deletion is implemented. The repository clone is not a running
Daytona server or proof of an existing sandbox. No fallback to host shell.

## Tests and opt-in UIA lab

Run in the repository root:

    python -B -m pytest -p no:cacheprovider -q tests/unit/test_sentra_executors_windows.py tests/unit/test_sentra_executors_daytona.py tests/unit/test_sentra_executors_registry.py tests/unit/test_sentra_executors_uia_lab.py

The registry tests use **real** SENTRA contracts, authorization decisions
and ExecutorRegistry with mocked backend side effects. No Daytona API E2E
is claimed from a fake SDK client.

A read-only Windows UIA integration test is available only with explicit
opt-in, an operator-confirmed isolated test VM and pywinauto installed there:

    $env:SENTRA_UIA_LAB_RUN='1'
    $env:SENTRA_UIA_LAB_VM_CONFIRMED='1'
    python -m pytest -q tests/unit/test_sentra_executors_uia_lab.py

The flag expresses operator confirmation, NOT independent proof of OS
isolation. Never run the test on a personal desktop without a lab VM.

That test launches its own Tk process, verifies PID/window ownership,
reads its own window title over UIA and terminates the lab process.
It does not attach to existing user applications; without opt-in it skips.

GATE-5: tests/unit/test_sentra_executors_gate3.py exercises actual
ExecutorRegistry + PolicyDecision for **both** adapters under policy failures,
revocations, concurrent submissions, and uncertain timeouts. The previously
xfail test for mutated OperationRequest.arguments is now an ordinary **passing
regression test**, after the coordinator added a canonical fingerprint and
request snapshot in sentra_runtime/executor.py. No core file was edited by
EXEC-001.

Discovery is now explicit and no-I/O: sentra_executors/discovery.py declares
Machine/Capability using configured Windows or Daytona bindings, then registers
the adapter via the actual ExecutorRegistry. The optional
plan_read_only_tk_lab() only allows read_window_title on a named test window.
It does NOT launch or enumerate applications; the guarded opt-in UIA test
creates and tears down its own Tk child when prerequisites exist.

All tests: python -B -m pytest -p no:cacheprovider -q
tests/unit/test_sentra_executors_*.py (in PowerShell, pass filenames from
Get-ChildItem instead of a wildcard to pytest).

Full source/code comparison, integration priorities, OS isolation requirements,
and explicit E2E gaps: sentra_executors/SOURCE_REUSE_MATRIX_GATE5.md.
Canvas/ControlStore handoff: sentra_executors/INTEGRATION_HANDOFF_GATE3.md.


## Sprint 3x3 (2026-10-09) — exactly three opt-in slices

1. `lab_discovery.py`: exact lab title + PID/HWND discovery, WindowsUIA
   read-only via real registry; optional isolated-VM Tk E2E.
2. `daytona_lifecycle.py`: policy + independent approval-gated snapshot
   provisioning, existing-ID discovery/status, manager-owned cleanup,
   with `DaytonaExecutor` allowlisted commands under the real registry.
3. `uia_workflow.py`: selected UFO/RPA-style read-only multi-step workflow,
   stable per-step idempotency, fresh policy and hashed trace evidence.

Detailed acceptance evidence, source paths, upstream license notes, and
the [REAL E2E] vs [FIXTURE E2E] boundaries:
`sentra_executors/SPRINT3X3_HANDOFF.md`.


## Sprint 3x3 Phase 2 (2026-10-09)

Three *new* opt-in capabilities:
- `browser_lab.py`: exact numeric-loopback HTTP read, Playwright
  Chromium in disposable profile, no personal Edge/cookie attach;
  actual browser requires approved isolated VM.
- `remote_readonly.py`: authenticated bidirectional HMAC TCP
  loopback session, read-only status/frame digest, no remote input.
- `windows_identity.py`: Windows process creation-time,
  executable SHA256, PID/HWND, lease-fencing proof at read time;
  no AppContainer/Hyper-V guarantee.

See `SPRINT3X3_PHASE2_HANDOFF.md` for upstream/licensing matrix,
negative tests, actual vs fixture E2E, exact test counts and P0/P1.


## Sprint 3x3 Phase 3 — gVisor, WinHCS, Tk benchmark

Three **new** optional executor-scope modules:
- `gvisor_runsc.py`: strict OCI config/rootfs path checks and
  pinned runsc executable, expiring lease/fence and manager-owned cleanup.
  Linux real runsc is disabled without independent runner approval.
- `winhcs_boundary.py`: typed WinHCS provider interface for
  allowlisted container status/terminate; create denied by default,
  cannot import/use HCS automatically.
- `tk_benchmark.py`: own Tk read-only baseline versioned
  `sentra-tk-lab-v1`, idempotent operations, deterministic timing,
  evidence hashes, denial/success/UNCERTAIN counters.

Details, upstream license comparison, P0/P1 and exact acceptance test
results: `sentra_executors/SPRINT3X3_PHASE3_HANDOFF.md`.


## Central ControlPlane / Canvas integration gate (2026-10-09)

`central_integration.py::CentralExecutorFactory` reuses the actual
`ControlPlaneService`, `BoundWorkItemPolicy`,
`AuthorizationService`, `GovernanceService`, `ExecutorRegistry`
and `DurableOperationGate`, with explicit Machine/Capability discovery
for existing Windows UIA/Daytona (inventory-only) and a
BrowserLab read-only dispatch path.

**No auto-wiring to Canvas:** coordinator still owns registering this
factory with Canvas/TaskRuntime. **No production dispatch:** legacy
`DurableRunService.create_operation` lacks the required atomic full
request fingerprint+fencing, so the factory fails closed without an
external `DurableIntentAuthority` provided by the coordinator.
A *test-only* SQLite authority and a disposable real Python loopback
HTTP subprocess prove Run -> WorkItem -> grant -> reserved Operation ->
ExecutorRegistry -> BrowserLab response. No production ledger is
introduced, and in-process context guards are not an OS security
boundary. Evidence, exact tests, and host handoff:
`sentra_executors/CENTRAL_INTEGRATION_HANDOFF.md`.
