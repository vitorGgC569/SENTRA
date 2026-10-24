# SENTRA — first-version acceptance review

Reviewed on **24 October 2026**, including the sealed application build `62d61fa`.

**The current product is a development preview. A stable first release is not
yet qualified.** The installed local interface is newer than the published
Windows installer. Working UI and selected passing tests do not establish that
every integration or installation scenario works.

| Area | Evidence | Open acceptance |
|---|---|---|
| Desktop presentation | 265 UI tests; real HTTP integration; current Home, selector, conversation and Canvas checked locally | Full accessibility/device matrix and all long-content/tool states |
| Local Windows delivery | Current Canvas executable and served asset hashes verified; backed-up local update applied | Unsigned 1.0.2 Setup generated; isolated install, upgrade and manual rollback passed. User update, clean-OS matrix and trusted signing remain open |
| Terminal recovery | Selected real ConPTY/receipt tests; separately identified 30-minute frozen trial | Installed crash recovery passed; 30-minute installed endurance interrupted for owner PC use; not qualified |
| Model execution | Catalog and durable admission/uncertain states available | Real Codex multi-Dot results passed in the Setup-installed fixture; updated user-app Web login/inference and Grok remain unverified |
| Floating activity bar | Earlier implementation and observations recorded | Earlier Electron image blocked by Windows; new probe timed out. Native display passed; external bar unqualified |
| Android | Signed preview APK is published | Physical device, VPN, suspension/reconnection/revocation acceptance |
| iPhone | Shared application source and LAN design | Apple signing/distribution account and an installable build; physical acceptance |
| Coordinated agents | Existing central permissions, WorkItems, coordination and worktree implementations | Installed two-worker task, checkpoint pause/reopen and verified result passed; unknown-effect crash remains a separate case |

## Installer comparison

Published Windows preview:
[installer-preview-20261023-1](https://github.com/vitorGgC569/SENTRA/releases/tag/installer-preview-20261023-1).

Its [release manifest](https://github.com/vitorGgC569/SENTRA/releases/download/installer-preview-20261023-1/windows-preview.json)
identifies executable source `8b24da4e9806ea3c01d6f9880d63f61291292483`,
Setup SHA-256 `360f0c9a6d194d10068a4defcc04c87f6f1c3802c1e1aab9be6627ce092e0f8d`
and a total size of 3,176,796,914 bytes split across three assets.

This installer **does not include the October 24 interface and central Dot
selector**. Its own metadata records incomplete clean-install/update/rollback,
signing, prolonged terminal and physical mobile qualification. Later source
fixes do not retroactively qualify that binary.

The current user-installed Canvas is a separate development delivery:
`c5f90fb29faf795ef0ef9204ec76db80e7adeb2f1f08313ce2d8a10f53e17a8e`.
It is not a complete new Setup or an automatic update.

## New local candidate

A full unsigned **1.0.2 Setup** was built from `62d61fa`, including the current
interface and backend fixes. Isolated installation, upgrade preservation,
manual backup rollback and a real two-worker Dot recovery journey passed.
MSI extraction failed (1619); installed endurance was interrupted when the owner
needed the PC. The user installation is unchanged. No new Windows tag/release
was published.

[Qualification and artifact hashes](WINDOWS_BUILD_QUALIFICATION_2026-10-24.md).

## Available downloads

- [Windows preview notes and multipart download](https://github.com/vitorGgC569/SENTRA/releases/tag/installer-preview-20261023-1).
- [Android preview v7](https://github.com/vitorGgC569/SENTRA/releases/tag/mobile-preview-20261023-7).
- No installable iPhone release is published.
- [Download page](https://vitorggc569.github.io/SENTRA/).

## Exit criteria for a stable first version

1. Build a complete installer from the final application inputs, verify all
   assets/sidecars and qualify clean install, upgrade and rollback.
2. Resolve trusted distribution and the blocked desktop component without
   weakening Windows security; verify its normal launch and external bar.
3. Obtain confirmed provider results and complete a recoverable multi-Dot job.
4. Run the supported-device acceptance matrix. Unqualified platforms must remain
   clearly marked preview/unavailable rather than silently counted as complete.

CI investigation remains deprioritized per the owner's instruction. Its known
failures are not converted into passing qualification. This review does not
publish or approve a stable tag.
