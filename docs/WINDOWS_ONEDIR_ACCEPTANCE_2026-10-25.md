# Windows 1.0.3: isolated local acceptance

The unsigned PyInstaller `onedir` + Inno Setup 7.1.0 candidate passed local
installation, same-version repair and rejection of an unowned destination.
It is published as an unsigned prerelease. The developer's installed SENTRA, account profiles
and provider configuration were not replaced.

Machine-readable evidence:
[windows-onedir-1.0.3-local-2026-10-25.json](release-evidence/windows-onedir-1.0.3-local-2026-10-25.json).

## Artifact identity

- Product: 1.0.3, 2,857,535,116 bytes.
- SHA256: `60acb92b83a2910bdf356c2d2f30fd4e9c541df40132824740cb6daaaab3905b`.
- Application executables: source `ffe72334a0d68b602771d9a675394e1ccf7751f9`.
- Installer worker and native envelope: source
  `d6726e3df1bcb89d6a31116da5c71eb5d3a976cc`.

These origins are intentionally separate. The previously qualified application
bytes were retained; the installer worker was rebuilt for repair handling, and
the native envelope was recompiled. Original source seals remain unchanged.
This is not presented as every application executable being rebuilt from the
installer worker revision. All earlier candidate Setup files are superseded.

## What passed

1. The complete Setup installed into a new private directory with spaces in its
   name. User/system registration and application launch were disabled; account
   homes and service ports were isolated.
2. Both installation and same-version repair returned exit code zero. Payload
   integrity, MCP health and the installed sandboxed display check passed.
   Installed executables had their sibling Python support directories.
3. A saved draft and a synthetic native-provider configuration survived repair
   byte for byte. The exact installed worker matched the candidate worker hash.
4. A destination containing an unrelated fixture file was rejected. The native
   Setup returned code 2, preserved the file and installed no Canvas executable
   there. Worker failure was not reported as successful installation.
5. Two simultaneous cold clients using the final frozen Canvas reached one
   physical broker and one runtime identity. Their private broker exited after
   the explicit shutdown confirmation.
6. The packaged Web component passed full startup with a fresh private profile
   and system-only PATH. No visible window was observed. Its actual BrowserHost
   passed the locally intercepted setup fixture; a synthetic persistent cookie
   also survived a Chromium process restart. No real account was used.

The latest focused installer/repair suite passed 61 tests. Earlier sweeps passed
237 backend and 265 frontend tests; these are separate runs, not an additive
unique-test count.

## Failures found and corrected

- A setup view initially inherited a 1-by-1 viewport before the normal browser
  panel mounted. Setup now uses the real content size.
- Managed hidden restarts could expose the component's own onboarding. Managed
  launches honor hidden mode; verified SENTRA onboarding records completion.
- The initial native envelope used `CreateAppDir=no`, so the worker received an
  incorrect destination. Directory selection is now enabled correctly.
- A worker exception could leave the native Setup reporting success. Its exit
  code and finished-page/open-application behavior now reflect worker failure.
- Read-only packaged licenses prevented repair. Only product-file replacement
  handles that attribute; no Windows ACL or global security policy is changed.
  A failed replacement preserves the original file and read-only attribute.
- Inno 7 version probing and padded OriginalFilename resources needed explicit
  handling so the updater could dispatch the native installer format.

An inert executable envelope fixture was blocked by Windows application control.
No security setting was relaxed. The relevant successful-install and failure-exit
behaviors were subsequently measured using the complete native Setup above.

## Remaining gates

- Real provider sign-in, account consent, MCP roundtrip and a model response in
  the installed application. Synthetic cookies do not qualify authentication.
- A disposable clean Windows installation, cross-version upgrade and rollback,
  registration/startup behavior and reboot acceptance. A new folder on this
  development computer is not a clean operating-system environment.
- Physical Android/iPhone LAN or VPN, suspension, reconnection and revocation.
- Release packaging/upload and download-site updates were completed in the
  subsequent publication below. Trusted automatic-update eligibility remains
  unqualified.

Code signing remains absent as agreed for this preview. Existing automatic
update signature/admission gates were retained.


## Preview publication and subsequent checks

[Windows Setup 1.0.3](https://github.com/vitorGgC569/SENTRA/releases/tag/installer-preview-20261025-1)
was published with three installer parts and six metadata/helper/evidence files.
All nine GitHub asset sizes and SHA-256 digests matched the reviewed local plan.
Independent streamed concatenation matched the complete Setup hash. This does
not qualify a stable release, MSI or signed automatic update.

The later owner-attended account trial recognized Platform login, but automatic
tunnel selection reported multiple visible identifiers. An exact named test
tunnel was reconciled by read-only observation and reused. No verified MCP
roundtrip or model response is claimed by this record. A test-harness-only
USERPROFILE override initially prevented Electron resolving AppData; it was
removed, without changing the packaged application or Windows profile settings.

An Android 35 x86_64 emulator booted with WHPX, without changing Windows optional
features. The published ARM64 APK installed but could not load its ARM64 React
Native library on that x86_64 runtime. An unpublished x86_64 QA build was
dispatched; this is not evidence of phone pairing or a replacement public APK.
Hyper-V management is denied to the current session and no Windows installation
image was available. iOS Simulator requires macOS/Xcode.

See the [subsequent live account and emulator record](LIVE_ACCOUNT_AND_EMULATOR_2026-10-25.md)
for verified login observations, two source compatibility corrections and their
separate qualification status. Post-package fixes are not included in Setup 1.0.3.
