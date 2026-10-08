"""Supervise installed SENTRA local MCP, Edge relay, tunnel and remote agent."""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from sentra_mcp.audit import AuditLogger

from .onboarding import build_onboarding_snapshot
from .tunnel_singleton import TunnelSingleton
from .product import (
    ProductPaths,
    ProductSettings,
    collect_product_status,
    ensure_browser_token,
    ensure_instance_id,
    json_get,
    load_tunnel_config,
    mcp_policy_status,
    sync_agent_policy,
    sync_workspace_registry,
    tcp_open,
    tunnel_credential_storage,
    tunnel_key_update,
)


class LocalRuntime:
    TUNNEL_FAILURE_GRACE_S = 9.0
    TUNNEL_RESTART_BACKOFF_BASE_S = 5.0
    TUNNEL_RESTART_BACKOFF_MAX_S = 300.0
    LOCAL_FAILURE_GRACE_S = 6.0
    LOCAL_RESTART_BACKOFF_S = 30.0
    LOCAL_MAX_RESTART_ATTEMPTS = 3

    def __init__(self, paths: ProductPaths, settings: ProductSettings) -> None:
        self.paths = paths
        self.settings = settings
        self.audit=AuditLogger(paths.audit_log,component="runtime")
        self.processes: dict[str, subprocess.Popen[Any]] = {}
        self.lock = threading.RLock()
        self.runtime_dir = self.paths.state_dir / "runtime"
        self.log_dir = self.paths.state_dir / "logs"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.authority_registry = self.paths.persist_runtime_authority()
        self._tunnel_failure_since: float | None = None
        self._tunnel_last_restart = 0.0
        self._tunnel_restart_attempts = 0
        self._tunnel_supervision: dict[str, Any] = {
            "state": "IDLE",
            "action": "none",
            "restart_attempts": 0,
        }
        self._local_failures: dict[str, float] = {}
        self._local_last_restarts: dict[str, float] = {}
        self._local_restart_attempts: dict[str, int] = {}

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

    def _matching_install_pids(self, name: str) -> list[int]:
        """Return Windows PIDs running the exact installed component binary."""
        if os.name != "nt":
            return []
        expected = self._expected_executable(name)
        if expected is None:
            return []
        try:
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode != 0:
            return []

        found: list[int] = []
        stdout = str(getattr(result, "stdout", "") or "")
        for row in csv.reader(stdout.splitlines()):
            if len(row) < 2:
                continue
            try:
                pid = int(row[1].strip())
            except ValueError:
                continue
            actual = self._windows_process_path(pid)
            if actual is not None and str(actual).casefold() == str(expected).casefold():
                found.append(pid)
        return sorted(set(found))

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
            log_mode = "wb" if name == "tunnel" else "ab"
            stdout = (self.log_dir / f"{name}.out.log").open(log_mode)
            stderr = (self.log_dir / f"{name}.err.log").open(log_mode)
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
            self.audit.emit("process.start","ok",{"service":name,"pid":proc.pid})
            return proc

    def _roots(self) -> list[str]:
        # In source-tree development the checkout itself is the canonical
        # configured workspace, so alias "sentra" keeps resolving to the repo
        # across MCP restarts. Installed product state is never a workspace.
        install_root = self.paths.install_dir.resolve()
        source_checkout = (
            (install_root / ".git").exists()
            and (install_root / "sentra_mcp").is_dir()
        )
        sync_workspace_registry(self.paths, self.settings)
        if source_checkout:
            return [str(install_root)]
        fallback = self.paths.state_dir / "default-workspace"
        fallback.mkdir(parents=True, exist_ok=True)
        return [str(fallback.resolve())]

    def _mcp_health(self) -> dict[str, Any] | None:
        try:
            health = json_get(f"http://127.0.0.1:{self.settings.mcp_port}/healthz")
        except Exception:
            return None
        instance_id = ensure_instance_id(self.paths)
        if (
            health.get("ok") is True
            and health.get("service") == "sentra-mcp"
            and health.get("instance_id") == instance_id
            and mcp_policy_status(self.settings, health)["ok"]
        ):
            return health
        return None

    def _wait_mcp_ready(self, timeout_s: float = 15.0) -> dict[str, Any] | None:
        deadline = time.monotonic() + max(0.1, float(timeout_s))
        while time.monotonic() < deadline:
            health = self._mcp_health()
            if health is not None:
                return health
            time.sleep(0.1)
        return None

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
                policy = mcp_policy_status(self.settings, health)
                if policy["ok"]:
                    self._roots()  # Apply current workspace grants even when reusing MCP.
                    return {
                        "ok": True,
                        "already_running": True,
                        "pid": self._persisted_pid("mcp"),
                    }
                # stop() accepts only owned handles or executable-verified persisted PIDs.
                if not self.stop("mcp"):
                    return {"ok": False, "reason": policy["reason"], "restart_required": True}
                deadline = time.monotonic() + 5.0
                while tcp_open("127.0.0.1", self.settings.mcp_port):
                    if time.monotonic() >= deadline:
                        return {"ok": False, "reason": "mcp_restart_port_still_in_use"}
                    time.sleep(0.1)
                self.audit.emit("mcp.policy.reconciled", "ok", {
                    "profile": self.settings.profile, "access_scope": self.settings.access_scope,
                })
            else:
                return {"ok": False, "reason": "port_in_use_by_different_instance"}
        policy = self.settings.policy()
        args = [
            "--transport", "streamable-http",
            "--host", "127.0.0.1",
            "--port", str(self.settings.mcp_port),
            "--state-dir", str(self.paths.state_dir),
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
                try:
                    auth = json_get(
                        f"http://127.0.0.1:{self.settings.relay_port}/auth/check",
                        token=token,
                    )
                except Exception as exc:
                    return {
                        "ok": False,
                        "reason": "relay_auth_mismatch",
                        "detail": str(exc)[:200],
                    }
                if auth.get("ok") is not True:
                    return {
                        "ok": False,
                        "reason": "relay_auth_mismatch",
                    }
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
            import yaml
            try:
                saved = yaml.safe_load(profile.read_text(encoding="utf-8")) or {}
                control = saved.get("control_plane") or {}
                servers = (saved.get("mcp") or {}).get("server_urls") or []
                if (control.get("tunnel_id") == tunnel_id
                        and control.get("api_key") == "env:CONTROL_PLANE_API_KEY"
                        and servers == [{"channel": "main", "url": f"http://127.0.0.1:{self.settings.mcp_port}/mcp"}]):
                    return
            except (OSError, ValueError, AttributeError, yaml.YAMLError):
                pass  # Regenerate an outdated or invalid managed profile.
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
            raise RuntimeError("tunnel_profile_initialization_failed")

    def start_tunnel(self) -> dict[str, Any]:
        config = load_tunnel_config(self.paths, reveal_secret=True)
        if not config:
            return {"ok": False, "reason": "not_configured"}
        if not self.paths.tunnel_client.is_file():
            return {"ok": False, "reason": "tunnel_client_missing"}
        secret = str(config.get("runtime_key") or "")
        tunnel_id = str(config.get("tunnel_id") or "")
        singleton = TunnelSingleton(
            tunnel_id,
            self.paths.state_dir,
            process_path=self._windows_process_path,
        )

        try:
            with singleton.acquire():
                global_live = singleton.live()
                if global_live is not None:
                    pid = int(global_live["pid"])
                    (self.runtime_dir / "tunnel.pid").write_text(
                        str(pid), encoding="ascii"
                    )
                    return {
                        "ok": True,
                        "already_running": True,
                        "adopted_global": True,
                        "pid": pid,
                    }

                existing = self._persisted_pid("tunnel")
                if existing is not None:
                    singleton.write(
                        existing, self.paths.tunnel_client, self.paths.state_dir
                    )
                    return {
                        "ok": True,
                        "already_running": True,
                        "pid": existing,
                    }

                # Legacy launchers did not write the global registry. Recover a
                # single exact-binary orphan and fail closed on duplicates.
                matching = self._matching_install_pids("tunnel")
                if len(matching) == 1:
                    pid = matching[0]
                    (self.runtime_dir / "tunnel.pid").write_text(
                        str(pid), encoding="ascii"
                    )
                    singleton.write(
                        pid, self.paths.tunnel_client, self.paths.state_dir
                    )
                    return {
                        "ok": True,
                        "already_running": True,
                        "adopted": True,
                        "pid": pid,
                    }
                if len(matching) > 1:
                    return {
                        "ok": False,
                        "reason": "duplicate_tunnel_processes",
                        "pids": matching,
                    }

                if self._mcp_health() is None:
                    return {
                        "ok": False,
                        "reason": "mcp_not_ready",
                        "detail": "authoritative MCP health is required before tunnel startup",
                    }

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
                singleton.write(
                    proc.pid, self.paths.tunnel_client, self.paths.state_dir
                )
                return {"ok": True, "pid": proc.pid}
        except RuntimeError as exc:
            return {
                "ok": False,
                "reason": "tunnel_singleton_busy",
                "detail": str(exc)[:200],
            }

    def start_agent(self) -> dict[str, Any]:
        existing = self._persisted_pid("agent")
        if existing is not None:
            return {"ok": True, "already_running": True, "pid": existing}
        config = self.paths.state_dir / "agent.json"
        if not config.is_file():
            return {"ok": False, "reason": "not_paired"}
        sync_agent_policy(self.paths, self.settings)
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
                if self.settings.autostart_mcp and self._wait_mcp_ready() is None:
                    result["tunnel"] = {
                        "ok": False,
                        "reason": "mcp_not_ready",
                        "detail": "MCP did not become authoritative before tunnel startup",
                    }
                else:
                    result["tunnel"] = self.start_tunnel()
            except Exception as exc:
                result["tunnel"] = {"ok": False, "reason": str(exc)[:500]}
        if self.settings.autostart_agent:
            result["agent"] = self.start_agent()
        return result

    def connect_and_verify(self, timeout_s: float = 15.0) -> dict[str, Any]:
        """Start configured services and return one bounded setup/doctor verdict."""
        started = self.start_all()
        tunnel_configured = bool(load_tunnel_config(self.paths))
        credential = tunnel_credential_storage(self.paths)
        deadline = time.monotonic() + max(0.1, float(timeout_s))
        status: dict[str, Any] = {}
        while True:
            status = self.status()
            mcp_ok = bool(status.get("mcp", {}).get("ok"))
            relay_ok = bool(status.get("relay", {}).get("ok"))
            tunnel_ok = bool(status.get("tunnel", {}).get("ok"))
            credential_ok = bool(credential.get("ok")) if tunnel_configured else True
            # The browser relay is an optional Edge surface. Connect & Verify
            # must validate the core MCP/tunnel path without blocking first-run
            # completion when the browser extension has not connected yet.
            if mcp_ok and credential_ok and (tunnel_ok or not tunnel_configured):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.2)

        mcp_ok = bool(status.get("mcp", {}).get("ok"))
        relay_ok = bool(status.get("relay", {}).get("ok"))
        tunnel_ok = bool(status.get("tunnel", {}).get("ok"))
        edge_ok = bool(status.get("edge", {}).get("ok"))
        web_models_status = status.get("web_models", {})
        web_models_installed = bool(web_models_status.get("installed", web_models_status.get("ok")))
        web_models_autostart = bool(web_models_status.get("autostart"))
        web_models_ready = bool(web_models_status.get("ready"))
        credential_ok = bool(credential.get("ok")) if tunnel_configured else True
        # Local product readiness cannot depend on optional external accounts.
        # A missing, invalid or offline OpenAI tunnel affects only ChatGPT.
        core_ready = mcp_ok
        onboarding_status = dict(status)
        onboarding_tunnel = dict(onboarding_status.get("tunnel") or {})
        onboarding_tunnel["configured"] = tunnel_configured
        onboarding_status["tunnel"] = onboarding_tunnel
        onboarding_credential = dict(credential)
        onboarding_credential["configured"] = tunnel_configured
        onboarding_status["credential_storage"] = onboarding_credential
        onboarding = build_onboarding_snapshot(onboarding_status)
        chatgpt_onboarding = build_onboarding_snapshot(onboarding_status, intent="chatgpt")
        # Optional integrations report separate health, never block local onboarding.
        onboarding_required = not onboarding.ready
        checks = [
            {"id": "mcp", "required": True, "ok": mcp_ok},
            {"id": "relay", "required": False, "ok": relay_ok},
            {
                "id": "credential_storage",
                "required": tunnel_configured,
                "ok": credential_ok,
                "scheme": credential.get("scheme"),
            },
            {"id": "tunnel", "required": tunnel_configured, "ok": tunnel_ok},
            {"id": "edge", "required": False, "ok": edge_ok},
            {
                "id": "web_models",
                "required": False,
                "ok": web_models_ready,
                "installed": web_models_installed,
                "autostart": web_models_autostart,
            },
        ]
        return {
            "ok": core_ready,
            "core_ready": core_ready,
            "onboarding_required": onboarding_required,
            "product_ready": onboarding.ready,
            "onboarding": onboarding.to_dict(),
            "chatgpt_onboarding": chatgpt_onboarding.to_dict(),
            "next_url": "sentra://onboarding" if onboarding_required else "sentra://home",
            "started": started,
            "checks": checks,
            "status": status,
        }

    def _stop_processes(
        self,
        name: str,
        proc: subprocess.Popen[Any] | None,
        *,
        tunnel_singleton: TunnelSingleton | None = None,
    ) -> bool:
        pids: set[int] = set()
        if proc is not None and proc.poll() is None:
            pids.add(int(proc.pid))

        if tunnel_singleton is not None:
            global_live = tunnel_singleton.live()
            if global_live is not None:
                pids.add(int(global_live["pid"]))

        if os.name == "nt":
            # A restarted Desktop process has an empty in-memory process map.
            # Persisted PIDs are accepted only after executable-path validation.
            persisted = self._persisted_pid(name)
            if persisted is not None:
                pids.add(persisted)
            if name == "tunnel":
                # First-run migration cleanup for legacy launchers that predate
                # the global Tunnel ID registry. The tunnel-client binary is
                # dedicated to this SENTRA installation/source checkout.
                pids.update(self._matching_install_pids(name))

        if not pids:
            if tunnel_singleton is not None:
                tunnel_singleton.clear()
            return False
        if os.name == "nt":
            for pid in sorted(pids):
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
        elif proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        else:
            return False
        (self.runtime_dir / f"{name}.pid").unlink(missing_ok=True)
        if tunnel_singleton is not None:
            tunnel_singleton.clear()
        return True

    def stop(self, name: str) -> bool:
        with self.lock:
            proc = self.processes.pop(name, None)

        if name != "tunnel":
            return self._stop_processes(name, proc)

        config = load_tunnel_config(self.paths)
        tunnel_id = str(config.get("tunnel_id") or "")
        if not tunnel_id:
            return self._stop_processes(name, proc)

        singleton = TunnelSingleton(
            tunnel_id,
            self.paths.state_dir,
            process_path=self._windows_process_path,
        )
        try:
            with singleton.acquire():
                return self._stop_processes(
                    name,
                    proc,
                    tunnel_singleton=singleton,
                )
        except RuntimeError:
            return False

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

    def supervise_local_once(
        self,
        status: dict[str, Any] | None = None,
        *,
        now: float | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Bounded self-healing for owned loopback services only.

        Never kill a conflicting process, reroute a session, or downgrade an
        isolated execution to unrestricted host execution.
        """
        current = status if status is not None else self.status()
        stamp = time.monotonic() if now is None else float(now)
        results: dict[str, dict[str, Any]] = {}
        components = (
            ("mcp", "autostart_mcp", self.start_mcp),
            ("relay", "autostart_relay", self.start_relay),
        )
        for name, setting, starter in components:
            if not getattr(self.settings, setting):
                results[name] = {"state": "DISABLED"}
                continue
            if bool((current.get(name) or {}).get("ok")):
                self._local_failures.pop(name, None)
                self._local_restart_attempts.pop(name, None)
                results[name] = {"state": "HEALTHY"}
                continue
            since = self._local_failures.setdefault(name, stamp)
            if stamp - since < self.LOCAL_FAILURE_GRACE_S:
                results[name] = {"state": "GRACE"}
                continue
            attempts = self._local_restart_attempts.get(name, 0)
            if attempts >= self.LOCAL_MAX_RESTART_ATTEMPTS:
                results[name] = {"state": "NEEDS_ATTENTION", "reason": "bounded_restart_exhausted"}
                continue
            if stamp - self._local_last_restarts.get(name, 0.0) < self.LOCAL_RESTART_BACKOFF_S:
                results[name] = {"state": "BACKOFF"}
                continue
            self._local_last_restarts[name] = stamp
            self._local_restart_attempts[name] = attempts + 1
            try:
                result = starter()
            except (OSError, RuntimeError, ValueError) as exc:
                result = {"ok": False, "reason": type(exc).__name__}
            results[name] = {
                "state": "RECOVERING" if result.get("ok") else "NEEDS_ATTENTION",
                "attempts": attempts + 1,
                "reason": result.get("reason"),
            }
        return results

    def supervise_once(
        self,
        status: dict[str, Any] | None = None,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        # A background restart must not replace a key being verified/rolled back.
        try:
            with tunnel_key_update(self.paths):
                return self._supervise_tunnel_once(status, now=now)
        except TimeoutError:
            return {"state": "CONFIGURING", "action": "none",
                    "restart_attempts": self._tunnel_restart_attempts}

    def _supervise_tunnel_once(
        self, status: dict[str, Any] | None = None, *, now: float | None = None,
    ) -> dict[str, Any]:
        current = status if status is not None else self.status()
        stamp = time.monotonic() if now is None else float(now)
        tunnel = dict(current.get("tunnel") or {})
        mcp = dict(current.get("mcp") or {})

        def finish(state: str, action: str = "none", **extra: Any) -> dict[str, Any]:
            payload = {
                "state": state,
                "action": action,
                "restart_attempts": self._tunnel_restart_attempts,
                **extra,
            }
            self._tunnel_supervision = payload
            previous=getattr(self,"_last_tunnel_audit_state",None)
            signature=(state,action,payload.get("reason"))
            if signature!=previous and hasattr(self,"audit"):
                self.audit.emit("runtime.tunnel.state","ok" if state in {"IDLE","HEALTHY","RUNNING"} else state.lower(),payload)
                self._last_tunnel_audit_state=signature
            return dict(payload)

        if not self.settings.autostart_tunnel or not tunnel.get("configured"):
            self._tunnel_failure_since = None
            self._tunnel_restart_attempts = 0
            return finish("IDLE")

        if tunnel.get("reauth_required"):
            self._tunnel_failure_since = None
            return finish("REAUTH_REQUIRED", reason="runtime_api_key_invalidated")

        if not mcp.get("ok"):
            self._tunnel_failure_since = None
            return finish("WAITING_MCP", reason="authoritative_mcp_not_ready")

        if tunnel.get("ok"):
            self._tunnel_failure_since = None
            self._tunnel_restart_attempts = 0
            return finish("HEALTHY")

        if self._tunnel_failure_since is None:
            self._tunnel_failure_since = stamp
            return finish(
                "DEGRADED",
                reason="tunnel_not_ready",
                grace_remaining_s=self.TUNNEL_FAILURE_GRACE_S,
            )

        elapsed = max(0.0, stamp - self._tunnel_failure_since)
        if elapsed < self.TUNNEL_FAILURE_GRACE_S:
            return finish(
                "DEGRADED",
                reason="tunnel_not_ready",
                grace_remaining_s=round(self.TUNNEL_FAILURE_GRACE_S - elapsed, 3),
            )

        backoff_s = min(
            self.TUNNEL_RESTART_BACKOFF_BASE_S * (2 ** self._tunnel_restart_attempts),
            self.TUNNEL_RESTART_BACKOFF_MAX_S,
        )
        since_restart = stamp - self._tunnel_last_restart
        if self._tunnel_last_restart and since_restart < backoff_s:
            return finish(
                "BACKOFF",
                reason="tunnel_not_ready",
                retry_after_s=round(backoff_s - since_restart, 3),
            )

        self.stop("tunnel")
        time.sleep(0.25)
        started = self.start_tunnel()
        self._tunnel_last_restart = stamp
        self._tunnel_restart_attempts += 1
        self._tunnel_failure_since = stamp
        if started.get("ok"):
            return finish(
                "RECOVERING",
                action="restart_tunnel",
                pid=started.get("pid"),
            )
        return finish(
            "DEGRADED",
            action="restart_failed",
            reason=str(started.get("reason") or "tunnel_restart_failed"),
        )

    def status(self, *, include_optional: bool = False) -> dict[str, Any]:
        data = collect_product_status(
            self.paths,
            self.settings,
            include_optional=include_optional,
        )
        data["runtime_authority"] = {
            "install_dir": str(self.paths.install_dir.resolve()),
            "state_dir": str(self.paths.state_dir.resolve()),
            "registry": str(self.authority_registry),
        }
        data["supervisor"] = {"tunnel": dict(self._tunnel_supervision)}
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
        data["onboarding"] = build_onboarding_snapshot(data).to_dict()
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
