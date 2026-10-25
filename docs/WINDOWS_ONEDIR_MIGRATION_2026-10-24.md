# Windows packaging and embedded account setup — 24 October 2026

Candidate application version: **1.0.3**. This document does not qualify a new
public Windows release. The published 1.0.2 installer remains a different build.

## Packaging

Python components now use PyInstaller `onedir`. Executable names and sibling
launch contracts stay stable. Each executable has a uniquely named installed
support directory, for example `sentra-mcp.exe` and `_runtime_sentra-mcp/`.
Python libraries and the Playwright driver are loaded from these directories
instead of being extracted on every process launch.

The build inventories and hashes dependency files. Setup manifests cover them;
publication rolls back both executable and dependencies when replacement fails.
The updater ZIP and external uninstall/rollback helpers carry their support
directories too. Building directly into a marked installation is rejected.

The default `SENTRA-Setup.exe` build now uses **Inno Setup 7.1.0**. Its native
wizard extracts a compressed offline bundle and runs the SENTRA installation
worker without opening another setup interface. The worker retains ownership,
installation locking, protected settings, registration and data-preserving
uninstall responsibilities; Inno's separate automatic uninstaller is disabled
intentionally. It is not claimed that Inno performs SENTRA's data migrations.

Installation succeeds independently of Web account onboarding. The final action
opens SENTRA once. Accounts are configured inside the application. Existing
signature/admission requirements for automatic updates remain in force.

Build compiler: set `SENTRA_ISCC` to an existing Inno Setup 7.1.0 `ISCC.exe`.
The full-build entry checks for the compiler before starting lengthy work.
Velopack is not part of this migration.

## Embedded account setup

The account panel provides an explicit **Configure connection** action. It
discloses the tunnel/key scope and keeps setup progress and recovery in SENTRA.
Concurrent clicks attach to the same running setup operation.

Platform and ChatGPT setup use one temporary owned view in the managed Chromium
window, with the same persistent session partition used by Web models. Closing
the view preserves that profile. Sign-in and provider consent stay with the
account owner. The implementation waits through the login redirect instead of
closing the setup immediately.

The new adapter uses the existing authenticated loopback host control and fixed
DOM operations. It adds no extension installation or extra debugging listener.
It exposes no cookie export or arbitrary JavaScript operation. Navigation,
extraction origins and setup-session identifiers are checked. Setup refuses to
commandeer a running model turn.

Tunnel health alone does not finish setup. A fresh, expiring challenge must
return through the MCP health tool. The read-only test can be sent from an empty
composer with SENTRA selected; existing drafts are preserved. Manual account
approval and a copyable test remain available. After the test, the isolated Web
adapter is configured without changing native provider routes.

Managed background restarts honor hidden mode even on a fresh profile. Verified
SENTRA setup records completion without requiring the component's separate
onboarding. Managed launches add no second tray icon or component update check;
startup failure is reported through SENTRA rather than a separate native modal.
Explicit foreground requests remain available. Launch-policy regression tests
cover fresh and configured profiles as well as ordinary upstream behavior.

Native models use their providers directly. Upstream subprocesses receive an
isolated Codex home. A legacy global SENTRA route is restored only when its
existing journal proves the baseline and there are no conflicting edits.

## Evidence and remaining qualification

- Source regressions: 237 backend tests and 265 frontend tests passed in the
  initial migration sweep; focused follow-up tests cover the managed setup.
- Real frozen `onedir` probe: installed sibling dependencies and bundled
  Playwright driver passed; no browser, account or product service was opened.
- The Web component compiled with the new embedded setup modules.
- The actual packaged setup module passed a real hidden Chromium fixture:
  Platform extraction, ChatGPT form input, retained synthetic session cookie,
  foreign-origin rejection and stale-session rejection. All HTTPS requests were
  intercepted locally; zero visible windows and no provider account were used.
- The first Web build failed under Windows redirected paths. Native real-path
  resolution corrected the issue; the second build succeeded.
- A stronger fixture using the full packaged BrowserHost then reproduced a
  first-use setup view sized at 1 by 1 pixel. The initial payload build was
  stopped and marked superseded. The setup now uses the actual window content
  size, independently of whether the ordinary browser panel has mounted.
- The third Web build passed the full BrowserHost fixture: setup filled the
  window, Platform login redirects remained navigable, automation on the login
  page was rejected, synthetic profile data survived closing the setup view,
  and no visible window or real provider account was used. This does not prove
  real provider authentication or consent.
- The packaged CLI restored a synthetic legacy native-provider configuration
  from its ownership journal. The test used private homes only. Recovery keeps
  the original lexical home identity across Windows redirected-path aliases;
  it still refuses conflicting edits or an unproven baseline. Local-only
  installation attempts this recovery even when Web onboarding is postponed
  and records whether review is needed.
- The final Web component also passed a full packaged, ordinary managed startup
  with a new profile, system-only PATH and no browser-host-only shortcut. Its
  embedded runtime executed successfully and Windows enumeration observed zero
  visible windows. A separate synthetic cookie survived a Chromium process
  restart. These checks used private profiles and no provider account.
- The Inno compiler was initially absent and automatic installation was rejected
  with `blocked by policy`. After renewed owner authorization, the official
  7.1.0 installer was downloaded, its pinned hash and valid Pyrsys signature
  verified, and the compiler installed. A tiny offline fixture compiled the
  actual Setup script without executing it. Version detection uses `--version`;
  Inno 7's help banner does not contain its full version. The payload candidate
  preceding that build-tool correction was superseded to keep source seals
  exact. Native update dispatch also trims the padding in Inno's OriginalFilename
  version-resource slot. Reproduce with `tests/qa/inno_compile_smoke.py`; it never
  executes its fixture EXE. This is not full Setup installation qualification.
- Real provider login/consent, final Setup clean installation, update, rollback
  and restart acceptance remain required before publishing this candidate.

The user's existing installation, profiles and account sessions were not
replaced by these build and fixture checks. No new tag or download is implied.
