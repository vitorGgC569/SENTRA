# Canvas file editor — October 22, 2026

## Delivered in source

The existing file tab now composes the existing CodeMirror editor. It starts in
read mode and offers Edit, Save, discard draft and explicit conflict comparison.
The outer SENTRA navigation is unchanged. Browser/computer/conversation transport
and installed sessions retain their existing services.

Drafts are encrypted with the existing DPAPI/keyring conversation codec in the
host's shell database. Their key includes owner, project, Space, Dot, conversation,
execution workspace and relative path. The schema is versioned, updates use a
monotonic revision, and clearing retains the revision to prevent ABA. Equal-content
recovery is idempotent. The bounded initial implementation permits 512 entries per
owner and 128 KiB each for base text and draft text. Draft restoration is data
retrieval and never starts a terminal, grants access or replays a physical save.

The original bytes' SHA-256, original text, current draft and UTF-16 cursor/selection
positions are retained. Removal or external edits do not erase the stored draft.
Saving first confirms the exact protected draft version, then uses the existing
`dot_computer_action` → `machine_execute` → `workspace:file.write` path. Every save
has its own request identity, central Grant/WorkItem and durable output capture.

The files machine checks the expected execution workspace at the request boundary;
its root still comes from the authoritative work assignment. An old tab cannot
silently save into a newly selected worktree. Legacy file tabs without complete
conversation/workspace identity ask the user to reopen the file from its Dot.

Full access prepares the configured files machine alongside the existing terminal
resources, derived from the owner's live full-access selection. A read-only editor
query never creates Grants. Revocation remains effective at central admission.

The renderer keeps only pending selectors in its workspace journal. File content
is excluded from the older sessionStorage mutation cache. A lost confirmation is
queried by original fingerprint; the write is never automatically repeated. A
successful operation only clears a matching draft after the receipt hash, current
file hash and submitted draft bytes agree. Draft CAS still protects other windows.

## Confirmed refusal and uncertain effects

A changed binding is refused before executor dispatch. A CAS mismatch detected
under the output lock raises a trusted backend exception before publication;
the receipt is FAILED with `workspace_file_revision_conflict`, freeing the machine
lease for an explicitly reviewed follow-up. Provider error text and response
flags cannot construct that exception.

Errors after possible publication, failed durable capture, timeouts and revoked
authority after dispatch retain UNCERTAIN semantics. The existing capture-failure
regression verifies that the output is not automatically published a second time.
The per-path lock coordinates SENTRA writers; it does not claim a filesystem-wide
transaction against arbitrary external programs that ignore that lock.

## Validation

- 52 unique Python cases passed across the editor/atomic-output and broader
  full-access/workspace/recovery regressions. One symlink case was skipped because
  this Windows host could not create the test link; it is not qualified by this run.
- 160 desktop Node cases passed, including eight editor state/contract cases.
- The new JSX modules passed in-memory syntax transformation.
- Real HTTP, Git/worktrees, central admission, DPAPI and atomic file capture were
  used. Model generation was not used in this round.
- An injected connection reset after a real committed write was recovered by a
  read-only receipt query, with unchanged file modification time and one dispatch.
- A real isolated worktree accepted the correctly pinned edit, rejected the old
  project selector and left the main repository's file unchanged.

Detailed reports: `.tmp/workspace-editor-python-final.xml`,
`.tmp/workspace-editor-regression.xml`, and
`sentra_canvas/desktop_ui/.tmp/editor-node-regression.log`.

## Pending

Interactive renderer/visual acceptance remains pending. Launching the disposable
Electron fixture was rejected by automatic tool approval with only “blocked by
policy” returned. No renderer pass or screenshot is claimed. Prepared fixture:
`sentra_canvas/desktop_ui/test/file-editor.{html,jsx,cjs}`; it uses a simulated host
and must not be represented as a production backend or real Grant test.

No bundle, installer, new tag or installed application update was generated for
this source milestone. The earlier Windows preview remains pinned to its original
commit. The validation-build manifest describes earlier outputs, not this editor.
Full migration acceptance, real three-Dot model completion, ACP, physical mobile
devices, relay and signed distribution remain open in the implementation tracker.
