# Coucou / macOS visual refinement

The existing Coucou-inspired implementation retained the old grey/blue SENTRA
skin. This checkpoint replaces that skin across the application with a shared
visual system derived from the pinned Coucou Windows/macOS palette and scale.

## Design

- Coucou dark palette: OLED-black sidebar, `#0e0f11` canvas, `#18191c` cards,
  `#1f2024` fields, `#f5f6f8` text and `#fb923c` primary actions.
- The light theme uses neutral macOS-style surfaces and darker orange text;
  white and orange buttons have explicit foreground colours.
- Native system font stack: SF Pro where installed, Segoe UI Variable on Windows.
  No font download, Apple assets or new dependency.
- Home gets a warm hero band, smaller continuation/start surfaces and clearer Dot
  cards. Sidebar, typography, focus, field and button styling are consistent.
- Conversation gets a calmer transcript and raised composer. Canvas tabs,
  splitters, side panels, welcome state and status bar share the same palette.
- Documents, computer tabs, context menus, configuration dialogs, decision cards,
  island and hub use the same surface tokens. ANSI terminal content is untouched.
- Narrow layouts, reduced motion, reduced transparency and forced colours have
  explicit rules. These are implementations, not claims of interactive acceptance.

## Files and delivery

The central stylesheet is
`sentra_canvas/desktop_ui/src/shell-coucou-macos.css`, imported **after** the old
polish sheet by all seven existing entries that load it
(production plus six QA entries). It overrides the legacy monochrome CTA rules,
including their stronger dark-theme selectors.

The existing isolated QA page accepts `?view=home`, `canvas`, `dots`,
`conversations` or `spaces`; its default remains Canvas. It continues to use
fixture data and does not call production services.

The desktop bundle was compiled and materialized using the existing sealed-input
build. The generated static assets now include the new design and the source
corrections from the previous checkpoint. No setup was rebuilt, no installed
session restarted, and no backend or authorization behavior changed in this
visual checkpoint.

Interactive visual acceptance remains pending: browser control reports
“Local browser use is disabled in Work settings.” Opening the Home preview was
queued in the Codex panel; that is not evidence of inspecting its rendering.
No unit tests were added or run for this styling-only request. The desktop build
completed successfully; its existing chunk-size warning remains.

Origin: Coucou `1e5180921c1326fc72e41d313e3e2855e9c10162`,
`windows/src/style.css`, `windows/src/hub/hub.css` and
`windows/src/settings/settings.css`. MIT notice and source hashes are in
`vendor/coucou`. The characters remain SENTRA's original Dots.
