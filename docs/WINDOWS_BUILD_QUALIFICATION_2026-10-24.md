# Windows 1.0.2 build and qualification â€” 24 October 2026

This is an unsigned development candidate. The owner explicitly chose to
continue without a code-signing certificate. No security policy, publisher
trust store or automatic-update signature gate was weakened.

## Build identity

Application inputs: `62d61fa65fec9b79a0f531a91ccafd2fd3163615`.
Immutable source snapshot SHA-256:
`b66ca69df7db99ce5d26aeceb35335726c335f73bdd643dce408b9e06f3fe3cd`.
The snapshot contains 1,875 tracked source files. This qualification report is
a later delivery document; it is not claimed to be embedded in those binaries.

Build and evidence are isolated from the user's current installation:

- Candidate: `%LOCALAPPDATA%/SENTRA/Build/product-20261024-final/`.
- Final inputs and binaries: `source-release/` and `dist-release/`.
- Release packages: `release-current/`.
- Local detailed evidence: `.tmp/release-qualification-20261024/`.

## Corrections included

- The Web Models runtime exposes authenticated account status/login control;
  missing or invalid credentials are rejected. The prior installed runtime's
  missing route is not treated as a successful account check.
- Contiguous pending PTY fragments share bounded queue records. This prevents
  queue overhead from discarding a large number of tiny output fragments;
  resize barriers and committed event ordering remain intact.
- The installer first verifies the Electron payload and attempts a real display
  probe. If Electron cannot start, it verifies the actual frozen native WebView2
  display with a nonce, DOM readiness, Node isolation, blocked network access
  and orderly window destruction. An invalid Electron payload remains an error.
- Automatic desktop launch can use the native backend on an OS startup refusal.
  An explicit Electron selection and credential errors do not silently fall back.
  Native readiness does not claim the external activity bar is available.
- The integral build has a sufficient timeout, includes root third-party notices
  and resolves the canonical frontend launcher under redirected Windows paths.

## Completed evidence before final Setup acceptance

- Targeted native display/installer suites: 68 passed.
- Targeted PTY persistence/recovery suites after coalescing: 37 passed.
  The 2,000-fragment regression fails on the earlier implementation and passes
  with bounded coalescing, exact output preservation and a resize barrier.
- A 1,800-second source-daemon endurance trial passed in 1,809.4 seconds:
  three physical ConPTY workers, three broker reopenings, 531 checkpoint reads,
  advancing checkpoint sequences, reply-loss recovery and one physical execution
  of a duplicate input request. History pruning is bounded by the 16 MiB quota;
  it must not be confused with a producer-queue persistence gap.
- The packaged Web account-control smoke trial passed HTTP status, unauthorized
  and invalid-action checks using a fresh isolated profile. It does not establish
  that an existing user's ChatGPT session can produce a model answer.
- A real two-worker Dot journey passed on an earlier sealed 1.0.2 payload:
  one owner Full selection, agent-created worker Dots, 60 synthetic sales rows,
  pause after completed child work, broker reopen and verified consolidation
  (total 594). Existing children and operations were retained without replay.
  This is not an interruption during an unknown physical effect and must not
  be described as final Setup-installed evidence until repeated there.

## Failed and superseded trials retained

- The previously installed daemon failed its prolonged trial at 1,271.3 seconds
  with unavailable checkpoint coverage. Its report is retained as failed.
- A source trial with periodic diagnostic traceback dumping ended in a native
  access violation after 125.7 seconds. The subsequent successful source trial
  uses the normal production daemon entrypoint. Causality is not asserted from
  that single diagnostic failure.
- Intermediate candidates were intentionally superseded after defects were
  found. Their stopped installer builds and missing-sidecar harness failure are
  retained; they are not counted as qualified releases.
- The first final Setup assembly collided with a concurrently running display
  probe while restaging Electron (`WinError 32`). The failed attempt is retained.
  The retry reuses all fourteen hash-verified executables and starts display
  qualification only after Setup assembly finishes. That invalid concurrent
  probe is not evidence of an intrinsic timeout in the intact Electron payload.
