# SENTRA Zero-Config Quick Start

SENTRA is **local first**. The Desktop/CLI/MCP startup does **not** require a
Tunnel ID, OpenAI Platform key, Codex, Docker or an Edge extension.

## Install and begin

1. Open the signed SENTRA Setup release, choose **Continue**. Setup preserves
   existing settings, uses the current Windows user and starts local services.
2. SENTRA Desktop opens Quick Start. Choose **Open SENTRA Terminal** or
   **Open starter project**. The starter is created in "SENTRA Projects/Starter"
   next to your state directory (normally under your Windows profile), outside
   install/state folders that may be deleted during uninstall. No blanket
   filesystem access is granted when the selected scope is Workspace. The
   installer now defaults to **Full** profile and **Computer** access, enabling
   all SENTRA tool surfaces and read/write/execute access within Windows rights.
3. For an existing project, choose **Add an existing project**. It is granted
   **read-only** initially; write/execute permissions are explicit advanced
   changes.

A working AI conversation additionally requires a usable model provider.
The Desktop detects the managed Web Models catalog and picks an advertised
default model only when no preference is saved. Authentication to a model
provider remains the account holder's responsibility.

## Connect ChatGPT (optional)

In SENTRA Desktop → Quick Start select **Guided ChatGPT connection**. The
quick-setup window embeds the secure local credential workflow and provides
buttons for the two bundled short videos from the pinned Codex Web GPT
upstream (tunnel creation and connector authorization). These videos show the
*upstream product*, so enter keys into **SENTRA's** own fields and authorize
the **SENTRA MCP** connector, not the upstream connector.

Use the **Start SENTRA automatically when I sign in to Windows** checkbox to
change the current user's startup setting. Disabling it does not stop an
already-running SENTRA process; it only affects future logins.

1. In Quick Start choose **Open OpenAI Tunnels** and create/select a tunnel in
   your own OpenAI Platform organization.
2. Choose **Open Runtime API Keys** and create a key with **All** permissions.
3. Paste the Tunnel ID and key into SENTRA Desktop and click
   **Connect OpenAI & Start**. SENTRA stores the key encrypted under the current
   Windows account (DPAPI), initializes the packaged pinned tunnel client,
   starts local services and checks health and readiness.
4. Complete the corresponding ChatGPT MCP plugin/app connection in ChatGPT.
   Authorization in ChatGPT is a separate account-controlled step.

For automatic setup, select the authorization checkbox in Setup before
installing. It explicitly covers tunnel creation/selection, creation of a
**new** key with **All** permissions, reading its one-time reveal, DPAPI
storage, and starting/verifying MCP and tunnel. Setup passes a DPAPI-protected,
installation-bound, single-use authorization to Desktop (valid for 30 minutes).
Desktop opens a temporary Edge window; sign in there and let setup continue.
The key uses the Default project (or sole available project) and **Never**
expiration when offered, so runtime access does not expire after a preset month.
No second SENTRA approval is needed. Opening the enrollment deep link without
that authorization prompts for consent once in Desktop.

The previous encrypted tunnel configuration is retained until verification
succeeds and restored if verification fails. An incomplete recovery preserves
an encrypted rollback file. Changed Platform controls or unavailable `All`
permissions stop automatic submission and leave the manual setup available.
Platform organization tunnel roles and login/MFA must be available for the
account; selecting `All` does not grant organization roles. ChatGPT plugin
installation and model-provider login remain separate account steps.
New tunnels also need a ChatGPT workspace association. Setup selects a sole
discoverable workspace automatically; otherwise choose the correct workspace
in the Platform tunnel form and setup resumes. A healthy local tunnel does
not prove access from a different ChatGPT account/workspace.
If Platform says it cannot automatically verify the workspace/organization
association, use its **Contact support** action to request a reviewed manual
association. `All` key permissions cannot override that OpenAI account boundary.

Do not paste Runtime API keys into chat, command-line arguments, browser
extension configuration or bug reports. Credential invalidation blocks only
the ChatGPT connection, not local MCP tools.

## Optional capabilities

- **Codex / Web Models:** choose **Enable Web Models / Codex**, sign in to the
  managed interface, connect Codex and verify. An existing Codex route must
  be preserved and restored when disconnecting.
- **Edge:** use the optional browser section in Quick Start. The relay can
  run without an extension: health only reports the browser feature ready
  after the extension connects. The current extension uses the Edge
  Developer Mode / Load unpacked flow until a signed Edge Add-ons submission
  has been approved and published. Publication cannot be automated locally.
- **Git / Docker / Ollama:** Desktop **Show advanced → Workspaces & Policy** has
  approved on-demand installs. Installation never starts without user
  confirmation. Docker CLI presence alone does not prove the daemon works:
  sandboxed workloads stay blocked if isolation is unavailable.
- **Offline/local AI:** Install Ollama (if needed), then choose **Download local
  AI model** to retrieve the lightweight Qwen2.5 0.5B model (~400 MB).
  Both software installation and model downloads require explicit consent;
  smaller models may have limited coding quality.
- **Remote agent:** pair only when needed, using the existing explicit
  relay URL and pairing code.

## Doctor and self-healing

**Doctor** distinguishes the local runtime from optional accounts, models,
browser and dependencies; it lists actionable next steps. Local MCP and relay
are supervised with a bounded grace period, cooldown and retry ceiling.
The tunnel keeps its own bounded supervisor, including fail-closed behavior
when its Runtime API key is revoked. A port owned by another process must
not be killed or silently reclaimed.

## Implementation

- `sentra_remote/onboarding.py`: independent readiness and guided OpenAI
  stages; request `intent="chatgpt"` when guiding external connection.
- `sentra_remote/setup_assistant.py`: capability detection, starter workspace,
  least-privilege folder grants, consent-aware installs and tunnel configuration.
- `sentra_remote/local_runtime.py`: local-optional readiness, independent
  ChatGPT integration result and bounded local/tunnel supervision.
- `sentra_remote/installer.py`: install-first wizard, collapsible OpenAI setup,
  starter workspace and local-first launch.
- `sentra_remote/desktop.py`: task-first Quick Start, doctor, approved
  dependencies and optional Codex/Edge setup.

## Known external prerequisites

No local code can create OpenAI organizational permissions, complete account
login, approve a ChatGPT plugin authorization, publish a Microsoft Edge Add-ons
extension or sign a public release without the corresponding credentials and
owner approvals. The local wizard reduces the work around these actions but
does not claim that they have already happened.
