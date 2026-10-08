# SENTRA unified completion evidence

This checklist tracks the full active implementation goal. Passing a component
check does not establish that the complete product or installer is ready.

## Verified baseline

- The existing Codex SENTRA Commander connection responds to `sentra_health`
  and can inspect the SENTRA repository. Its active endpoint now advertises 115
  tools at the Full baseline and now 116 with native Canvas, all six surfaces
  under Full/Computer. This was rechecked through the
  existing connector; no additional key or tunnel was created.
- The source Canvas/graph/integrations/CLI/build baseline passed 64 tests before
  this iteration. These results precede the new persistence changes.
- Previous live OpenAI enrollment evidence is recorded outside the repository
  in the task's `live_validation_report.json`: protected runtime key, real
  authenticated tunnel, Full/Computer profile and 115 local tools. ChatGPT
  plugin registration remained blocked by OpenAI workspace association.
- The workspace ID from the user's authenticated session is the reference for
  further association checks. This does not turn OpenAI's previous rejection
  into evidence that registration succeeded.

## Current implementation changes

- Canvas schema v2 stores bounded terminal transcripts in OS protected chunks,
  with stable absolute cursors and explicit truncation. SQLite contains
  ciphertext; live terminal data remains in process memory.
- A restarted backend exposes persisted output with `recoverable=false`, and
  marks owned processes interrupted and owned in-flight tasks uncertain.
  Recovery never changes another principal's resources or repeats a task.
- Persistence failures are visible in terminal status and audit events while
  the reader continues draining ConPTY. A failed suffix is never claimed durable.
- Agents launched with SENTRA CLI have the correct terminal adapter type, so
  supported agent handoffs can address them.
- Canvas is included in Windows payload/Setup/MSI requirements and the payload
  build. Its frozen entrypoint uses the installed runtime's recorded state
  directory rather than whichever working directory launched the application.
- The native window now attaches to a hidden persistent broker. Protected
  endpoint discovery checks the runtime identity and PID with an authenticated
  loopback request; concurrent launches reuse the same owner. Closing a window
  detaches it without stopping the broker. Explicit shutdown is a separate
  authenticated action. Actual broker crash recovery was exercised with an
  isolated Windows process and real ConPTY output.

## Validation from this iteration

- 149 regression tests passed covering Canvas, CLI, build/release, browser
  enrollment, installer consent and secure key import. The negative permission
  fixture now declares its already-configured tunnel, so it tests the missing
  All permission control rather than waiting for a duplicate fixture tunnel ID.
- 38 Canvas lifecycle/UI checks passed after the broker changes, including real
  hidden process startup, concurrent client attachment, actual broker process
  termination/recovery, protected transcripts and both real Canvas DOM surfaces
  in Edge. These checks overlap the regression suite and are not additive.
- A fresh Canvas executable was built and tested in an isolated native Windows
  installation directory. It started its actual authenticated broker and real
  CMD/ConPTY terminal. Closing the native window with Windows Alt+F4 and reopening
  it preserved both the broker and terminal PIDs; the terminal's marker appeared
  in the native UI. The owned QA broker was shut down afterwards. Metadata and
  SHA-256 are recorded in the task's `canvas-native-qa/validation.json`.
  This evidence concerns Canvas, not the entire Setup payload.
- Native compiled QA uncovered excessive pywebview bridge reflection through
  a public Window attribute. The bridge now retains that object privately and
  exposes only minimize/maximize/close; the corrected binary was rebuilt.
  The initial binary's window-control failures do not count as a passing native
  close/reopen test. The corrected binary passed native close/reopen with
  Windows Alt+F4. Custom titlebar button behavior still needs final review.
  A separate regression confirms that a real existing
  workspace loads correctly in the actual Canvas DOM.

## Required remaining acceptance work

### Windows registration and complete Setup candidate (2026-10-08)

- Setup now creates real per-user Start Menu Desktop/Canvas links and a Desktop
  launcher. Shortcut cleanup checks the linked executable before removing it.
  Registry cleanup similarly checks startup/protocol/install ownership; PATH
  removal remains scoped to the requested installation. Registered uninstall
  commands name their actual installation and preserve configuration/history.
