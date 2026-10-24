# Headless Windows acceptance — 24 October 2026

The checks below used no interactive computer/browser control, model inference,
physical phone, or real pointer/keyboard input. Private projects, credentials,
processes and loopback endpoints were created only for QA. The user's installed
application and existing accounts/sessions were not replaced.

## Published 1.0.2 binaries

Source: `62d61fa65fec9b79a0f531a91ccafd2fd3163615`. Setup SHA-256:
`e005f82bcef7d4ab8955d8f4061d423bb8d443f343be8742d0189f5e00b8a678`.
The Setup-installed Canvas SHA-256 is
`35cb224e558f6cbf7cf923961a0d582bc8ca35ee1a6fd2c29289466f54513564`.
All fourteen installed executable hashes were rechecked before testing.

### Installed daemon endurance: passed

The requested 1,800-second trial finished in **1813.4 seconds**:
three physical ConPTY workers, **3 broker-object reopenings** and
**531 checkpoint observations**, with the same worker PIDs,
advancing checkpoints, recovered input confirmations and one physical execution
of the duplicated input identity. The owned daemon closed normally.

The daemon was the actual frozen Setup-installed executable. The controlling
Canvas objects came from its sealed source snapshot. Python generated the
synthetic output/input workload; it is not a client installation requirement.
This trial does not itself prove HTTP terminal rendering or visual UI recovery.
The earlier owner-interrupted 563.1-second trial remains recorded as interrupted.
Bounded history pruning is not a promise to retain every output byte indefinitely.

### MSI administrative image: passed with the unchanged artifact

MSI SHA-256:
`776b4c89979b71af270bf0ec5276721c14516835e4b10e927b9b9f590bd590c2`.

The retained failure returned 1619 when Windows Installer opened the caller's
redirected local-data alias. The native path obtained from the open file handle
identifies the same physical file and hash. Using that path, `/a /qn /norestart`
returned **0**. The four external CABs and their inventory were verified;
**14 executables and 7,808 distribution files** matched, along with runtime
sidecars and extension identity. No security setting or MSI byte was changed.

The extracted frozen broker then rejected unauthenticated access, served
**122 hash-verified static assets**, and preserved its workspace and SSE
snapshot availability after a real broker restart.

Administrative extraction is not a registered MSI installation, upgrade,
uninstall, rollback or clean-Windows-VM test. The public release still excludes
MSI/CAB downloads until those separate acceptance steps are completed.

### Mobile protocol: 27 passed, zero skipped

Real encrypted loopback clients exercised pairing, Dot scope, credential
rotation, revocation, broker reconnection, scoped presentation streaming and
terminal receipt recovery without repeating physical input. Selected cases used
the Setup-installed mobile launcher, Node 24.20.0 and bundled gateway. The
production broker ran from source in private fixtures. Pointer/keyboard release
logic used simulated devices; no physical desktop input was sent.

This is not Android/iPhone hardware, OS suspension, real Wi-Fi or private-VPN
acceptance. The published Android v8 APK was not driven on a phone in this run.

## Real defect found, fixed and frozen-candidate checked

The published binary returned HTTP 500 for the owner
`/api/terminal/output` route with a durable terminal. The HTTP cursor remained
a string while the daemon requires an integer. The ordinary source tests had
not exercised that route with the durable backend enabled.

The new actual-ConPTY regression failed before the fix. Commit
`15f2c2e566bd2cd113e6d1bf1015e959c736531f` validates a single bounded ASCII decimal cursor,
converts it to an integer and returns HTTP 400 for invalid/ambiguous cursors.
**20 related frame, receipt and recovery tests passed**.

Only a QA Canvas was rebuilt, below normal process priority. Candidate SHA-256:
`dce0e6c2eb563792475dfa424d9aff6eedf027321f8ba96d768b50df71213392`. It passed the frozen HTTP/assets probe and a
stronger crash scenario:

1. Send one command and discard its HTTP response.
2. Confirm the private worker started, while a fixture gate prevents completion.
3. Kill the actual frozen broker, preserving the daemon and worker PID.
4. Reopen the broker and reconcile/acknowledge the original receipt by observation.
5. Release the fixture gate; independently verify 200 values totaling **20,100**.
6. Close the terminal, recheck one physical execution, and verify all owned
   brokers and the daemon stopped. No extra worker or input resend was observed.

The delivery receipt explicitly did not claim task completion. Result checking
was separate. This is a synthetic PowerShell job, not an autonomous-model or
Web-provider crash-recovery proof.

**The cursor fix is not in the published Setup 1.0.2 or the user's installation.**
The candidate is not a full Setup or an automatic update. A subsequent full
Windows package must incorporate and requalify this correction before shipping.
The released daemon endurance/MSI results do not retroactively remove this API
bug from the released broker.

## Reproduction and remaining acceptance

- `scripts/qa/terminal_soak.py --binary <Setup-installed Canvas> --state <new private directory> --seconds 1800 --correlated-inputs`
- `tests/qa/astra_frozen_canvas.py <Canvas> --proof <matching provenance JSON> --output <private directory>`
- `tests/qa/frozen_terminal_crash.py --executable <corrected Canvas> --proof <matching provenance JSON> --output <new directory inside .tmp>`

Private detailed logs are retained in `.tmp/headless-qualification-20261024/`.
[Sanitized machine-readable evidence](release-evidence/headless-acceptance-20261024.json)
identifies the exact artifact/candidate boundaries.

Open: full Setup containing the cursor fix, current-user installation update,
registered MSI/clean-OS matrix, Web login/inference in that updated installation,
Electron/external-bar operation, physical Android/iPhone/VPN and real input
acceptance. In-flight model/provider recovery remains distinct from the terminal
fixture. No stable release or new installer tag is approved by these results.
