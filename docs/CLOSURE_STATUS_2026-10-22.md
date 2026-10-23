# SENTRA closure and qualification status — 22 October 2026

This record supersedes the implementation status in `OPEN_ITEMS_AUDIT_2026-10-22.md`.
That audit and the earlier delivery acceptance record remain historical evidence.
Implementation, automated acceptance, installed delivery and physical device
qualification are separate results. Overlapping test reruns are not added together.

## Implemented in this revision

| Area | Changes and current evidence |
|---|---|
| Python quality | Enforced mypy findings reduced from 297 to zero. The gate now permits zero, rejects incomplete runs and rejects a new finding. No baseline expansion or diagnostic suppression. |
| Durable execution | Windows atomic projection writes use unique temporary files and bounded sharing retries. Run/task/validation/budget snapshots and ProgramMemory publish the same already-fsynced snapshot under bounded Windows sharing retries, without repeating the operation. Protected JobStore reads decode through the protected store. Cold PTY owner startup waits for the one launched process; no fallback process or uncertain command replay. |
| Host concurrency | Catalog reads leave the host event loop available for effects and cancellation. Reader ownership survives caller cancellation. Same-loop synchronous calls fail immediately. Actual concurrent Git/file/command jobs passed. |
| Workspace | Resource reattachment, unavailable/orphan resource controls, explicit layout conflict choice, edge splitting, pane/tab keyboard navigation and context menus. Restoring views does not create processes. |
| Editor and Git | Grouped scoped observation, protected draft conflict preservation, disk staleness after discard, draft/cleanup serialization and rollback-compatible scope metadata. Central, separately scoped Git review/commit/discard/fast-forward merge/nonforce publication/cleanup. New and binary files have size/hash evidence. Lost push confirmation stays uncertain. |
| Browser | Design Mode selects observed elements and creates a conversation draft. Optional login retention uses bounded, versioned owner-protected storage tied to machine/principal/binding/profile. Forgetting deletes the protected cache and prevents open contexts from resaving it; it does not claim to log out a live page. Actual Chromium suite: 20 passed, one provider-absence negative test skipped because the provider was installed; four subtests passed. Final central admission/revocation/profile checks: five passed. |
| Remote input | Desktop queued input keeps its original scope and lease epoch. Mobile chords and drags are bounded atomic actions with host-side release. Navigation, backgrounding, lost control and transport failure fence pending input; uncertain effects are not resent. |
| Mobile continuity | Protected Unicode-safe chunked chat/terminal drafts; exact conversation scope; foreground sequential refresh with backoff and stale-result fencing; paired scope navigation; pinned-host address recovery; recoverable credential rotation and revocation. |
| LAN discovery | Host mDNS advertisement and explicit bounded discovery of already-paired hosts. An encrypted host identity probe precedes credential use. Discovery is not execution permission. |
| Installer | Required Platform project/expiry validation, exact parsed loopback host checks, bounded browser-host responses, installer introspection/default compatibility and typed UI-thread worker options. Installer/setup tests: 130 passed. |
| Packaging | Snapshot includes every desktop src/public seal input, required extensionless licenses, connectors and the sealed generated terminal engine. Actual repository-seal coverage and tamper tests guard against incomplete isolated builds. Bounded CAB partitions preserve global MSI file/media sequence and legal payloads. A streaming multipart preview utility verifies original/part hashes and generates a no-overwrite PowerShell reassembly helper. |
| Terminal dependency integrity | Engine manifest v2 seals every external xterm dependency after the pinned serializer patch. Source, staging, installed consumer and worker reject missing, altered, extra or legacy dependencies before starting the worker. The worker protocol remains version1. Real source/staged worker and refusal scope:26 Python tests and4 Node tests passed. |
| Interoperability | A2A/SSE shutdown drains accepted clients. HTTP SSE consumes dechunked bytes and refuses truncated declared bodies. Federation closes failed handshakes and bounds accepted connections. Actual HTTP framing regressions preserve uncertain/no-replay behavior. |
| Task accounting | Quote, step and cost reservation share a transaction. A rejected budget request no longer pins a quote for a later step. Canonical central intent hashes are used for workflow signal acknowledgement. |
| Remote adapters | Existing protected GitHub/Drive machine registrations restore through their existing adapter. Explicit guest reconciliation records VM identity and rejects a replaced VM. No substitute host directory or fabricated remote provider result. |

