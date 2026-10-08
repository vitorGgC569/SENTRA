# SENTRA CLI

The SENTRA CLI is the terminal-first SENTRA agent surface. It uses the SENTRA
Model Gateway for Web models, authenticated Codex CLI as a native model transport,
and the native SENTRA Canvas for collaboration. Maestri's public CLI remains an
optional external adapter.
It also shares protected conversation memory with SENTRA Canvas and the local MCP.

## Native Codex model

`--model sentra/codex/current` uses the installed Codex CLI and its authenticated
session. SENTRA does not read or export OAuth tokens. `current` uses the CLI's
default model; `sentra/codex/IDENTIFIER` explicitly selects a model. The native
option appears in `/models` when local authentication is available.

The transport sends context through stdin and requires a final response plus
`turn.completed`. Partial/failed output or native harness tool use cannot execute
SENTRA directives. Uncertain calls never switch providers or replay automatically.
Codex supplies text; SENTRA executes directives under its configured profile and
records effects in its protected journal. New Canvas agents suggest the native
option when authenticated; existing model selections remain unchanged.

Reference: [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode).

## Persistent conversations

Every CLI conversation has a stable ID displayed in its banner. Messages and
tool results are protected by Windows DPAPI (OS keyring on supported non-Windows
hosts) and stored under the runtime state directory. Switching installation
directories does not change the frozen CLI's recorded runtime authority.

```powershell
sentra-cli --workspace C:\Projects\Example --session-id example-agent-01
sentra-cli --workspace C:\Projects\Example --resume example-agent-01
sentra-cli --workspace C:\Projects\Example --resume example-agent-01 --continue
```

`--resume` opens saved context without submitting a model request. `--continue`
explicitly continues an unfinished turn and reuses its recorded tool results.
If execution stopped after a request or tool started but before its result was
committed, its state is uncertain; it is not automatically repeated. Inspect
`/session` and record a verified decision with
`/resolve <call-id> <done|not-run> <evidence>` before continuing.

`/sessions` lists this workspace's saved conversations; `/resume <id>` switches
between them. `/clear` starts a new logical conversation and preserves the old
one. `MEMORY` directives can retrieve earlier messages from the same operator
and workspace, with session IDs and message sequence numbers. Search excludes
previous memory-query results to preserve original provenance, and returns
`next_cursor` when additional bounded search pages are needed.

The local MCP exposes `conversation_list`, `conversation_get` and
`conversation_search` through `sentra_coordination`, using the existing signed
MCP conversation session and filesystem workspace grants. Local desktop history
does not become readable by an arbitrary OAuth subject. Audit records contain
operation metadata; they do not contain memory queries or message bodies.

Canvas agents retain their own conversation IDs. “Abrir conversa salva” starts
a replacement CLI terminal after interruption, reuses the original conversation
and does not resend its previous prompt. Closing a SENTRA CLI terminal sends
its local `/exit` command, not an `exit` request to the model.

## Start

From a source checkout:

```powershell
cd C:\Users\vitor\OneDrive\Desktop\SENTRA
.\sentra-cli.cmd
```

From an installed SENTRA release, open a new terminal and use the PATH-registered command:

```powershell
sentra-cli
```

Fallback/diagnostic path:

```powershell
& "$env:LOCALAPPDATA\SENTRA\Commander\sentra-cli.exe"
```

For a Maestri custom terminal, use `.\sentra-cli.cmd` when the Maestri
workspace is the SENTRA checkout. For an installed/runtime-independent
workspace, use:

```text
%LOCALAPPDATA%\SENTRA\Commander\sentra-cli.exe
```

Maestri injects its terminal identity and transport into the terminal. Do not
hard-code `MAESTRI_PIPE` or `MAESTRI_TERMINAL_ID` for normal use.

## Diagnostics

Inside SENTRA CLI:

```text
/status
/doctor
/models
/gateway start
/maestri list
/maestri debug
```

`/doctor` verifies the SENTRA Gateway and, when running inside Maestri, the
live Maestri named-pipe connection and terminal identity.

## Native collaboration

Inside a Maestri manager terminal, explicit requests such as "gerencie outros
terminais", "coordene os agentes" or "crie uma colaboração" are intercepted
before the Web model call. SENTRA idempotently creates/reuses at most two
workers:

- `SENTRA-Implementation`: implementation, tests and concrete changes.
- `SENTRA-Review`: independent review, risk discovery and validation.

The workers are linked and receive their tasks through background dispatch, so
the manager terminal remains available. In practice this is three terminals:
one manager + two workers.

