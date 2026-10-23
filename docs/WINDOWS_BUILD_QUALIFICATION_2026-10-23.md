# Windows build and qualification — 23 October 2026

## Result

The full Windows application payload and Setup were rebuilt. **Prolonged
terminal qualification failed. The MSI also failed administrative extraction.**
This is an experimental Setup preview, not a stable or fully homologated release.
The existing installed application, accounts and user sessions were preserved.

The application executables were built from
`8b24da4e9806ea3c01d6f9880d63f61291292483`, using a verified, immutable source
snapshot with SHA-256
`551fda6af65903d4e4e42b98915f726e857f15bea0c7759946f96df3fdee359d`.
The delivery revision adds CI fixture preparation, the download instructions,
an Int64 correction to the external reassembly helper, and this report. It does
not claim that those later delivery files were embedded in the earlier build.

## Actual local artifacts

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Setup | 3,176,796,914 | `360f0c9a6d194d10068a4defcc04c87f6f1c3802c1e1aab9be6627ce092e0f8d` |
| MSI — failed qualification, excluded from publication | 2,902,208,512 | `7dda1907cb7fe6143dbc41259b72fc92b2aad574509273513e16b3928c5a3a5a` |
| Update ZIP — local only | 3,320,840,855 | `6a6df3f3fb3cc212e4baec1b3526085d8adec48f3062955219c45698a8cfa64e` |

Local output directory:
`%LOCALAPPDATA%\SENTRA\Build\closure-20261022-reviewed\release8`.
CycloneDX, component/license inventory, checksums and local release metadata
were generated alongside the packages. No trusted Authenticode signer is
configured. No automatic-update or stable-release channel was enabled.

All fourteen application executables were built. The packaging copy was checked
against every executable hash in the payload provenance. The already completed
MSI and Setup were retained when the update ZIP initially rejected the generic
offline archive filename. The final ZIP uses the same checksum-verified archive
under its expected versioned name; no application executable was rebuilt or
changed during that recovery. The failed attempt remains recorded.

## Checks completed

- Actual frozen CLI timezone/scheduler checks, embedded Canvas timezone data,
  authenticated broker health and packaged desktop asset hashes passed.
- Three actual concurrent ConPTY sessions, snapshot capture and idempotent
  duplicate-request handling passed the short frozen-runtime checks.
- Local encrypted mobile pairing, scoped access, credential rotation/recovery,
  revocation, host identity after restart and mDNS passed with automated clients.
  These were not physical phone or real private-VPN acceptance tests.
- Actual Setup `--check` returned `payload_ok=true`, `payload_verified=true` and
  exit code zero. Account login, installation and operational readiness were
  not attempted by that check; its `homologated` flag remains false.
- Actual frozen Tcl/Tk/ttk creation and orderly window destruction passed.
- Update ZIP CRC checks passed for all three entries. MSI table checks covered
  7,887 consecutive file sequences and four embedded cabinets. Those structural
  checks did **not** predict the administrative extraction failure below.
- The recursive local unit run completed with **4,201 passed, 62 skipped and
  one failure**, plus 14 subtests. The failure was the default-breakaway lifetime
  case run under the explicit `windows-interactive` launcher context. The entire
  lifetime file separately passed **four tests** in its required default context.
  The recursive run remains recorded as failed, not converted to a green run.
- Failure/integration suites: **183 passed, 12 skipped**. Mypy gate: **zero
  findings, maximum zero**. Source identity stayed unchanged throughout that run.
- [GitHub CI for the application source](https://github.com/vitorGgC569/SENTRA/actions/runs/39886529110)
  completed its unit run with **4,197 passed, 66 skipped and one failure**, plus
  14 subtests. Source, Canvas/Edge, Web Models, failure and integration jobs passed.
  The failing installed-path fixture lacked the locked mobile transport packages.
  A clean isolated reproduction failed without them and passed after `npm ci`.
  CI now prepares that transport before the suite; a new full remote green run
  is still separate evidence. Counts from overlapping reruns are not summed.

## Failures that block full qualification

1. **Prolonged terminal observation:** the requested 1,800-second run failed at
   1,430.4 seconds while requesting a checkpoint, with an eight-second HTTP
   timeout. It had observed 417 checkpoints and two broker reopenings. The owned
   test daemon was closed; its retained history database passes integrity checks.
   The exact cause is not established. This does not qualify long-running or
   unattended terminal work and is not evidence that the worker was restarted.
2. **Actual MSI consumption:** `msiexec /a /qn /norestart` into a fresh disposable
   administrative image returned **110**. The Windows Installer log records
   error **131** while preparing its cached MSI. This package is not offered as
   an installable download. Successful database reads and embedded-cabinet checks
   do not override the real failure. No size-limit theory is treated as a proven
   root cause; the CAB/storage arrangement needs correction and a new real test.
3. **External acceptance:** independent clean Windows installation, upgrade,
   rollback, uninstall, trusted publisher signing, physical Android/iPhone and
   real private-VPN operation remain open. No iOS installation channel is claimed.

## Download packaging

Only the experimental Setup is prepared for download, as three parts below
GitHub's per-file limit, a manifest, a reassembly helper and checksums. The
external helper now uses explicit Int64 arithmetic: the real 3.18 GB trial
exposed PowerShell selecting an Int32 overload. Its regression suite passed
26 tests, with one unavailable symlink-privilege case skipped.

Use the [multipart download instructions](WINDOWS_PREVIEW_DOWNLOADS.md).
The helper reconstructs verified bytes; it never executes the installer or
changes the computer's execution policy. Its isolated QA invocation follows
the existing trusted-script test harness. Downloaded scripts remain subject
to the recipient's policy. Integrity verification does not provide publisher
signing or qualify installation. The full-size reassembly result is retained
with the delivery evidence.

## Retained local evidence

- `.tmp/closure-root/windows-build-result8.json`
- `.tmp/closure-root/windows-qualification8.json`
- `.tmp/closure-mobile/frozen-qa-reviewed-result.json`
- `.tmp/closure-root/package-qa8.json`
- `.tmp/closure-root/setup-gui7.json`
- `.tmp/closure-root/msi-admin-image8.json`
- `.tmp/closure-root/soak-candidate7-result.json`
- `.tmp/closure-root/candidate7-soak-1800/report.json`
- `.tmp/closure-quality/full-ci-complete-v3-result.json`
- `.tmp/closure-quality/mobile-ci-fixture7.json`
- `.tmp/closure-root/setup-preview-prepared11.json`

Earlier failed reports are retained. No failed trial was relabeled as passing.