- Related installer/desktop/release tests passed 84 checks. Actual WScript links
  were tested with non-ASCII folders and quoted installation paths. A real HKCU
  test preserved another installation's startup/protocol/uninstall/PATH entries,
  removed owned entries and restored the user's exact original registration.
  Evidence: task artifacts, `windows-registration-qa/validation.json`.
- A full build completed all 13 payload executables, Web Models and a 1.72 GB
  Setup. Its actual registered install and repair passed with Full/Computer,
  116 tools/all six surfaces, protected CLI history and real Windows shortcuts.
  Original registration was restored after acceptance. Evidence:
  `final-installer-qa/validation.json`. This candidate predates the cold-start
  correction below and is not final release acceptance.
- Inspection found that frozen MCP would cold-start itself with Canvas flags;
  prior compiled component acceptance had prestarted Canvas and did not cover
  this case. broker_command now selects the installed sibling sentra-canvas.exe
  and fails explicitly when it is missing. Eleven related broker/native/shortcut
  checks passed. A corrected full build is running, and its registered Setup
  acceptance explicitly tests MCP-driven Canvas startup while Canvas is closed.
- The user-requested independent read-only Codex feedback subagent is running
  against the integrated source. Findings, installed real-provider/lifecycle
  acceptance and final requirement audit remain part of the gauntlet.

### Compiled update, rollback and uninstall acceptance (2026-10-08)

- Extended Win32 paths are now shared by Setup and the external update helper.
  Update and rollback stop only processes within the selected installation's
  directory boundary before replacing files. Update preserves installation ID;
  rollback rejects metadata belonging to a different installation and uses a
  unique replacement backup name. A failed-update regression restored actual
  deep files and the original marker. The related final suite passed 80 checks.
- The newly compiled helper updated the existing isolated installation while
  its actual compiled MCP was running. Update exited zero, preserved installation
  identity and protected CLI history, and removed a previous-release sentinel.
  Actual rollback exited zero, restored that sentinel and preserved history.
  Evidence: task artifact directory, `full-installer-qa/lifecycle-validation.json`.
- That first uninstall scheduled the older helper restored by rollback. Its
  exit zero was not proof of cleanup: the program directory remained. The newer
  Setup now selects its own bundled helper for uninstall. After rebuilding, a
  real retry removed the actual long program tree and preserved protected
  conversation history. Evidence: `full-installer-qa/uninstall-recovery-validation.json`.
  The earlier incomplete cleanup remains recorded as a failed acceptance check.
- These runs disabled system registration and desktop launch and made no model
  requests, new API keys or new tunnels. Native Canvas/gateway calls from the
  installed product, system integration and the complete final review remain
  separate required acceptance work.

### Full policy reconciliation and active endpoint (2026-10-08)

- MCP health now reports the effective registered tool surfaces, process mode
  and tool allowlist. Local readiness compares that policy with ProductSettings;
  same-instance identity alone no longer establishes Full readiness. Owned
  processes can be restarted to reconcile a profile change; a different instance
  is never stopped. A real Developer-to-Full process transition passed.
- The existing active source endpoint at 127.0.0.1:8000 was upgraded to
  Full/Computer with all 115 tools. The existing Codex Commander connector
  responded afterwards with all six surfaces. An actual tool read outside the
  repository, in an owned public QA directory, confirmed the computer grant.
  Protected internal directories remain governed by the path policy. No key or
  tunnel was created or rotated. Evidence: task artifact directory,
  `active-full-runtime/validation.json`. This concerns the active endpoint;
  it does not claim that AppData's older installation binaries were updated.
- The Windows build now has a tracked Canvas phase and records source/output
  hashes, rejecting a source change during compilation. A full build of the
  Electron integration, Python payload and Setup is underway in an isolated
  LOCALAPPDATA build directory. An initial legacy-PowerShell module failure was
  corrected by preferring PowerShell 7; it is not counted as a passing build.

### Current compiled component validation (2026-10-08)

- The complete Electron/Python/Setup build subsequently passed in 1168 seconds.
  Actual silent Setup installation in an isolated long Windows directory found
  Win32 path-length failures copying deep npm files. The copy now uses extended
  paths without changing global OS policy. Silent failures return a nonzero code
  and persist a redacted diagnostic instead of opening a PyInstaller error dialog.
  Two direct regression checks and the related 72-check suite passed.
