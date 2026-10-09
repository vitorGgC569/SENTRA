# Agent-assisted installation and release

This workflow belongs to the **SENTRA Desktop distribution** workstream. The
native SENTRA multi-agent terminal/canvas runtime is developed separately;
do not edit those modules in this workstream.

## Entry points

Run these commands from the repository root on Windows using the authorized
user session (Desktop Commander, Codex, or an ordinary terminal). Start with
read-only/low-impact diagnostics:

```powershell
python -B scripts/commander/release_assistant.py doctor
python -B scripts/commander/integration_probe.py --install-dir .
python -B scripts/commander/edge_store_assistant.py doctor
python -B scripts/commander/setup_assistant_cli.py --help
```

The release doctor checks prerequisites but does not mutate Git, compile
software, retrieve secrets, install packages, sign binaries or publish anything.
The **setup** doctor initializes SENTRA-owned local runtime state; it does not
create external OpenAI credentials or request permissions on your behalf.

## User-approved local setup

```powershell
python -B scripts/commander/setup_assistant_cli.py doctor
python -B scripts/commander/setup_assistant_cli.py start-local --approve
python -B scripts/commander/setup_assistant_cli.py workspace --workspace "C:\my-project" --permission read --approve
python -B scripts/commander/setup_assistant_cli.py install-optional --optional git --approve
```

The default starter workspace can be created with `workspace` (no external
folder required). An existing project must receive explicit approval. To
connect OpenAI, create the tunnel and Runtime API key with All permissions in your own
account first, and supply the key only via a private environment variable
controlled in the user's session. **Do not paste Runtime keys into a chat.**

```powershell
python -B scripts/commander/setup_assistant_cli.py connect-openai --tunnel-id tunnel_YOUR_ID --approve
```

After successful local Connect & Verify, SENTRA Desktop → Guided ChatGPT connection → **Install plugin in ChatGPT** checks the local MCP/tunnel health, copies only the Tunnel ID, opens ChatGPT, and gives the account-owned plugin installation steps. It does not bypass the ChatGPT risk warning or install a plugin on behalf of the user. The official UI is ChatGPT → Plugins → + → Add custom MCP server → Tunnel; the account owner must review, create and install the plugin.

### Browser-assisted enrollment during initial Setup

In SENTRA Setup choose **Optional: Connect ChatGPT during setup** and select
the authorization checkbox for **automatic tunnel and NEW key creation (All)**. The installer
first installs the local product, then opens SENTRA Desktop directly at
`sentra://openai-enroll`. It never tries to save credentials into an
uninstalled or unverified runtime. If the product is already installed, the
same option opens the existing installation.

The checkbox explicitly authorizes creation, All permissions, capture,
DPAPI storage and connection. A single-use, DPAPI-protected grant tied to the
installation passes this consent to Desktop; there is no second SENTRA prompt.
An enrollment deep link alone does not authorize these actions. Starting
directly from Desktop asks once and retains authorization for retries in that
Desktop session.

SENTRA uses Playwright's official Edge channel in a temporary, nonpersistent
profile. After the user logs in to `platform.openai.com`, SENTRA automatically:

1. Reuses the previously configured SENTRA tunnel when visible, or creates a
   dedicated tunnel with a name, description, current organization and ChatGPT
   workspace. A sole discoverable workspace is selected automatically; if
   Platform cannot discover it, setup waits for the account holder to select
   the workspace in that same browser form, without another consent prompt.
2. Selects the Default project (or sole available project), creates a NEW key
   with **All** permissions and chooses **Never** expiration when offered.
3. Reads only the one-time key dialog and saves the secret through DPAPI.
   The key is not returned to callbacks or printed in process output.
4. Verifies authenticated MCP/tunnel readiness. Failed verification restores
   the previous encrypted configuration; interrupted recovery retains a
   recovery copy. Enrollment and key rotation share a lock so a background
   tunnel restart cannot race credential verification.

The installer defaults to the **Full** profile and **Computer** scope. All
tool surfaces are enabled within the Windows user's existing rights.
ChatGPT custom plugin installation remains an account-controlled step.

The assistant never automates password entry, enumerates cookies, attaches
to a personal Edge profile, bypasses an MFA/CAPTCHA/risk acknowledgement,
creates organization roles or silently registers a ChatGPT plugin.
Browser memory and temporary session cookies are discarded when closed;
the source code does not persist browser storage. If Edge/Playwright is
unavailable, the manual Secure MCP Tunnel tutorial remains functional.

Official OpenAI references:
https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
https://developers.openai.com/api/docs/guides/custom-mcp-server

