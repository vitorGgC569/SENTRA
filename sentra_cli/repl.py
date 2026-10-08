"""Interactive terminal interface for SENTRA CLI."""
from __future__ import annotations

import json
import shlex
import sys
from typing import Any

from rich.console import Console
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

    def print_banner(self) -> None:
        health = self.agent.client.probe_health()
        if self.agent.canvas.is_available:
            maestri_status="[bold green]Native session[/bold green] · directed connections"
        elif self.config.is_in_maestri:
            terminal = (self.config.maestri_terminal_id or "")[:8]
            maestri_status = (
                f"[bold green]Connected[/bold green] terminal={terminal}"
            )
        else:
            maestri_status = "[dim]Standalone[/dim]"

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_row("[bold cyan]Workspace:[/bold cyan]", str(self.config.workspace))
        table.add_row("[bold cyan]Model:[/bold cyan]", self.config.model)
        table.add_row("[bold cyan]Conversation:[/bold cyan]", self.agent.session_id)
        table.add_row(
            "[bold cyan]SENTRA Gateway:[/bold cyan]",
            self._gateway_label(health),
        )
        table.add_row(
            "[bold cyan]SENTRA Canvas:[/bold cyan]" if self.agent.canvas.is_available else "[bold cyan]Maestri:[/bold cyan]",
            maestri_status,
        )

        self.console.print(
            Panel(
                table,
                title="[bold yellow]SENTRA CLI v1.1[/bold yellow]",
                subtitle="Type a request or /help",
                border_style="cyan",
            )
        )

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

    def _print_models(self) -> None:
        try:
            models = self.agent.client.list_models()
        except Exception as exc:
            self.console.print(f"[red]Model catalog unavailable:[/] {exc}")
            return
        table = Table(title="Available models", border_style="cyan")
        table.add_column("Model")
        table.add_column("Selected", justify="center")
        for model in models:
            table.add_row(
                model,
                "✓" if model == self.config.model else "",
            )
        if not models:
            table.add_row("(none)", "")
        self.console.print(table)

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
                ("/gateway start|status|stop", "Manage Web Model runtime"),
                ("/models", "List models advertised by SENTRA Gateway"),
                ("/model <id>", "Select one advertised model"),
                ("/diff", "Show current Git diff"),
                ("/test [target]", "Dispatch pytest in background"),
                ("/lint", "Dispatch lint gate in background"),
                ("/typecheck", "Dispatch typecheck gate in background"),
                ("/build", "Dispatch build gate in background"),
                ("/bench", "Dispatch benchmark gate in background"),
                ("/jobs", "List recent background jobs"),
                ("/job <id>", "Show background job status/result"),
                ("/collab <goal>", "Create/reuse a two-worker Maestri collaboration without blocking"),
                ("/maestri dispatch <agent> <prompt>", "Send peer work in background and keep working"),
                ("/maestri check <agent>", "Read peer progress/result later"),
                ("/maestri ...", "Use the complete native Maestri CLI surface"),
                ("/clear", "Reset conversation context"),
                ("/session", "Show the persistent conversation and uncertain calls"),
                ("/sessions", "List saved conversations for this workspace"),
                ("/resume <id>", "Open saved context without submitting a model request"),
                ("/continue", "Continue the unfinished turn from its durable journal"),
                ("/resolve <call> <done|not-run> <evidence>", "Record a verified decision for an uncertain call"),
                ("/exit", "Close CLI"),
            ]
            for row in rows:
                table.add_row(*row)
            self.console.print(table)
            return True

        if cmd == "/status":
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
            self.console.print(
                "Maestri: "
                + (
                    "connected"
                    if self.agent.maestri.is_available
                    else "unavailable"
                )
            )
            self.console.print(
                git_status(self.config.workspace),
                markup=False,
            )
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
                self.console.print(
                    f"Current model: [bold]{self.config.model}[/bold]"
                )
                return True
            try:
                models = self.agent.client.list_models()
            except Exception as exc:
                self.console.print(
                    f"[red]Cannot validate model catalog:[/] {exc}"
                )
                return True
            if models and arg not in models:
                self.console.print(
                    f"[red]Model not advertised by Gateway:[/] {arg}"
                )
                return True
            self.config.model = arg
            self.agent.client.active_model = arg
            self.console.print(f"[green]Model selected:[/] {arg}")
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
            self.console.print(
                self.agent.execute_directive("MAESTRI", "orchestrate|" + goal),
                markup=False,
            )
            return True

        if cmd == "/clear":
            self.agent.reset()
            self.console.print("[green]Conversation context cleared.[/green]")
            return True

        if cmd == "/session":
            self.console.print(json.dumps(self.agent.store.status(self.agent.session_id), ensure_ascii=False, indent=2), markup=False)
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

        return False

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

    def run_one_shot(self, prompt: str) -> None:
        prompt_clean = prompt.strip()
        if prompt_clean.startswith("/"):
            if self.handle_slash_command(prompt_clean):
                return

        if (
            self.agent.maestri.is_available
            and self.agent.wants_maestri_orchestration(prompt_clean)
        ):
            self.console.print(
                self.agent.execute_directive("MAESTRI", "orchestrate|" + prompt_clean),
                markup=False,
            )
            return

        if prompt_clean.startswith("[[") and prompt_clean.endswith("]]"):
            match = DIRECTIVE_RE.fullmatch(prompt_clean)
            if match:
                op = match.group(1)
                raw_args = match.group(2) or ""
                self.on_tool_call(op, raw_args[:120])
                self.console.print(
                    self.agent.execute_directive(op, raw_args),
                    markup=False,
                )
                return

        for chunk in self.agent.step_stream(
            prompt,
            on_tool_call=self.on_tool_call,
            on_tool_result=self.on_tool_result,
        ):
            sys.stdout.write(chunk)
            sys.stdout.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()

    def run_interactive(self) -> None:
        self.print_banner()
        while True:
            try:
                self._print_job_notifications()
                self.console.print(
                    "\n[bold cyan]sentra>[/bold cyan] ",
                    end="",
                )
                line = input()
                if not line.strip():
                    continue
                line_clean = line.strip()

                if line_clean.startswith("/"):
                    if self.handle_slash_command(line_clean):
                        continue

                if (
                    self.agent.maestri.is_available
                    and self.agent.wants_maestri_orchestration(line_clean)
                ):
                    self.console.print(
                        self.agent.execute_directive("MAESTRI", "orchestrate|" + line_clean),
                        markup=False,
                    )
                    continue

                if (
                    line_clean.startswith("[[")
                    and line_clean.endswith("]]")
                ):
                    match = DIRECTIVE_RE.fullmatch(line_clean)
                    if match:
                        op = match.group(1)
                        raw_args = match.group(2) or ""
                        self.on_tool_call(op, raw_args[:120])
                        self.console.print(
                            self.agent.execute_directive(op, raw_args),
                            markup=False,
                        )
                        continue

                self.console.print()
                for chunk in self.agent.step_stream(
                    line,
                    on_tool_call=self.on_tool_call,
                    on_tool_result=self.on_tool_result,
                ):
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                sys.stdout.write("\n")
                sys.stdout.flush()
            except KeyboardInterrupt:
                self.console.print(
                    "\n[yellow]Interrupted. Use /exit to close.[/yellow]"
                )
            except EOFError:
                self.console.print("\n[dim]Session closed.[/dim]")
                break
            except Exception as exc:
                self.console.print(
                    f"\n[bold red]Unexpected error:[/] "
                    f"{type(exc).__name__}: {exc}"
                )

    def continue_previous(self):
        for chunk in self.agent.step_stream("", on_tool_call=self.on_tool_call,
                                            on_tool_result=self.on_tool_result, continue_previous=True):
            sys.stdout.write(chunk)
            sys.stdout.flush()
        sys.stdout.write("\n")