- The corrected compiled Setup was rebuilt and then passed actual install and
  repair runs, both exit code zero, in that same long directory. Fresh settings
  were Full/Computer; the installed MCP advertised all six surfaces and 115 tools.
  The installed CLI wrote a real file and protected conversation history; repair
  preserved both the selected profile and the conversation. Evidence:
  `full-installer-qa/validation.json`. System registration, actual update/rollback/
  uninstall, native Canvas from this installation and model inference still need
  acceptance. The QA did not create keys/tunnels or make external model requests.
- The earlier compiled-component QA terminated bootloader parents but initially
  left three owned one-file MCP children. Their exact executable and QA state
  paths were reverified, and those three children were stopped. That initial
  parent-only cleanup is not counted as proof of complete process cleanup.

- A fresh isolated Windows payload build completed in 850 seconds and produced
  all 13 required executables, including CLI and Canvas. This is a payload build;
  the combined Setup/Electron install/update/repair acceptance is still pending.
  A subsequent source-only gateway cleanup change must be rebuilt into affected
  executables before final release; this payload is QA evidence, not a final release.
- The compiled MCP served real streamable HTTP with all six tool surfaces and
  115 tools. Its signed local MCP session recovered context written by the
  compiled CLI. Three independent compiled CLI processes verified write, resume
  and memory search; the conversation database held protected content. The
  owned QA MCP was stopped after validation. Evidence: task artifact directory,
  `unified-binary-qa/validation.json`.
- The compiled native Canvas displayed the bundled xterm VT renderer in actual
  WebView2. Windows Alt+F4 closed the original UI process; reopening produced a
  new HWND, retained the broker and CMD PIDs, and displayed protected history.
  The custom close button did not produce a confirmed close, so that control
  and window geometry remain incomplete. Evidence: `unified-canvas-native-qa/validation.json`.
- A subsequent Canvas rebuild starts in a restored 1280x760 window, keeping its
  custom controls visible. The actual custom close button then closed the native
  HWND/process, and reopening retained the broker/terminal PIDs and displayed VT
  history. The owned broker was shut down after QA. Evidence with the newer
  executable hash: `unified-canvas-controls-qa/validation.json`. Maximize/restore
  and DPI behavior still require validation; the earlier maximized result remains
  a failure and is not retroactively counted as passing.
- A central bounded SQLite event journal now indexes installer/runtime/gateway/
  MCP/CLI/Canvas events. Conversation and Canvas producers publish through
  transactionally queued, idempotent outboxes; index outages do not discard
  protected conversation history. Legacy JSONL import has bounded work and
  retained cursors. Content and credentials are excluded; lifetime counters
  survive retained-event pruning. Native turn/browser trace correlation survives
  authority restart. HTTP transport success is not model completion evidence.
- Regression runs passed 218 checks, then 102 checks after install/default and
  correlation changes; later 96 Canvas/gateway/native-DOM checks and 77 enrollment/
  secure-import/release checks passed. These suites overlap and are not additive.
  Real Windows/Edge tests confirmed direct keyboard execution, ANSI color,
  cursor placement, viewport resize and page reload continuity. This does not
  establish that every TUI/IME/paste scenario passed on native WebView2.
- The owned fresh ChatGPT browser surface was inspected without composing or
  submitting messages. Root navigation showed Chat/Work controls, while direct
  temporary navigation showed Think/Pensar. Selecting Work displayed an
  introduction dialog offering "Desbloquear com Plus" and left Chat selected.
  The old home surface still exposes Auto. This account/surface discrepancy
  contradicts treating the cached home model catalog as proof that a fresh
  worker can use Work/Sol. No subscription, new key, tunnel or model resend was made.
  `compare_model_surfaces.py` reproduces the bounded owned-tab diagnosis.

### Conversation persistence implementation and evidence

- `sentra_core/conversations.py` now provides protected append-only messages,
  durable provider/tool journals, a stable logical identity and an OS writer
  lease. Source CLI, Canvas agents and the MCP memory reader share this store.
