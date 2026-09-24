"""Loopback Responses gateway. The upstream owns the browser and protocol runtime.

The gateway owns routing and the public model namespace. It deliberately forwards
SSE bytes without collecting a turn, so upstream cancellation and event ordering
remain observable to Codex.
"""
from __future__ import annotations

import ctypes
import hashlib
import hmac
import http.client
import io
import json
import os
import secrets
import signal
import socket
import subprocess
import threading
import zstandard as zstd
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from orchestrator.resources import ResourceRegistry
from sentra_remote.product import ProductPaths, ProductSettings, collect_product_status
from sentra_mcp.services.durable import DurableStateConflict, StaleFenceError
from .turn_authority import TurnAuthority

PREFIX = "sentra/chatgpt-web/"
UPSTREAM_PREFIX = "chatgpt-web/"
EXPECTED_UPSTREAM_VERSION = "6.0.0"
MAX_REQUEST_BYTES = 128 * 1024 * 1024
HOP_HEADERS = {"connection", "content-length", "transfer-encoding", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "upgrade", "host"}
REQUEST_REWRITE_HEADERS = {"content-encoding"}


def _decode_json_request_bytes(raw: bytes, content_encoding: str) -> bytes:
    encoding = content_encoding.strip().lower()
    if not encoding or encoding == "identity":
        return raw
    if encoding != "zstd":
        raise ValueError(f"unsupported content encoding: {encoding}")
    try:
        with zstd.ZstdDecompressor().stream_reader(io.BytesIO(raw)) as reader:
            decoded = reader.read(MAX_REQUEST_BYTES + 1)
    except zstd.ZstdError as exc:
        raise ValueError("invalid zstd request body") from exc
    if len(decoded) > MAX_REQUEST_BYTES:
        raise ValueError("decoded request body exceeds limit")
    return decoded


def _load_or_create_private_token(state_root: Path, filename: str) -> str:
    token_dir = state_root / "web-models"
    token_dir.mkdir(parents=True, exist_ok=True)
    token_path = token_dir / filename
    try:
        current = token_path.read_text(encoding="utf-8").strip()
        if len(current) >= 32:
            return current
    except OSError:
        pass
    token = secrets.token_urlsafe(48)
    temp = token_path.with_suffix(".tmp")
    temp.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, token_path)
    return token


def load_or_create_gateway_admin_token(state_root: Path) -> str:
    return _load_or_create_private_token(state_root, "gateway-admin.token")


def _load_or_create_turn_authority_token(state_root: Path) -> str:
    return _load_or_create_private_token(state_root, "turn-authority.token")


def _codex_turn_identity(raw: object, *, path: str, model: str) -> str | None:
    if isinstance(raw, str):
        if not raw or len(raw) > 16_384:
            return None
        try:
            metadata = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    elif isinstance(raw, dict):
        metadata = raw
    else:
        return None
    if not isinstance(metadata, dict):
        return None
    thread_id = metadata.get("thread_id")
    turn_id = metadata.get("turn_id")
    if not isinstance(thread_id, str) or not thread_id or len(thread_id) > 256:
        return None
    if not isinstance(turn_id, str) or not turn_id or len(turn_id) > 256:
        return None
    request_kind = metadata.get("request_kind")
    if not isinstance(request_kind, str) or not request_kind or len(request_kind) > 64:
        request_kind = "turn"
    return json.dumps(
        {"thread_id": thread_id, "turn_id": turn_id, "request_kind": request_kind,
         "path": path, "model": model},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )


@dataclass(frozen=True)
class GatewayConfig:
    upstream: str = "http://127.0.0.1:17841"
    host: str = "127.0.0.1"
    port: int = 17842
    admin_token: str = ""
    upstream_control_token: str = ""
    connector_name: str = "SENTRA tunnel"
    checkout: Path = Path(__file__).resolve().parent.parent / "third_party" / "codex-chatgpt-web"
    launcher_executable: Path | None = None
    state_root: Path | None = None
    browser_descriptor: Path | None = None

    def __post_init__(self) -> None:
        parsed = urlsplit(self.upstream)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path not in {"", "/"} or parsed.username or parsed.password:
            raise ValueError("upstream must be a loopback HTTP origin")
        if self.host not in {"127.0.0.1", "localhost"}:
            raise ValueError("gateway must bind to loopback")
        if not 0 <= self.port <= 65535:
            raise ValueError("invalid gateway port")
        if (not self.connector_name.strip() or len(self.connector_name.strip()) > 80
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in self.connector_name)):
            raise ValueError("invalid SENTRA connector name")