## Real execution evidence

- OpenCode **1.19.3**: actual generation, exact one-shot path approval, provider
  cancellation, same-session loading and uncertain transport loss passed.
- Three model-created workers: three physical isolated Git worktrees, one owner
  Full authorization, zero manual Grants, edits with hash verification, broker
  reopen preserving bindings and a deliberately detected conflict passed.
  The three workers overlapped for **313.36 seconds**. Each child was submitted
  once; failed earlier laboratories were retained and were not replayed.
- Installed daemon from source `c8c8a59`: a **30-minute** isolated soak passed
  with three concurrent terminals, three broker reopens, 17,586 output reads,
  preserved process identities and a single physical duplicate-intent execution.
  This qualifies that earlier binary, not a newly generated setup.
- Workspace/backend final combined scope: **34 passed**. Final protected draft
  scope/cleanup scope: **15 passed**. Adapter continuity scope: **66 passed,
  two skipped** (external shim absent and Windows symlink privilege absent).
- Frontend Node scope: **243 passed**. Interactive current-renderer checks
  covered dark/light themes, pane keyboard resizing and view-only splitting.
  A white-on-white resume action and legacy workspace button colors were fixed.
- Complete native Electron workspace fixture passed: guided draft, contextual
  session tools, scoped file-tab recovery, layout persistence, keyboard tab
  movement, narrow viewport, light theme, inline permission and lost-ACK
  observation without repeated effect. Production isolation and the native
  bar/reconnection/shortcut/monitor fixture both passed. Real Chromium-to-HTTP
  Canvas/PDF scope: **four passed**. The fixture now uses named arguments to
  avoid Electron rejecting a positional URL before JavaScript starts.
- Rename observation and adjacent editor scope: **17 passed**, including
  retaining the original path after refused reads and rejecting an identity
  replaced during the read. Snapshot/provenance/version scope: **63 passed**;
  terminal generated-input snapshot/tamper follow-up: **27 passed**.
- MSI partitioning and adjacent release scope: **32 passed**, including actual
  FCI compression, MSI File/Media/_Streams tables and byte-for-byte extraction
  through the native Windows CAB API. Multipart utility: **25 passed, one
  symlink-privilege skip**, with real PowerShell reconstruction and refusals.
- Failure/integration matrix in a normal Windows user context: **183 passed,
  12 skipped**. Full unit qualification is recorded separately below.

Detailed working evidence is retained locally under `.tmp/closure-root`,
`.tmp/closure-quality`, `.tmp/closure-workspace`, `.tmp/closure-mobile` and
`.tmp/sentra-delivery`. These directories are not product inputs or public
proof bundles. Do not treat file presence as artifact qualification.

## Full-suite and native package qualification

The first complete recursive unit diagnostic collected4116 cases across505
files, including all29 nested files:4045 passed,61 skipped and10 failed.
Two genuine/fixture publication issues and two imported-module/live-source
inspection mismatches were corrected and rechecked; six terminal failures
used an old imported manifest consumer while its on-disk worker changed.
The subsequent matrix exposed three real validation/budget publication
failures through the same Windows atomic writer. Those results remain failed
evidence. A new full run after source freeze is required, rather than adding
targeted reruns together and calling the whole suite green.