- Resume loads context without contacting a provider. Explicit continuation
  reuses completed tool results. Interrupted effects remain uncertain until a
  verified resolution; a writer already running cannot be marked interrupted
  by another process. Provider response text and its received-call state are
  committed atomically.
- Provider requests are recorded before HTTP submission. A truncated response
  cannot execute embedded directives, and an uncertain direct API request does
  not fall through to another provider. Native message IDs remain stable after
  history windows are bounded; older messages stay available on disk and via
  bounded, paginated memory search with provenance.
- Canvas schema v3 associates each agent with a persistent conversation ID.
  Source CLI restarts preserve that identity in the shared runtime state root.
  Canvas uses the CLI's local exit command when closing it, avoiding accidental
  inference from the plain word `exit`.
- 115 component/regression checks passed for conversations, actual loopback
  delivery, MCP memory access, CLI, Canvas, governance and both native DOM paths.
  Separate Windows processes were terminated before effects, after effects and
  after result commits; verified recovery did not repeat committed effects.
- A subsequent focused run passed 71 checks after final conversation-state
  handling changes. Three separate real CLI processes verified direct-tool
  execution, session resume and recall from a new conversation without making
  external model calls. These runs overlap the broader suite.
- Live gateway/browser readiness is confirmed, and the authenticated browser
  session inspection returned `authenticated=true`. A live Web model request
  failed at `effort_selection`: the owned temporary tab exposed no supported
  model control. Its browser trace ended with `submission=prepared` and an empty
  composer. The first uncertain provider journal was reconciled from this
  pre-submission evidence; an explicit diagnostic continuation failed at the
  same stage and remains uncertain pending inspection. No automatic resend,
  new OpenAI key or new tunnel was used.
- Live evidence is in the task artifact directory's
  `live-conversation-qa/validation.json` and `model_diagnostic_result.json`.
  Native broker/CLI source checks are stronger than a metadata-only readiness
  check, but they do not prove a successful real Web-model response or a newly
  compiled full installation. The active source endpoint has since been upgraded
  to Full/Computer, and fresh isolated Setup settings were Full/Computer. The
  user's older AppData binaries have not been replaced by those QA builds.

### Native agent coordination and task shutdown (2026-10-08)

- Native Canvas agents now use a workspace/terminal-bound HTTP capability rather
  than an inherited external Maestri identity. Only directed connections from
  their terminal/agent card authorize peer output, note access and delivery.
  The capability cannot use UI/runtime bearer endpoints and is revoked on close.
- The CLI journals the CANVAS directive before executing it and uses its durable
  call ID for handoff idempotency. Delivery can target an active agent card or its
  CLI terminal. Handoff state survives transport ambiguity without automatic replay.
- A real loopback broker and two genuine Windows ConPTY SENTRA CLI processes
  updated a connected note and delivered a direct tool operation that wrote an
  actual file in the worker workspace. Cross-workspace, unconnected-note and
  runtime-shutdown attempts were rejected. This proves real native coordination
  and direct tools, not external model inference.
- Task startup and shutdown now share an atomic lifecycle boundary. Shutdown
  rejects new workers, awaits cancellation, and retains its database/owner lease
  if workers remain. A real worker and its spawned subprocess were both stopped
  before database closure; an effect made before interruption remained uncertain.
- Six focused native coordination/delivery/lifecycle tests passed. A 21-check
  Canvas regression run and a 78-check broker/conversation/CLI/native DOM run also
  passed; these suites overlap.
- Fresh CLI and Canvas builds completed with recorded source/output hashes.
  Their actual compiled broker launched two compiled CLI processes, updated a
  directed note, delivered a direct tool effect in the worker workspace and
  recovered the same delivery identity without retransmission. Actual Edge DOM
  interactions then delivered a second direct operation through connected agent
  cards. Broker shutdown exited zero, removed its discovery endpoint and all
  three owned process IDs were confirmed stopped. Evidence:
  `compiled-native-agent-qa/validation.json` and `compiled-native-agent-ui.png`
  in the task artifact directory. The first QA attempt had an ambiguous test
  locator; its failure is retained separately and is not counted as passing.
  This validates the compiled native coordination components; Setup still needs
  repackaging, and external model inference remains unproven.

