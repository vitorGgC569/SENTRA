# Native Dot activity bar — local Windows delivery

The subsequent [original Coucou island delivery](WORKSPACE_STATUS.md)
supersedes the floating-bar visual description and Canvas binary hash below.

## Installed result

The physical installation at `C:\Users\vitor\AppData\Local\SENTRA\Commander`
has been updated and opened with the current Canvas executable and Electron
display. This is a local development delivery, not a published or signed setup.

The installed display reported two real Dots, a fresh authenticated observation,
the native bar visible, a working system tray and two connected monitors.
`physical-install.json` under `.tmp/native-presence-delivery/` records the
observation and installed hashes without credentials or conversation contents.

The final Canvas executable SHA-256 is
`38642031753a9463f893f62edae9c8a3046733ae29fe7008154d23b3f8aef096`.

## Operation

- Open **SENTRA Canvas** using the new Desktop shortcut.
- The floating bar remains available when the main window is minimized or hidden.
- Close the main window to keep the display in the Windows system tray.
- Right-click the SENTRA tray icon to show/hide the bar, select its monitor,
  or open conversation, Canvas and approvals. Approvals open for review; these
  shortcuts never grant permission themselves.
- Use **Sair da interface do SENTRA** for an explicit display exit.

The bar receives a bounded, sanitized projection from the same authenticated
SENTRA shell. It has no network access, broker credential or executor. Stale
observations stop working animations and show an unavailable indication.
Reconnection updates observations without resending work or creating terminals.
An authenticated second launch can replace an expired broker handoff.

The source launchers use Windows process breakaway where supported. For this
delivery, `Open-InstalledCanvas.ps1` launched the installed application through
the Windows interactive task service, outside the development app's nested
jobs. The on-demand registration has no triggers and is immediately removed.
Its explicit launch context allows Windows to own the application's lifetime
where Task Scheduler forbids child breakaway. No password is stored or elevation
requested. Normal subsequent launches use the Windows shortcut.

## Validation

- 231 frontend unit tests passed.
- 47 Python tests passed, covering broker lifecycle, process lifetime, staging,
  terminal input receipts, Dot companions and the approval inbox.
- 13 Electron tests passed, including actual sandboxed renderer isolation,
  native rendering, hide/reopen, keeping the bar visible with its owner hidden,
  conversation/Canvas/approval IPC and disconnect/reconnect without extra windows.
- The native integration fixture placed the actual bar on both connected
  1920 × 1032 work areas and checked that it remained contained. This fixture
  used synthetic Dots and no installed account or backend.
- Unit cases also cover monitor removal, negative coordinates, portrait and tiny
  work areas, forged senders and rejected actions.
- A real Windows process test closed a caller's kill-on-close job and confirmed
  its independently launched child survived. Other Windows-managed jobs may
  still exist; `IsProcessInJob` alone cannot establish dependence on Codex.
- Installed readiness was observed separately against the real persisted Dots.
  Test results do not imply a real approval was submitted or a real task replayed.

Logs are under `.tmp/native-presence-*.log` and
`sentra_canvas/desktop_ui/.tmp/presence-full-ui-tests.log`.

## Visual refinement

The shared Coucou-inspired palette now applies to Home, Dot and conversation
lists, conversation composer, workspace, dialogs, configuration inspectors,
documents and the network screen. Network connection and advanced coordination
forms are progressively disclosed. Documents use a constrained reading surface.
Native activity uses the same dark materials, orange accent, typography and
original SENTRA companions. Visual acceptance remains an iterative user review.

## Recovery and scope

The patch replaces only Canvas and display files. It keeps the installed Electron
runtime and preserves the separate desktop, MCP, browser relay, Web Models,
accounts, cookies and existing user databases. Only newly launched idle Canvas
owners were restarted; their terminal and task inventories were checked empty.

Backups of replaced physical installation files and their before/after hashes:

- `.tmp/native-presence-delivery/physical-installed-backup/` — original physical installation.
- `.tmp/native-presence-delivery/physical-final-backup/` — immediately preceding delivery.

Restore files only with Canvas idle and the display exited. The local updater
refuses to replace an active broker and rolls back file changes on failure.

Windows packaged-app filesystem redirection initially targeted a private Codex
copy. A separate Windows-owned inspection and update were necessary to confirm
and change the physical installation; a hash observed only inside Codex was
insufficient evidence of delivery.
