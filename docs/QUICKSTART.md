# SENTRA Desktop — 5-minute quickstart

> Quer entender todas as formas de usar o produto antes de configurar? Veja **[START HERE](START_HERE.md)**.

## 1. Install

Download the signed `SENTRA-Setup-<version>.exe` from the GitHub Release and run it.

The installer is per-user by default. It installs under:

```text
%LOCALAPPDATA%\SENTRA\Commander
```

Private runtime state is stored separately under:

```text
%USERPROFILE%\.sentra
```

No API key or device credential is stored in the installation directory or Git repository.

## Primeiros 5 minutos

Para o primeiro uso, não configure tudo de uma vez:

1. Abra o **SENTRA Desktop** e confirme que o MCP inicia.
2. Para usar o SENTRA diretamente, teste o **Terminal / SENTRA CLI**.
3. Para o ChatGPT chamar tools locais, configure **Secure MCP Tunnel**.
4. Para usar ChatGPT/Gemini Web dentro do Codex, configure **Web Models → Conectar Codex**.
5. Só habilite a **extensão Edge** se algum fluxo precisar operar uma aba web existente.

Quando aparecer **MCP ✓ Ready** e **Tunnel ✓ Ready**, o caminho ChatGPT → SENTRA já está pronto; Web Models e Edge são capacidades adicionais.

## Escolha o seu caminho em 30 segundos

| Objetivo | Use | Precisa do quê |
|---|---|---|
| Conversar e executar tools no terminal | **SENTRA CLI** | instalação local + workspace autorizado |
| Usar ChatGPT/Gemini Web dentro do Codex | **Web Models** | login Web + Gateway local conectado ao Codex |
| Fazer o ChatGPT chamar o SENTRA | **Secure MCP Tunnel + app/plugin MCP** | `tunnel_...` + Runtime API key Restricted |
| Automatizar uma aba já aberta no Edge | **Extensão Edge** | Edge principal + extensão pareada ao relay local |

O fluxo recomendado para um primeiro uso completo é: **Install → Connect OpenAI → Confirm Ready → escolher uma superfície**. Instale a extensão Edge apenas se o seu fluxo realmente usa navegador/Web Models.

## 2. Connect OpenAI

Setup v2 keeps the normal path to two credentials: a `tunnel_...` ID and a Restricted Runtime API key with **Tunnels: Read + Use**. You can enter them during Setup or later in Desktop **Quick Start**.

1. Click **Open OpenAI Tunnels** and create/select the tunnel.
2. Click **Open Runtime API Keys** and create the Restricted Runtime key.
3. Paste both values and choose **Continue** in Setup; with both values present, Setup installs and connects in one pass. In Desktop, use **Connect OpenAI & Start**.

The Runtime API key is encrypted with Windows DPAPI and cleared from the input after saving. The MCP remains loopback-only; the tunnel is the outbound HTTPS bridge to OpenAI.

Workspace, profile, filesystem scope, Docker and other policy choices are intentionally under **Advanced options**. Fresh installs use the existing compatible defaults; you can add project folders and change policy later in **Show advanced → Workspaces & Policy**.

For the manual/source-checkout flow, see [`SECURE_MCP_TUNNEL.md`](SECURE_MCP_TUNNEL.md).

## Optional: enable the Edge browser plugin

The browser plugin is not required for the core **Ready** state. Enable it only when SENTRA should operate existing ChatGPT/Gemini browser tabs. Open **Quick Start → Open Edge extensions**.

1. Enable **Developer mode**.
2. Choose **Load unpacked**.
3. Select the installed `edge_extension` folder shown by SENTRA Desktop.
4. Leave the extension enabled.

Current product builds pair the extension with the local relay automatically using an install-local proof. **Do not copy a bearer/relay token into the extension.**

The Edge bridge is separate from the Secure MCP Tunnel. It is used only for browser/Web-provider work: SENTRA adopts an existing eligible, inactive ChatGPT/Gemini tab in the principal Edge profile, uses it temporarily, and fails closed when no safe controller tab is available. It does not create or close tabs in the normal principal-Edge path.

## After Ready: choose how you want to use SENTRA

- **Terminal agent:** after installation, open a new terminal and run `sentra-cli` from any folder. In a source checkout, use `sentra-cli.cmd`. Inside the CLI, start with `/status`, `/doctor` and `/models`.
- **Codex / Web Models:** open **Web Models**, click **Abrir interface Web**, finish the Web login, click **Conectar Codex**, restart Codex, then click **Verificar conexões**. Codex must point to the SENTRA Gateway `http://127.0.0.1:17842/v1`, not directly to the upstream sidecar. For Gemini, the integration may support more routes than your current account/UI exposes; `flash` is the default and an unavailable explicit choice fails before the prompt is sent.
- **ChatGPT app/plugin:** after the Secure MCP Tunnel is healthy, connect the tunnel as an MCP app/plugin in ChatGPT. ChatGPT then calls SENTRA tools under the local workspace/profile policy.
- **Browser automation:** install the Edge bridge above. This is what allows SENTRA to operate eligible ChatGPT/Gemini Web tabs when a workflow needs the browser; it is not what exposes the MCP to ChatGPT.

See [`SENTRA_CLI.md`](SENTRA_CLI.md) and [`WEB_MODELS.md`](WEB_MODELS.md) for the terminal and Codex/Web Models surfaces.

## 3. Confirm Ready

Desktop opens on **Quick Start**. The core Ready state is intentionally simple:

```text
MCP      ✓ Ready
Tunnel   ✓ Ready
```

Edge, Docker/Sandbox, Git, Remote Agent and Web Models are capability-specific checks, not blockers for the basic Install → Connect OpenAI → Ready journey. Choose **Doctor** whenever Quick Start says a component needs attention; the visible message includes the next action and the Status page keeps recent service errors without exposing Runtime API keys or device tokens.

## Advanced: persistent ChatGPT + Gemini swarm

For one shared implementation goal, SENTRA can keep logical Agents persistent
while their physical ChatGPT/Gemini conversations remain replaceable:

```powershell
sentra swarm start --goal "Implement feature X" --workspace C:\path\to\repo --rounds 3
```

Use `--execute` to let OMA consume the swarm's shared context and run the
deterministic implementation/Quality Gate. Model agreement never promotes code;
promotion remains explicit.

For a low-cost smoke cycle, add `--profile lean` (one ChatGPT + one Gemini).
The normal `balanced` profile uses seven specialists. To resume the same
logical Agents and conversation bindings:

```powershell
sentra swarm continue <run-id> --rounds 2 --execute
sentra swarm status <run-id>
```

The collaboration loop is bounded:
`discover -> peer_questions -> cross_review -> implement -> test -> challenge -> synthesize`.
Questions are targeted through the Context Bus rather than unrestricted
all-to-all fanout, and uncertain browser delivery is never replayed automatically.

## Next steps

- Add/remove workspaces and edit read/write/execute permissions.
- Queue an OMA task in **Jobs & Queue**.
- Start a persistent ChatGPT + Gemini swarm for a shared implementation goal.
- Inspect the current Git diff before changes.
- Create a snapshot before risky work; use rollback when required.
- Pair the optional Remote Agent only when another SENTRA relay/device workflow is needed. The Agent inherits the current Profile and Filesystem scope and re-synchronizes that policy before each start.

For the full tunnel setup and OpenAI Platform permission model, see
`docs/SECURE_MCP_TUNNEL.md`.