| Requirement | Acceptance evidence still needed |
| --- | --- |
| Unified automatic installation | Fresh compiled Setup install, update, repair, uninstall and rollback in an isolated installation, followed by real MCP, gateway and Canvas calls. |
| Full access requested by installer consent | Installed plugin and installed runtime advertise and execute the intended Full profile consistently; the installer does not add a second consent prompt. |
| Terminal continuity across window closes | Source and fresh packaged native close/reopen checks pass. Verify lifecycle integration with the installed main runtime, update/repair and custom titlebar controls. |
| Conversation continuity | Protected store, source CLI/Canvas identity, MCP access and crash-recovery checks pass. Verify successful real-provider recall across processes and the freshly compiled installed CLI/Canvas. |
| Durable delegation and coordination | Task claim/recovery/idempotency integrated with existing durable jobs, shared context, authorization and governance; safe directed Canvas handoffs and cancellation. |
| Unified telemetry | Correlated and bounded operational events/metrics across installer, gateway, MCP, CLI, Canvas and workers, with protected credentials excluded from logs. |
| Canvas usability and actual model integration | Native packaged UI validation, terminal rendering, authenticated model catalog, real agents/teams/tasks, recovery and cross-workspace checks. |
| Release reproducibility | Appropriate regression suite, reproducible packaging, integrity validation and no use of stale executables as proof of the current source. |
| Final feedback gauntlet | Invoke the user-requested feedback subagent after integrated implementation; fix findings and repeat meaningful checks until resolved. |

The local Codex path remains usable while external ChatGPT workspace association
is unresolved. No new key or tunnel should be created to work around that issue.

### Canvas governance admission and native default (2026-10-08)

- Canvas tasks now have stable work item IDs in the existing governance store.
  The ledger contains metadata and protected-content references, not a second
  plaintext copy of instructions/results. Success of execution moves a work item
  to VALIDATING and releases its execution ownership; it does not fabricate a
  Quality Gate, complete the objective or promote a work product.
- Before claiming a task or starting any child, the dispatcher checks work item
  state, blockers/dependencies and applicable budgets. A quota admission reserves
  one execution attempt under a serialized ledger transaction. Concurrent claims
  cannot overbook quota, and a reservation survives restart without double billing.
  Interrupted admission is blocked until explicit reconciliation. Reservations
  are not automatically refunded when child startup fails. Monetary pricing and
  provider token usage are not inferred from these admission events.
- Native MCP now exposes task_governance, task_block/task_unblock and scoped
  budget_list/budget_set. Existing signed sessions, workspace grants and protected
  request receipts still apply. Policies can be disabled/enabled within their own
  workspace. The real native UI shows execution separately from validation and
  offers queued task block/release controls, with visible budget holds.
- Real Edge UI plus broker/CLI checks verified blocking, budget holds, release
  and an actual file effect. Admission concurrency, restart, interruption, no
  automatic replay, scope isolation and Quality Gate separation passed in the
  31-check related source suite. The provider/CLI/private-stdin/conversation suite
  passed 72 checks after automatic native model selection was added.
- Without an explicit model flag or SENTRA_CLI_MODEL preference, the CLI selects
  sentra/codex/current when the local Codex CLI is authenticated. Explicit choices
  remain authoritative; an uncertain native response never falls back or replays.
  Fresh compiled component acceptance is still required. Outstanding integration
  includes provider usage projection into budgets, verified quality/work product
  completion, final Setup/system integration and the final feedback gauntlet.
- Fresh MCP, CLI and Canvas executables completed the same real governance
  chain: 116 tools/all six surfaces, native default inference, scoped budget
  holds, actual Edge task release controls, direct CLI effect and real Codex
  model effect through the queued worker. Completed receipts recovered their
  original task without another execution; protected provider history and
  execution/quality separation were checked. All three component provenance
  records match the current 289 source inputs and output hashes. Evidence:
  `compiled-governance-qa/validation.json`, `build-verification.json` and
  `cleanup-verification.json` in the task artifacts. The initial QA assertion
  incorrectly expected an interactive model banner in one-shot output; its
  failure is retained and recovery verified the existing completed provider
  call without submitting it again. QA packaged process count is zero and
  its broker discovery file is removed. This does not update the primary
  installed product or establish acceptance of the final Setup.