The connection command reads `CONTROL_PLANE_API_KEY` from the environment,
stores it through SENTRA's Windows DPAPI secret protection, and verifies the
connection. ChatGPT connector installation/consent still takes place in the
user's authorized ChatGPT account. The account-holder can use the bundled
two-video quick-setup flow under **SENTRA Desktop → Quick Start → Guided ChatGPT
connection**. The upstream videos show a different MCP connector; select the
SENTRA connector in the final ChatGPT step.

## Build and release candidates

Run QA after other development conversations have stopped changing the same
checkout, or use a dedicated branch/worktree with the intended integration
merged. A signed release must use the existing guarded GitHub Actions workflow.

```powershell
python -B scripts/commander/release_assistant.py qa --approve-run
python -B scripts/commander/release_assistant.py candidate --approve-run --tunnel-archive "<verified-official-tunnel-client-zip>"
python -B scripts/commander/release_assistant.py verify --dist "<candidate-output-folder>"
python -B scripts/commander/release_assistant.py smoke --dist "<candidate-output-folder>" --tunnel-archive "<verified-official-tunnel-client-zip>" --approve-run
```

By default, `candidate` refuses a dirty Git tree. For **unsigned local
experiments only**, `--allow-dirty --targeted-tests` can bypass the clean
tree/full-suite gates. Such binaries are **not** stable release candidates.
Never represent hash verification as Authenticode signing, a functional install
test or an approved store submission.

The launcher runs the official Windows build scripts and verifies that all
expected executables are present. Given an official pinned tunnel archive, it
also invokes the existing release assets workflow to produce an unsigned MSI
and Setup artifact. The MSI and Setup must then pass a **real** installation
and uninstall smoke roundtrip in a disposable test folder or VM. The default
build flow is heavy (PyInstaller plus Electron); avoid initiating a fresh build
while the main source tree is changing concurrently.

The current native Canvas package is source-only. A public binary release must explicitly package the Canvas executable and bundled static frontend (without requiring a system Python). A successful build of the older Desktop binaries is not proof that the Canvas shipped. The graph UI end-to-end regression must pass without forcing pointer events through the sidebar.

A formal release requires passing regression tests, code-signing material in
CI secret storage, signed payloads and installer, checked update manifest,
SHA-256, SBOM, signed MSI, executable smoke checks, disposable install/uninstall,
version/tag consistency and no unreviewed source changes. No agent should
silently turn an unsigned experiment into a published release.

## Edge Add-ons

```powershell
python -B scripts/commander/edge_store_assistant.py doctor
python -B scripts/commander/edge_store_assistant.py package
```

The ZIP is useful for QA but is NOT currently an approved store submission.
The original unpacked extension includes an **install-local pairing proof**.
The store upload assistant must not upload that proof: a per-install store
pairing/approval flow is required first. The existing `<all_urls>` permission
has a documented technical dependency on unattended tab capture and requires
a carefully justified scope and store privacy review, rather than an
unexamined permission reduction. These remain intentional *fail-closed*
publication blockers. The product's first submission, store listing, privacy
details and review must be completed through Microsoft Partner Center.

After the first successful store publication, the Microsoft Edge Add-ons
Update REST API v1.1 supports controlled subsequent updates. The helper has
an explicit `--approve-upload` / `--approve-publish` authorization boundary
and reads API secrets from environment variables; the account owner's CI
secret store is preferable. Even a `202 Accepted` only means submission
processing has started, not that an update was approved or is publicly live.

Official reference:
https://learn.microsoft.com/en-us/microsoft-edge/extensions/update/api/using-addons-api

## Release completion gates

- [ ] New first-run UI manually tested with keyboard navigation, video
      playback and accessibility on supported Windows environments
- [ ] Autostart enabled/disabled and preserved across upgrade/uninstall
- [ ] Fresh local install succeeds without Tunnel ID or Runtime API key
- [ ] External ChatGPT guided flow verified with real user approval
- [ ] Credentials redacted in installer output, exceptions, logs and reports
- [ ] EXE and MSI packaging both contain onboarding tutorial videos
- [ ] Full test suite green (fix any tool-count-contract regressions)
- [ ] Clean worktree and source/assets pinned for a reproducible build
- [ ] New signed or explicitly unsigned QA Setup + MSI built from current source
- [ ] Real installer and uninstaller smoke tests, upgrade, rollback and data safety
- [ ] Edge store-capable per-install pairing and permissions/privacy review
- [ ] Edge Partner Center first publication and subsequent update workflow
- [ ] Authenticode signing certificate, GitHub secrets and protected release CI
- [ ] Final smoke checks on a fresh Windows profile/VM
- [ ] Final SENTRA native agent manager merged without breaking Desktop setup
