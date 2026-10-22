# Direct mobile delivery and execution acceptance — 22 October 2026

## Delivery scope

The owner selected a local host reached directly over LAN or a private VPN.
A public relay, public port forwarding and hosted login are not required.
The mobile device still pairs with the pinned host identity and receives an
explicit project/Space/Dot scope. Pairing never grants unrestricted execution.

The [download page](https://vitorggc569.github.io/SENTRA/) presents the app with
screenshots captured from disposable demonstration fixtures. The first signed
Android ARM64 preview is [mobile-preview-20261022-1](https://github.com/vitorGgC569/SENTRA/releases/tag/mobile-preview-20261022-1).
It predates the later browser-frame, palette and continuation changes; builds
are identified individually rather than changing an existing release asset.
There is no Apple Developer account or published iPhone installation channel.
No unsigned IPA or simulator bundle is offered as a phone installation.

## Completed source and local protocol checks

- The installed gateway can be explicitly enabled in Devices, using a bundled
  Node 24 executable and compiled gateway. Runtime hashes and dependency notices
  travel with the package; the user does not need npm or tsx.
- Automatic address selection prefers physical LAN. A reachable private VPN
  interface can be selected explicitly; RFC1918 and 100.64.0.0/10 are accepted.
- The production gateway bundle passed encryption, pinning, identity mutation,
  replay refusal, connection replacement and encrypted Canvas pairing/revocation
  checks. These are local automated clients, not physical Android/iPhone tests.
- The existing browser machine now supplies an optional bounded JPEG of its
  actual Playwright viewport. Image hash, observation identity, page identity
  and policy checks are verified. Desktop semantic actions use the same central
  operation journal. This is not full ORCA Design Mode or unrestricted remote input.
- A clean workspace adopts a newer host layout revision. Unsaved local changes
  retain their conflict instead of being overwritten. Mobile can reopen an
  existing recent resource; it never recreates the resource from a saved layout.
- A stalled renderer is disposed and restored as a viewer. Observation timeouts
  release read credits, preserve uncertain input, and never restart a PTY.

## Real concurrent Dots / worktrees

`tests/qa/dot_worktree_execution.py` passed with `sentra/codex/current`, one
owner Full selection, zero manual Grant calls and three model-created workers.
Each worker edited its own tracked file in a separate Git worktree and verified
the result by actual read/hash. The three worker operations overlap for about
234 seconds. The main repository remained unchanged; each child was submitted
once. A deliberate overlapping patch was detected, and the same execution
workspace bindings survived broker reopening. No commit, merge or push was
performed by the workers. Conflict injection/reopening are host QA steps.

Local report: `.tmp/sentra-delivery/three-worktrees/report.json`.

## Real pinned ACP / OpenCode

`scripts/qa/opencode_acceptance.py` passed using OpenCode **1.19.3**, ACP v1 and
the advertised free `opencode/big-pickle` model in an isolated provider profile.
No installed model keys, cookies, user OpenCode profile or plugins were used.

Verified: streamed real generation; exact file write after owner approval of
only the matching path with `allow_once`; cancellation requested while awaiting
permission and confirmed by provider `stopReason=cancelled`; explicit transport
relaunch/load of the same session; disconnect while permission is pending;
no unapproved file creation and no automatic replay. A sent cancellation receipt
remains uncertain until the prompt's separate completion confirms cancellation.
The cancelled prompt is never first recorded as success.

Reverse permission questions are retired with their original prompt; the peer
receives a literal cancellation so it cannot block the next turn or inherit a
stale approval. A regression also checks retirement after the original fence
has expired.

Earlier failed attempts are retained, including a prompt that asked for approval
in prose instead of invoking a tool. They do not count as passing cancellation.
Local passing report: `.tmp/sentra-delivery/opencode-real-v10/report.json`.

## Installed terminal reliability

An initial 180-second test passed with three actual ConPTY workloads, concurrent
observation, three Canvas reopenings, unchanged worker PIDs and one physical
input delivery after a deliberately duplicated request identity.

The first **30-minute** run failed with an observation timeout. Its report is
preserved, not converted to success. The protected SQLite transcript reached
its page ceiling because ciphertext-only quota accounting omitted the cost of
many small records. The source correction accounts for row/index overhead,
maintains its budget transactionally instead of scanning the entire transcript
on every chunk, and evicts with headroom. Tiny-frame/rollback regression passes.
The next installed binary must repeat the prolonged acceptance; the earlier
short passing run does not qualify the corrected binary.

Reports: `.tmp/sentra-delivery/installed-soak-v2/report.json` and
`.tmp/sentra-delivery/installed-soak-30min/report.json`.

## Remaining acceptance and distribution limits

- Physical Android and iPhone pairing, suspension, reconnection, revocation and
  remote input; actual private VPN routing across devices.
- iPhone signing/distribution credentials and an installation channel.
- Prolonged corrected installed daemon test, aggregate emulator memory budget,
  extended TUI and installed real-agent CLI recovery.
- Complete orphan recovery qualification, unified sequenced subscriptions,
  browser Design Mode and full remote keyboard/pointer input lifecycle.
- Git cleanup/publication workflows, guest workspace mapping, SSH and connectors.
- Clean-machine Windows setup, upgrade/rollback and independently qualified
  signed distribution. A local Canvas patch is not a new full Windows setup.

The macro migration is still open. Direct LAN/VPN delivery does not claim these
remaining criteria have passed.
