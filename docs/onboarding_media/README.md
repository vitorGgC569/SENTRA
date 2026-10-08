# Tutorials for connecting the SENTRA Secure MCP Tunnel

These bundled example videos were copied from the pinned
`codex-chatgpt-web` upstream checkout:

- `launcher/src/assets/mcp-create-tunnel.mp4`
- `launcher/src/assets/mcp-connect-connector.mp4`

Source: https://github.com/miuuyy/codex-chatgpt-web
Pinned upstream reference: `v6.1.1` (`a13cd09950969f43e3b7e25c71fa43efaf5446c5`)
Upstream repository license: MIT (see `third_party/codex-chatgpt-web/LICENSE`).

The local `SENTRA_SETUP_GUIDE.html` is an original SENTRA-produced offline page
that plays these MP4 tutorials inline without requesting credentials or
loading third-party media. It is not part of the upstream media license.

The videos illustrate **OpenAI Platform and ChatGPT UI steps**, but show
an integration belonging to the upstream Codex Web GPT product. SENTRA uses
its **own** Secure MCP Tunnel, so its Tunnel ID and Runtime API key with All permissions
must be entered in the SENTRA Desktop wizard, *not* copied into the upstream
application. The final ChatGPT connector must also point to the SENTRA MCP
configuration. These credentials must never be placed in chat or logs.

Packaging: `scripts/commander/build_windows.py` includes `docs/` when
building the Setup payload; `sentra_remote/installer.py` installs that docs
tree. The Desktop wizard locates these trusted bundled videos through
`sentra_remote.onboarding.tutorial_video_path`.
The Setup also opens the local HTML guide directly from its bundled docs before
installation. The current SENTRA instructions use All permissions and no expiration;
the upstream videos are illustrations and may show different account interfaces.
