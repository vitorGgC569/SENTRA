# Original Coucou island in the installed SENTRA display

## Scope

The floating bar now uses the original presentation from Coucou commit
`1e5180921c1326fc72e41d313e3e2855e9c10162`.

Seven unmodified upstream modules are stored in
`sentra_canvas/desktop_ui/src/vendor/coucou/`: CSS, layout, tracked animations,
diff helpers, island state machine, icon paths and ticker. `ORIGIN.json` records
their hashes. The MIT license is included there and in the installed Electron
third-party notices. The DOM helper and React integration are SENTRA adapters.
Characters are SENTRA Dots. No Mochi assets, fonts or recorded sounds were
imported; the optional navigation sound is synthesized locally.

## Presentation and behavior

- Original black island, flush with the top of the work area, original cards,
  icon tabs, spacing, typography and spring/closing curves.
- Compact: 288 × 32; expanded: 640 × 160. The transparent native window is
  720 × 320, with click-through outside the animated shape.
- Original overview/settings arrangement, Dot grid and activity ticker.
- Click to expand, 15-second collapse, 60-second idle hide and 6-pixel wake strip.
- Conversation, Canvas and approvals use the existing authenticated display
  bridge. The island has no execution authority or broker credentials.
- Work animation requires fresh, validated physical execution; verified
  completion differs from idle or uncertain observations.

Main SENTRA pages do not import the island stylesheet. Visual acceptance remains
a user review; geometry checks do not establish a manual pixel comparison.

## Frozen resource lifetime fix

The old one-file broker remained healthy after its launcher exited but lost its
inherited PyInstaller extraction directory. HTML returned 500; JS/CSS returned
404. Independent frozen children now receive
`PYINSTALLER_RESET_ENVIRONMENT=1`, so resources belong to their own lifetime.
Explicit caller environment mappings are copied, not mutated.

## Validation

- Desktop/island production build completed with matching source seals.
- 13 Electron tests passed, including sandbox isolation and a disposable native
  integration fixture. Expanded geometry, black background, top corners, two
  cards and three icon tabs were checked in a real WebContents.
- The fixture checked hide/reopen, reconnect without duplicate windows,
  conversation/Canvas/approval routing and both connected monitor work areas.
  Its data was synthetic; no real approval or execution was submitted.
- 18 Python lifecycle, broker and staging tests passed, including independent
  frozen resource extraction.
- The physical installed Canvas was restarted after confirming empty terminal
  and task inventories. Separate desktop, browser relay, MCP, Web Models,
  accounts and persisted conversations were preserved.
- Physical installed readiness: two real Dots, two displays, tray available,
  connected, preview false. Hashes were inspected outside packaged-app
  filesystem redirection.
- After display and launcher exit, the same broker PID/runtime retained HTML,
  manifest, JS and CSS with HTTP 200 and unchanged hashes. The installed display
  reopened against the same broker.

Evidence: `.tmp/coucou-original-bar/`, `.tmp/coucou-original-native.log` and
`.tmp/coucou-original-lifetime.log`.

## Local delivery

Physical installation: `%LOCALAPPDATA%\SENTRA\Commander`.

Canvas executable SHA-256:
`6ea2844afe790921a1522155caae3a8eac94a4f3a1a29b5d1ab6e5118686bdff`.

This is an installed local development patch, not a signed setup release.
Backups and before/after hashes are in
`.tmp/coucou-original-bar/physical-final-backup/` and
`.tmp/coucou-original-bar/physical-notices-backup/`. Restore only with Canvas
idle and its display exited. Runtime DLLs were not replaced.

This document supersedes the floating-bar visual description and Canvas binary
hash in `NATIVE_PRESENCE_DELIVERY_2026-10-22.md`.
