"""Direct control of the live Maestri canvas from SENTRA MCP."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..audit import AuditLogger
from ..config import MCPConfig


@dataclass(frozen=True, slots=True)
class _MaestriRuntime:
    cli: str
    pipe: str
    workspace_id: str
    workspace_name: str
    workspace_path: str
    terminal_id: str
    terminal_name: str
    terminal_status: str


class MaestriService:
    """Discover and control Maestri without inheriting a Maestri terminal env."""

    def __init__(
        self,
        config: MCPConfig,
        audit: AuditLogger | None = None,
    ) -> None:
        self.config = config
        self.audit = audit

    def update_config(self, config: MCPConfig) -> None:
        self.config = config

    @staticmethod
    def _home() -> Path:
        return Path(
            os.environ.get("USERPROFILE")
            or os.environ.get("HOME")
            or Path.home()
        ).expanduser()

    @classmethod
    def _state_root(cls) -> Path:
        configured = os.environ.get("MAESTRI_STATE_DIR", "").strip()
        return Path(configured).expanduser() if configured else cls._home() / ".maestri"

    @staticmethod
    def _find_cli() -> str:
        env_cli = os.environ.get("MAESTRI_CLI", "").strip()
        if env_cli and Path(env_cli).is_file():
            return str(Path(env_cli).resolve())

        local = os.environ.get("LOCALAPPDATA", "").strip()
        if local:
            candidate = (
                Path(local)
                / "Programs"
                / "Maestri"
                / "resources"
                / "cli"
                / "maestri.exe"
            )
            if candidate.is_file():
                return str(candidate.resolve())

        found = shutil.which("maestri")
        if found and Path(found).is_file():
            return str(Path(found).resolve())
        raise FileNotFoundError("Maestri CLI is not installed or discoverable")

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"invalid JSON object: {path}")
        return raw

    @classmethod
    def _workspace_documents(cls) -> list[tuple[Path, dict[str, Any]]]:
        root = cls._state_root() / "workspaces"
        if not root.is_dir():
            return []
        items: list[tuple[Path, dict[str, Any]]] = []
        for path in root.glob("*/workspace.json"):
            try:
                doc = cls._read_json(path)
            except (OSError, ValueError, TypeError):
                continue
            payload = doc.get("payload")
            if isinstance(payload, dict):
                items.append((path, payload))
        return items

    @classmethod
    def _active_workspace_id(cls) -> str | None:
        path = cls._state_root() / "app-state.json"
        try:
            doc = cls._read_json(path)
            payload = doc.get("payload")
            value = payload.get("activeWorkspaceId") if isinstance(payload, dict) else None
            return str(value).strip() if value else None
        except (OSError, ValueError, TypeError):
            return None

    @classmethod
    def _select_workspace(
        cls,
        selector: str | None,
    ) -> tuple[Path, dict[str, Any]]:
        documents = cls._workspace_documents()
        if not documents:
            raise FileNotFoundError("no Maestri workspaces were found")

        wanted = (selector or "").strip().casefold()
        active_id = cls._active_workspace_id()
        if wanted:
            for path, payload in documents:
                candidates = {
                    str(payload.get("id") or "").casefold(),
                    str(payload.get("name") or "").casefold(),
                    str(payload.get("workingDirectory") or "").casefold(),
                }
                if wanted in candidates:
                    return path, payload
            raise KeyError(f"Maestri workspace not found: {selector}")

        if active_id:
            for path, payload in documents:
                if str(payload.get("id") or "") == active_id:
                    return path, payload

        documents.sort(
            key=lambda item: str(item[1].get("lastOpenedAt") or ""),
            reverse=True,
        )
        return documents[0]

    @staticmethod
    def _terminals(payload: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        nodes = payload.get("nodes")
        if not isinstance(nodes, list):
            return result
        for node in nodes:
            if not isinstance(node, dict):
                continue
            content = node.get("content")
            terminal_box = content.get("terminal") if isinstance(content, dict) else None
            terminal = terminal_box.get("_0") if isinstance(terminal_box, dict) else None
            if not isinstance(terminal, dict):
                continue
            result.append({
                "id": str(terminal.get("id") or node.get("id") or ""),
                "name": str(terminal.get("name") or ""),
                "agent_type": str(terminal.get("agentType") or ""),
                "command": str(terminal.get("command") or ""),
                "status": str(terminal.get("status") or ""),
                "is_manager": bool(terminal.get("isManager")),
                "working_directory": str(terminal.get("workingDirectory") or ""),
            })
        return result

    @staticmethod
    def _manager(terminals: list[dict[str, Any]]) -> dict[str, Any]:
        for terminal in terminals:
            if terminal.get("is_manager"):
                return terminal
        for terminal in terminals:
            if terminal.get("status") == "running":
                return terminal
        if terminals:
            return terminals[0]
        raise RuntimeError("Maestri workspace has no terminal identity")

    @staticmethod
    def _pipe_candidates() -> list[str]:
        explicit = os.environ.get("MAESTRI_PIPE", "").strip()
        candidates: list[str] = [explicit] if explicit else []
        if os.name == "nt":
            try:
                for name in os.listdir("\\\\.\\pipe\\"):
                    if str(name).casefold().startswith("maestri-"):
                        value = "\\\\.\\pipe\\" + str(name)
                        if value not in candidates:
                            candidates.append(value)
            except OSError:
                pass
        return candidates

    @staticmethod
    def _env(
        runtime: _MaestriRuntime,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env.update({
            "MAESTRI_PIPE": runtime.pipe,
            "MAESTRI_TERMINAL_ID": runtime.terminal_id,
            "MAESTRI_WORKSPACE_ID": runtime.workspace_id,
            "MAESTRI_CLI": runtime.cli,
        })
        return env

    @staticmethod
    def _creationflags() -> int:
        if os.name != "nt":
            return 0
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    @classmethod
    def _probe(
        cls,
        *,
        cli: str,
        pipe: str,
        workspace_id: str,
        workspace_name: str,
        workspace_path: str,
        terminal: dict[str, Any],
    ) -> _MaestriRuntime | None:
        runtime = _MaestriRuntime(
            cli=cli,
            pipe=pipe,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            workspace_path=workspace_path,
            terminal_id=str(terminal.get("id") or ""),
            terminal_name=str(terminal.get("name") or ""),
            terminal_status=str(terminal.get("status") or ""),
        )
        try:
            result = subprocess.run(
                [cli, "debug"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3.0,
                env=cls._env(runtime),
                creationflags=cls._creationflags(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return runtime if result.returncode == 0 else None

    @classmethod
    def _discover(cls, selector: str | None) -> _MaestriRuntime:
        cli = cls._find_cli()
        _path, payload = cls._select_workspace(selector)
        terminals = cls._terminals(payload)
        identity = cls._manager(terminals)
        workspace_id = str(payload.get("id") or "")
        workspace_name = str(payload.get("name") or workspace_id)
        workspace_path = str(payload.get("workingDirectory") or "")
        if not workspace_id:
            raise RuntimeError("Maestri workspace has no id")

        pipes = cls._pipe_candidates()
        if not pipes:
            raise RuntimeError("no live Maestri named pipe was discovered")
        for pipe in pipes:
            runtime = cls._probe(
                cli=cli,
                pipe=pipe,
                workspace_id=workspace_id,
                workspace_name=workspace_name,
                workspace_path=workspace_path,
                terminal=identity,
            )
            if runtime is not None:
                return runtime
        raise RuntimeError(
            "Maestri is installed but no live pipe accepted the active workspace identity"
        )

    @classmethod
    def _run(
        cls,
        runtime: _MaestriRuntime,
        args: list[str],
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        result = subprocess.run(
            [runtime.cli, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=cls._env(runtime),
            cwd=(runtime.workspace_path or None),
            creationflags=cls._creationflags(),
        )
        payload = {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
        if result.returncode != 0:
            detail = payload["stderr"] or payload["stdout"] or f"exit {result.returncode}"
            raise RuntimeError(f"Maestri command failed: {detail}")
        return payload

    @classmethod
    def _snapshot(
        cls,
        selector: str | None,
        runtime: _MaestriRuntime | None = None,
    ) -> dict[str, Any]:
        _path, payload = cls._select_workspace(selector)
        terminals = cls._terminals(payload)
        data: dict[str, Any] = {
            "workspace": {
                "id": str(payload.get("id") or ""),
                "name": str(payload.get("name") or ""),
                "working_directory": str(payload.get("workingDirectory") or ""),
            },
            "terminals": terminals,
            "terminal_count": len(terminals),
        }
        if runtime is not None:
            data["control_identity"] = {
                "terminal_id": runtime.terminal_id,
                "terminal_name": runtime.terminal_name,
                "terminal_status": runtime.terminal_status,
                "pipe": runtime.pipe,
                "cli": runtime.cli,
            }
        return data

    @staticmethod
    def _raw_input(text: str) -> str:
        return (
            text.replace("\\", "\\\\")
            .replace("\r", "")
            .replace("\t", r"\t")
            .replace("\n", r"\n")
        )

    @classmethod
    def _raw_submit(cls, text: str) -> str:
        return cls._raw_input(text) + r"\n"

    def execute(
        self,
        action: str,
        *,
        owner: str,
        workspace: str | None = None,
        name: str | None = None,
        target: str | None = None,
        prompt: str | None = None,
        command: str | None = None,
        preset: str | None = None,
        role: str | None = None,
        confirm: bool = False,
        allow_manager: bool = False,
    ) -> dict[str, Any]:
        action = action.strip().lower()
        allowed = {
            "status", "list", "recruit", "send", "check", "connect", "dismiss"
        }
        if action not in allowed:
            raise ValueError(f"unsupported Maestri action: {action}")

        runtime = self._discover(workspace)
        snapshot = self._snapshot(workspace, runtime)
        terminals = snapshot["terminals"]
        by_name = {
            str(item.get("name") or "").casefold(): item
            for item in terminals
            if item.get("name")
        }

        if action == "status":
            result = {"available": True, **snapshot}
        elif action == "list":
            evidence = self._run(runtime, ["list"], timeout=8.0)
            result = {**snapshot, "evidence": evidence}
        elif action == "recruit":
            clean_name = (name or "").strip()
            if not clean_name:
                raise ValueError("recruit requires name")
            existing = by_name.get(clean_name.casefold())
            if existing:
                result = {
                    "recruited": False,
                    "idempotent_replay": True,
                    "terminal": existing,
                    **snapshot,
                }
            else:
                args = ["recruit", clean_name]
                if preset:
                    args.extend(["--preset", preset])
                if role:
                    args.extend(["--role", role])
                if command:
                    args.extend(["--command", command])
                elif not preset:
                    args.extend([
                        "--command",
                        r".\sentra-cli.cmd --model sentra/chatgpt-web/medium --timeout 55",
                    ])
                evidence = self._run(runtime, args, timeout=20.0)
                result = {
                    "recruited": True,
                    "evidence": evidence,
                    **self._snapshot(workspace, runtime),
                }
        elif action == "send":
            clean_name = (name or "").strip()
            clean_prompt = prompt or ""
            if not clean_name or not clean_prompt.strip():
                raise ValueError("send requires name and prompt")
            if clean_name.casefold() not in by_name:
                raise KeyError(f"Maestri terminal not found: {clean_name}")
            typed = self._run(
                runtime,
                ["ask", clean_name, "--raw", self._raw_input(clean_prompt)],
                timeout=8.0,
            )
            submitted = self._run(
                runtime,
                ["ask", clean_name, "--raw", r"\n"],
                timeout=8.0,
            )
            result = {
                "submitted": True,
                "terminal": clean_name,
                "evidence": {
                    "typed": typed,
                    "submit": submitted,
                },
            }
        elif action == "check":
            clean_name = (name or "").strip()
            if not clean_name:
                raise ValueError("check requires name")
            evidence = self._run(runtime, ["check", clean_name], timeout=8.0)
            result = {"terminal": clean_name, "evidence": evidence}
        elif action == "connect":
            source = (name or "").strip()
            destination = (target or "").strip()
            if not source or not destination:
                raise ValueError("connect requires name and target")
            evidence = self._run(
                runtime,
                ["connect", source, destination],
                timeout=10.0,
            )
            result = {
                "connected": True,
                "source": source,
                "target": destination,
                "evidence": evidence,
            }
        else:
            clean_name = (name or "").strip()
            if not clean_name:
                raise ValueError("dismiss requires name")
            if not confirm:
                raise PermissionError("dismiss requires confirm=true")
            terminal = by_name.get(clean_name.casefold())
            if terminal is None:
                result = {
                    "dismissed": False,
                    "idempotent_replay": True,
                    "already_absent": True,
                    **snapshot,
                }
            else:
                if terminal.get("is_manager") and not allow_manager:
                    raise PermissionError(
                        "refusing to dismiss the Maestri manager; set allow_manager=true"
                    )
                evidence = self._run(
                    runtime,
                    ["dismiss", clean_name, "--confirm"],
                    timeout=15.0,
                )
                result = {
                    "dismissed": True,
                    "evidence": evidence,
                    **self._snapshot(workspace, runtime),
                }

        if self.audit is not None:
            self.audit.emit(
                "tool.sentra_maestri",
                "ok",
                {
                    "owner": owner,
                    "action": action,
                    "workspace": runtime.workspace_name,
                },
            )
        return result