The remote unit job exceeded its35-minute bound. Its unit-only budget is now
90 minutes; the other lanes retain35 minutes. Unit CI prepares and validates
the actual patched terminal engine. Venv process fixtures distinguish the
Windows launcher from the interpreter and prove daemon Job membership.
Docker grant-only fixtures have no physical CLI prerequisite; physical cases
still require the trusted CLI and Linux image. All three physical Docker
scenarios ran locally in the22-case passing scope, with zero skips.

At the owner's request, the complete Windows rebuild and prolonged final
qualification were deferred to conserve usage. The candidate attempt was
stopped after the validation writer defect was discovered; it is not a
delivered or qualified package. The source preview contains the correction.
Stable publication gates remain unchanged.

Final focused publication checks:107 passed across prepared-publication,
ProgramMemory/Persistence and site verification; enforced mypy0/max0. The
prepared-publication cases cover all six actual caller wrappers, native
Windows delete-sharing refusal, permanent failures and no provider replay.

The development host also exposed path-specific HTTP interception under Codex:
an unchanged stdlib `/mcp` response acquired a chunked header without chunk
framing. The same script launched through the ordinary Windows interactive task
service received the correct response. Affected tests run unchanged in that
normal user context; production endpoint names, framing validation and TLS
verification are retained. Windows broker lifecycle tests use the existing
interactive launch context of the installed shortcut, not a breakaway fallback.

Native workspace and bar fixtures passed using the real Electron runtime and
isolated fixture state. They do not qualify clean installation or update of a
newly generated complete package.

## External acceptance gates and explicit limits

| Gate | Required next evidence |
|---|---|
| Android physical | Install the newly identified ARM64 APK on an actual phone, pair, approve on Windows, continue a conversation, suspend/resume, reconnect, revoke and verify input release. No physical device result has been claimed. |
| Private VPN | Repeat pinned-host pairing/recovery and remote input through a real private VPN route. Do not expose the host publicly to substitute for this test. |
| iPhone distribution | Apple Developer account, signing/provisioning and a Mac or configured signing build service. The prepared iOS project/export is not an installable signed app or a TestFlight release. |
| Windows stable release | Independent disposable Windows clean Setup/MSI installation, upgrade, rollback, uninstall residual inspection, actual native/Web Models/MCP checks, trusted signatures and release-owner review bound to the exact Setup/MSI hashes. The publication gate remains enforced. |
| SSH | Existing Guacamole SSH support requires configured guacd, target identity, credentials and a real server. No unauthenticated placeholder transport is enabled. |
| GitHub/Linear | GitHub read adapter and Git publication are distinct capabilities. Guided issues/PR operations remain separate work. Linear can use the existing authenticated MCP route, but no configured server/account has been supplied or qualified. |
| Guest workspace | Existing explicit one-way import/reconciliation routes coordinator tools and terminals. Guest remote file editing, bidirectional sync and back-publication still require scoped adapters. The host editor is not presented as a guest filesystem. |
| Broader visual acceptance | Current theme/split checks do not certify every narrow-screen, screen-reader, attachment, dialog, long-content or multi-monitor interaction. |

Public relay hosting and relay-dependent remote push are outside the owner’s
selected LAN/private-VPN scope. They are not silently replaced by a public
service. Complex merge/rebase and destructive new/binary deletion require an
explicit reviewed operation; neither is disguised as a successful safe merge
or ordinary text discard.

## Reproduction entry points

```powershell
python scripts/check_mypy_baseline.py
python -B -m pytest tests/failure tests/integration -q
node --test sentra_canvas/desktop_ui/test/*.test.mjs
npm --prefix integrations/orca-mobile/transport run typecheck
npm --prefix integrations/orca-mobile/transport test
npm --prefix integrations/orca-mobile/app run typecheck
npm --prefix integrations/orca-mobile/app test
```

Use the normal Windows interactive launch path for process-lifetime and real
HTTP qualification on a development host with the interception described above.
Keep disposable stores, worktrees and owned subprocesses separate from user
profiles. Source snapshots exclude accounts, cookies, sessions and signing keys.
