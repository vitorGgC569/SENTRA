"""Model commands resolve to registered operations; only trusted code supplies argv."""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from .paths import resolve_workspace_path

MAX_OUTPUT_BYTES = 64_000


class CommandRunner:
    def __init__(self, cwd: Path, profiles: Mapping[str, Sequence[str]] | None = None):
        self.cwd = Path(cwd).resolve()
        # Profiles are supplied by the local operator, never by model metadata.
        self.profiles = {key: tuple(argv) for key, argv in (profiles or {}).items()}
        configured_python = os.environ.get("SENTRA_WORKSPACE_PYTHON", "").strip()
        if configured_python:
            candidate = Path(configured_python).expanduser()
            self.python_executable = str(candidate.resolve()) if candidate.exists() else shutil.which(configured_python)
        elif getattr(sys, "frozen", False):
            self.python_executable = shutil.which("python") or shutil.which("python3")
        else:
            self.python_executable = sys.executable

    def _python(self) -> str:
        if not self.python_executable:
            raise PermissionError(
                "workspace Python runtime unavailable; install Python or set SENTRA_WORKSPACE_PYTHON"
            )
        return self.python_executable

    def resolve_command(self, command: str) -> List[str]:
        from repository.parser import parse
        if not isinstance(command, str) or len(command) > 10000:
            raise ValueError("command must be a compact directive")
        directive = parse(command)
        if directive is None or not directive.known:
            raise ValueError("unregistered command; use [[TEST|target]], [[LINT]], [[TYPECHECK]], [[BUILD]] or [[BENCH]]")
        op, args = directive.operation, directive.args
        if op == "TEST":
            if len(args) > 1:
                raise ValueError("TEST accepts one target")
            target = args[0] if args else "all"
            if target in self.profiles:
                return list(self.profiles[target])
            scope = "tests" if target.lower() == "all" else (
                f"tests/{target}" if target in {"unit", "integration", "e2e", "load", "failure"} else target)
            path = resolve_workspace_path(self.cwd, scope)
            if not path.exists():
                raise ValueError(f"test target missing: {scope}")
            return [self._python(), "-m", "pytest", "-q", "--", str(path)]
        if args:
            raise ValueError(f"{op} accepts no payload")
        if op in self.profiles:
            return list(self.profiles[op])
        if op == "LINT":
            if getattr(sys, "frozen", False):
                return [self._python(), "-m", "compileall", "-q", str(self.cwd)]
            return [self._python(), "-I", str(Path(__file__).with_name("syntax_check.py")), str(self.cwd)]
        if op == "BUILD":
            return [self._python(), "-m", "pytest", "--collect-only", "-q", "--",
                    str(resolve_workspace_path(self.cwd, "tests"))]
        if op == "TYPECHECK":
            return [self._python(), "-m", "mypy", "."]
        if op == "BENCH":
            if "BENCH" in self.profiles:
                return list(self.profiles["BENCH"])
            raise PermissionError("BENCH requires an operator-owned BENCH execution profile")
        raise ValueError(f"operation is not executable: {op}")

    @staticmethod
    def _result(command: Any, passed: bool, code: int, stdout: str = "", stderr: str = "",
                refused: bool = False) -> Dict[str, Any]:
        # refused=True: a checagem foi RECUSADA pela política (não executada).
        # Recusa não é evidência de falha — consumidores devem separar refused
        # de failed (ver verification.py). Campo aditivo; leitores antigos ignoram.
        return {"command": command, "passed": passed, "exit_code": code,
                "stdout": stdout, "stderr": stderr, "refused": refused}

    async def run_command(self, cmd: str, timeout: float = 120) -> Dict[str, Any]:
        try:
            argv = self.resolve_command(cmd)
        except (ValueError, PermissionError) as exc:
            return self._result(cmd, False, -1, stderr=f"POLICY_DENIED: {exc}", refused=True)
        result = await self.run_argv(argv, timeout)
        result["command"] = cmd
        return result

    async def run_argv(self, argv: Sequence[str], timeout: float = 120) -> Dict[str, Any]:
        """Internal/operator API. Never forward model text or split shell strings here."""
        if isinstance(argv, (str, bytes)) or not argv or timeout <= 0:
            raise ValueError("structured argv and positive timeout required")
        process = None
        readers = []
        buffers = [bytearray(), bytearray()]
        truncated = [False, False]

        async def drain(stream, idx):
            while True:
                chunk = await stream.read(8192)
                if not chunk:
                    return
                buffers[idx].extend(chunk)
                if len(buffers[idx]) > MAX_OUTPUT_BYTES:
                    del buffers[idx][:-MAX_OUTPUT_BYTES]
                    truncated[idx] = True

        async def terminate():
            if process is None:
                return
            if os.name == "nt":
                killer = await asyncio.create_subprocess_exec(
                    "taskkill", "/PID", str(process.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await killer.wait()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()

        try:
            env = {k: v for k, v in os.environ.items()
                   if not any(word in k.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "COOKIE"))
                   and k not in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME")}
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            kwargs = {"start_new_session": True} if os.name != "nt" else {}
            process = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=str(self.cwd), env=env, **kwargs)
            readers = [asyncio.create_task(drain(process.stdout, 0)),
                       asyncio.create_task(drain(process.stderr, 1))]
            # Deadline includes pipe draining: descendants cannot hold them forever.
            async with asyncio.timeout(timeout):
                await process.wait()
                await asyncio.gather(*readers)
            output = [b.decode("utf-8", errors="replace") for b in buffers]
            result = self._result(list(argv), process.returncode == 0, process.returncode,
                                  output[0], output[1])
            result["output_truncated"] = any(truncated)
            return result
        except asyncio.CancelledError:
            await terminate()
            raise
        except TimeoutError:
            await terminate()
            return self._result(list(argv), False, -1,
                                buffers[0].decode("utf-8", errors="replace"),
                                f"Command timed out after {timeout} seconds.")
        except Exception as exc:
            await terminate()
            return self._result(list(argv), False, -1, stderr=f"Execution error: {exc}")
        finally:
            for reader in readers:
                if not reader.done():
                    reader.cancel()
            if readers:
                await asyncio.gather(*readers, return_exceptions=True)

    async def run_all(self, commands: List[str], timeout: float = 120) -> Dict[str, Any]:
        results = [await self.run_command(cmd, timeout=timeout) for cmd in commands]
        return {
            "all_passed": bool(results) and all(r["passed"] for r in results),
            "passed_commands": [r["command"] for r in results if r["passed"]],
            "failed_commands": [r["command"] for r in results if not r["passed"]],
            "results": results,
        }
