"""Supervise installed SENTRA local MCP, Edge relay, tunnel and remote agent."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .product import (
    ProductPaths,
    ProductSettings,
    collect_product_status,
    ensure_browser_token,
    ensure_instance_id,
    json_get,
    load_tunnel_config,
    sync_workspace_registry,
    tcp_open,
)


class LocalRuntime:
    def __init__(self, paths: ProductPaths, settings: ProductSettings) -> None:
        self.paths = paths
        self.settings = settings
        self.processes: dict[str, subprocess.Popen[Any]] = {}
        self.lock = threading.RLock()
        self.runtime_dir = self.paths.state_dir / "runtime"
        self.log_dir = self.paths.state_dir / "logs"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _expected_executable(self, name: str) -> Path | None:
        mapping = {
            "mcp": self.paths.install_dir / "sentra-mcp.exe",
            "browser-relay": self.paths.install_dir / "sentra-browser-relay.exe",
            "tunnel": self.paths.tunnel_client,
            "agent": self.paths.install_dir / "sentra-agent.exe",
        }
        path = mapping.get(name)
        return path.resolve() if path is not None and path.is_file() else None

    @staticmethod
    def _windows_process_path(pid: int) -> Path | None:
        if os.name != "nt" or pid <= 0:
            return None
        import ctypes
        from ctypes import wintypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return None
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
                process, 0, buffer, ctypes.byref(size)
            ):
                return None
            return Path(buffer.value).resolve()
        finally:
            ctypes.windll.kernel32.CloseHandle(process)

    def _persisted_pid(self, name: str) -> int | None:
        path = self.runtime_dir / f"{name}.pid"
        try:
            pid = int(path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            return None
        expected = self._expected_executable(name)
        if expected is None:
            path.unlink(missing_ok=True)
            return None
        actual = self._windows_process_path(pid)
        if actual is None or str(actual).casefold() != str(expected).casefold():
            path.unlink(missing_ok=True)
            return None
        return pid

    def _command(self, exe_name: str, module: str, *args: str) -> list[str]:
        candidate = self.paths.install_dir / exe_name
        if candidate.is_file():
            return [str(candidate), *args]
        return [sys.executable, "-B", "-m", module, *args]

    def _spawn(
        self,
        name: str,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen[Any]:
        with self.lock:
            current = self.processes.get(name)
            if current is not None and current.poll() is None:
                return current
            stdout = (self.log_dir / f"{name}.out.log").open("ab")
            stderr = (self.log_dir / f"{name}.err.log").open("ab")
            try:
                proc = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    env=env,
                    cwd=self.paths.install_dir if self.paths.install_dir.is_dir() else None,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            finally:
                stdout.close()
                stderr.close()
            self.processes[name] = proc
            (self.runtime_dir / f"{name}.pid").write_text(str(proc.pid), encoding="ascii")
            return proc

    def _roots(self) -> list[str]:
        # Product state is never a workspace. Installed user workspaces are
        # persisted as locally approved grants with explicit permissions.
        fallback = self.paths.state_dir / "default-workspace"
        fallback.mkdir(parents=True, exist_ok=True)
        sync_workspace_registry(self.paths, self.settings)
        return [str(fallback)]

    def start_mcp(self) -> dict[str, Any]:
        instance_id = ensure_instance_id(self.paths)
        if tcp_open("127.0.0.1", self.settings.mcp_port):
            try:
                health = json_get(f"http://127.0.0.1:{self.settings.mcp_port}/healthz")
            except Exception as exc:
                return {
                    "ok": False,
                    "reason": "port_in_use_by_unmanaged_process",
                    "detail": str(exc)[:200],
                }
            if (
                health.get("ok") is True
                and health.get("service") == "sentra-mcp"
                and health.get("instance_id") == instance_id
            ):
                return {
                    "ok": True,
                    "already_running": True,
                    "pid": self._persisted_pid("mcp"),
                }
            return {"ok": False, "reason": "port_in_use_by_different_instance"}
        policy = self.settings.policy()
        args = [
            "--transport", "streamable-http",
            "--host", "127.0.0.1",
            "--port", str(self.settings.mcp_port),
            "--process-mode", str(policy["process_mode"]),
        ]
        for surface in policy["surfaces"]:
            args += ["--surface", str(surface)]
        for root in self._roots():
            args += ["--allowed-root", root]
        env = os.environ.copy()
        env["SENTRA_STATE_DIR"] = str(self.paths.state_dir)
        env["SENTRA_INSTANCE_ID"] = instance_id
        env["SENTRA_EDGE_RELAY_URL"] = f"http://127.0.0.1:{self.settings.relay_port}"
        allowlist = tuple(policy.get("tool_allowlist") or ())
        if allowlist:
            env["SENTRA_MCP_TOOL_ALLOWLIST"] = ",".join(allowlist)
        else:
            env.pop("SENTRA_MCP_TOOL_ALLOWLIST", None)
        proc = self._spawn("mcp", self._command("sentra-mcp.exe", "sentra_mcp", *args), env=env)
        return {"ok": True, "pid": proc.pid}

    def start_relay(self) -> dict[str, Any]:
        token = ensure_browser_token(self.paths)
        if tcp_open("127.0.0.1", self.settings.relay_port):
            try:
                health = json_get(
                    f"http://127.0.0.1:{self.settings.relay_port}/health",
                    token=token,
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "reason": "port_in_use_by_unmanaged_process",
                    "detail": str(exc)[:200],
                }
            if health.get("ok") is True:
                return {
                    "ok": True,
                    "already_running": True,
                    "pid": self._persisted_pid("browser-relay"),
                }
            return {"ok": False, "reason": "port_in_use_by_different_instance"}
        command = self._command(
            "sentra-browser-relay.exe",
            "sentra_remote.browser_relay",
            "--state-dir", str(self.paths.state_dir),
            "--extension-dir", str(self.paths.extension_dir),
            "--port", str(self.settings.relay_port),
        )
        proc = self._spawn("browser-relay", command)
        return {"ok": True, "pid": proc.pid}

    def _init_tunnel_profile(self, secret: str, tunnel_id: str) -> None:
        profiles = self.paths.tunnel_dir / "profiles"
        profiles.mkdir(parents=True, exist_ok=True)
        profile = profiles / "sentra-local.yaml"
        if profile.is_file():
            return
        env = os.environ.copy()
        env["CONTROL_PLANE_API_KEY"] = secret
        command = [
            str(self.paths.tunnel_client),
            "init",
            "--sample", "sample_mcp_remote_no_auth",
            "--profile", "sentra-local",
            "--profile-dir", str(profiles),
            "--tunnel-id", tunnel_id,
            "--mcp-server-url", f"http://127.0.0.1:{self.settings.mcp_port}/mcp",
            "--control-plane-api-key-ref", "env:CONTROL_PLANE_API_KEY",
            "--health-listen-addr", "127.0.0.1:0",
            "--force",
        ]
        result = subprocess.run(
            command, env=env, capture_output=True, text=True, timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "tunnel init failed")[:1000])

    def start_tunnel(self) -> dict[str, Any]:
        existing = self._persisted_pid("tunnel")
        if existing is not None:
            return {"ok": True, "already_running": True, "pid": existing}
        config = load_tunnel_config(self.paths, reveal_secret=True)
        if not config:
            return {"ok": False, "reason": "not_configured"}
        if not self.paths.tunnel_client.is_file():
            return {"ok": False, "reason": "tunnel_client_missing"}
        secret = str(config.get("runtime_key") or "")
        tunnel_id = str(config.get("tunnel_id") or "")
        self._init_tunnel_profile(secret, tunnel_id)
        profiles = self.paths.tunnel_dir / "profiles"
        health_url = self.paths.tunnel_dir / "health-url.txt"
        health_url.unlink(missing_ok=True)
        env = os.environ.copy()
        env["CONTROL_PLANE_API_KEY"] = secret
        command = [
            str(self.paths.tunnel_client),
            "run",
            "--profile", "sentra-local",
            "--profile-dir", str(profiles),
            "--health.listen-addr", "127.0.0.1:0",
            "--health.url-file", str(health_url),
        ]
        proc = self._spawn("tunnel", command, env=env)
        return {"ok": True, "pid": proc.pid}

    def start_agent(self) -> dict[str, Any]:
        existing = self._persisted_pid("agent")
        if existing is not None:
            return {"ok": True, "already_running": True, "pid": existing}
        config = self.paths.state_dir / "agent.json"
        if not config.is_file():
            return {"ok": False, "reason": "not_paired"}
        proc = self._spawn(
            "agent",
            self._command(
                "sentra-agent.exe",
                "sentra_remote",
                "--config", str(config),
                "run",
            ),
        )
        return {"ok": True, "pid": proc.pid}

    def start_all(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.settings.autostart_relay:
            result["relay"] = self.start_relay()
        if self.settings.autostart_mcp:
            result["mcp"] = self.start_mcp()
        if self.settings.autostart_tunnel:
            try:
                result["tunnel"] = self.start_tunnel()
            except Exception as exc:
                result["tunnel"] = {"ok": False, "reason": str(exc)[:500]}
        if self.settings.autostart_agent:
            result["agent"] = self.start_agent()
        return result

    def stop(self, name: str) -> bool:
        with self.lock:
            proc = self.processes.pop(name, None)
        if proc is None or proc.poll() is not None:
            return False
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        (self.runtime_dir / f"{name}.pid").unlink(missing_ok=True)
        return True

    def stop_all(self) -> None:
        for name in ("agent", "tunnel", "mcp", "browser-relay"):
            try:
                self.stop(name)
            except Exception:
                pass

    def restart_all(self) -> dict[str, Any]:
        self.stop_all()
        time.sleep(0.25)
        return self.start_all()

    def status(self) -> dict[str, Any]:
        data = collect_product_status(self.paths, self.settings)
        with self.lock:
            data["managed_processes"] = {
                name: {
                    "pid": proc.pid,
                    "running": proc.poll() is None,
                }
                for name, proc in self.processes.items()
            }
            agent = self.processes.get("agent")
            if data.get("remote_agent", {}).get("configured"):
                data["remote_agent"]["ok"] = bool(agent is not None and agent.poll() is None)
        return data

    def save_runtime_state(self) -> None:
        payload = {
            "updated": time.time(),
            "status": self.status(),
        }
        path = self.runtime_dir / "status.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp.replace(path)