- The earlier installed CLI was refused by Windows Application Control. A newly
  compiled CLI ran successfully. That does not retroactively qualify the older
  blocked image or prove that every new component is permitted.
- An earlier Web-provider trial ended UNCERTAIN because the selected provider
  was not ready. The request was retained and was not automatically resent or
  redirected to another provider.

## Final artifact and installed-runtime acceptance

The full unsigned 1.0.2 Setup was generated: **3,193,341,241 bytes**, SHA-256
`e005f82bcef7d4ab8955d8f4061d423bb8d443f343be8742d0189f5e00b8a678`.
All fourteen executable hashes match the sealed payload provenance.

- Actual Setup payload verification and frozen Tcl/Tk checks passed.
- Installation into an empty directory passed payload/core-MCP/native-display
  checks. Setup returned code 2 because account/tunnel completion is pending;
  this is not a complete first-use onboarding pass.
- Upgrade from 1.0.1 preserved the protected synthetic credential, draft marker,
  workspace document, profile and allowed roots. Manual backup rollback restored
  every program-file hash. A real saved Dot and conversation retained their IDs
  when read with both the new and restored binaries.
- Forced death of the Setup-installed daemon passed protected-history recovery,
  orphan-input refusal and no duplicate physical execution.
- The Setup-installed multi-Dot journey passed using `sentra/codex/current`:
  two agent-created workers, checkpoint pause, broker reopen, retained child
  conversations and a verified total of 594 across 60 synthetic records.
  No child instruction or operation was duplicated.
- The frozen native display passed. The intact Electron display probe timed out;
  the external activity bar is **not qualified**.
- Distribution assets, inventories and hashes were generated. Update ZIP CRC
  checks passed for all three entries. **MSI administrative extraction failed
  with Windows Installer code 1619**; the MSI is not qualified for publication.
- Installed endurance was intentionally interrupted at **563.1 seconds** when
  the owner requested the PC for studying. Its three synthetic terminals and
  owned daemon were closed. The raw harness records an assertion after that
  deliberate shutdown; a separate interruption record supplies the context.
  This is not a 30-minute pass. The separate 1,809.4-second source trial passed.

The existing user installation was backed up but **not updated**. Computer Use
was interrupted before its update, and work was then stopped at the owner's
request. User sessions/accounts were preserved. Real ChatGPT Web login/inference
in the updated user application remains open. No new Windows tag or release
was published during this qualification.

[Machine-readable artifact and acceptance evidence](release-evidence/windows-1.0.2-20261024.json).
Detailed private logs remain local; account material and user-state backups are
not committed or included in distribution packages.

## Qualification boundaries

A fresh directory on this Windows host is not a clean Windows VM. Administrative
MSI extraction is not a registered MSI installation. Synthetic protected-secret
and draft marker preservation is not an end-to-end browser draft test. A manual
backup restoration does not qualify the signed automatic updater. Physical
Android/iPhone, VPN, trusted signing and a clean-OS matrix remain separate work.

The external activity bar depends on Electron. If Windows refuses that image,
the native main window can work while the bar remains unavailable. No stable
release claim follows from the native fallback alone.

## Subsequent preview publication

The same unchanged Setup was subsequently published as an unsigned
[Windows 1.0.2 preview](https://github.com/vitorGgC569/SENTRA/releases/tag/installer-preview-20261024-1). All eleven public assets were checked against
the reviewed publication plan, including the three installer parts. Independent
streamed reconstruction matched the full Setup SHA-256. The PowerShell helper
was not executed on this host because script execution is restricted; no policy
was changed. Download instructions include a built-in binary-copy alternative.

[Android preview v8](https://github.com/vitorGgC569/SENTRA/releases/tag/mobile-preview-20261024-8) was built, signature-checked and published by
the existing GitHub workflow. Its package and dedicated signing identity are
preserved. Both platform builds identify source `62d61fa65fec9b79a0f531a91ccafd2fd3163615`. This does not
establish physical-device qualification or change the open acceptance above.
The user's installation remains unchanged. MSI/CAB and automatic-update ZIP
are not attached to the public preview.