### Real native model response and memory (2026-10-08)

- `sentra/codex/current` now selects the authenticated local Codex CLI as an
  explicit text transport. Credentials remain with Codex. Requests use stdin;
  JSONL parsing requires a final message and completed turn, rejects native tool
  effects/partial output and never switches providers after uncertain delivery.
  SENTRA executes emitted directives through its protected tool journal.
- A genuine Codex CLI request returned the exact generated nonce with a completed
  turn and no native tool items. Through SENTRA itself, three separate CLI
  processes verified the first model response, resumed recall and real MEMORY
  search/recall from a fresh conversation. Protected history was verified.
  The initial QA assertion incorrectly expected a public message provenance field;
  recovery inspected the already completed first two calls and ran only the third,
  without replaying those calls. Evidence: task artifacts,
  `real-native-model-qa/validation.json`; the initial fixture failure is retained.
- Through the existing live Commander/native Canvas, an approved real-model task
  emitted W, created an actual nonce-bearing file, completed its provider/tool
  journals and returned SUCCEEDED. Reusing its request recovered the task without
  another model/tool effect. Evidence: `real-canvas-model-qa/validation.json`.
- The related final provider/CLI/conversation/native-DOM suite passed 57 checks.
  New Canvas agents suggest the authenticated native option; existing model
  selections remain unchanged. Fresh CLI/Canvas packaging is being validated
  separately; this is not yet final Setup/system-integration acceptance.
- Fresh compiled CLI returned the exact real-model nonce, committed protected
  history and exited zero with no uncertain calls. The compiled Canvas and its
  compiled CLI then executed a real-model file-writing task, verified SUCCEEDED
  in the shared durable registry and recovered its request without another effect.
  Actual Edge agent-card delivery and protected task content passed in the same
  owned compiled run. Evidence: `compiled-native-model-qa/validation.json` and
  `compiled-canvas-model-qa/validation.json`. The first Canvas build failed on its
  running executable's Windows file lock; closing only its native window released
  the executable and a retry succeeded. The failed build log is retained.
- This establishes real native Codex inference and cross-conversation recall.
  The earlier external ChatGPT Web account/workspace rejection remains a distinct
  unresolved route; native success is not evidence that Web registration succeeded.

### Reported provider usage and durable budget projection (2026-10-08)

- Usage is committed with the original protected conversation call and a
  transaction outbox. Stable cost-event IDs prevent duplicate accounting after
  a ledger commit/acknowledgment loss. Context captured before submission keeps
  the original owner, workspace, task, work item and run.
- Native Codex, Gateway Responses and direct OpenAI Chat Completions can report
  counters through the same callback; direct OpenAI requests ask for the final
  usage chunk. Missing counters stay unknown and monetary prices are not
  estimated. Reasoning/cached subsets are not added twice to input/output totals.
- Hard token budgets check reported usage before another submission and refuse
  captured incomplete usage. Hard monetary limits are refused when pricing is
  unknown. Warning policies keep warning semantics. An already admitted model
  call can exceed a token limit because its output is unknown before completion.
- Canvas recovery, workers and admission drain the usage outbox. The real UI
  exposes reported/partial/unknown counts and pending accounting. New tables are
  additive to schema v2 and keep old message/call formats usable during rollback.
  Migration is serialized; the WAL contention demonstrated by eight concurrent
  initializations was fixed without repeating any provider submission.
- The final related source suite passed 94 checks. A real native task created
  its file through two model calls reporting 32,815 input and 32 output tokens.
  Exact counts matched its task ledger. An input limit then blocked the next
  task before any provider-call journal entry, with no second file or invented
  uncertain delivery. Completed task replay did not charge again. Evidence:
  task artifacts, `real-provider-usage-qa/validation.json`.
- Actual Edge showed that same existing real-model usage and the separate
  unknown-usage state without more inference. Evidence:
  `real-provider-usage-qa/ui-validation.json` and `real-usage-ui.png`.
  Fresh compiled usage acceptance, final result validation, Setup/system
  integration and the final feedback gauntlet remain separate requirements.
