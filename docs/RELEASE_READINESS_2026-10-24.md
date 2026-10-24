# SENTRA — first-version acceptance review

Reviewed on **24 October 2026**, including the sealed application build `62d61fa`.

**The current product is a development preview. A stable first release is not
yet qualified.** The published unsigned Windows 1.0.2 preview includes the
current interface and reviewed runtime fixes. Working UI and selected passing
tests do not establish that every integration or installation scenario works.

| Area | Evidence | Open acceptance |
|---|---|---|
| Desktop presentation | 265 UI tests; real HTTP integration; current Home, selector, conversation and Canvas checked locally | Full accessibility/device matrix and all long-content/tool states |
| Windows delivery | Full unsigned 1.0.2 Setup published; fourteen executable hashes, isolated install, upgrade preservation and manual backup rollback passed | User-install update, clean-OS matrix and trusted distribution remain open |
| Terminal recovery | Source 30-minute endurance and installed crash recovery passed | Installed 30-minute endurance interrupted for owner PC use; not qualified |
| Model execution | Real Codex results passed in the Setup-installed multi-Dot fixture | Updated user-app Web login/inference and Grok remain unverified |
| Floating activity bar | Earlier implementation and observations recorded | Earlier Electron image blocked by Windows; new probe timed out. Native display passed; external bar unqualified |
| Android | Signed preview APK is published | Physical device, VPN, suspension/reconnection/revocation acceptance |
| iPhone | Shared application source and LAN design | Apple signing/distribution account and an installable build; physical acceptance |
| Coordinated agents | Installed two-worker task, checkpoint pause/reopen and verified result passed | In-flight unknown-effect crash and broader coordination cases remain separate acceptance |

## Published Windows preview

[Setup 1.0.2](https://github.com/vitorGgC569/SENTRA/releases/tag/installer-preview-20261024-1) includes the October 24 interface and runtime fixes.
Executable source: `62d61fa65fec9b79a0f531a91ccafd2fd3163615`. The full Setup is 3,193,341,241 bytes, distributed
in three verified parts. SHA-256:
`e005f82bcef7d4ab8955d8f4061d423bb8d443f343be8742d0189f5e00b8a678`.

The older [October 23 preview](https://github.com/vitorGgC569/SENTRA/releases/tag/installer-preview-20261023-1)
remains a historical release and does not contain the October 24 interface.
Publishing 1.0.2 does not retroactively qualify that older binary.

The current user-installed Canvas is a separate development delivery:
`c5f90fb29faf795ef0ef9204ec76db80e7adeb2f1f08313ce2d8a10f53e17a8e`.
It is not a complete new Setup or an automatic update.

## Windows 1.0.2 acceptance

A full unsigned **1.0.2 Setup** was built from `62d61fa`, including the current
interface and backend fixes. Isolated installation, upgrade preservation,
manual backup rollback and a real two-worker Dot recovery journey passed.
MSI extraction failed (1619); installed endurance was interrupted when the owner
needed the PC. The user installation is unchanged. The unsigned preview is
now public; stable-release acceptance remains incomplete.

[Qualification and artifact hashes](WINDOWS_BUILD_QUALIFICATION_2026-10-24.md).

## Available downloads

- [Windows preview notes and multipart download](https://github.com/vitorGgC569/SENTRA/releases/tag/installer-preview-20261024-1).
- [Android preview v8](https://github.com/vitorGgC569/SENTRA/releases/tag/mobile-preview-20261024-8).
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