class LauncherSupervisor:
    """Starts the upstream launcher only; its own supervisor owns child processes."""

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.lock = threading.RLock()
        self.process: subprocess.Popen | None = None
        self.authority_port = config.port
        self.turn_authority_token = ""
        self.upstream_control_token = ""
        self.upstream_control_token = ""

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if not isinstance(pid, int) or pid <= 0:
            return False
        if os.name == "nt":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
            kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == 259
            finally:
                kernel.CloseHandle(handle)
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _adopted_status(self) -> dict[str, Any] | None:
        try:
            descriptor = json.loads(self._browser_descriptor_path().read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        pid = descriptor.get("pid")
        if (descriptor.get("version") != 3
                or descriptor.get("kind") != "codex-web-gpt-launcher"
                or descriptor.get("sentraManaged") is not True
                or not self._pid_alive(pid)):
            return None
        payload = self.validate_payload()
        expected_patch = str(payload.get("patch_sha256") or "")
        if expected_patch and descriptor.get("sentraIntegrationPatchSha256") != expected_patch:
            return {
                "running": False,
                "pid": None,
                "source": "stale",
                "stale_pid": pid,
                "reason": "integration_patch_mismatch",
            }
        return {"running": True, "pid": pid, "source": "adopted"}

    def status(self) -> dict:
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            if running:
                return {"running": True, "pid": self.process.pid, "source": "owned"}
            adopted = self._adopted_status()
            return adopted or {"running": False, "pid": None, "source": "none"}

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["SENTRA_TURN_AUTHORITY_URL"] = f"http://{self.config.host}:{self.authority_port}"
        environment["SENTRA_WEB_GATEWAY_URL"] = f"http://{self.config.host}:{self.authority_port}/v1"
        environment["SENTRA_CONNECTOR_NAME"] = self.config.connector_name.strip()
        payload = self.validate_payload()
        if payload.get("packaged"):
            environment["SENTRA_INTEGRATION_PATCH_SHA256"] = str(payload["patch_sha256"])
            if payload.get("commit"):
                environment["SENTRA_UPSTREAM_COMMIT"] = str(payload["commit"])
        if self.turn_authority_token:
            environment["SENTRA_TURN_AUTHORITY_TOKEN"] = self.turn_authority_token
        if self.upstream_control_token:
            environment["SENTRA_WEB_CONTROL_TOKEN"] = self.upstream_control_token
        return environment

    def _browser_descriptor_path(self) -> Path:
        packaged = self._packaged_launcher_path().is_file()
        return Path(self.config.browser_descriptor or (
            Path.home()
            / (".codex-chatgpt-web" if packaged else ".codex-chatgpt-web-dev")
            / "runtime"
            / "launcher-browser.json"
        )).resolve()

    def _packaged_launcher_path(self) -> Path:
        checkout = self.config.checkout.resolve()
        if self.config.launcher_executable:
            return Path(self.config.launcher_executable).resolve()

        install_root = checkout.parents[1]
        installed = install_root / "web-models" / "win-unpacked" / "Codex Web GPT.exe"
        development = install_root / "dist" / "web-models" / "win-unpacked" / "Codex Web GPT.exe"
        if installed.is_file():
            return installed.resolve()
        if development.is_file():
            return development.resolve()
        return installed.resolve()

    def validate_payload(self) -> dict[str, Any]:
        packaged = self._packaged_launcher_path()
        if not packaged.is_file():
            return {"packaged": False, "launcher": str(packaged)}

        runtime_manifest = packaged.parent / "resources" / "runtime" / "manifest.json"
        if not runtime_manifest.is_file():
            raise RuntimeError("Web Models packaged runtime manifest is missing")

        payload_root = packaged.parent.parent
        build_state_path = payload_root / "integration-build.json"
        if not build_state_path.is_file():
            raise RuntimeError("Web Models integration build metadata is missing")
        try:
            build_state = json.loads(build_state_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Web Models integration build metadata is invalid") from exc

        checkout = self.config.checkout.resolve()
        install_root = checkout.parents[1]
        source_integration = install_root / "integrations" / "codex_chatgpt_web"
        source_patch = source_integration / "sentra-upstream.patch"
        packaged_patch = payload_root / "licenses" / "codex-chatgpt-web" / "sentra-upstream.patch"
        reference_patch = source_patch if source_patch.is_file() else packaged_patch
        if not reference_patch.is_file():
            raise RuntimeError("Web Models integration patch provenance is missing")

        patch_hash = hashlib.sha256(reference_patch.read_bytes()).hexdigest()
        if str(build_state.get("patch_sha256") or "").lower() != patch_hash:
            raise RuntimeError(
                "Web Models payload is stale; rebuild scripts/integrations/Build-CodexChatGPTWebRuntime.ps1"
            )

        source_manifest = source_integration / "upstream.json"
        if source_manifest.is_file():
            try:
                manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError("Web Models integration manifest is invalid") from exc
            expected_files = manifest.get("patch_files")
            built_files = build_state.get("patch_files")
            if not isinstance(expected_files, list) or not isinstance(built_files, list):
                raise RuntimeError("Web Models integration patch file set is invalid")
            if sorted(map(str, built_files)) != sorted(map(str, expected_files)):
                raise RuntimeError("Web Models payload patch file set is stale; rebuild the integration")
            expected_commit = str(manifest.get("commit") or "")
            if expected_commit and str(build_state.get("commit") or "") != expected_commit:
                raise RuntimeError("Web Models payload upstream commit is stale; rebuild the integration")

        return {
            "packaged": True,
            "launcher": str(packaged),
            "patch_sha256": patch_hash,
            "commit": build_state.get("commit"),
        }

    def runtime_control(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if action not in {"drain", "resume", "interrupt-turn", "verify-connector"}:
            raise ValueError("invalid upstream runtime control action")
        descriptor = json.loads(self._browser_descriptor_path().read_text(encoding="utf-8"))
        if descriptor.get("version") != 3 or descriptor.get("kind") != "codex-web-gpt-launcher":
            raise ValueError("launcher browser descriptor is incompatible")
        if descriptor.get("sentraManaged") is not True:
            raise PermissionError("launcher is not running under SENTRA authority")
        control = descriptor.get("control")
        if not isinstance(control, dict):
            raise ValueError("launcher browser control descriptor is missing")
        endpoint = str(control.get("endpoint") or "")
        token = str(control.get("token") or "")
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
                or not parsed.port or parsed.path not in {"", "/"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("launcher browser control endpoint is invalid")
        if len(token) < 40 or any(not (char.isalnum() or char in "_-") for char in token):
            raise ValueError("launcher browser control token is invalid")
        body = {"action": action, **(payload or {})}
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=8)
        try:
            connection.request(
                "POST",
                "/v1/sentra/runtime-control",
                encoded,
                {
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                    "Content-Length": str(len(encoded)),
                },
            )
            response = connection.getresponse()
            raw = response.read()
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"launcher runtime control rejected: HTTP {response.status}")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("launcher runtime control response is invalid")
            return result
        finally:
            connection.close()

    def route(self, action: str = "status") -> dict:
        if action not in {"status", "sentra", "disconnect", "doctor"}:
            raise ValueError("invalid Codex route action")
        checkout = self.config.checkout.resolve()
        packaged = self._packaged_launcher_path()
        if packaged.is_file():
            self.validate_payload()
            command = [str(packaged.parent / "resources" / "runtime" / "bin" / "codex-chatgpt-web.cmd")]
            cwd = packaged.parent
        else:
            import shutil
            bun = shutil.which("bun") or str(checkout.parents[1] / ".sentra" / "toolchain" / "node_modules" / "bun" / "bin" / "bun.exe")
            if not Path(bun).is_file():
                raise FileNotFoundError("Bun is required to inspect the Codex route")
            patched = checkout.parents[1] / ".sentra" / "integrations" / "codex-chatgpt-web" / "source" / "6.0.0"
            if patched.is_dir():
                checkout = patched
            command = [bun, "run", "src/cli.ts"]
            cwd = checkout
        command += ["doctor", "--json"] if action == "doctor" else ["route", action]
        result = subprocess.run(command, cwd=str(cwd), env=self._environment(), capture_output=True,
                                text=True, timeout=60 if action == "doctor" else 20, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0 and action != "doctor":
            raise RuntimeError((result.stderr or result.stdout).strip()[-600:] or "Codex route command failed")
        route = json.loads(result.stdout)
        if not isinstance(route, dict):
            raise ValueError("Codex route status is invalid")
        if action != "doctor":
            route["points_to_sentra"] = route.get("routeUrl") == self._environment()["SENTRA_WEB_GATEWAY_URL"]
        return route

    def start(self, *, hidden: bool = False) -> dict:
        with self.lock:
            checkout = self.config.checkout.resolve()
            packaged = self._packaged_launcher_path()
            if packaged.is_file():
                self.validate_payload()
            current = self.status()
            if current.get("source") == "stale":
                raise RuntimeError(
                    f"stale Web Models launcher is still running (pid={current.get('stale_pid')}); "
                    "stop the old launcher before starting the rebuilt payload"
                )
            if current["running"]:
                if not hidden and packaged.is_file():
                    subprocess.Popen([str(packaged)],
                                     cwd=str(packaged.parent), env=self._environment(),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return current
            environment = self._environment()
            if packaged.is_file():
                self.process = subprocess.Popen(
                    [str(packaged), *(["--hidden"] if hidden else [])], cwd=str(packaged.parent), env=environment,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
                    start_new_session=os.name != "nt",
                )
                return self.status()
            if not (checkout / "scripts" / "start-launcher.ts").is_file():
                raise FileNotFoundError("pinned upstream launcher is missing")
            import shutil
            bun = shutil.which("bun")
            if not bun:
                candidate = checkout.parents[1] / ".sentra" / "toolchain" / "node_modules" / "bun" / "bin" / ("bun.exe" if os.name == "nt" else "bun")
                if candidate.is_file():
                    bun = str(candidate)
            if not bun:
                raise FileNotFoundError("Bun is required to launch the upstream UI")
            self.process = subprocess.Popen(
                [bun, "run", "scripts/start-launcher.ts"], cwd=str(checkout), env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
                start_new_session=os.name != "nt",
            )
            return self.status()

    def stop(self) -> dict:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                else:
                    os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None
            return self.status()


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows, SO_REUSEADDR permits multiple listeners on the same port and can
    # split Codex traffic across different Gateway/Launcher owners. Keep fast
    # restarts on POSIX, but require an exclusive loopback owner on Windows.
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, config: GatewayConfig):
        self.config = config
        state_root = Path(config.state_root or ProductPaths.default().state_dir).resolve()
        if config.launcher_executable and config.launcher_executable.is_file():
            install_root = config.launcher_executable.resolve().parents[2]
        else:
            install_root = config.checkout.resolve().parents[1]
        self.product_paths = ProductPaths(install_root, state_root)
        try:
            self.product_settings = ProductSettings.load(self.product_paths.settings)
        except (OSError, ValueError, json.JSONDecodeError):
            self.product_settings = ProductSettings()
        self.admin_token = config.admin_token.strip() or load_or_create_gateway_admin_token(state_root)
        self.turn_authority_token = _load_or_create_turn_authority_token(state_root)
        self.upstream_control_token = (
            config.upstream_control_token.strip()
            or _load_or_create_private_token(state_root, "upstream-control.token")
        )
        self.launcher = LauncherSupervisor(config)
        self.launcher.turn_authority_token = self.turn_authority_token
        self.launcher.upstream_control_token = self.upstream_control_token
        self.resources = ResourceRegistry()
        # TurnAuthority must observe the exact same Browser Host descriptor as the
        # launcher supervisor. Auto-detected packaged payloads leave
        # config.launcher_executable unset, so deriving this independently used to
        # point authority at ~/.codex-chatgpt-web-dev while the launcher published
        # ~/.codex-chatgpt-web. That made every browser-start look stale.
        descriptor = self.launcher._browser_descriptor_path()
        self.turn_authority = TurnAuthority(state_root, descriptor)
        super().__init__((config.host, config.port), GatewayHandler)
        self.launcher.authority_port = self.server_port

    def sentra_doctor(self, *, verify_connector: bool = False) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        def add(check_id: str, status: str, message: str, detail: str | None = None) -> None:
            item: dict[str, Any] = {"id": check_id, "status": status, "message": message}
            if detail:
                item["detail"] = detail[:500]
            checks.append(item)

        add("sentra-gateway", "ok", "SENTRA Model Gateway is healthy")

        try:
            payload = self.launcher.validate_payload()
            if payload.get("packaged"):
                add("web-payload", "ok", "Web Models payload matches the current SENTRA integration")
            else:
                add("web-payload", "warning", "Packaged Web Models payload is not configured; source launcher will be used")
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            add("web-payload", "error", "Web Models payload is stale or incomplete", str(exc))

        try:
            product = collect_product_status(self.product_paths, self.product_settings)
        except Exception as exc:
            product = {}
            add("sentra-status", "error", "SENTRA product status could not be collected", str(exc))

        mcp = product.get("mcp") if isinstance(product, dict) else {}
        add(
            "sentra-mcp",
            "ok" if isinstance(mcp, dict) and mcp.get("ok") else "error",
            "SENTRA MCP is healthy" if isinstance(mcp, dict) and mcp.get("ok") else "SENTRA MCP is unavailable",
            str(mcp.get("detail") or "") if isinstance(mcp, dict) else "",
        )

        relay = product.get("relay") if isinstance(product, dict) else {}
        add(
            "sentra-relay",
            "ok" if isinstance(relay, dict) and relay.get("ok") else "warning",
            "SENTRA browser relay is healthy" if isinstance(relay, dict) and relay.get("ok") else "SENTRA browser relay is idle or unavailable",
            str(relay.get("detail") or "") if isinstance(relay, dict) else "",
        )

        tunnel = product.get("tunnel") if isinstance(product, dict) else {}
        tunnel_configured = isinstance(tunnel, dict) and bool(tunnel.get("configured"))
        tunnel_ok = tunnel_configured and bool(tunnel.get("ok"))
        add(
            "sentra-tunnel",
            "ok" if tunnel_ok else ("error" if tunnel_configured else "warning"),
            "SENTRA tunnel is healthy and ready" if tunnel_ok else (
                "SENTRA tunnel is configured but not ready" if tunnel_configured
                else "SENTRA tunnel is not configured"
            ),
            str(tunnel.get("detail") or "") if isinstance(tunnel, dict) else "",
        )

        edge = product.get("edge") if isinstance(product, dict) else {}
        workers = edge.get("workers", []) if isinstance(edge, dict) else []
        add(
            "sentra-edge",
            "ok" if workers else "warning",
            f"SENTRA Edge bridge has {len(workers)} worker(s) online" if workers
            else "SENTRA Edge bridge has no worker online (lazy/idle is allowed)",
        )

        remote = product.get("remote_agent") if isinstance(product, dict) else {}
        remote_configured = isinstance(remote, dict) and bool(remote.get("configured"))
        add(
            "sentra-remote-agent",
            "ok" if isinstance(remote, dict) and remote.get("ok") else "warning",
            "SENTRA Remote Agent is online" if isinstance(remote, dict) and remote.get("ok") else (
                "SENTRA Remote Agent is configured but not online" if remote_configured
                else "SENTRA Remote Agent is optional and not configured"
            ),
        )

        try:
            self.turn_authority.durable.list_runs("sentra:web-model-gateway", offset=0, limit=1)
            add("sentra-durable", "ok", "SENTRA Durable Core is available")
        except Exception as exc:
            add("sentra-durable", "error", "SENTRA Durable Core is unavailable", str(exc))

        upstream_checks: list[dict[str, Any]] = []
        try:
            report = self.launcher.route("doctor")
            if isinstance(report, dict):
                for item in report.get("checks", []):
                    if isinstance(item, dict) and item.get("id") in {
                        "config", "browser-host", "login", "chrome", "proxy"
                    }:
                        upstream_checks.append(dict(item))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            upstream_checks.append({
                "id": "browser-host",
                "status": "error",
                "message": "ChatGPT Web runtime could not be verified",
                "detail": str(exc)[:500],
            })
        checks.extend(upstream_checks)

        try:
            route = self.launcher.route("status")
            route_ok = bool(route.get("installed") and route.get("active") and route.get("points_to_sentra"))
            add(
                "codex-route",
                "ok" if route_ok else "warning",
                "Codex model route points to the SENTRA Gateway" if route_ok
                else "Codex model route is not connected to the SENTRA Gateway",
            )
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            add("codex-route", "error", "Codex model route could not be verified", str(exc))

        if verify_connector:
            try:
                connector = self.launcher.runtime_control(
                    "verify-connector",
                    {"connectorName": self.config.connector_name.strip()},
                )
                verified = bool(
                    isinstance(connector, dict)
                    and connector.get("ok") is True
                    and connector.get("verified") is True
                    and connector.get("connectorName") == self.config.connector_name.strip()
                )
                add(
                    "connector",
                    "ok" if verified else "error",
                    (
                        f"ChatGPT connector {self.config.connector_name.strip()!r} is available"
                        if verified else
                        f"ChatGPT connector {self.config.connector_name.strip()!r} could not be verified"
                    ),
                )
            except (OSError, PermissionError, ValueError, RuntimeError, http.client.HTTPException) as exc:
                message = str(exc)
                manual = "Zero Risk" in message or "manual" in message.lower()
                add(
                    "connector",
                    "warning" if manual else "error",
                    (
                        f"ChatGPT connector {self.config.connector_name.strip()!r} requires manual selection in Zero Risk mode"
                        if manual else
                        f"ChatGPT connector {self.config.connector_name.strip()!r} could not be verified"
                    ),
                    message,
                )
        else:
            add(
                "connector",
                "warning",
                f"ChatGPT connector {self.config.connector_name.strip()!r} has not been actively verified",
            )
        return {
            "ok": not any(item.get("status") == "error" for item in checks),
            "mode": "sentra",
            "checks": checks,
            "sentra": product,
        }

    def server_close(self) -> None:
        super().server_close()
        self.turn_authority.durable.close()


class GatewayHandler(BaseHTTPRequestHandler):
    server: GatewayServer
    # Codex probes /v1/responses with a WebSocket handshake before falling back to
    # HTTP Responses. The handshake itself requires an HTTP/1.1 response; replying
    # with HTTP/1.0 makes Codex treat the route as a broken WebSocket endpoint
    # instead of honoring the 426 fallback response.
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def _json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized_admin(self) -> bool:
        expected = self.server.admin_token
        given = self.headers.get("Authorization", "")
        return bool(expected) and hmac.compare_digest(given, "Bearer " + expected)

    def _authorized_internal(self) -> bool:
        expected = self.server.turn_authority_token
        given = self.headers.get("Authorization", "")
        return bool(expected) and hmac.compare_digest(given, "Bearer " + expected)

    def _upstream(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict | None = None,
        *,
        body_reencoded: bool = False,
    ) -> http.client.HTTPResponse:
        parsed = urlsplit(self.server.config.upstream)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=900)
        excluded = HOP_HEADERS | {"cookie", "content-type", "accept"}
        if body_reencoded:
            excluded |= REQUEST_REWRITE_HEADERS
        outbound = {"Accept": self.headers.get("Accept", "application/json")}
        for name, value in self.headers.items():
            if name.lower() not in excluded:
                outbound[name] = value
        if body is not None:
            outbound["Content-Type"] = "application/json"
        if headers:
            outbound.update(headers)
        connection.request(method, path, body=body, headers=outbound)
        response = connection.getresponse()
        response._sentra_connection = connection
        return response

    def _proxy(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict | None = None,
        *,
        body_reencoded: bool = False,
        rewrite_web_model_namespace: bool = False,
    ) -> int | None:
        response = None
        try:
            response = self._upstream(method, path, body, headers, body_reencoded=body_reencoded)
            self.send_response(response.status)
            response_headers = response.getheaders()
            content_type = next(
                (value for name, value in response_headers if name.lower() == "content-type"),
                "",
            )
            content_encoding = next(
                (value for name, value in response_headers if name.lower() == "content-encoding"),
                "",
            ).strip().lower()
            if rewrite_web_model_namespace and content_encoding not in {"", "identity"}:
                raise http.client.HTTPException(
                    f"cannot rewrite compressed upstream response: {content_encoding}"
                )
            has_length = False
            for name, value in response_headers:
                lower = name.lower()
                if lower not in HOP_HEADERS:
                    self.send_header(name, value)
                    has_length = has_length or lower == "content-length"
            # http.client removes upstream chunk framing before exposing read1().
            # Re-frame unknown-length responses as HTTP/1.1 chunked downstream so
            # Codex receives each SSE heartbeat immediately instead of waiting for
            # a close-delimited body to terminate.
            body_allowed = (
                method.upper() != "HEAD"
                and not 100 <= response.status < 200
                and response.status not in {204, 304}
            )
            downstream_chunked = body_allowed and not has_length
            if downstream_chunked:
                self.send_header("Transfer-Encoding", "chunked")
            elif not body_allowed and not has_length:
                self.send_header("Content-Length", "0")
            self.end_headers()
            if body_allowed:
                while data := response.read1(65536):
                    if rewrite_web_model_namespace:
                        data = data.replace(
                            b'"chatgpt-web/',
                            b'"sentra/chatgpt-web/',
                        )
                    if os.getenv("SENTRA_GATEWAY_DEBUG_STREAM", "").strip() == "1":
                        preview = data[:4096].decode("utf-8", errors="replace")
                        events = [
                            line[7:].strip()
                            for line in preview.splitlines()
                            if line.startswith("event: ")
                        ]
                        print(
                            "SENTRA_GATEWAY_STREAM "
                            + json.dumps({
                                "path": path,
                                "bytes": len(data),
                                "events": events[:16],
                                "done": "data: [DONE]" in preview,
                                "failed_data": [
                                    line[6:].strip()[:1500]
                                    for line in preview.splitlines()
                                    if "response.failed" in events and line.startswith("data: ")
                                ][:2],
                            }, separators=(",", ":")),
                            flush=True,
                        )
                    if downstream_chunked:
                        self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
                        self.wfile.write(data)
                        self.wfile.write(b"\r\n")
                    else:
                        self.wfile.write(data)
                    self.wfile.flush()
                if downstream_chunked:
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
            return response.status
        except (OSError, http.client.HTTPException) as exc:
            if response is None:
                self._json(502, {"error": {"type": "upstream_error", "message": str(exc)}})
        finally:
            if response is not None:
                response._sentra_connection.close()

    def _read_chunked_body(self) -> bytes:
        body = bytearray()
        while True:
            line = self.rfile.readline(8192)
            if not line or not line.endswith(b"\r\n"):
                raise ValueError("invalid chunk framing")
            size_text = line[:-2].split(b";", 1)[0].strip()
            if not size_text:
                raise ValueError("missing chunk size")
            try:
                size = int(size_text, 16)
            except ValueError as exc:
                raise ValueError("invalid chunk size") from exc
            if size < 0 or len(body) + size > MAX_REQUEST_BYTES:
                raise ValueError("invalid request size")
            if size == 0:
                # Consume bounded trailers until the terminating empty line.
                trailer_bytes = 0
                while True:
                    trailer = self.rfile.readline(8192)
                    trailer_bytes += len(trailer)
                    if trailer_bytes > 64 * 1024 or not trailer:
                        raise ValueError("invalid chunk trailers")
                    if trailer == b"\r\n":
                        return bytes(body)
                    if not trailer.endswith(b"\r\n"):
                        raise ValueError("invalid chunk trailers")
            chunk = self.rfile.read(size)
            if len(chunk) != size or self.rfile.read(2) != b"\r\n":
                raise ValueError("truncated chunk")
            body.extend(chunk)

    def _raw_body(self) -> bytes | None:
        try:
            transfer_encoding = self.headers.get("Transfer-Encoding", "").strip().lower()
            content_length = self.headers.get("Content-Length")
            if transfer_encoding and content_length is not None:
                raise ValueError("ambiguous request framing")
            if transfer_encoding:
                codings = [part.strip() for part in transfer_encoding.split(",") if part.strip()]
                if codings != ["chunked"]:
                    raise ValueError("unsupported transfer encoding")
                return self._read_chunked_body()
            if content_length is None:
                raise ValueError("missing request size")
            size = int(content_length)
            if not 0 <= size <= MAX_REQUEST_BYTES:
                raise ValueError("invalid request size")
            body = self.rfile.read(size)
            if len(body) != size:
                raise ValueError("truncated request body")
            return body
        except ValueError:
            self._json(400, {"error": {"type": "invalid_request_error", "message": "invalid request size"}})
            return None

    def _body(self) -> dict | None:
        raw = self._raw_body()
        if raw is None:
            return None
        try:
            raw = _decode_json_request_bytes(raw, self.headers.get("Content-Encoding", ""))
        except ValueError as exc:
            self._json(415, {"error": {"type": "invalid_request_error", "message": str(exc)}})
            return None
        if os.getenv("SENTRA_GATEWAY_DEBUG_HTTP", "").strip() == "1":
            print(
                "SENTRA_GATEWAY_REQUEST "
                + json.dumps({
                    "method": self.command,
                    "path": self.path,
                    "content_length": self.headers.get("Content-Length"),
                    "transfer_encoding": self.headers.get("Transfer-Encoding"),
                    "content_encoding": self.headers.get("Content-Encoding"),
                    "content_type": self.headers.get("Content-Type"),
                    "raw_bytes": len(raw),
                    "raw_prefix_hex": raw[:16].hex(),
                }, separators=(",", ":")),
                flush=True,
            )
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("request body must be an object")
            return value
        except (ValueError, json.JSONDecodeError) as exc:
            if os.getenv("SENTRA_GATEWAY_DEBUG_HTTP", "").strip() == "1":
                print(
                    "SENTRA_GATEWAY_INVALID_JSON "
                    + json.dumps({
                        "path": self.path,
                        "content_length": self.headers.get("Content-Length"),
                        "transfer_encoding": self.headers.get("Transfer-Encoding"),
                        "content_encoding": self.headers.get("Content-Encoding"),
                        "content_type": self.headers.get("Content-Type"),
                        "raw_len": len(raw),
                        "raw_prefix_hex": raw[:96].hex(),
                        "error": str(exc)[:200],
                    }, separators=(",", ":")),
                    flush=True,
                )
            self._json(400, {"error": {"type": "invalid_request_error", "message": "invalid JSON request"}})
            return None

    def do_GET(self) -> None:
        parsed_request = urlsplit(self.path)
        path = parsed_request.path
        if path == "/healthz":
            try:
                response = self._upstream("GET", "/healthz")
                upstream = json.loads(response.read())
                response._sentra_connection.close()
                healthy = (
                    response.status == 200
                    and upstream.get("service") == "codex-chatgpt-web"
                    and upstream.get("version") == EXPECTED_UPSTREAM_VERSION
                    and upstream.get("status") == "ok"
                    and upstream.get("accepting_turns", True) is True
                )
            except (OSError, ValueError, http.client.HTTPException):
                upstream, healthy = {}, False
            self.server.resources.ingest_manifest({
                "resource_type": "model_browser",
                "resources": [{
                    "resource_id": "model:chatgpt-web:primary",
                    "state": "READY" if healthy else "OFFLINE",
                    "capacity": 5,
                    "capabilities": {"responses": True, "sse": True, "compaction": True, "browser_host": "electron"},
                    "labels": {"provider": "chatgpt-web", "version": str(upstream.get("version") or "")},
                    "active_turns": upstream.get("active_browser_turns", 0),
                    "accepting_turns": upstream.get("accepting_turns") is True,
                }],
            })
            self._json(200 if healthy else 503, {"status": "ok" if healthy else "unavailable", "service": "sentra-model-gateway", "upstream": upstream, "launcher": self.server.launcher.status()})
            return
        if path == "/sentra/doctor":
            if not (self._authorized_internal() or self._authorized_admin()):
                self._json(401, {"error": "unauthorized"})
                return
            verify_values = parse_qs(parsed_request.query).get("verify_connector", [])
            verify_connector = any(value.lower() in {"1", "true", "yes"} for value in verify_values)
            self._json(200, self.server.sentra_doctor(verify_connector=verify_connector))
            return
        if path == "/sentra/resources":
            if not self._authorized_admin():
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, {"resources": self.server.resources.snapshot()})
            return
        if path == "/sentra/browser/leases":
            if not self._authorized_admin():
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, {"leases": self.server.turn_authority.active_leases()})
            return
        if path == "/sentra/status":
            if not self._authorized_admin():
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, {"launcher": self.server.launcher.status(), "upstream": self.server.config.upstream})
            return
        if path == "/sentra/codex/status":
            if not self._authorized_admin():
                self._json(401, {"error": "unauthorized"})
                return
            try:
                self._json(200, self.server.launcher.route("status"))
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                self._json(503, {"error": str(exc)})
            return
        if path == "/v1/models":
            try:
                response = self._upstream("GET", self.path)
                payload = response.read()
                status = response.status
                response._sentra_connection.close()
                if status != 200:
                    self._json(502, {"error": {"type": "upstream_error", "message": "model catalog unavailable"}})
                    return
                catalog = json.loads(payload)
                for collection in ("models", "data"):
                    if isinstance(catalog.get(collection), list):
                        catalog[collection] = [
                            {
                                **model,
                                **{
                                    key: PREFIX + str(model[key])[len(UPSTREAM_PREFIX):]
                                    for key in ("slug", "id")
                                    if str(model.get(key, "")).startswith(UPSTREAM_PREFIX)
                                },
                            }
                            for model in catalog[collection] if isinstance(model, dict)
                        ]
                self._json(200, catalog)
            except (OSError, ValueError, KeyError, http.client.HTTPException) as exc:
                self._json(502, {"error": {"type": "upstream_error", "message": str(exc)}})
            return
        if path == "/v1/responses":
            self._proxy("GET", self.path)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path in {"/internal/turn/register", "/internal/turn/tool", "/internal/turn/prepare", "/internal/turn/complete", "/internal/turn/browser-start", "/internal/turn/browser-heartbeat", "/internal/turn/browser-complete"}:
            if not self._authorized_internal():
                self._json(401, {"error": "unauthorized"})
                return
            value = self._body()
            if value is None:
                return
            action = path.rsplit("/", 1)[-1]
            if os.getenv("SENTRA_GATEWAY_DEBUG_TURN", "").strip() == "1":
                capability = value.get("capability")
                capability_hash = (
                    hashlib.sha256(capability.encode()).hexdigest()[:12]
                    if isinstance(capability, str) else None
                )
                print(
                    "SENTRA_TURN_AUTH "
                    + json.dumps({
                        "phase": "request",
                        "action": action,
                        "trace_id": value.get("traceId"),
                        "revision": value.get("revision"),
                        "capability_hash": capability_hash,
                    }, separators=(",", ":")),
                    flush=True,
                )
            try:
                result = self.server.turn_authority.authorize(action, value)
                if os.getenv("SENTRA_GATEWAY_DEBUG_TURN", "").strip() == "1":
                    print(
                        "SENTRA_TURN_AUTH "
                        + json.dumps({
                            "phase": "response",
                            "action": action,
                            "trace_id": value.get("traceId"),
                            "revision": value.get("revision"),
                            "result": result,
                        }, separators=(",", ":")),
                        flush=True,
                    )
                self._json(200, result)
            except (PermissionError, StaleFenceError, DurableStateConflict, ValueError) as exc:
                if os.getenv("SENTRA_GATEWAY_DEBUG_TURN", "").strip() == "1":
                    print(
                        "SENTRA_TURN_AUTH "
                        + json.dumps({
                            "phase": "error",
                            "action": action,
                            "trace_id": value.get("traceId"),
                            "revision": value.get("revision"),
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }, separators=(",", ":")),
                        flush=True,
                    )
                self._json(409, {"error": str(exc)})
            return
        if path.startswith("/sentra/"):
            if not self._authorized_admin():
                self._json(401, {"error": "unauthorized"})
                return
            try:
                if path == "/sentra/launcher/start":
                    self._json(200, self.server.launcher.start())
                elif path == "/sentra/launcher/stop":
                    self._json(200, self.server.launcher.stop())
                elif path == "/sentra/codex/connect":
                    self._json(200, self.server.launcher.route("sentra"))
                elif path == "/sentra/codex/disconnect":
                    self._json(200, self.server.launcher.route("disconnect"))
                elif path in {"/sentra/upstream/drain", "/sentra/upstream/resume", "/sentra/upstream/interrupt-turn"}:
                    action = path.rsplit("/", 1)[-1]
                    value: dict[str, Any] | None = None
                    if action == "interrupt-turn":
                        value = self._body()
                        if value is None:
                            return
                    try:
                        self._json(200, self.server.launcher.runtime_control(action, value))
                    except (OSError, PermissionError, ValueError, RuntimeError, http.client.HTTPException) as launcher_error:
                        token = self.server.config.upstream_control_token
                        if not token:
                            self._json(409, {
                                "error": "launcher runtime control is unavailable",
                                "detail": str(launcher_error)[:500],
                            })
                            return
                        body = json.dumps(value).encode("utf-8") if value is not None else b""
                        response = self._upstream(
                            "POST",
                            "/admin/" + action,
                            body,
                            {"Authorization": "Bearer " + token},
                        )
                        payload = response.read()
                        status = response.status
                        response._sentra_connection.close()
                        self._json(status, json.loads(payload))
                else:
                    self._json(404, {"error": "not found"})
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, http.client.HTTPException) as exc:
                self._json(502, {"error": str(exc)})
            return
        if path in {"/v1/alpha/search", "/v1/images/generations", "/v1/images/edits"}:
            data = self._raw_body()
            if data is not None:
                self._proxy("POST", self.path, data, {"Content-Type": self.headers.get("Content-Type", "application/octet-stream")})
            return
        if path not in {"/v1/responses", "/v1/responses/compact"}:
            self._json(404, {"error": "not found"})
            return
        value = self._body()
        if value is None:
            return
        model = value.get("model")
        canonical_web_model = isinstance(model, str) and model.startswith(PREFIX)
        legacy_web_model = isinstance(model, str) and model.startswith(UPSTREAM_PREFIX)
        if (not isinstance(model, str) or not model
                or (model.startswith("sentra/") and not canonical_web_model)
                or model in {PREFIX, UPSTREAM_PREFIX}):
            self._json(400, {"error": {"type": "invalid_request_error", "message": "invalid model namespace"}})
            return
        # Codex may keep the model selected before its route was moved behind the SENTRA
        # Gateway. Treat that legacy chatgpt-web/* spelling as the same managed Web model
        # so it cannot bypass TurnCapability/lease authority during the migration window.
        if canonical_web_model or legacy_web_model:
            if canonical_web_model:
                value["model"] = UPSTREAM_PREFIX + model[len(PREFIX):]
            metadata = value.get("client_metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            conversation_uri = metadata.get("sentra_conversation_uri")
            if not isinstance(conversation_uri, str) or not conversation_uri.startswith("conversation://") or len(conversation_uri) > 160:
                conversation_uri = None
            raw_turn_metadata = self.headers.get("x-codex-turn-metadata")
            if not raw_turn_metadata:
                raw_turn_metadata = metadata.get("x-codex-turn-metadata")
            request_identity = _codex_turn_identity(
                raw_turn_metadata,
                path=path,
                model=model,
            )
            try:
                capability = self.server.turn_authority.issue(
                    conversation_uri=conversation_uri,
                    request_identity=request_identity,
                )
            except DurableStateConflict as exc:
                self._json(409, {
                    "error": {
                        "type": "duplicate_turn",
                        "message": str(exc),
                    }
                })
                return
            value["client_metadata"] = {
                **metadata,
                **({"x-codex-turn-metadata": raw_turn_metadata} if raw_turn_metadata is not None else {}),
                "sentra_managed": True,
                "sentra_turn_capability": capability,
            }
        else:
            capability = None
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        status = None
        try:
            status = self._proxy(
                "POST",
                self.path,
                body,
                body_reencoded=True,
                rewrite_web_model_namespace=canonical_web_model,
            )
        finally:
            if capability:
                self.server.turn_authority.retire(capability, failed=status is None or status >= 400)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="SENTRA loopback Responses gateway")
    parser.add_argument("--upstream", default=os.getenv("SENTRA_WEB_UPSTREAM", "http://127.0.0.1:17841"))
    parser.add_argument("--port", type=int, default=17842)
    parser.add_argument("--launch-upstream", action="store_true")
    args = parser.parse_args()
    state_root = ProductPaths.default().state_dir
    admin_token = os.getenv("SENTRA_GATEWAY_ADMIN_TOKEN", "").strip() or load_or_create_gateway_admin_token(state_root)
    config = GatewayConfig(upstream=args.upstream, port=args.port, state_root=state_root,
                           admin_token=admin_token,
                           upstream_control_token=os.getenv("SENTRA_WEB_CONTROL_TOKEN", ""),
                           connector_name=os.getenv("SENTRA_CONNECTOR_NAME", "SENTRA tunnel"))
    server = GatewayServer(config)
    try:
        if args.launch_upstream:
            server.launcher.start()
        print(f"SENTRA Model Gateway listening on http://127.0.0.1:{server.server_port}/v1", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown() if threading.current_thread() is not threading.main_thread() else None
        server.launcher.stop()
        server.server_close()


if __name__ == "__main__":
    main()