- Fresh packaged MCP/CLI/Canvas then passed the integrated usage check. Two
  genuine Codex calls reported 32,521 input and 34 output tokens; exact counts
  matched the task budget, the outbox was acknowledged, and another task was
  blocked before submission. All three binaries match the current 290 source
  inputs. Evidence: `compiled-provider-usage-qa/validation.json`,
  `build-verification.json` and `cleanup-verification.json`. Original QA process
  IDs are absent and its endpoint is removed; no API key or tunnel was created.
- The idle primary source Canvas and Commander were reloaded after checking
  zero active terminals/tasks/MCP jobs. Workspace IDs/run IDs and settings were
  preserved. The updated packaged Canvas window reopened on the same primary
  broker state. The existing installed connector responded successfully after
  reload. Evidence: `active-provider-usage/reload-validation.json`; updated
  action/schema and existing-task API verification is tracked separately.
- The existing source endpoint also returned its updated action schema and
  successfully inspected a preserved real task through task_governance. Its
  legacy provider consumption stayed unknown instead of being fabricated.
  `active-provider-usage/api-validation.json` confirms 116 tools and the new
  controls. Native Windows inspection confirmed the re-opened updated Canvas
  window with all three prior workspaces on the new primary broker endpoint.
  The first schema-inspection fixture used the SDK's old camelCase spelling;
  using its actual input_schema property fixed that read-only fixture.

### Caller-declared output verification (2026-10-08)

- Delegation accepts up to 16 immutable protected file criteria: expected UTF-8
  text (normalized line endings) or exact byte SHA-256. Invalid paths/specifications
  are rejected before MCP receipt delivery and before task creation. File reads
  are bounded to 16 MiB per file/64 MiB per validation, with change detection.
- Genuine CLI success verifies declared outputs and registers output artifacts
  and a separate immutable verification report in the existing durable runtime.
  Stable artifact identities make projection retries idempotent. Artifacts reject
  changed content before registration; quality failure preserves execution and
  moves the work item to REPAIRING. No provider judgment substitutes for checks.
- Passing criteria follows configured review/approval stages. Without stages it
  completes the declared work item; without criteria it remains VALIDATING.
  task_verify rechecks files after manual repair without rerunning the CLI/model.
  Later output changes are signaled while preserving historical completion.
- Native UI defaults to the genuine CLI, offers optional file/content criteria
  and re-verification, and avoids duplicate execution-consent dialogs. Inspector
  controls now use fresh execution status instead of a stale pre-completion row.
- Related source validation passed 98 checks, with one symbolic-link scenario
  skipped because the Windows environment denied link creation. Tests exercised
  real CLI effects and actual Edge UI, criterion identity collisions, protected
  storage, correction/reverification, configured review, retry after artifact
  commit and mutation between checking and registration. Fresh compiled quality
  acceptance is in progress. Final Setup/system integration and feedback remain.
- Fresh compiled MCP/CLI/Canvas passed the genuine Codex file task with immutable
  declared criteria. Its exact output passed the deterministic gate, output and
  verification artifacts were registered, the work item reached COMPLETED and
  reverification did not rerun the task. Provider usage matched its budget, a
  further request was blocked before model submission, and completed receipts
  remained idempotent. The three binaries match all 292 current source inputs.
  Evidence: `compiled-quality-qa/validation.json`, `build-verification.json` and
  `cleanup-verification.json`; original QA processes are absent and its endpoint
  is removed. No OpenAI key or tunnel was created.
- The idle primary source broker/Commander were refreshed, preserving workspace
  IDs/runs and settings, and the updated packaged Canvas interface was reopened.
  The existing installed connector remained healthy. Evidence:
  `active-quality/reload-validation.json`. Final Setup/system registration,
  launcher shortcuts/lifecycle acceptance and the final feedback gauntlet remain.

### Native Canvas MCP and run control (2026-10-08)

- The developer MCP surface now exposes `sentra_canvas`. It connects to the
  protected native broker using existing workspace grants, enforces the host
  execution ceiling and scopes resource IDs to the selected workspace. Existing
  repositories can be attached after normal filesystem/grant validation.
- Mutations commit protected call receipts before transport. Lost replies remain
  uncertain and block repeated effects. Status/resolution is explicit; identical
  completed requests recover their recorded responses. Audit IDs link receipt,
  workspace, task and common durable operation without recording message bodies.
