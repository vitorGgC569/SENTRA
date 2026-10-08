"""Native Maestri canvas integration for SENTRA CLI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from .config import CLIConfig


_DESTRUCTIVE_COMMANDS = (
    ("dismiss",),
    ("note", "delete"),
    ("portal", "close"),
    ("role", "delete"),
    ("routine", "delete"),
)


def _is_destructive_command(args: list[str]) -> bool:
    normalized = tuple(item.lower() for item in args)
    return any(
        normalized[: len(prefix)] == prefix
        for prefix in _DESTRUCTIVE_COMMANDS
    )


class MaestriBridge:
    """Talk to the live Maestri CLI using the terminal's injected identity."""

    def __init__(self, config: CLIConfig) -> None:
        self.config = config
        self.cli_path = config.maestri_cli_path

    @property
    def is_connected(self) -> bool:
        return self.config.is_in_maestri

    @property
    def is_available(self) -> bool:
        return bool(
            self.is_connected
            and self.cli_path
            and os.path.isfile(self.cli_path)
        )

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.config.maestri_pipe:
            env["MAESTRI_PIPE"] = self.config.maestri_pipe
        if self.config.maestri_socket:
            env["MAESTRI_SOCKET"] = self.config.maestri_socket
        if self.config.maestri_terminal_id:
            env["MAESTRI_TERMINAL_ID"] = self.config.maestri_terminal_id
        if self.config.maestri_workspace_id:
            env["MAESTRI_WORKSPACE_ID"] = self.config.maestri_workspace_id
        if self.cli_path:
            env["MAESTRI_CLI"] = self.cli_path
        return env

    def run_cmd(
        self,
        args: list[str],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Execute one Maestri command and preserve its exact exit evidence."""
        if not self.is_available:
            missing = []
            if not self.config.maestri_transport:
                missing.append("MAESTRI_PIPE/MAESTRI_SOCKET")
            if not self.config.maestri_terminal_id:
                missing.append("MAESTRI_TERMINAL_ID")
            if not self.cli_path or not os.path.isfile(self.cli_path or ""):
                missing.append("Maestri CLI")
            detail = ", ".join(missing) or "unknown reason"
            return {
                "ok": False,
                "error": f"Maestri unavailable: {detail}",
                "exit_code": None,
            }

        cli_path = self.cli_path
        if not cli_path:
            return {
                "ok": False,
                "error": "Maestri unavailable: Maestri CLI",
                "exit_code": None,
            }

        try:
            res = subprocess.run(
                [cli_path, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=self._environment(),
            )
            return {
                "ok": res.returncode == 0,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
                "exit_code": res.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": f"Maestri command timed out after {timeout:.0f}s",
                "exit_code": None,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "exit_code": None,
            }

    @staticmethod
    def _text(
        result: Mapping[str, Any],
        success_default: str = "OK",
    ) -> str:
        if result.get("ok"):
            return str(result.get("stdout") or success_default)
        detail = (
            result.get("error")
            or result.get("stderr")
            or f"exit {result.get('exit_code')}"
        )
        return f"Error: {detail}"

    def debug(self) -> str:
        # Doctor is diagnostic and must never pin the interactive terminal
        # behind a slow/broken Maestri transport.
        return self._text(self.run_cmd(["debug"], timeout=5.0))

    def list_peers(self) -> str:
        return self._text(
            self.run_cmd(["list"]),
            "No connected agents, notes, or portals.",
        )

    def _dispatch_background(self, args: list[str]) -> str:
        """Launch a Maestri command without blocking this SENTRA turn."""
        if not self.is_available or not self.cli_path:
            missing = []
            if not self.config.maestri_transport:
                missing.append("MAESTRI_PIPE/MAESTRI_SOCKET")
            if not self.config.maestri_terminal_id:
                missing.append("MAESTRI_TERMINAL_ID")
            if not self.cli_path or not os.path.isfile(self.cli_path or ""):
                missing.append("Maestri CLI")
            return "Error: Maestri unavailable: " + (
                ", ".join(missing) or "unknown reason"
            )

        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "env": self._environment(),
            "cwd": str(self.config.workspace),
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )
        else:
            kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen([self.cli_path, *args], **kwargs)
        except Exception as exc:
            return f"Error: {type(exc).__name__}: {exc}"
        return f"dispatched pid={process.pid}"

    def dispatch_ask(self, agent_name: str, prompt: str) -> str:
        result = self._dispatch_background(["ask", agent_name, prompt])
        if result.startswith("Error:"):
            return result
        return (
            f"Maestri ask dispatched to '{agent_name}' in background "
            f"({result}). Continue other work and use check later."
        )

    @staticmethod
    def _raw_terminal_input(text: str, *, submit: bool = False) -> str:
        """Encode literal text for Maestri --raw without losing backslashes."""
        encoded = (
            text.replace("\\", "\\\\")
            .replace("\r", "")
            .replace("\t", r"\t")
            .replace("\n", r"\n")
        )
        if submit:
            encoded += r"\n"
        return encoded

    def dispatch_terminal_submit(
        self,
        agent_name: str,
        prompt: str,
    ) -> str:
        """Type a prompt, then submit Enter as a separate deterministic step."""
        raw = self._raw_terminal_input(prompt, submit=False)
        typed = self.run_cmd(
            ["ask", agent_name, "--raw", raw],
            timeout=8.0,
        )
        if not typed.get("ok"):
            return self._text(typed)

        result = self._dispatch_background(
            ["ask", agent_name, "--raw", r"\n"]
        )
        if result.startswith("Error:"):
            return result
        return (
            f"Maestri terminal submit dispatched to '{agent_name}' "
            f"({result})."
        )

    def dispatch_batch(self, prompts: Mapping[str, str]) -> str:
        payload = json.dumps(
            dict(prompts), ensure_ascii=False, separators=(",", ":")
        )
        result = self._dispatch_background(["ask", "--batch", payload])
        if result.startswith("Error:"):
            return result
        return (
            "Maestri batch dispatched in background "
            f"({result}). Continue other work and check agents later."
        )

    def ask(
        self,
        agent_name: str,
        prompt: str,
        timeout: float = 600.0,
    ) -> str:
        return self._text(
            self.run_cmd(["ask", agent_name, prompt], timeout=timeout)
        )

    def ask_batch(
        self,
        prompts: Mapping[str, str],
        timeout: float = 600.0,
    ) -> str:
        payload = json.dumps(
            dict(prompts), ensure_ascii=False, separators=(",", ":")
        )
        return self._text(
            self.run_cmd(["ask", "--batch", payload], timeout=timeout)
        )

    def ask_raw(
        self,
        agent_name: str,
        raw_input: str,
        timeout: float = 60.0,
    ) -> str:
        return self._text(
            self.run_cmd(
                ["ask", agent_name, "--raw", raw_input],
                timeout=timeout,
            )
        )

    def check(self, agent_name: str) -> str:
        return self._text(self.run_cmd(["check", agent_name], timeout=30.0))

    def note_read(
        self,
        note_name: str,
        start: int | None = None,
        count: int | None = None,
    ) -> str:
        args = ["note", "read", note_name]
        if start is not None:
            args.append(str(start))
            if count is not None:
                args.append(str(count))
        return self._text(self.run_cmd(args))

    def note_write(self, note_name: str, content: str) -> str:
        return self._text(
            self.run_cmd(["note", "write", note_name, content]),
            f"Note '{note_name}' updated.",
        )

    def note_create(
        self,
        note_name: str | None = None,
        content: str = "",
        stack: str | None = None,
    ) -> str:
        args = ["note", "create"]
        if content:
            args.append(content)
        if note_name:
            args.extend(["--name", note_name])
        if stack:
            args.extend(["--stack", stack])
        return self._text(self.run_cmd(args), "Note created.")

    def note_edit(
        self,
        note_name: str,
        old_text: str,
        new_text: str,
    ) -> str:
        return self._text(
            self.run_cmd(
                ["note", "edit", note_name, old_text, new_text]
            ),
            f"Note '{note_name}' edited.",
        )

    def note_stack(
        self,
        note_name: str,
        stack: str | None = None,
    ) -> str:
        args = ["note", "stack", note_name]
        if stack:
            args.append(stack)
        return self._text(
            self.run_cmd(args),
            f"Note '{note_name}' filed.",
        )

    def note_unstack(self, note_name: str) -> str:
        return self._text(
            self.run_cmd(["note", "unstack", note_name]),
            f"Note '{note_name}' unstacked.",
        )

    def command(
        self,
        *args: str,
        timeout: float = 60.0,
        allow_destructive: bool = False,
    ) -> str:
        """Run any command from Maestri's public CLI surface."""
        argv = list(args)
        if _is_destructive_command(argv) and not allow_destructive:
            return (
                "Error: destructive Maestri command requires explicit "
                "--confirm"
            )
        return self._text(self.run_cmd(argv, timeout=timeout))

    def execute_json(
        self,
        payload: str,
        timeout: float = 180.0,
    ) -> str:
        """Execute a Maestri argv encoded as a JSON array of strings."""
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            return f"Error: invalid Maestri JSON argv: {exc}"
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, str) for item in value)
        ):
            return "Error: Maestri argv must be a non-empty JSON string array"
        confirmed = "--confirm" in value
        clean = [item for item in value if item != "--confirm"]
        return self.command(
            *clean,
            timeout=timeout,
            allow_destructive=confirmed,
        )

    def notify(self, message: str) -> str:
        return self.command("notify", message)

    def connect(self, source: str, target: str) -> str:
        return self.command("connect", source, target)

    def recruit(
        self,
        name: str,
        *,
        preset: str | None = None,
        role: str | None = None,
        directory: str | None = None,
        command: str | None = None,
    ) -> str:
        args = ["recruit", name]
        for flag, value in (
            ("--preset", preset),
            ("--role", role),
            ("--dir", directory),
            ("--command", command),
        ):
            if value:
                args.extend([flag, value])
        return self._text(self.run_cmd(args, timeout=90.0))

    @staticmethod
    def _listed_names(listing: str) -> set[str]:
        names: set[str] = set()
        for line in listing.splitlines():
            line = line.strip()
            if not line.startswith("- name:"):
                continue
            value = line.split(":", 1)[1].strip().strip('"')
            if value:
                names.add(value)
        return names

    def _worker_command(self) -> str:
        """Resolve a fast bounded SENTRA worker independently from the target workspace."""
        model = os.environ.get(
            "SENTRA_MAESTRI_WORKER_MODEL",
            "sentra/chatgpt-web/gpt-5.6-sol-instant",
        ).strip() or "sentra/chatgpt-web/gpt-5.6-sol-instant"
        raw_timeout = os.environ.get("SENTRA_MAESTRI_WORKER_TIMEOUT", "50").strip()
        try:
            timeout = float(raw_timeout)
        except ValueError:
            timeout = 50.0
        timeout = max(15.0, min(timeout, 55.0))
        timeout_arg = str(int(timeout)) if timeout.is_integer() else str(timeout)

        local_launcher = self.config.workspace / "sentra-cli.cmd"
        if local_launcher.is_file():
            return subprocess.list2cmdline(
                [r".\sentra-cli.cmd", "--model", model, "--timeout", timeout_arg]
            )

        candidates: list[Path] = []
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            candidates.append(
                Path(local_app_data)
                / "SENTRA"
                / "Commander"
                / "sentra-cli.exe"
            )
        candidates.append(
            Path(__file__).resolve().parent.parent / "sentra-cli.cmd"
        )
        for candidate in candidates:
            if candidate.is_file():
                return subprocess.list2cmdline(
                    [str(candidate.resolve()), "--model", model, "--timeout", timeout_arg]
                )

        return subprocess.list2cmdline(
            [
                sys.executable,
                "-B",
                "-m",
                "sentra_cli",
                "--model",
                model,
                "--timeout",
                timeout_arg,
            ]
        )

    def orchestrate_repository(self, goal: str) -> str:
        """Create an idempotent two-worker collaboration for this repository."""
        if not self.is_available:
            return "Error: Maestri bridge is unavailable."

        goal = goal.strip() or (
            "Trabalhar neste repositório com implementação rigorosa, revisão "
            "independente e validação por evidência."
        )
        listing = self.list_peers()
        if listing.startswith("Error:"):
            return listing
        existing = self._listed_names(listing)

        worker_command = self._worker_command()
        workers = (
            ("SENTRA-Implementation", worker_command),
            ("SENTRA-Review", worker_command),
        )
        actions: list[str] = []
        for name, command in workers:
            if name in existing:
                actions.append(f"{name}: already connected")
                continue
            result = self.recruit(
                name,
                directory=str(self.config.workspace),
                command=command,
            )
            actions.append(f"{name}: {result}")
            if not result.startswith("Error:"):
                existing.add(name)

        if all(name in existing for name, _ in workers):
            connect_result = self.connect(
                "SENTRA-Implementation",
                "SENTRA-Review",
            )
            if (
                "already" not in connect_result.lower()
                and "connected" not in connect_result.lower()
                and not connect_result.startswith("Error:")
            ):
                actions.append(f"peer link: {connect_result}")

        prompts = {
            "SENTRA-Implementation": (
                "Você é o implementador principal deste repositório. "
                "Inspecione o estado atual antes de editar, preserve trabalho "
                "concorrente, implemente as melhorias de maior valor alinhadas "
                f"ao objetivo do maestro: {goal}. Rode testes relevantes e "
                "mantenha evidências concretas do que mudou. Para operações "
                "demoradas, dispare jobs duráveis/background e devolva ACK/status "
                "no turno atual em vez de bloquear o terminal. Quando houver "
                "dúvida arquitetural, deixe-a explícita para o maestro."
            ),
            "SENTRA-Review": (
                "Você é o reviewer/auditor independente deste repositório. "
                "Comece por leitura e diagnóstico; não concorra em edição com "
                "o implementador sem necessidade. Procure bugs, regressões, "
                "riscos de segurança, lacunas de testes, contratos quebrados "
                "e problemas de integração. Objetivo do maestro: "
                f"{goal}. Produza achados falsificáveis e valide o trabalho "
                "do implementador quando houver mudanças."
            ),
        }
        active_prompts = {
            name: prompt
            for name, prompt in prompts.items()
            if name in existing
        }
        if not active_prompts:
            return "Error: no collaboration workers are available.\n" + "\n".join(actions)

        submissions: list[str] = []
        for name, prompt in active_prompts.items():
            submissions.append(
                self.dispatch_terminal_submit(name, prompt)
            )

        return (
            "Maestri collaboration started without blocking the master.\n"
            + "\n".join(f"- {item}" for item in actions)
            + "\n"
            + "\n".join(
                f"- submit: {item}" for item in submissions
            )
            + "\nUse /maestri check SENTRA-Implementation and "
            "/maestri check SENTRA-Review later; do not wait idly."
        )

    def context_summary(self) -> dict[str, Any]:
        return {
            "available": self.is_available,
            "connected": self.is_connected,
            "transport": (
                "pipe" if self.config.maestri_pipe
                else "socket" if self.config.maestri_socket
                else None
            ),
            "terminal_id": self.config.maestri_terminal_id,
            "workspace_id": self.config.maestri_workspace_id,
            "cli_path": self.cli_path,
        }
