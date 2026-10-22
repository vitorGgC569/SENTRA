"""Interactive terminal interface for SENTRA CLI."""
from __future__ import annotations

import json
import re
import shlex
import sys
from typing import Any

from rich.console import Console
from rich.align import Align
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from .agent import DIRECTIVE_RE, SentraAgent
from .config import CLIConfig
from .tools import git_diff, git_status


class SentraREPL:
    """Maestri-friendly REPL with explicit operational diagnostics."""

    def __init__(self, config: CLIConfig) -> None:
        self.config = config
        self.console = Console()
        self.agent = SentraAgent(config)
        self._phase_announced = False
        self._last_visible: dict | None = None

    @staticmethod
    def _gateway_label(health: dict[str, Any]) -> str:
        if health.get("gateway"):
            return "[bold green]Ready[/bold green]"
        if health.get("gateway_reachable"):
            code = (
                health.get("gateway_status", {}).get("status_code")
                or "degraded"
            )
            return f"[bold yellow]Listener online / not ready ({code})[/bold yellow]"
        return "[bold red]Offline[/bold red]"

    def _effort_label(self) -> str:
        effort=self.config.reasoning_effort
        if self.config.model.startswith("sentra/codex/"):
            return f"[bold cyan]{effort}[/bold cyan] [dim](Codex CLI)[/dim]"
        if self.config.model.startswith("sentra/chatgpt-web/"):
            requested = self.config.web_reasoning_effort or "provider default"
            return f"[bold cyan]{requested}[/bold cyan] [dim](Web requested; physical confirmation required)[/dim]"
        return f"[dim]{effort} (Codex only; Web model does not use this setting)[/dim]"

    def print_banner(self) -> None:
        """Compact OpenCode-inspired landing screen; /status retains diagnostics."""
        self.console.print()
        self.console.print(Align.center("[bold bright_white]S E N T R A[/bold bright_white]"))
        self.console.print(Align.center("[dim]Seu ambiente de execução e colaboração[/dim]"))
        self.console.print()
        # Provider readiness stays discoverable from /status and /doctor,
        # without crowding the interactive composer with a diagnostics table.

    def _print_composer(self) -> None:
        model = str(self.config.model or "nenhum modelo selecionado")
        provider = ("Codex" if model.startswith("sentra/codex/") else
                    "ChatGPT Web" if model.startswith("sentra/chatgpt-web/") else
                    "SENTRA Gateway")
        effort = (self.config.web_reasoning_effort or "padrão") if provider == "ChatGPT Web" else self.config.reasoning_effort
        safe_model = escape(model)
        self.console.print()
        self.console.print("[bold bright_blue]▏[/bold bright_blue] [dim]Pergunte qualquer coisa...[/dim]")
        self.console.print("[bold bright_blue]▏[/bold bright_blue] [bright_blue]Build[/bright_blue]  ·  "
                           + safe_model + "  ·  " + provider + "  ·  [yellow]" + str(effort) + "[/yellow]")
        self.console.print("[dim]~[/dim]  [dim]/model[/dim] modelos   [dim]/help[/dim] comandos")

    def _print_gateway_status(self) -> None:
        status = self.agent.client.gateway_status()
        table = Table(title="SENTRA Model Gateway", border_style="cyan")
        table.add_column("Field")
        table.add_column("Value")
        table.add_row("Reachable", str(status["reachable"]))
        table.add_row("Turn ready", str(status["turn_ready"]))
        table.add_row("Full ready", str(status["ready"]))
        table.add_row("HTTP", str(status["status_code"]))
        table.add_row("Catalog ready", str(status["catalog_ready"]))
        table.add_row("Upstream", str(status["upstream_status"]))
        table.add_row(
            "ChatGPT browser host",
            str(self.agent.client._browser_host_ready()),
        )
        table.add_row("Launcher", str(status.get("launcher") or "n/a"))
        if status.get("error"):
            table.add_row("Error", str(status["error"]))
        self.console.print(table)

    def _print_models(self) -> list[str]:
        """Display only provider-advertised models plus authenticated Codex."""
        try:
            models = list(dict.fromkeys(self.agent.client.list_models()))
        except Exception:
            models = []
            self.console.print("[yellow]Live model catalog unavailable.[/yellow]")
        table = Table(title="SENTRA · Selecionar modelo", border_style="cyan")
        table.add_column("#", justify="right", style="bold cyan")
        table.add_column("Modelo")
        table.add_column("Ativo", justify="center")
        for index, model in enumerate(models, 1):
            table.add_row(str(index), model,
                          "✓" if model == self.config.model else "")
        if not models:
            table.add_row("—", "Nenhum modelo autenticado/disponível", "")
        self.console.print(table)
        return models

    def _select_model(self, selected: str, *, catalog: list[str] | None = None) -> None:
        """Preserve existing selection until the chosen provider is validated."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}", selected):
            self.console.print("[red]Identificador de modelo inválido.[/red]")
            return
        if selected.startswith("sentra/codex/"):
            from .codex_native import authenticated
            suffix = selected.removeprefix("sentra/codex/")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", suffix):
                self.console.print("[red]Invalid native Codex model name.[/red]")
                return
            if not authenticated():
                self.console.print("[red]Codex CLI is not authenticated; model was not changed.[/red]")
                return
        else:
            try:
                known = catalog if catalog is not None else self.agent.client.list_models()
            except Exception:
                self.console.print("[red]Cannot validate model catalog; current model preserved.[/red]")
                return
            if selected not in known:
                self.console.print(f"[red]Model not advertised by Gateway:[/] {selected}")
                return
        self.config.model = selected
        self.agent.client.active_model = selected
        if hasattr(self.agent, "persist_model_preferences"):
            self.agent.persist_model_preferences()
        self.console.print(f"[green]Model selected:[/] {selected}")
        if selected.startswith("sentra/codex/") and selected != "sentra/codex/current":
            self.console.print("[dim]Codex validates this explicit model on the next turn.[/dim]")
        self.console.print(f"Reasoning: {self._effort_label()}")

    def _select_model_number(self, text: str, catalog: list[str]) -> bool:
        """Never submit a numbered choice to the provider as prose."""
        if not text.isascii() or not text.isdecimal() or len(text) > 4:
            return False
        index = int(text)
        if not 1 <= index <= len(catalog):
            return False
        self._select_model(catalog[index - 1], catalog=catalog)
        return True

    def _choose_model(self) -> None:
        models = self._print_models()
        if not models:
            self.console.print("[yellow]Conecte um provedor pelo Quick Start e tente novamente.[/yellow]")
            return
        self.console.print("[dim]Digite o número do modelo e pressione Enter; 0 cancela.[/dim]")
        try:
            answer = self.console.input("[bold cyan]Modelo › [/]").strip()
        except (EOFError, KeyboardInterrupt):
            self.console.print("[dim]Seleção cancelada.[/dim]")
            return
        if answer in {"", "0", "q", "Q", "cancel"}:
            self.console.print("[dim]Modelo mantido.[/dim]")
            return
        if (len(answer) > 4 or not answer.isascii() or not answer.isdecimal()
                or not 1 <= int(answer) <= len(models)):
            self.console.print("[yellow]Escolha inválida; modelo mantido.[/yellow]")
            return
        self._select_model_number(answer, models)

    def _maestri_command(self, arg: str) -> None:
        if not self.agent.maestri.is_available:
            self.console.print(
                "[yellow]Maestri bridge unavailable. "
                "Run this CLI from a Maestri terminal.[/yellow]"
            )
            return
        try:
            parts = shlex.split(arg) if arg else ["list"]
        except ValueError as exc:
            self.console.print(f"[red]Invalid command quoting:[/] {exc}")
            return

        action = parts[0].lower() if parts else "list"
        if action == "list":
            self.console.print(
                self.agent.maestri.list_peers(),
                markup=False,
            )
            return
        if action == "debug":
            self.console.print(
                self.agent.maestri.debug(),
                markup=False,
            )
            return
        if action == "check" and len(parts) >= 2:
            self.console.print(
                self.agent.maestri.check(parts[1]),
                markup=False,
            )
            return
        if action == "dispatch" and len(parts) >= 3:
            self.console.print(
                self.agent.maestri.dispatch_ask(
                    parts[1],
                    " ".join(parts[2:]),
                ),
                markup=False,
            )
            return
        if action == "ask" and len(parts) >= 3:
            self.console.print(
                self.agent.maestri.ask(
                    parts[1],
                    " ".join(parts[2:]),
                ),
                markup=False,
            )
            return
        if action == "raw" and len(parts) >= 3:
            self.console.print(
                self.agent.maestri.ask_raw(
                    parts[1],
                    " ".join(parts[2:]),
                ),
                markup=False,
            )
            return
        if action in {"batch", "dispatch_batch"} and len(parts) >= 2:
            raw = arg[arg.lower().find(action) + len(action):].strip()
            try:
                payload = json.loads(raw)
            except ValueError as exc:
                self.console.print(f"[red]Invalid batch JSON:[/] {exc}")
                return
            if not isinstance(payload, dict):
                self.console.print("[red]Batch JSON must be an object.[/red]")
                return
            prompts = {str(k): str(v) for k, v in payload.items()}
            result = (
                self.agent.maestri.dispatch_batch(prompts)
                if action == "dispatch_batch"
                else self.agent.maestri.ask_batch(prompts)
            )
            self.console.print(result, markup=False)
            return
        if action == "exec":
            raw = arg[len(parts[0]):].strip()
            try:
                argv = shlex.split(raw)
            except ValueError as exc:
                self.console.print(f"[red]Invalid exec quoting:[/] {exc}")
                return
            if not argv:
                self.console.print("[red]Usage: /maestri exec <command> [args...][/red]")
                return
            confirmed = "--confirm" in argv
            clean = [item for item in argv if item != "--confirm"]
            self.console.print(
                self.agent.maestri.command(
                    *clean,
                    timeout=180.0,
                    allow_destructive=confirmed,
                ),
                markup=False,
            )
            return
        if action == "json":
            raw = arg[len(parts[0]):].strip()
            self.console.print(
                self.agent.maestri.execute_json(raw),
                markup=False,
            )
            return

        destructive = {
            ("dismiss",),
            ("note", "delete"),
            ("portal", "close"),
            ("role", "delete"),
            ("routine", "delete"),
        }
        normalized = tuple(item.lower() for item in parts[:2])
        is_destructive = any(
            normalized[:len(prefix)] == prefix
            for prefix in destructive
        )
        if is_destructive and "--confirm" not in parts:
            self.console.print(
                "[yellow]Destructive Maestri command requires --confirm.[/yellow]"
            )
            return
        clean = [item for item in parts if item != "--confirm"]
        self.console.print(
            self.agent.maestri.command(
                *clean,
                timeout=180.0,
                allow_destructive=is_destructive,
            ),
            markup=False,
        )

    def handle_slash_command(self, line: str) -> bool:
        parts = line.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in {"/exit", "/quit", ":q"}:
            self.console.print("[dim]Closing SENTRA CLI...[/dim]")
            raise EOFError

        if cmd == "/help":
            table = Table(title="Commands", border_style="cyan")
            table.add_column("Command", style="bold green")
            table.add_column("Description")
            rows = [
                ("/status", "Gateway, providers, Maestri and Git status"),
                ("/doctor", "Detailed Gateway and Maestri diagnostics"),
                ("/doctor codex", "Codex CLI read-only version, login and uncertain-session status"),
                ("/gateway start|status|stop", "Manage Web Model runtime"),
                ("/models", "List models advertised by SENTRA Gateway"),
                ("/model", "Abrir menu numerado para escolher um modelo disponível"),
                ("/model list|<id>", "Exibir catálogo ou selecionar modelo pelo ID"),
                ("/effort [low|medium|high|xhigh]", "Choose provider-supported reasoning effort"),
                ("/delivery", "Show the protected durable Web delivery projection"),
                ("/compact-resume prepare|status|resume <JSON>", "Protected checkpoint and receipt-gated successor"),
                ("/diff", "Show current Git diff"),
                ("/test [target]", "Dispatch pytest in background"),
                ("/lint", "Dispatch lint gate in background"),
                ("/typecheck", "Dispatch typecheck gate in background"),
                ("/build", "Dispatch build gate in background"),
                ("/bench", "Dispatch benchmark gate in background"),
                ("/jobs", "List recent background jobs"),
                ("/job <id>", "Show background job status/result"),
                ("[[CANVAS|...]]", "Native Canvas: recruit, connect, dispatch and check peer replies"),
                ("/collab <goal>", "Create/reuse a two-worker Maestri collaboration without blocking"),
                ("/maestri dispatch <agent> <prompt>", "Send peer work in background and keep working"),
                ("/maestri check <agent>", "Read peer progress/result later"),
                ("/maestri ...", "Use the complete native Maestri CLI surface"),
                ("/clear", "Reset conversation context"),
                ("/session", "Show the persistent conversation and uncertain calls"),
                ("/goal set <objective>|status|stop", "Manage the durable conversation Goal"),
                ("/loop start|status|stop|step <objective>", "Control the bounded central loop; requires existing grants"),
                ("/sessions", "List saved conversations for this workspace"),
                ("/resume <id>", "Open saved context without submitting a model request"),
                ("/continue", "Continue the unfinished turn from its durable journal"),
                ("/resolve <call> <done|not-run> <evidence>", "Record a verified decision for an uncertain call"),
                ("/shell <action> [project]", "Shell bridge: home/space/dot/conversation via the authoritative route"),
                ("/space list|get|create", "Spaces sharing the same agents and state (via shell bridge)"),
                ("/dot list|create|update", "Dots via admission flow; prose is never a command"),
                ("/conversation list|create|send", "Conversations dispatched to a Dot with receipts"),
                ("/backup status [stage]", "Coordinated backup status (SQLite/Postgres/config/artifacts/keys)"),
                ("/update status [stage]", "Staged product update status (apply on exit, ConPTY-safe)"),
                ("/provider list", "Optional provider pins/SBOM/NOTICE inventory (read-only)"),
                ("/doctor-export <text>", "Redacted diagnostics export preview (IP/URL/path/email/title/project)"),
                ("/exit", "Close CLI"),
            ]
            for row in rows:
                table.add_row(*row)
            self.console.print(table)
            return True

        if cmd == "/status":
            self.console.print(f"Model: [bold cyan]{self.config.model}[/bold cyan]")
            self.console.print(f"Reasoning: {self._effort_label()}")
            health = self.agent.client.probe_health()
            self.console.print(
                f"Gateway: {self._gateway_label(health)}"
            )
            self.console.print(
                "ChatGPT browser host: "
                + ("ready" if health["browser_host"] else "offline")
            )
            self.console.print(
                "OpenAI API fallback: "
                + ("configured" if health["openai"] else "not configured")
            )
            self.console.print(
                "Local model: "
                + ("ready" if health["local"] else "offline")
            )
            if self.agent.canvas.is_available:
                self.console.print("SENTRA Canvas: conectado (agentes e mensagens dirigidas)")
            else:
                self.console.print(
                    "Maestri legado: "
                    + ("connected" if self.agent.maestri.is_available else "unavailable")
                )
            self.console.print(
                git_status(self.config.workspace),
                markup=False,
            )
            return True

        if cmd == "/doctor" and arg.lower() == "codex":
            from .codex_native import find_cli, authenticated
            import subprocess
            executable = find_cli()
            if executable is None:
                self.console.print("[yellow]Codex CLI: não encontrado.[/yellow]")
            else:
                try:
                    result = subprocess.run([str(executable), "--version"], capture_output=True,
                                            timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    version = (result.stdout.decode("utf-8", errors="replace").strip()
                               if result.returncode == 0 else "versão indisponível")
                except (OSError, subprocess.TimeoutExpired):
                    version = "versão indisponível"
                self.console.print("Codex CLI: " + escape(version[:90]))
                self.console.print("Autenticação: " + ("disponível" if authenticated() else "não confirmada"))
            pending = [call for call in self.agent.store.status(self.agent.session_id)["uncertain_calls"]
                       if call.get("kind") == "provider"]
            self.console.print("Chamadas de provedor incertas: " + str(len(pending)))
            if pending:
                self.console.print("[yellow]Não repetir essas chamadas; use /session para conferir o recibo.[/yellow]")
            return True

        if cmd == "/doctor":
            self._print_gateway_status()
            if self.agent.canvas.is_available:
                self.console.print(self.agent.canvas.execute("list",None),markup=False)
            elif self.agent.maestri.is_available:
                self.console.print(
                    Panel(
                        self.agent.maestri.debug(),
                        title="Maestri diagnostics",
                        border_style="cyan",
                    )
                )
            else:
                self.console.print(
                    "[yellow]Maestri diagnostics unavailable "
                    "outside a Maestri terminal.[/yellow]"
                )
            return True

        if cmd == "/gateway":
            action = arg.lower() or "status"
            if action == "status":
                self._print_gateway_status()
            elif action == "start":
                self.console.print(
                    "[dim]Ensuring Gateway + headless Web runtime are ready...[/dim]"
                )
                status = self.agent.client.ensure_gateway_ready()
                self._print_gateway_status()
                if not status["turn_ready"]:
                    self.console.print(
                        "[yellow]Gateway did not become turn-ready. "
                        f"Start action: {status.get('action')}[/yellow]"
                    )
                elif not status["catalog_ready"]:
                    self.console.print(
                        "[yellow]Web turns are ready; model catalog is not "
                        "authenticated/primed yet.[/yellow]"
                    )
            elif action == "stop":
                status = self.agent.client.stop_gateway_runtime()
                self.console.print(
                    f"Gateway runtime action: {status.get('action')}",
                    markup=False,
                )
                self._print_gateway_status()
            else:
                self.console.print(
                    "[yellow]Usage: /gateway start|status|stop[/yellow]"
                )
            return True

        if cmd == "/models":
            self._print_models()
            return True

        if cmd == "/model":
            if not arg:
                self._choose_model()
            elif arg.lower() == "list":
                self._print_models()
            elif arg.isascii() and arg.isdecimal():
                catalog = list(dict.fromkeys(self.agent.client.list_models()))
                if not self._select_model_number(arg, catalog):
                    self.console.print("[yellow]Número de modelo fora do catálogo.[/yellow]")
            else:
                self._select_model(arg)
            return True

        if cmd == "/effort":
            if not arg:
                self.console.print(f"Reasoning effort: {self._effort_label()}")
                self.console.print("Options: [bold]low[/bold], medium, high, xhigh")
                return True
            selected=arg.lower()
            if selected not in {"low","medium","high","xhigh"}:
                self.console.print("[yellow]Usage: /effort low|medium|high|xhigh[/yellow]")
                return True
            if self.config.model.startswith("sentra/chatgpt-web/"):
                try:
                    available = self.agent.client.supported_efforts(self.config.model)
                except (OSError, ValueError, RuntimeError, AttributeError):
                    self.console.print("[yellow]Current Web effort capabilities unavailable; choice preserved.[/yellow]")
                    return True
                if selected not in available:
                    self.console.print("[yellow]Web provider does not advertise this effort; choice preserved.[/yellow]")
                    return True
                self.config.web_reasoning_effort = selected
            elif self.config.model.startswith("sentra/codex/"):
                self.config.reasoning_effort=selected
            else:
                self.console.print("[yellow]This provider has no verified effort control.[/yellow]")
                return True
            if hasattr(self.agent, "persist_model_preferences"):
                self.agent.persist_model_preferences()
            self.console.print(f"[green]Reasoning effort:[/] [bold]{selected}[/bold]")
            return True

        if cmd == "/diff":
            self.console.print(
                Panel(
                    git_diff(self.config.workspace),
                    title="Git Diff",
                    border_style="yellow",
                )
            )
            return True

        if cmd == "/test":
            self.console.print(
                self.agent.jobs.submit(
                    "TEST",
                    arg or "all",
                    timeout=max(self.config.timeout_s, 60.0),
                ),
                markup=False,
            )
            return True

        if cmd in {"/lint", "/typecheck", "/build", "/bench"}:
            operation = cmd[1:].upper()
            self.console.print(
                self.agent.jobs.submit(
                    operation,
                    timeout=max(self.config.timeout_s, 180.0),
                ),
                markup=False,
            )
            return True

        if cmd == "/jobs":
            self.console.print(
                self.agent.jobs.list_jobs(),
                markup=False,
            )
            return True

        if cmd == "/job":
            self.console.print(
                self.agent.jobs.status(arg),
                markup=False,
            )
            return True

        if cmd == "/collab":
            if not self.agent.maestri.is_available:
                self.console.print(
                    "[yellow]Maestri bridge unavailable. "
                    "Run this CLI from a Maestri terminal.[/yellow]"
                )
                return True
            goal = arg or (
                "Atuar neste repositório com implementação e revisão "
                "independente, preservando trabalho concorrente."
            )
            produced = self.agent.execute_directive("MAESTRI", "orchestrate|" + goal)
            self._present(produced if isinstance(produced, str) else "")
            return True

        if cmd == "/clear":
            self.agent.reset()
            self.console.print("[green]Nova sessão aberta. A sessão anterior e seus recibos foram preservados.[/green]")
            return True

        if cmd in {"/goal", "/loop"}:
            action, _, objective = arg.strip().partition(" ")
            result = self.agent.goal_loop_command(cmd[1:], action or "status", objective=objective)
            self.console.print(json.dumps(result, ensure_ascii=False, indent=2), markup=False)
            return True
        if cmd == "/compact-resume":
            action, _, raw = arg.strip().partition(" ")
            result = self.agent.compact_resume_command(action, json.loads(raw or "{}"))
            self.console.print(json.dumps(result, ensure_ascii=False, indent=2), markup=False)
            return True

        if cmd == "/session":
            self.console.print(json.dumps(self.agent.store.status(self.agent.session_id), ensure_ascii=False, indent=2), markup=False)
            return True
        if cmd == "/delivery":
            view = self.agent.store.web_delivery_status(self.agent.session_id, workspace=self.config.workspace)
            self.console.print(json.dumps(view, ensure_ascii=False, indent=2), markup=False)
            return True
        if cmd == "/sessions":
            self.console.print(json.dumps(self.agent.store.list(self.config.workspace), ensure_ascii=False, indent=2), markup=False)
            return True
        if cmd == "/resume":
            self.agent.resume(arg.strip())
            self.console.print("Conversation restored: " + self.agent.session_id, markup=False)
            return True
        if cmd == "/continue":
            self.continue_previous()
            return True
        if cmd == "/resolve":
            parts = arg.split(None, 2)
            if len(parts) != 3 or parts[1] not in {"done", "not-run"}:
                raise ValueError("use /resolve <call> <done|not-run> <verified evidence>")
            self.agent.store.resolve_call(self.agent.session_id, parts[0], executed=parts[1] == "done", evidence=parts[2])
            self.agent.messages = self.agent._history()
            self.console.print("Recovery decision recorded; no action was repeated.", markup=False)
            return True

        if cmd == "/maestri":
            self._maestri_command(arg)
            return True

        if cmd in {"/shell", "/space", "/dot", "/conversation", "/coordinate"}:
            self._shell_command(cmd, arg)
            return True

        if cmd in {"/backup", "/restore", "/update", "/provider", "/doctor-export"}:
            self._maintenance_command(cmd, arg)
            return True

        return False

    def _shell_command(self, cmd: str, arg: str) -> None:
        """Shell bridge via the principal-composed route. No second authority."""
        from .shell_bridge import ShellBridge
        bridge = ShellBridge(self.config)
        if not bridge.is_available:
            self.console.print(
                "[yellow]Shell bridge unavailable: start the local SENTRA Canvas "
                "broker (SENTRA_CANVAS_PORT/SENTRA_CANVAS_BEARER) so CLI, chat, "
                "Canvas and Desktop share the same state.[/yellow]"
            )
            return
        parts = arg.strip().split(None, 1)
        sub = (parts[0].lower() if parts else "")
        rest = (parts[1] if len(parts) > 1 else "")
        mapping = {
            ("/shell", ""): "home",
            ("/shell", "home"): "home",
            ("/space", ""): "space_list",
            ("/space", "list"): "space_list",
            ("/space", "get"): "space_get",
            ("/space", "create"): "space_create",
            ("/dot", "list"): "dot_list",
            ("/dot", "create"): "dot_create",
            ("/dot", "update"): "dot_update",
            ("/conversation", "list"): "conversation_list",
            ("/conversation", "create"): "conversation_create",
            ("/conversation", "send"): "message_send",
            ("/coordinate", ""): "coordinate",
        }
        action = mapping.get((cmd, sub))
        if cmd == '/coordinate':
            action, rest = 'coordinate', arg.strip()
        if action is None and cmd == "/shell" and sub:
            action = sub if sub in {
                "home", "space_list", "space_get", "dot_list",
                "conversation_list", "message_list", "events",
                "space_create", "dot_create", "dot_update",
                "conversation_create", "message_send", "coordinate",
                "turn_permission_list", "turn_permission_grant", "turn_permission_revoke",
            } else None
        if action is None:
            self.console.print(
                "[yellow]Usage: /shell home | /space list|get|create | "
                "/dot list|create|update | /conversation list|create|send[/yellow]"
            )
            return
        try:
            if action == 'coordinate' and not rest.strip().startswith('{'):
                raise ValueError('coordinate requires a structured JSON intent; prose does not authorize actions')
            payload = json.loads(rest) if rest.strip().startswith('{') else {"project_id": rest.strip() or bridge.project_id}
            if not isinstance(payload, dict): raise ValueError("shell command requires a JSON object")
            project = payload.pop("project_id", bridge.project_id)
            space = payload.pop("space_id", "")
            conversation = payload.pop("conversation_id", "")
            key = payload.pop("request_key", "")
            if action in {'turn_permission_grant', 'turn_permission_revoke'} and not key:
                raise ValueError('turn permission mutation requires a stable request_key')
            if action == "message_send":
                if not key: raise ValueError("message_send requires a stable request_key; uncertain sends are never repeated")
                content, attachments = payload.pop("content", ""), payload.pop("attachments", [])
                if payload: raise ValueError("unknown message_send fields")
                result = bridge.send_turn(content, project_id=project, space_id=space,
                    conversation_id=conversation, request_key=key, attachments=attachments)
            else:
                result = bridge.dispatch(action, project_id=project, space_id=space,
                    conversation_id=conversation, request_key=key, extra=payload)
        except (ValueError, PermissionError, RuntimeError) as exc:
            self.console.print(f"[red]Shell bridge: {exc}[/red]")
            return
        self.console.print(json.dumps(result, ensure_ascii=False, indent=2), markup=False)

    def _maintenance_command(self, cmd: str, arg: str) -> None:
        """Vitra maintenance projections: read-only, fail-closed, no authority."""
        from .maintenance import backup_status, doctor_preview, provider_inventory, update_status
        if cmd == "/backup":
            self.console.print(json.dumps(backup_status(arg.strip()), ensure_ascii=False, indent=2), markup=False)
            return
        if cmd == "/restore":
            self.console.print(
                "[yellow]Restore is an explicit owner-authorized offline operation; "
                "this CLI only reports backup status. Use /backup status [stage].[/yellow]"
            )
            return
        if cmd == "/update":
            self.console.print(json.dumps(update_status(arg.strip()), ensure_ascii=False, indent=2), markup=False)
            return
        if cmd == "/provider":
            self.console.print(json.dumps(provider_inventory(), ensure_ascii=False, indent=2), markup=False)
            return
        if cmd == "/doctor-export":
            self.console.print(
                json.dumps(doctor_preview({"note": arg}), ensure_ascii=False, indent=2), markup=False
            )
            return

    def on_tool_call(self, op: str, args_preview: str) -> None:
        preview = args_preview.replace("\n", " ")
        self.console.print(
            f"[dim cyan]tool[/] [bold yellow]{op}[/] [dim]{preview}[/]"
        )

    def on_tool_result(self, preview: str) -> None:
        safe = preview.replace("\n", " ")
        if len(safe) > 500:
            safe = safe[:497] + "..."
        if preview.startswith("ACK "):
            self.console.print(
                f"[bold green]dispatched[/] [dim]{safe}[/]"
            )
            return
        self.console.print(f"[dim green]result[/] [dim]{safe}[/]")

    def _print_job_notifications(self) -> None:
        for notice in self.agent.jobs.completed_notifications():
            self.console.print(
                f"[bold green]✓[/] [dim]{notice}[/]",
                markup=True,
            )

    def _stream_receipts(self) -> tuple[str, ...]:
        raw = getattr(self.agent, "stream_receipts", ())
        if isinstance(raw, str):
            return (raw,) if raw else ()
        return tuple(item for item in raw if isinstance(item, str) and item)

    def _present(self, text: str = "", *, announce: bool | None = None, on_delta=None, on_phase=None) -> dict:
        """Show text that was already produced. Does not run the effect again."""
        from .__main__ import stream_turn
        if announce is None:
            announce = not self._phase_announced
        source = (text,) if text else ()
        visible = stream_turn(
            source,
            receipts=self._stream_receipts(),
            announce=announce,
            on_delta=on_delta,
            on_phase=on_phase,
        )
        client = getattr(self.agent, "client", None)
        visible["delivery"] = getattr(client, "last_delivery_state", "not_submitted")
        self._last_visible = visible
        return visible

    def _note_delivery(self, visible: dict, preview) -> dict:
        """Record the delivery already observed. Does not run the turn again."""
        visible["delivery"] = getattr(self.agent.client, "last_delivery_state", "not_submitted")
        if visible["delivery"] == "uncertain":
            preview.activity("delivery_uncertain")
        self._last_visible = visible
        return visible

    def run_one_shot(self, prompt: str) -> dict | int:
        from .__main__ import stream_turn
        from .shell_live_preview import LivePreviewWriter
        preview = LivePreviewWriter()
        prompt_clean = prompt.strip()
        slash_announced = False
        if prompt_clean.startswith("/"):
            announced = self._present("", announce=True, on_phase=preview.activity)
            slash_announced = True
            self._phase_announced = True
            try:
                handled = self.handle_slash_command(prompt_clean)
            finally:
                self._phase_announced = False
            if handled:
                return self._last_visible or announced

        if (
            self.agent.maestri.is_available
            and self.agent.wants_maestri_orchestration(prompt_clean)
        ):
            produced = self.agent.execute_directive(
                "MAESTRI", "orchestrate|" + prompt_clean,
            )
            return self._note_delivery(self._present(
                produced if isinstance(produced, str) else "",
                on_delta=preview.send,
                on_phase=preview.activity,
            ), preview)

        if prompt_clean.startswith("[[") and prompt_clean.endswith("]]"):
            match = DIRECTIVE_RE.fullmatch(prompt_clean)
            if match:
                op = match.group(1)
                raw_args = match.group(2) or ""
                self.on_tool_call(op, raw_args[:120])
                produced = self.agent.execute_directive(op, raw_args)
                self._note_delivery(self._present(
                    produced if isinstance(produced, str) else "",
                    on_delta=preview.send,
                    on_phase=preview.activity,
                ), preview)
                # Tool completion is not the unit receipt gate.
                return 0

        def live_tool_call(operation, arguments_preview):
            preview.activity("tool_call", operation)
            self.on_tool_call(operation, arguments_preview)

        def live_tool_result(result_preview):
            preview.activity("tool_result")
            self.on_tool_result(result_preview)

        def committed_receipts():
            # Consumed after step_stream finishes; a pre-stream tuple is stale.
            yield from self._stream_receipts()

        visible = stream_turn(
            self.agent.step_stream(
                prompt,
                on_tool_call=live_tool_call,
                on_tool_result=live_tool_result,
            ),
            receipts=committed_receipts(),
            on_delta=preview.send,
            on_phase=preview.activity,
            announce=not slash_announced,
        )
        return self._note_delivery(visible, preview)

    def _paint_live_frame(self, ui, turns, effort: str) -> None:
        from .terminal_ui import geometry
        layout = geometry(*ui._limits(), has_history=True)
        ui._draw(
            layout,
            model=self.config.model,
            effort=effort,
            turns=list(turns),
            value="",
            cursor=0,
        )

    def _consume_live_text(self, text, *, ui, turns, line, reply, effort, state, now) -> None:
        """Paint the centered UI. Coordinating is immediate. Deltas wait 70 ms."""
        if text == "coordinating\n":
            if ui.enabled:
                label = "Coordenando"
                if ("system", label) not in turns:
                    turns.append(("system", label))
                self._paint_live_frame(ui, turns + [("user", line)], effort)
                state["last_draw"] = now
            else:
                sys.stdout.write(text)
                sys.stdout.flush()
            return
        if text == "\n":
            if not ui.enabled:
                sys.stdout.write(text)
                sys.stdout.flush()
            return
        reply.append(text)
        if not ui.enabled:
            sys.stdout.write(text)
            sys.stdout.flush()
            return
        if now - state.get("last_draw", 0.0) >= 0.07:
            self._paint_live_frame(
                ui,
                turns + [("user", line), ("assistant", "".join(reply))],
                effort,
            )
            state["last_draw"] = now

    def _finish_live_frame(self, *, ui, turns, line, reply, effort) -> None:
        """Paint the frame that closed the stream, outside the 70 ms window."""
        if not ui.enabled:
            return
        frame = list(turns)
        frame.append(("user", line))
        shown = "".join(reply)
        if shown:
            frame.append(("assistant", shown))
        self._paint_live_frame(ui, frame, effort)

    def run_interactive(self) -> None:
        from .terminal_ui import CenteredTerminalUI
        import time
        ui = CenteredTerminalUI()
        turns: list[tuple[str, str]] = []
        choosing: list[str] | None = None
        if ui.enabled:
            self.console.record = True
        else:
            self.print_banner()

        def remember(role: str, content: str) -> None:
            if not ui.enabled or not content.strip():
                return
            normalized = content.replace("\r", "").strip()
            if role == "system":
                # A table/JSON dump is for terminal scrollback, not the mini feed.
                lines = [line.strip() for line in normalized.splitlines()
                         if line.strip() and not line.strip().startswith(("┏", "┡", "└", "│", "┃"))]
                normalized = (lines[0] if lines else "Comando concluído")
                if len(lines) > 1:
                    normalized += "  ·  saída detalhada acima"
            turns.append((role, normalized[:420] if role == "system" else normalized[-2200:]))
            del turns[:-12]

        def flush_console() -> str:
            if ui.enabled:
                return self.console.export_text(clear=True)
            return ""

        def catalog() -> list[str]:
            try:
                return list(dict.fromkeys(self.agent.client.list_models()))
            except (OSError, ValueError, RuntimeError, AttributeError) as exc:
                remember("system", "Catálogo indisponível: " + type(exc).__name__)
                return []

        while True:
            try:
                self._print_job_notifications()
                remember("system", flush_console())
                if ui.enabled:
                    effort = ((self.config.web_reasoning_effort or "padrão")
                              if self.config.model.startswith("sentra/chatgpt-web/")
                              else self.config.reasoning_effort)
                    line = ui.read(model=self.config.model, effort=effort, turns=turns,
                                   choices=choosing)
                else:
                    self._print_composer()
                    line = self.console.input("[bold bright_blue]▏[/bold bright_blue] ")
                if not line.strip():
                    continue
                clean = line.strip()
                if choosing is not None:
                    if clean in {"0", "cancel", "q", "Q", "/cancel"}:
                        choosing = None
                        remember("system", "Seleção cancelada; modelo mantido.")
                        continue
                    if self._select_model_number(clean, choosing):
                        choosing = None
                        remember("system", flush_console() or "Modelo selecionado: " + self.config.model)
                        continue
                    if clean.startswith("/"):
                        choosing = None  # An explicit command exits the picker.
                    else:
                        remember("system", "Digite o número do modelo ou 0 para cancelar.")
                        continue
                if ui.enabled and clean in {"/models", "/model", "/model list"}:
                    choosing = catalog()
                    if not choosing:
                        choosing = None
                        remember("system", "Nenhum modelo anunciado. Use /gateway status.")
                    continue
                slash_announced = False
                if clean.startswith("/"):
                    self._present("", announce=True)
                    slash_announced = True
                    self._phase_announced = True
                    try:
                        handled = self.handle_slash_command(clean)
                    finally:
                        self._phase_announced = False
                    if handled:
                        remember("user", clean)
                        remember("system", flush_console())
                        continue

                if (self.agent.maestri.is_available
                        and self.agent.wants_maestri_orchestration(clean)):
                    produced = self.agent.execute_directive("MAESTRI", "orchestrate|" + clean)
                    self._present(produced if isinstance(produced, str) else "")
                    remember("user", clean)
                    remember("system", flush_console())
                    continue

                if clean.startswith("[[") and clean.endswith("]]"):
                    match = DIRECTIVE_RE.fullmatch(clean)
                    if match:
                        op, args = match.group(1), match.group(2) or ""
                        self.on_tool_call(op, args[:120])
                        produced = self.agent.execute_directive(op, args)
                        self._present(produced if isinstance(produced, str) else "")
                        remember("user", clean)
                        remember("system", flush_console())
                        continue

                reply: list[str] = []
                live = {"last_draw": 0.0}
                try:
                    if not ui.enabled:
                        self.console.print()
                    from .__main__ import stream_turn
                    from .shell_live_preview import LivePreviewWriter
                    preview = LivePreviewWriter()

                    def write_delta(text: str) -> None:
                        self._consume_live_text(
                            text,
                            ui=ui,
                            turns=turns,
                            line=line,
                            reply=reply,
                            effort=effort,
                            state=live,
                            now=time.monotonic(),
                        )

                    visible = stream_turn(
                        self.agent.step_stream(
                            line,
                            on_tool_call=self.on_tool_call,
                            on_tool_result=self.on_tool_result,
                        ),
                        receipts=self._stream_receipts(),
                        write=write_delta,
                        on_delta=preview.send,
                        on_phase=preview.activity,
                        announce=not slash_announced,
                    )
                    visible = self._note_delivery(visible, preview)
                    if ui.enabled:
                        self._finish_live_frame(
                            ui=ui, turns=turns, line=line, reply=reply, effort=effort,
                        )
                    if not ui.enabled:
                        sys.stdout.flush()
                    flush_console()
                    remember("user", line)
                    if visible.get("delivery") == "uncertain":
                        remember(
                            "system",
                            "Entrega UNCERTAIN. Nenhuma chamada foi repetida.",
                        )
                    elif self.agent.client.last_error:
                        error = str(self.agent.client.last_error)[:130]
                        remember("system", "Provedor falhou: " + error +
                                 ". Verifique /doctor codex e /session; nenhuma chamada foi repetida.")
                    else:
                        remember("assistant", visible.get("shown") or "".join(reply))
                except Exception:
                    # Preserve the user's draft and terminal state; the outer
                    # handler prints a bounded error without a new provider call.
                    flush_console()
                    raise
            except KeyboardInterrupt:
                self.console.print("\n[yellow]Interrompido. Use /exit para sair.[/yellow]")
                remember("system", flush_console() or "Interrompido.")
            except EOFError:
                self.console.print("\n[dim]Sessão encerrada.[/dim]")
                break
            except Exception as exc:
                name = type(exc).__name__
                if name == "UncertainCall":
                    message = ("Sessão com chamada pendente de reconciliação. "
                               "Use /session e /resolve somente com evidência. /clear abre uma sessão nova, preservando a anterior.")
                else:
                    message = f"Erro na sessão: {name}: {str(exc)[:220]}"
                if ui.enabled:
                    remember("system", message)
                    flush_console()
                else:
                    self.console.print("[red]" + escape(message) + "[/red]")

    def continue_previous(self) -> dict:
        from .__main__ import stream_turn
        from .shell_live_preview import LivePreviewWriter
        preview = LivePreviewWriter()
        def committed_receipts():
            # Consumed after step_stream finishes; a pre-stream tuple is stale.
            yield from self._stream_receipts()

        visible = stream_turn(
            self.agent.step_stream(
                "",
                on_tool_call=self.on_tool_call,
                on_tool_result=self.on_tool_result,
                continue_previous=True,
            ),
            receipts=committed_receipts(),
            on_delta=preview.send,
            on_phase=preview.activity,
        )
        return self._note_delivery(visible, preview)