- Canvas schema v5 binds each task to its original durable run. Pause holds new
  admissions, cancellation stops queued/running work, and explicit resume after a
  terminal run starts a fresh run without moving/replaying old tasks. The current
  run lookup is bounded rather than loading all operation history every queue tick.
- The existing idle source Commander was reloaded after confirming zero active
  MCP jobs and its executable/module/state/instance identity. It now advertises
  116 Full/Computer tools. The already installed Codex connector responded with
  that count and the native tool name; settings, key and tunnel were unchanged.
  Evidence: task artifacts, `active-native-commander/validation.json`.
- The initial live native start failed because the old experimental window held
  its schema-v1 database owner lock. Both database tables and the actual native UI
  showed zero terminals/tasks/nodes. Graceful controls did not close that window.
  Committed SQLite backups preceded stopping the two verified prototype processes;
  process absence and all original workspace records were verified separately.
  The first stop command's nonzero exit was retained instead of counted as cleanup
  proof. Evidence: `legacy-canvas-transition/validation.json`.
- Through the same existing live HTTP MCP endpoint, a signed session started the
  new broker, attached an owned public project, created a team, paused/resumed a
  queued genuine CLI operation, verified its actual file effect and recovered the
  same request without retransmission. Original schema-v1 workspace records
  survived migration to v5. Evidence: `active-native-commander/native-workflow.json`.
  This is real Commander/native CLI integration, not external model inference.
- The final related regression passed 116 checks, including a genuine broker
  mutation with an injected lost reply and verified no replay. The compact native
  tool intentionally increases developer budgets by one (64/78); specialized
  administrative tools remain absent. Fresh MCP and Canvas builds completed with
  source/output hashes. The updated native window reuses the live source broker.
  These component builds do not establish final Setup/system integration readiness.

### Persistent Canvas task queue and owned process trees (2026-10-08)

- Canvas schema v4 retains authorization, cancellation requests, revisions and
  OS protected CLI task content. A bounded dispatcher reserves a task before
  spawning its worker, runs at most four workers/128 pending tasks by default and
  serializes tasks for each agent. Approved queued tasks resume after restart;
  previously running tasks remain uncertain. Legacy authorization is never assumed.
- Tasks project through a revisioned transaction outbox into the existing
  DurableRunService, with stable run/operation/conversation IDs and metadata only.
  Projection failures preserve the task/outbox. Failure after a claim was committed
  but before publication prevents child creation. Pending cancellation is persisted.
- Real CLI task workers can use their agent's directed Canvas connections. Their
  capability expires after completion. Instructions use a bounded UTF-8 stdin pipe
  rather than process arguments. Fresh CLI tasks persist protected instructions and
  results; owned legacy task/handoff records migrate without changing another owner.
- Windows task/ConPTY processes start suspended, join a kill-on-close Job Object,
  then resume. Actual broker termination killed two child processes and two
  grandchildren. Restart preserved the interrupted task as uncertain and executed
  the approved queued direct operation with the genuine CLI, without replaying the
  started effect. This is process lifetime control, not isolation of external effects.
- The final source regression passed 120 checks, including these actual process
  scenarios, queue recovery, shared durable state, private stdin, persistence and
  real Edge DOM. A subsequent owner-isolation migration check also passed.
- Fresh CLI and Canvas builds finished successfully. Their compiled broker and
  compiled CLI executed a queued native Canvas context update through the private
  stdin/capability path. The task appeared as SUCCEEDED in the common durable
  registry, with protected instruction/result columns; repeating its request key
  recovered the completed task. Actual Edge agent-card delivery passed as well.
  Shutdown exited zero, removed discovery state and the three owned broker/CLI
  process IDs were confirmed stopped. Evidence: task artifact directory,
  `compiled-task-queue-qa/validation.json`. This does not claim real model inference.
- Remaining unification work includes exposing the native Canvas through the
  Codex MCP surface, integrating run/governance admission and cancellation across
  services, verifying real model recall, rebuilding final Setup/system integration,
  and the user-requested final feedback gauntlet. Component acceptance above does
  not replace those requirements.