Workers default to `sentra/chatgpt-web/gpt-5.6-sol-instant` with a 50-second
turn deadline. Long tests/builds should run as durable/background jobs so the
worker can return an ACK/status without holding the terminal. The worker route
can be overridden without changing the repository:

```powershell
$env:SENTRA_MAESTRI_WORKER_MODEL = 'sentra/gemini-web/flash'
$env:SENTRA_MAESTRI_WORKER_TIMEOUT = '45'
```

Worker timeouts are clamped to 15–55 seconds. Gemini availability depends on
the current account/UI; `flash` is the default Gemini route and explicit model
choices fail closed when that option is absent.

The explicit equivalent is:

```text
/collab <objective>
/maestri check SENTRA-Implementation
/maestri check SENTRA-Review
```

## Maestri collaboration

Common operations:

```text
/maestri list
/maestri dispatch "Agent Name" "long-running task"
/maestri check "Agent Name"
/maestri ask "Agent Name" "question that must be answered synchronously"
/maestri note read "Note Name"
/maestri portal snapshot "Portal Name"
```

The autonomous agent can call the same public Maestri surface with directives:

```text
[[MAESTRI|list]]
[[MAESTRI|dispatch|Agent Name|long-running task]]
[[MAESTRI|check|Agent Name]]
[[MAESTRI|ask|Agent Name|question that must be answered synchronously]]
[[MAESTRI|exec|portal|snapshot|Portal Name]]
[[MAESTRI|exec|recruit|Reviewer|--preset|Codex]]
```

The pipe-delimited `exec` form is preferred inside directives. JSON argv is
still available from the interactive slash command as `/maestri json ...`.

For peer work that may take more than a few seconds, `dispatch` and
`dispatch_batch` are the preferred orchestration primitives. They start the
Maestri request in a detached process, immediately return control to SENTRA,
and let the agent continue independent work. Use `check` later to inspect the
peer. Synchronous `ask`/`batch` remain available for cases where the answer
is an immediate dependency.

Destructive Maestri commands such as dismiss, note delete, portal close, role
delete, and routine delete require explicit user intent. The interactive
generic Maestri command path additionally requires `--confirm`.

## Model transport

Web models are sent through the SENTRA Gateway Responses endpoint
(`/v1/responses`) with a stable CLI thread identity and a unique turn identity
per request. A Web turn is never silently replayed to another provider after
delivery becomes uncertain. Direct OpenAI or local model fallback is considered
only before a Web turn is submitted.

Without an explicit `--model` or `SENTRA_CLI_MODEL` preference, the CLI selects
`sentra/codex/current` when the installed Codex CLI is authenticated; otherwise
it selects `sentra/chatgpt-web/high`. Explicit choices take precedence and
native failures never trigger automatic provider fallback. Use `/models` to inspect the
live catalog and `/model <id>` to switch.

Automatic recovery keeps the control plane and Web runtime headless: SENTRA
starts the Python Gateway plus `codex-chatgpt-web serve` with no console
window. ChatGPT browser automation is lazy: on the first ChatGPT Web turn,
SENTRA adopts a compatible launcher that is already running or starts the
packaged `Codex Web GPT.exe` hidden in browser-host-only mode. The CLI waits
for the launcher's startup session refresh before submitting the first prompt,
so a cold start cannot race a browser turn. `/gateway stop` stops only the
headless upstream and a browser host that is explicitly marked as SENTRA-owned;
an external compatible launcher is never terminated.

## Live-safe Web Models updates

`Build-CodexChatGPTWebRuntime.ps1` builds into a staging directory and
publishes transactionally. If the current payload is live, the publisher first
proves that `active_http_turns == 0` and `active_browser_turns == 0`.
With active work it fails closed and leaves the running payload untouched.

When idle, it stops only the headless upstream and a browser host whose
descriptor proves `sentraManaged=true` and whose executable matches the
current payload, performs the staged swap with rollback, and restarts the
SENTRA-owned runtime. Model catalog traffic is control-plane traffic and is
not counted as an active user turn, so health/catalog polling cannot
permanently block an update.

## One-shot usage

```powershell
.\sentra-cli.ps1 -p "Responda exatamente: OK"
.\sentra-cli.ps1 -p '[[MAESTRI|list]]'
python -B -m sentra_cli -p "/doctor"
```

Use `sentra-cli.ps1` for PowerShell one-shot calls, especially directives
containing `|`, `&`, `<` or `>`. Windows `cmd.exe` consumes those
metacharacters before a batch wrapper can forward them safely. The
`sentra-cli.cmd` entry remains the simple interactive launcher used by the
Maestri custom terminal; once the REPL is open, directives are parsed by
SENTRA itself and are not interpreted by the shell.
