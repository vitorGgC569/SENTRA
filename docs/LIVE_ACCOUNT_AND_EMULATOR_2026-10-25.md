# Account and Android qualification — 25 October 2026

## Historical record

This records the earlier Setup 1.0.3 and emulator qualification. Its public-download
and embedded-probe limitations are superseded where explicitly stated in the
[1.0.4 acceptance record](RELEASE_1_0_4_ACCEPTANCE_2026-10-25.md).


This supplements [the onedir acceptance record](WINDOWS_ONEDIR_ACCEPTANCE_2026-10-25.md).
It distinguishes published bytes, source fixes and owner-attended checks.

## Public delivery

- [Windows Setup 1.0.3 preview](https://github.com/vitorGgC569/SENTRA/releases/tag/installer-preview-20261025-1)
  and the [download site](https://vitorggc569.github.io/SENTRA/) are published.
  All nine release asset sizes and SHA-256 digests matched the local publication plan.
- The public Android download remains preview v8. Emulator-only artifacts are not
  replacement phone releases. There is no installable iOS release.
- Fixes in `76b11fddfd977bdb2819bdae3a5e6db5cc4e11e1` were made **after** Setup 1.0.3
  was packaged. They are not claimed to be present in that public installer or APK v8.

## Real account observations

The owner signed into Platform and ChatGPT in an isolated, persistent Chromium
profile belonging to the private installed test copy. No production profile was
imported, and no existing native-provider configuration was redirected.

The coordinator verified local MCP and the official tunnel. Platform automation
created a Windows-protected runtime credential. Ambiguous tunnel creation was
reconciled by observing and reusing one exact named test tunnel, without replaying
another creation. One additional unused test tunnel remains in the test account;
it has not been deleted automatically.

The live ChatGPT form exposed two compatibility issues: its Add menu entry is a
`menuitem`, and its tunnel identifier is a textbox rather than a native select.
Source now supports both representations, refuses a different prefilled tunnel,
and leaves authentication selection, account consent and submission with the
owner. The focused suite passed 21 tests; the complete related enrollment suite
passed 102 tests with one skipped test.

The account already has an app named SENTRA. The owner reported that creating
another app with that name was rejected. A separately named **SENTRA Validação
1.0.3** app was created and authorized by the owner; the existing app was preserved.
A fresh read-only `sentra_health` challenge was subsequently observed by the
isolated MCP server through that exact tunnel. Its one-use proof verified the
roundtrip. A previous expired probe was recorded as unconfirmed and was not replayed.

A real message through the installed frozen Canvas returned the requested marker
and a confirmed `SUCCEEDED` receipt. The broker was reopened and the same result
was read again with exactly one physical user message. Markdown-escaped underscores
initially caused the harness's raw substring assertion to fail; read-only
reconciliation confirmed the rendered marker without sending another message.
The observed assistant content SHA-256 is
`351d4a174dada467349f5f29218bb880c7e4bfd242bda7ee8bd2e0bb1b93de80`.

These checks use a source coordinator and the actual installed Web/MCP components,
plus the frozen Canvas for the model turn. They are not a fully automatic frozen
installer UI end-to-end qualification: the owner handled account consent, and
the named-app probe used the private browser's Playwright connection. Modern
composers use a plugin mention rather than `#prompt-textarea`; direct-browser
preparation now preserves that mention and existing drafts. The bounded embedded
DOM protocol retains its manual verification fallback instead of gaining generic
keyboard or attribute access. Existing-app reuse and fully automatic embedded
probe preparation remain integration work.

## Android emulator observations and correction

An Android 35 Google APIs x86_64 emulator booted using WHPX without enabling
Windows optional features. The public ARM64 APK could not load its ARM64 React
Native library on this x86_64 image; this is not a finding about ARM64 phones.

An independently signed, unpublished x86_64 QA artifact from
[run 40160862938](https://github.com/vitorGgC569/SENTRA/actions/runs/40160862938)
launched the native app successfully. Its SHA-256 was
`bebf987571ecb0690ac72de6782dfc5a561771a4390e9a39b69821f6bd403f22`.

The real app reached the pairing UI, but the connection closed before a pending
device appeared on the host. React Native's Android WebSocket implementation
adds an HTTP Origin by default, whereas the gateway rejected every Origin.
The correction sends an explicit native-only Origin marker and accepts exactly
that marker or no Origin. Ordinary HTTP origins, `null`, and lookalike markers
remain rejected. Host-key pinning, encrypted frames, replay checks and scoped
device credentials remain required.

Transport type checking, app type checking and all seven app tests passed.
Transport tests passed 22 tests, with one optional discovery test skipped. The
real encrypted socket test exercises the native marker and rejects four browser
or malformed origins. A new unpublished emulator APK was built successfully in
[run 40162874283](https://github.com/vitorGgC569/SENTRA/actions/runs/40162874283).
Its verified SHA-256 is
`38c94f0804f43932e49039b763f1bd1d538096e8e5c3814de899beea38664bc3`;
its version code is 10 and its signer matches the published preview certificate.

The actual native APK, a source gateway at `76b11fd`, installed Node runtime and
the installed frozen Canvas broker passed:

- Pending pairing request, exact scoped approval and native conversation inventory.
- Draft persistence after force-stop and relaunch, without sending a message.
- Background/foreground return.
- Gateway restart, reconnection and preservation of the host's cryptographic identity.
- Device revocation reflected in the native app.

This is Android emulator NAT reaching a Windows private LAN interface, with a
manual deep-link invite. No QR-camera, physical phone, VPN or remote-control test
is implied. The corrected gateway and APK still need distribution builds together;
the public Setup 1.0.3 and Android v8 do not contain the native Origin correction.

## Remaining environment gates

- A disposable Windows OS is still needed for clean install, cross-version
  upgrade, rollback and reboot. Current Hyper-V management is denied and the owner
  has no Windows ISO/VHD. No administrative policy or host feature was changed.
- An emulator can test native UI, storage and transport, but does not qualify
  physical Wi-Fi, QR camera, device suspension or real VPN behavior.
- iOS Simulator requires macOS/Xcode. No Mac or Apple distribution account is
  available, so neither simulator nor physical iPhone acceptance is claimed.
- Windows signing remains absent by agreement. No signing or update-admission
  checks were weakened.

Private reports, invite tokens, account identifiers and browser profiles remain
outside version control. Public notes contain no credentials or live challenges.
