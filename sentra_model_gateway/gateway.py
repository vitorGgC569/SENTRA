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
import re
import secrets
import signal
import socket
import sqlite3
import subprocess
import threading
import time
from collections import deque
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
GEMINI_PREFIX = "sentra/gemini-web/"
GEMINI_UPSTREAM_PREFIX = "gemini-web/"
WEB_MODEL_PREFIXES = (
    (PREFIX, UPSTREAM_PREFIX),
    (GEMINI_PREFIX, GEMINI_UPSTREAM_PREFIX),
)
_UPSTREAM_REF_RE = re.compile(r"^v?(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)$")


def _upstream_version_from_ref(ref: str) -> str:
    match = _UPSTREAM_REF_RE.fullmatch(str(ref or "").strip())
    if match is None:
        raise ValueError("Web Models upstream ref must be an exact semantic version")
    return match.group("version")


MAX_REQUEST_BYTES = 128 * 1024 * 1024


class UpstreamTransportError(OSError):
    """Local transport evidence, never permission to replay a POST."""

    def __init__(self, phase: str, cause: Exception):
        super().__init__(str(cause))
        self.phase = phase


HOP_HEADERS = {"connection", "content-length", "transfer-encoding", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "upgrade", "host"}
REQUEST_REWRITE_HEADERS = {"content-encoding"}
_SSE_TERMINAL_EVENT_RE = re.compile(
    rb"(?:^|\r?\n)event:\s*response\.(?:completed|failed|incomplete)\s*(?:\r?\n|$)",
    re.IGNORECASE,
)
_SSE_DONE_RE = re.compile(
    rb"(?:^|\r?\n)data:\s*\[DONE\]\s*(?:\r?\n|$)",
    re.IGNORECASE,
)


def _sse_terminal_seen(data: bytes) -> bool:
    """Return True only for a complete terminal SSE field line."""
    return bool(
        _SSE_TERMINAL_EVENT_RE.search(data)
        or _SSE_DONE_RE.search(data)
    )


def _upstream_chunks(response, *, framed_sse=False):
    """Keep injected delivery events outside fragmented upstream SSE frames."""
    pending = bytearray()
    while chunk := response.read1(65536):
        if not framed_sse:
            yield chunk
            continue
        pending.extend(chunk)
        while match := re.search(rb"\r?\n\r?\n", pending):
            end = match.end()
            if end > 2_000_000:
                raise http.client.HTTPException("upstream SSE frame exceeds limit")
            yield bytes(pending[:end])
            del pending[:end]
        if len(pending) > 2_000_000:
            raise http.client.HTTPException("upstream SSE frame exceeds limit")
    if pending:
        raise http.client.HTTPException("upstream SSE closed inside a frame")


def _web_model_route(model: str) -> tuple[str, str, bool] | None:
    """Return canonical/upstream prefixes and whether *model* is canonical SENTRA."""
    for canonical, upstream in WEB_MODEL_PREFIXES:
        if model.startswith(canonical):
            return canonical, upstream, True
        if model.startswith(upstream):
            return canonical, upstream, False
    return None


def fleet_status_payload() -> dict[str, Any]:
    """Catalog of the single provider/CLI admission. It does not send a prompt."""
    try:
        from orchestrator.providers.fleet_admission import describe_local_fleet
        return describe_local_fleet()
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        return {
            "admitted": False,
            "inference_executed": False,
            "availability": "unavailable",
            "reason": type(exc).__name__,
            "lanes": [],
        }


def _canonical_web_model_name(value: str) -> str:
    for canonical, upstream in WEB_MODEL_PREFIXES:
        if value.startswith(upstream):
            return canonical + value[len(upstream):]
    return value


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



def _extract_codex_goal_signal(value: Any) -> tuple[bool, str | None]:
    """Return whether the Codex harness supplied goal context and its value.

    SENTRA never interprets the user's slash command. It observes only the
    harness-produced context. Presence is tracked separately from text so an
    explicit empty goal context can pause/clear steering without treating an
    omitted context during compaction as a clear operation.
    """
    texts: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)

    visit(value)
    patterns = (
        re.compile(r"<goal_context(?:\s[^>]*)?>(.*?)</goal_context>", re.I | re.S),
        re.compile(
            r"<codex_internal_context\b[^>]*\bsource=[\"']goal[\"'][^>]*>"
            r"(.*?)</codex_internal_context>",
            re.I | re.S,
        ),
    )
    latest: tuple[int, int, str | None] | None = None
    for text_index, text in enumerate(texts):
        for pattern in patterns:
            for match in pattern.finditer(text):
                goal = match.group(1).strip()
                candidate = (
                    text_index,
                    match.start(),
                    goal[:100_000] if goal else None,
                )
                if latest is None or candidate[:2] > latest[:2]:
                    latest = candidate
    if latest is None:
        return False, None
    return True, latest[2]


def _extract_codex_goal_context(value: Any) -> str | None:
    """Compatibility projection returning only non-empty harness goal text."""
    return _extract_codex_goal_signal(value)[1]


def _extract_codex_task_text(value: Any) -> str | None:
    """Extract a bounded human/task instruction from a Codex child-turn payload.

    This is descriptive metadata only. It never authorizes tools or interprets
    slash commands; native Codex remains the owner of agent lifecycle semantics.
    """
    if not isinstance(value, list):
        return None
    candidates: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "agent_message":
            for key in ("message", "text", "content"):
                raw = item.get(key)
                if isinstance(raw, str) and raw.strip():
                    candidates.append(raw.strip())
                    break
            continue
        if kind != "message" or item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            values = [content]
        elif isinstance(content, list):
            values = [
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict)
                and part.get("type") in {"input_text", "text"}
            ]
        else:
            values = []
        for raw in values:
            text = raw.strip()
            if not text:
                continue
            lowered = text.casefold()
            if lowered.startswith((
                "<goal_context",
                "<codex_internal_context",
                "<environment_context",
                "<recommended_plugins",
                "<subagent_notification",
            )):
                continue
            candidates.append(text)
    return candidates[-1][:20_000] if candidates else None


def _extract_codex_subagent_notifications(value: Any) -> list[dict[str, Any]]:
    """Extract native Codex subagent lifecycle notifications conservatively."""
    if not isinstance(value, list):
        return []
    notifications: list[dict[str, Any]] = []
    pattern = re.compile(
        r"^<subagent_notification>\s*(\{[\s\S]*\})\s*</subagent_notification>$"
    )
    for item in value:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message" or item.get("role") != "user":
            continue
        passthrough = item.get("internal_chat_message_metadata_passthrough")
        if not isinstance(passthrough, dict) or not isinstance(
            passthrough.get("turn_id"), str
        ):
            continue
        content = item.get("content")
        parts = content if isinstance(content, list) else []
        for part in parts:
            if not isinstance(part, dict) or part.get("type") not in {
                "input_text", "text"
            }:
                continue
            raw = part.get("text")
            if not isinstance(raw, str):
                continue
            match = pattern.fullmatch(raw.strip())
            if match is None:
                continue
            try:
                payload = json.loads(match.group(1))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            agent_path = payload.get("agent_path")
            status = payload.get("status")
            if (
                not isinstance(agent_path, str)
                or not agent_path
                or len(agent_path) > 512
                or not isinstance(status, dict)
            ):
                continue
            notifications.append({
                "agent_path": agent_path,
                "status": status,
                "turn_id": passthrough["turn_id"],
            })
    return notifications


def _load_or_create_private_token(state_root: Path, filename: str) -> str:
    token_dir = state_root / "web-models"
    token_dir.mkdir(parents=True, exist_ok=True)
    token_path = token_dir / filename
    try:
        current = token_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        token = secrets.token_urlsafe(48)
        try:
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            current = token_path.read_text(encoding="utf-8").strip()
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(token + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return token
    # Read errors/corruption never authorize replacement of a live host key.
    if re.fullmatch(r"[A-Za-z0-9_-]{32,256}", current) is None:
        raise RuntimeError("gateway private token is invalid; host repair required")
    return current


def load_or_create_gateway_admin_token(state_root: Path) -> str:
    return _load_or_create_private_token(state_root, "gateway-admin.token")


def resolve_gateway_state_root() -> Path:
    """Resolve the same runtime authority used by the active SENTRA install.

    In source/dev runs this adopts <repo>/.sentra when it owns tunnel state;
    installed builds still honor SENTRA_STATE_DIR and ProductPaths authority.
    """
    install_root = Path(__file__).resolve().parent.parent
    return ProductPaths.default(install_root).state_dir


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
    identity: dict[str, str] = {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "request_kind": request_kind,
        "path": path,
        "model": model,
    }
    for key, limit in (
        ("parent_thread_id", 256),
        ("agent_name", 256),
        ("subagent_kind", 64),
    ):
        item = metadata.get(key)
        if isinstance(item, str) and item and len(item) <= limit:
            identity[key] = item
    return json.dumps(
        identity,
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )


@dataclass(frozen=True)
class GatewayConfig:
    upstream: str = "http://127.0.0.1:17841"
    host: str = "127.0.0.1"
    port: int = 17842
    admin_token: str = ""
    upstream_control_token: str = ""
    connector_name: str = "SENTRA"
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
            process = self.process
            if process is not None and process.poll() is None:
                return {"running": True, "pid": process.pid, "source": "owned"}
            adopted = self._adopted_status()
            return adopted or {"running": False, "pid": None, "source": "none"}

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        # This subprocess is a Web-model adapter, never the user's native Codex.
        # Upstream setup/doctor/subagent commands may write Codex configuration;
        # every such write must stay inside this installation's private home.
        state_root = Path(self.config.state_root or ProductPaths.default().state_dir).expanduser().resolve()
        environment["CODEX_HOME"] = str(state_root / "web-models" / "codex-home")
        environment["SENTRA_NATIVE_CODEX_HOME"] = str(Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve())
        environment["SENTRA_TURN_AUTHORITY_URL"] = f"http://{self.config.host}:{self.authority_port}"
        environment["SENTRA_WEB_GATEWAY_URL"] = f"http://{self.config.host}:{self.authority_port}/v1"
        environment["SENTRA_CONNECTOR_NAME"] = self.config.connector_name.strip()
        # The SENTRA Gateway owns the OpenAI tunnel. The embedded Web Models
        # launcher must keep its Responses/browser runtime but must never publish
        # a second MCP worker for the same ChatGPT connector.
        environment["SENTRA_MANAGED_TUNNEL"] = "1"
        payload = self.validate_payload()
        if payload.get("packaged"):
            environment["SENTRA_INTEGRATION_PATCH_SHA256"] = str(payload["patch_sha256"])
            if payload.get("commit"):
                environment["SENTRA_UPSTREAM_COMMIT"] = str(payload["commit"])
        if self.turn_authority_token:
            environment["SENTRA_TURN_AUTHORITY_TOKEN"] = self.turn_authority_token
        if self.upstream_control_token:
            environment["SENTRA_WEB_CONTROL_TOKEN"] = self.upstream_control_token
        state_root = Path(
            self.config.state_root or ProductPaths.default().state_dir
        ).expanduser().resolve()
        relay_token = state_root / "browser" / "relay-token"
        if relay_token.is_file():
            environment["SENTRA_GEMINI_WEB_ENABLED"] = "1"
            environment["SENTRA_BROWSER_RELAY_TOKEN_FILE"] = str(relay_token)
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

    def _integration_manifest(self) -> dict[str, Any]:
        checkout = self.config.checkout.resolve()
        source_manifest = (
            checkout.parents[1]
            / "integrations"
            / "codex_chatgpt_web"
            / "upstream.json"
        )
        candidates = [source_manifest]
        packaged = self._packaged_launcher_path()
        if packaged.is_file():
            candidates.append(
                packaged.parent.parent
                / "licenses"
                / "codex-chatgpt-web"
                / "upstream.json"
            )
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                value = json.loads(candidate.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError("Web Models integration manifest is invalid") from exc
            if not isinstance(value, dict):
                raise RuntimeError("Web Models integration manifest is invalid")
            return value
        raise RuntimeError("Web Models integration manifest is missing")

    def expected_upstream_version(self) -> str:
        return _upstream_version_from_ref(str(self._integration_manifest().get("ref") or ""))

    def patched_source_path(self) -> Path:
        checkout = self.config.checkout.resolve()
        return (
            checkout.parents[1]
            / ".sentra"
            / "integrations"
            / "codex-chatgpt-web"
            / "source"
            / self.expected_upstream_version()
        )

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
        if action not in {"drain", "resume", "interrupt-turn", "verify-connector", "setup", "configure-web"}:
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
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port,
            timeout=180 if action == "configure-web" else 35 if action == "setup" else 8)
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
        if action not in {"status", "sentra", "disconnect", "doctor", "recover-native"}:
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
            patched = self.patched_source_path()
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

    def start(self, *, hidden: bool = False, browser_host_only: bool = False) -> dict:
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
            # Undo only a journal-proven legacy SENTRA global route, preserving
            # unrelated provider settings and refusing conflicting user edits.
            self.route("recover-native")
            if current["running"]:
                if not hidden and packaged.is_file():
                    subprocess.Popen([str(packaged)],
                                     cwd=str(packaged.parent), env=self._environment(),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return current
            environment = self._environment()
            if browser_host_only:
                environment["SENTRA_BROWSER_HOST_ONLY"] = "1"
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
                    getattr(os, "killpg")(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None
            return self.status()


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    # The product admission target is 10 simultaneous model streams per host.
    # Backlog is not a concurrency limit; keep enough room for connection bursts.
    request_queue_size = 64
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
        self._web_transport = None
        # Reserve exclusive ownership before touching state or private tokens.
        # A competing process must fail without mutating the active host.
        super().__init__((config.host, config.port), GatewayHandler)
        try:
            self._initialize_gateway(config)
        except BaseException:
            self.server_close()
            raise

    def _initialize_gateway(self, config: GatewayConfig):
        state_root = Path(config.state_root or ProductPaths.default().state_dir).resolve()
        if config.launcher_executable and config.launcher_executable.is_file():
            install_root = config.launcher_executable.resolve().parents[2]
        else:
            install_root = config.checkout.resolve().parents[1]
        self.product_paths = ProductPaths(install_root, state_root)
        from sentra_mcp.audit import AuditLogger
        self.audit=AuditLogger(self.product_paths.audit_log,component="gateway")
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
        self.expected_upstream_version = self.launcher.expected_upstream_version()
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
        # Candidate modules are initialized only on their own guarded route.
        # A rollout/storage/dependency failure must not remove the listener
        # serving already authorized clients while production is still legacy.
        self._web_transport = None
        self._web_transport_lock = threading.RLock()
        self.launcher.authority_port = self.server_port
        self.model_catalog_cache_path = state_root / "web-models" / "model-catalog.json"
        self._model_catalog_lock = threading.RLock()
        from .account_models import AccountModelCatalog
        self.account_catalog = AccountModelCatalog(state_root)
        self._upstream_watchdog_stop = threading.Event()
        self._upstream_watchdog_thread: threading.Thread | None = None
        self._upstream_failure_since: float | None = None
        self._upstream_last_restart = 0.0
        self._upstream_restart_attempts = 0
        self._upstream_supervision: dict[str, Any] = {
            "state": "IDLE",
            "restart_attempts": 0,
        }
        self._inference_metrics_lock = threading.RLock()
        self._inference_outcomes: deque[tuple[float, int | None]] = deque(maxlen=512)

    def record_inference_outcome(self, status: int | None) -> None:
        # Observe responses only; a failure is NEVER consent to replay POST.
        with self._inference_metrics_lock:
            self._inference_outcomes.append((time.monotonic(), status))

    def inference_health(self, window_s: float = 300.0) -> dict[str, Any]:
        stamp = time.monotonic()
        with self._inference_metrics_lock:
            entries = [(at, status) for at, status in self._inference_outcomes
                       if stamp - at <= window_s]
        total = len(entries)
        upstream_5xx = sum(isinstance(status, int) and status >= 500
                           for _, status in entries)
        transport_unknown = sum(status is None for _, status in entries)
        degraded = total >= 5 and upstream_5xx + transport_unknown >= 3 and (
            upstream_5xx + transport_unknown) / total >= 0.5
        return {
            "state": "DEGRADED" if degraded else "OBSERVING" if total < 5 else "HEALTHY",
            "window_seconds": window_s,
            "sample_count": total,
            "upstream_5xx_count": upstream_5xx,
            "transport_unknown_count": transport_unknown,
            "failure_rate_percent": round(100 * (upstream_5xx + transport_unknown) / total, 1) if total else None,
            "automatic_retry": False,
        }

    def web_transport_mode(self) -> str:
        import sqlite3
        with self.turn_authority.store.connect("session_checkpoint") as db:
            try:
                row = db.execute("SELECT mode FROM gateway_web_transport_mode WHERE singleton=1").fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                return "legacy"
            except Exception as exc:
                # PostgreSQL backend: missing relation (undefined table) also
                # means uninitialized routing -> legacy. Anything else raises.
                message = str(exc)
                if ("does not exist" not in message
                        and "undefined" not in message.lower()):
                    raise
                return "legacy"
        if row is None or row[0] not in {"legacy", "candidate_v2", "durable_v2"}:
            raise RuntimeError("Web transport routing state is invalid; sending is blocked")
        return row[0]

    @property
    def web_transport(self):
        with self._web_transport_lock:
            if self._web_transport is None:
                from .web_transport import DurableWebTransport
                self._web_transport = DurableWebTransport(self.turn_authority)
            return self._web_transport

    def _upstream_health(self) -> tuple[bool, dict[str, Any]]:
        parsed = urlsplit(self.config.upstream)
        hostname = parsed.hostname
        if not hostname:
            return False, {}
        try:
            connection = http.client.HTTPConnection(hostname, parsed.port, timeout=2)
            connection.request("GET", "/healthz")
            response = connection.getresponse()
            payload = json.loads(response.read() or b"{}")
            connection.close()
        except (OSError, ValueError, json.JSONDecodeError, http.client.HTTPException):
            return False, {}
        healthy = (
            response.status == 200
            and isinstance(payload, dict)
            and payload.get("service") == "codex-chatgpt-web"
            and payload.get("version") == self.expected_upstream_version
            and payload.get("status") == "ok"
            and payload.get("accepting_turns", True) is True
        )
        return healthy, payload if isinstance(payload, dict) else {}

    def reap_orphan_turns(self) -> dict[str, Any]:
        """Cancel browser leases only when no HTTP request can still own them."""
        _healthy, health = self._upstream_health()
        http_turns = health.get("active_http_turns")
        browser_turns = health.get("active_browser_turns")
        if not isinstance(http_turns, int) or not isinstance(browser_turns, int):
            raise RuntimeError(
                "cannot prove upstream turn ownership before orphan cleanup"
            )
        if http_turns > 0:
            raise RuntimeError(
                "refusing orphan cleanup while HTTP turns are active "
                f"(http={http_turns}, browser={browser_turns})"
            )
        if browser_turns <= 0:
            return {
                "status": "ok",
                "reaped": False,
                "cancelled_http_turns": 0,
                "cancelled_browser_turns": 0,
                "active_http_turns": http_turns,
                "active_browser_turns": browser_turns,
            }
        if not self.upstream_control_token:
            raise RuntimeError("upstream control token is unavailable")

        parsed = urlsplit(self.config.upstream)
        hostname = parsed.hostname
        if not hostname:
            raise RuntimeError("upstream URL has no hostname")
        connection = http.client.HTTPConnection(
            hostname,
            parsed.port,
            timeout=5,
        )
        try:
            connection.request(
                "POST",
                "/admin/cancel-turns",
                b"",
                {
                    "Authorization": "Bearer " + self.upstream_control_token,
                    "Content-Length": "0",
                },
            )
            response = connection.getresponse()
            raw = response.read()
        finally:
            connection.close()

        if response.status < 200 or response.status >= 300:
            raise RuntimeError(
                "upstream orphan cleanup failed: "
                f"HTTP {response.status}: {raw[:300]!r}"
            )
        result = json.loads(raw or b"{}")
        if not isinstance(result, dict):
            raise RuntimeError("upstream orphan cleanup returned invalid JSON")
        remaining_http = result.get("active_http_turns")
        remaining_browser = result.get("active_browser_turns")
        if remaining_http != 0 or remaining_browser != 0:
            raise RuntimeError(
                "upstream did not acknowledge complete orphan cleanup "
                f"(http={remaining_http}, browser={remaining_browser})"
            )
        return {
            **result,
            "reaped": True,
        }

    def supervise_upstream_once(self, *, now: float | None = None) -> dict[str, Any]:
        stamp = time.monotonic() if now is None else float(now)
        healthy, payload = self._upstream_health()
        launcher = self.launcher.status()
        if healthy:
            self._upstream_failure_since = None
            self._upstream_restart_attempts = 0
            self._upstream_supervision = {
                "state": "HEALTHY",
                "restart_attempts": 0,
            }
            return dict(self._upstream_supervision)

        if self._upstream_failure_since is None:
            self._upstream_failure_since = stamp
            self._upstream_supervision = {
                "state": "DEGRADED",
                "reason": "upstream_unreachable",
                "launcher_running": bool(launcher.get("running")),
                "restart_attempts": self._upstream_restart_attempts,
            }
            return dict(self._upstream_supervision)

        if stamp - self._upstream_failure_since < 6.0:
            return dict(self._upstream_supervision)

        counts = (payload.get("active_http_turns"), payload.get("active_browser_turns"))
        verified_idle = all(type(value) is int and value == 0 for value in counts)
        with self.turn_authority.lock:
            pending_turns = bool(self.turn_authority.capabilities)
        external_launcher = launcher.get("source") in {"adopted", "stale"}
        if (external_launcher or pending_turns or
                (launcher.get("running") and not verified_idle) or
                (payload and not verified_idle)):
            self._upstream_supervision = {
                "state": "RECOVERY_BLOCKED",
                "reason": "external_launcher" if external_launcher else "active_or_unverified_turn_ownership",
                "restart_attempts": self._upstream_restart_attempts,
                "automatic_resend": False,
            }
            return dict(self._upstream_supervision)

        backoff = min(5.0 * (2 ** self._upstream_restart_attempts), 60.0)
        if self._upstream_last_restart and stamp - self._upstream_last_restart < backoff:
            self._upstream_supervision = {
                "state": "BACKOFF",
                "reason": "upstream_unreachable",
                "retry_after_s": round(backoff - (stamp - self._upstream_last_restart), 3),
                "restart_attempts": self._upstream_restart_attempts,
            }
            return dict(self._upstream_supervision)

        if launcher.get("running"):
            self.launcher.stop()
        started = self.launcher.start(hidden=True)
        self._upstream_last_restart = stamp
        self._upstream_restart_attempts += 1
        self._upstream_failure_since = stamp
        self._upstream_supervision = {
            "state": "RECOVERING" if started.get("running") else "DEGRADED",
            "action": "restart_launcher",
            "launcher_pid": started.get("pid"),
            "restart_attempts": self._upstream_restart_attempts,
        }
        return dict(self._upstream_supervision)

    def start_upstream_watchdog(self, interval_s: float = 3.0) -> None:
        if self._upstream_watchdog_thread and self._upstream_watchdog_thread.is_alive():
            return
        self._upstream_watchdog_stop.clear()

        def worker() -> None:
            while not self._upstream_watchdog_stop.wait(interval_s):
                try:
                    self.supervise_upstream_once()
                except Exception as exc:
                    self._upstream_supervision = {
                        "state": "ERROR",
                        "detail": str(exc)[:300],
                        "restart_attempts": self._upstream_restart_attempts,
                    }

        self._upstream_watchdog_thread = threading.Thread(
            target=worker,
            name="sentra-model-upstream-watchdog",
            daemon=True,
        )
        self._upstream_watchdog_thread.start()

    def stop_upstream_watchdog(self) -> None:
        self._upstream_watchdog_stop.set()
        thread = self._upstream_watchdog_thread
        if thread is not None:
            thread.join(timeout=5)
        self._upstream_watchdog_thread = None

    def cache_model_catalog(self, catalog: dict[str, Any]) -> dict[str, Any]:
        """Persist only safe Web-model metadata from an authenticated Codex catalog."""
        web_models: list[dict[str, str]] = []
        for collection in ("models", "data"):
            values = catalog.get(collection)
            if not isinstance(values, list):
                continue
            for model in values:
                if not isinstance(model, dict):
                    continue
                identifier = str(model.get("slug") or model.get("id") or "")
                if _web_model_route(identifier) is None:
                    continue
                safe: dict[str, str] = {}
                for key in ("slug", "id", "display_name", "description"):
                    value = model.get(key)
                    if isinstance(value, str) and value:
                        safe[key] = (
                            _canonical_web_model_name(value)
                            if key in {"slug", "id"} and _web_model_route(value) is not None
                            else value
                        )
                if safe:
                    web_models.append(safe)
            break

        payload: dict[str, Any] = {
            "status": "ready" if web_models else "empty",
            "updated_at": time.time(),
            "models": web_models,
        }
        with self._model_catalog_lock:
            self.model_catalog_cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.model_catalog_cache_path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                os.chmod(temp, 0o600)
            except OSError:
                pass
            temp.replace(self.model_catalog_cache_path)
        return payload

    def cached_model_catalog(self) -> dict[str, Any]:
        """Return the last authenticated Web-model catalog without exposing Codex auth."""
        with self._model_catalog_lock:
            if not self.model_catalog_cache_path.is_file():
                return {
                    "status": "awaiting_codex_catalog",
                    "updated_at": None,
                    "models": [],
                }
            try:
                payload = json.loads(self.model_catalog_cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                return {
                    "status": "invalid_cache",
                    "updated_at": None,
                    "models": [],
                }
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            return {
                "status": "invalid_cache",
                "updated_at": None,
                "models": [],
            }
        return payload

    def observe_account_models(self, account_fingerprint: str, models: list[dict[str, Any]], *,
                               collector_ref: str, nonce: str,
                               picker_available: bool = True) -> dict[str, Any]:
        """Host-only account observation; Codex/CLI/Canvas consume cached_view/select."""
        return self.account_catalog.observe(
            account_fingerprint, models, collector_ref=collector_ref,
            nonce=nonce, picker_available=picker_available)

    def account_model_view(self, account_fingerprint: str | None = None) -> dict[str, Any]:
        """Safe account/model/effort projection for Canvas and CLI (no auth material)."""
        return self.account_catalog.cached_view(account_fingerprint)

    def select_account_model(self, account_fingerprint: str, requested_model: str | None,
                             requested_effort: str | None = None, *,
                             expected_generation: int | None = None,
                             active_generation: int | None = None) -> dict[str, Any]:
        """Resolve the effective model/effort strictly from observed account entries."""
        return self.account_catalog.select(
            account_fingerprint, requested_model, requested_effort,
            expected_generation=expected_generation,
            active_generation=active_generation)

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

        raw_tunnel = product.get("tunnel") if isinstance(product, dict) else None
        tunnel: dict[str, Any] = raw_tunnel if isinstance(raw_tunnel, dict) else {}
        tunnel_configured = bool(tunnel.get("configured"))
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
            route_ok = bool(route.get("scope") == "sentra-web-only" and route.get("gatewayHealthy"))
            add(
                "codex-route",
                "ok" if route_ok else "warning",
                "SENTRA Web adapter is isolated; native providers keep their own routes" if route_ok
                else "SENTRA Web adapter isolation or gateway health could not be verified",
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
        if self._web_transport is not None:
            self._web_transport.close()
        authority = getattr(self, "turn_authority", None)
        if authority is not None:
            authority.durable.close()


class GatewayHandler(BaseHTTPRequestHandler):
    server: GatewayServer
    # Codex probes /v1/responses with a WebSocket handshake before falling back to
    # HTTP Responses. The handshake itself requires an HTTP/1.1 response; replying
    # with HTTP/1.0 makes Codex treat the route as a broken WebSocket endpoint
    # instead of honoring the 426 fallback response.
    # Stream small SSE frames without Nagle/delayed-ACK latency on loopback.
    # No changes to authorization, delivery receipts, or retry semantics.
    disable_nagle_algorithm = True
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def _audit_route(self, action: str, outcome: str, details: dict) -> None:
        # No prompt, payload or authorization values may enter diagnostics.
        # Audit failures must not alter HTTP delivery or retry semantics.
        try:
            self.server.audit.emit(action, outcome, details)
        except (OSError, RuntimeError, ValueError, sqlite3.Error):
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
        timeout: float = 900.0,
    ) -> http.client.HTTPResponse:
        parsed = urlsplit(self.server.config.upstream)
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("upstream host is missing")
        connection = http.client.HTTPConnection(hostname, parsed.port or 80, timeout=min(timeout, 5.0))
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
        # Establish the socket before writing any HTTP bytes. Only this failure
        # proves that this attempt did not reach the upstream. Never reconnect
        # or repeat a POST after request() has begun.
        try:
            connection.connect()
            if connection.sock is not None:
                connection.sock.settimeout(timeout)
        except (OSError, http.client.HTTPException) as exc:
            connection.close()
            raise UpstreamTransportError("connect", exc) from exc
        try:
            connection.request(method, path, body=body, headers=outbound)
            response = connection.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            connection.close()
            raise UpstreamTransportError("request_or_headers", exc) from exc
        setattr(response, "_sentra_connection", connection)
        return response

    @staticmethod
    def _close_upstream(response: http.client.HTTPResponse) -> None:
        connection = getattr(response, "_sentra_connection", None)
        if connection is not None:
            connection.close()

    def _proxy(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict | None = None,
        *,
        body_reencoded: bool = False,
        rewrite_web_model_namespace: bool = False,
        delivery_capability: str | None = None,
        request_correlation_id: str | None = None,
    ) -> int | None:
        response = None
        phase = 'upstream_connect'
        try:
            response = self._upstream(method, path, body, headers, body_reencoded=body_reencoded)
            phase = 'upstream_headers'
            response_headers = response.getheaders()
            if response.status >= 500:
                # Provider CF-Ray is a diagnostic identifier, never a credential.
                cf_ray = next((value for name, value in response_headers
                               if name.lower() == 'cf-ray'), '')
                diagnostic = {'correlation_id': request_correlation_id,
                              'path': urlsplit(path).path,
                              'upstream_http_status': response.status}
                if re.fullmatch(r'[0-9a-fA-F]{8,32}-[A-Za-z]{3}', cf_ray.strip()):
                    diagnostic['cf_ray'] = cf_ray.strip()
                self._audit_route('model.gateway.upstream_5xx', 'error', diagnostic)
            content_type = next(
                (value for name, value in response_headers if name.lower() == "content-type"),
                "",
            )
            content_encoding = next(
                (value for name, value in response_headers if name.lower() == "content-encoding"),
                "",
            ).strip().lower()
            is_sse = content_type.split(";", 1)[0].strip().lower() == "text/event-stream"
            if delivery_capability and 200 <= response.status < 300 and not is_sse:
                try:
                    self.server.web_transport.require_receipts(delivery_capability)
                except PermissionError:
                    self._json(409, {"error": {"type": "web_completion_unconfirmed",
                        "automatic_retry": False, "reconciliation_required": True}})
                    return 409
            self.send_response(response.status)
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
            if request_correlation_id:
                self.send_header('X-SENTRA-Request-ID', request_correlation_id)
            self.end_headers()
            phase = 'stream_or_downstream_delivery'
            if body_allowed:
                if is_sse and delivery_capability:
                    view = self.server.web_transport.delivery_view(delivery_capability)
                    event = ("event: sentra.web_delivery\ndata: " + json.dumps(view, separators=(",", ":")) + "\n\n").encode()
                    if downstream_chunked:
                        self.wfile.write(f"{len(event):X}\r\n".encode() + event + b"\r\n")
                    else:
                        self.wfile.write(event)
                    self.wfile.flush()
                sse_terminal_detected = False
                # A terminal event may span many TCP reads (its final text can
                # be large). Never stop at its header before forwarding data.
                # Frame all SSE, including CLI turns without delivery injection.
                for data in _upstream_chunks(response, framed_sse=is_sse):
                    if rewrite_web_model_namespace:
                        for canonical, upstream in WEB_MODEL_PREFIXES:
                            data = data.replace(
                                ('"' + upstream).encode("utf-8"),
                                ('"' + canonical).encode("utf-8"),
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
                            }, separators=(",", ":")),
                            flush=True,
                        )
                    if is_sse:
                        terminal = _sse_terminal_seen(data)
                        sse_terminal_detected = sse_terminal_detected or terminal
                        if terminal and delivery_capability:
                            view = self.server.web_transport.delivery_view(delivery_capability)
                            event = ("event: sentra.web_delivery\ndata: " + json.dumps(view, separators=(",", ":")) + "\n\n").encode()
                            self.wfile.write(f"{len(event):X}\r\n".encode() + event + b"\r\n")
                            self.wfile.flush()
                            # Failure/incomplete events retain upstream semantics.
                            # Only successful terminal completion needs final
                            # independently attested ANSWERED receipts.
                            if (re.search(rb"(?:^|\r?\n)event:\s*response\.completed\s*(?:\r?\n|$)", data, re.IGNORECASE)
                                    or _SSE_DONE_RE.search(data)):
                                self.server.web_transport.require_receipts(delivery_capability)
                    if downstream_chunked:
                        self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
                        self.wfile.write(data)
                        self.wfile.write(b"\r\n")
                    else:
                        self.wfile.write(data)
                    self.wfile.flush()

                    if is_sse and terminal:
                        break
                if downstream_chunked:
                    if is_sse and not sse_terminal_detected:
                        raise http.client.HTTPException("upstream SSE closed without a terminal event")
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
            return response.status
        except (OSError, http.client.HTTPException, sqlite3.Error, RuntimeError, PermissionError) as exc:
            self._audit_route("model.gateway.transport_error", "error", {
                "path": urlsplit(path).path,
                "failure_phase": getattr(exc, "phase", phase),
                "correlation_id": request_correlation_id,
                "exception_class": type(exc).__name__,
                "upstream_headers_received": response is not None,
                "automatic_retry": False,
            })
            if response is None:
                phase = getattr(exc, "phase", "unknown")
                self._json(503, {"error": {
                    "type": "upstream_unavailable",
                    "message": "The upstream transport is unavailable; this request was not retried.",
                    "phase": phase,
                    "delivery_state": "NOT_SENT" if phase == "connect" else "UNCONFIRMED",
                    "automatic_retry": False,
                    "reconciliation_required": phase != "connect",
                }})
            else:
                # Truncated SSE must remain a broken stream. A clean terminating
                # chunk would disguise uncertainty as successful completion.
                self.close_connection = True
        finally:
            if response is not None:
                self._close_upstream(response)
        return None

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
                        "error": str(exc)[:200],
                    }, separators=(",", ":")),
                    flush=True,
                )
            self._json(400, {"error": {"type": "invalid_request_error", "message": "invalid JSON request"}})
            return None

    def do_GET(self) -> None:
        parsed_request = urlsplit(self.path)
        path = parsed_request.path
        if path == "/livez":
            self._json(200, {"status": "alive", "service": "sentra-model-gateway", "ready": False})
            return
        if path == "/healthz":
            response = None
            try:
                response = self._upstream("GET", "/healthz", timeout=1.5)
                raw_health = response.read(128_001)
                if len(raw_health) > 128_000:
                    raise ValueError("upstream health exceeds limit")
                upstream = json.loads(raw_health)
                if not isinstance(upstream, dict):
                    raise ValueError("upstream health must be an object")
                healthy = (
                    response.status == 200
                    and upstream.get("service") == "codex-chatgpt-web"
                    and upstream.get("version") == self.server.expected_upstream_version
                    and upstream.get("status") == "ok"
                    and upstream.get("accepting_turns", True) is True
                )
            except (OSError, ValueError, http.client.HTTPException):
                upstream, healthy = {}, False
            finally:
                if response is not None:
                    self._close_upstream(response)
            catalog = self.server.cached_model_catalog()
            catalog_ready = (
                catalog.get("status") == "ready"
                and bool(catalog.get("models"))
            )
            # The installed Web Models launcher can be stale while the active
            # upstream still serves legacy Responses. An invalid integration
            # patch is a diagnostic condition, never a reason to drop /healthz
            # without HTTP headers (which makes every Codex client see 503).
            try:
                launcher_status = self.server.launcher.status()
            except (OSError, ValueError, RuntimeError, PermissionError) as exc:
                launcher_status = {
                    "running": False,
                    "pid": None,
                    "source": "unverified",
                    "reason": "launcher_status_unavailable",
                    "error_type": type(exc).__name__,
                }
            try:
                self.server.resources.ingest_manifest({
                    "resource_type": "model_browser",
                    "resources": [{
                        "resource_id": "model:chatgpt-web:primary",
                        "state": "READY" if healthy and catalog_ready else ("DEGRADED" if healthy else "OFFLINE"),
                        "capacity": 5,
                        "capabilities": {"responses": True, "sse": True, "compaction": True, "browser_host": "electron"},
                        "labels": {"provider": "chatgpt-web", "version": str(upstream.get("version") or "")},
                        "active_turns": upstream.get("active_browser_turns", 0),
                        "accepting_turns": upstream.get("accepting_turns") is True,
                    }],
                })
            except (OSError, sqlite3.Error, ValueError, RuntimeError):
                self._json(503, {"service": "sentra-model-gateway", "status": "local_state_unavailable", "ready": False})
                return
            self._json(
                200 if healthy else 503,
                {
                    "status": "ok" if healthy else "unavailable",
                    "service": "sentra-model-gateway",
                    "ready": bool(healthy and catalog_ready),
                    "catalog": catalog,
                    "upstream": upstream,
                    "launcher": launcher_status,
                    "supervisor": dict(self.server._upstream_supervision),
                    "inference_health": self.server.inference_health(),
                },
            )
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
        if path == "/sentra/web-transport":
            if not self._authorized_admin():
                self._json(401, {"error": "unauthorized"}); return
            try:
                self._json(200, self.server.web_transport.status())
            except (OSError, sqlite3.Error, RuntimeError, ImportError):
                self._json(503, {"error": {"type": "web_transport_unavailable", "automatic_retry": False}})
            return
        if path == "/sentra/status":
            if not self._authorized_admin():
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, {
                "launcher": self.server.launcher.status(),
                "upstream": self.server.config.upstream,
                "fleet": fleet_status_payload(),
            })
            return
        if path == "/sentra/model-catalog":
            if not (self._authorized_admin() or self._authorized_internal()):
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, self.server.cached_model_catalog())
            return
        if path == "/sentra/account-models":
            if not (self._authorized_admin() or self._authorized_internal()):
                self._json(401, {"error": "unauthorized"})
                return
            query = parse_qs(parsed_request.query).get("account_fingerprint", [])
            fingerprint = query[0] if query else None
            try:
                self._json(200, self.server.account_model_view(fingerprint))
            except (ValueError, RuntimeError) as exc:
                self._json(400, {"error": str(exc)})
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
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer ") or len(authorization) <= len("Bearer "):
                self._json(401, {
                    "error": {
                        "type": "authentication_error",
                        "message": "Codex model catalog requires incoming Bearer authorization",
                    }
                })
                return
            try:
                response = self._upstream("GET", self.path, timeout=3.0)
                payload = response.read()
                status = response.status
                self._close_upstream(response)
                if status == 200:
                    catalog = json.loads(payload)
                    for collection in ("models", "data"):
                        if isinstance(catalog.get(collection), list):
                            catalog[collection] = [
                                {
                                    **model,
                                    **{
                                        key: _canonical_web_model_name(str(model[key]))
                                        for key in ("slug", "id")
                                        if _web_model_route(str(model.get(key, ""))) is not None
                                    },
                                }
                                for model in catalog[collection] if isinstance(model, dict)
                            ]
                    self.server.cache_model_catalog(catalog)
                    self._json(200, catalog)
                    return
            except (OSError, ValueError, KeyError, http.client.HTTPException):
                pass

            # Upstream unavailable or returned error: serve only observed entries.
            # Never invent model rights from names; an empty observation means
            # "unavailable", and Automatic is resolved by AccountModelCatalog.
            cached = self.server.cached_model_catalog()
            cached_models = cached.get("models") if isinstance(cached, dict) else []
            if cached_models:
                data = [
                    {"id": m.get("id") or m.get("slug"), "object": "model", "owned_by": "sentra"}
                    for m in cached_models if isinstance(m, dict) and (m.get("id") or m.get("slug"))
                ]
            else:
                data = []
            self._json(200, {"object": "list", "data": data, "models": data,
                             "status": "ready" if data else "unavailable",
                             "automatic_resend": False})
            return
        if path == "/v1/responses":
            self._proxy("GET", self.path)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path in {"/internal/turn/browser-preflight", "/internal/turn/browser-sending",
                    "/internal/turn/browser-receipt", "/internal/turn/browser-failure", "/internal/turn/browser-answer"}:
            if not self._authorized_internal():
                self._json(401, {"error": "unauthorized"}); return
            value = self._body()
            if value is None:
                return
            try:
                result = self.server.web_transport.browser_event(path.rsplit("-", 1)[-1], value)
                self._json(200, result)
            except (PermissionError, StaleFenceError, DurableStateConflict, ValueError, RuntimeError) as exc:
                self._json(409, {"error": {"type": "web_delivery_denied", "message": str(exc)}})
            except (sqlite3.Error, OSError, ImportError):
                self._json(503, {"error": {"type": "web_transport_unavailable", "automatic_retry": False}})
            return
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
                if action in {"complete", "browser-complete"} and self.server.turn_authority._capability(value["capability"]).shared_run:
                    self.server.web_transport.require_receipts(value["capability"])
                result = self.server.turn_authority.authorize(action, value)
                self.server.audit.emit("model.browser." + action, "ok", {
                    **self.server.turn_authority.telemetry_metadata(value["capability"]),
                    "revision": value.get("revision"),
                })
                if os.getenv("SENTRA_GATEWAY_DEBUG_TURN", "").strip() == "1":
                    print(
                        "SENTRA_TURN_AUTH "
                        + json.dumps({
                            "phase": "response",
                            "action": action,
                            "trace_id": value.get("traceId"),
                            "revision": value.get("revision"),
                            "result": {key: result[key] for key in (
                                "authorized", "run_id", "operation_id", "prepared", "idempotent_replay"
                            ) if key in result},
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
                if path == "/sentra/web-transport/bind":
                    value = self._body()
                    if value is None:
                        return
                    if set(value) != {"conversation_uri","owner","run_id","work_item_id","principal_id","grant_id"}:
                        raise ValueError("exact host Web binding schema required")
                    self._json(200, self.server.web_transport.bind(**value))
                elif path == "/sentra/web-transport/mode":
                    value = self._body()
                    if value is None:
                        return
                    if set(value) != {"mode", "expected_revision"}:
                        raise ValueError("exact Web transport mode schema required")
                    self._json(200, self.server.web_transport.set_mode(**value))
                elif path == "/sentra/launcher/start":
                    self._json(200, self.server.launcher.start())
                elif path == "/sentra/launcher/stop":
                    self._json(200, self.server.launcher.stop())
                elif path == "/sentra/codex/connect":
                    self._json(200, self.server.launcher.route("sentra"))
                elif path == "/sentra/codex/disconnect":
                    self._json(200, self.server.launcher.route("disconnect"))
                elif path == "/sentra/upstream/reap-orphans":
                    self._json(200, self.server.reap_orphan_turns())
                elif path in {"/sentra/upstream/drain", "/sentra/upstream/resume", "/sentra/upstream/interrupt-turn"}:
                    action = path.rsplit("/", 1)[-1]
                    control_value: dict[str, Any] | None = None
                    if action == "interrupt-turn":
                        control_value = self._body()
                        if control_value is None:
                            return
                    try:
                        self._json(200, self.server.launcher.runtime_control(action, control_value))
                    except (OSError, PermissionError, ValueError, RuntimeError, http.client.HTTPException) as launcher_error:
                        token = self.server.upstream_control_token
                        if not token:
                            self._json(409, {
                                "error": "launcher runtime control is unavailable",
                                "detail": str(launcher_error)[:500],
                            })
                            return
                        body = json.dumps(control_value).encode("utf-8") if control_value is not None else b""
                        response = self._upstream(
                            "POST",
                            "/admin/" + action,
                            body,
                            {"Authorization": "Bearer " + token},
                        )
                        payload = response.read()
                        status = response.status
                        self._close_upstream(response)
                        self._json(status, json.loads(payload))
                else:
                    self._json(404, {"error": "not found"})
            except PermissionError as exc:
                self._json(403, {"error": str(exc)})
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
        gateway_request_id = secrets.token_hex(8)
        gateway_started = time.monotonic()
        self._audit_route("model.gateway.received", "ok", {
            "correlation_id": gateway_request_id, "path": path,
        })
        model = value.get("model")
        if model == "sentra/grok/grok-4.7":
            self._json(409, {
                "error": {
                    "type": "model_access_unverified",
                    "message": "sentra/grok/grok-4.7 is listed and access is unverified",
                },
                "model": model,
                "model_access_verified": False,
                "inference_executed": False,
            })
            return
        web_route = _web_model_route(model) if isinstance(model, str) else None
        canonical_web_model = bool(web_route and web_route[2])
        legacy_web_model = bool(web_route and not web_route[2])
        managed_web_model = canonical_web_model or legacy_web_model
        if isinstance(model, str) and model and not managed_web_model:
            self._json(400, {"error": {"type": "native_provider_route_required",
                                      "message": "Use the provider directly for native models; this endpoint serves Web models only"}})
            return
        bare_web_prefixes = {prefix for pair in WEB_MODEL_PREFIXES for prefix in pair}
        if (not isinstance(model, str) or not model
                or (model.startswith("sentra/") and not canonical_web_model)
                or model in bare_web_prefixes):
            self._json(400, {"error": {"type": "invalid_request_error", "message": "invalid model namespace"}})
            return
        # Codex may keep a Web model selected before its route was moved behind the SENTRA
        # Gateway. Treat upstream chatgpt-web/* and gemini-web/* spellings as managed
        # migration aliases so neither can bypass TurnCapability/lease authority.
        if managed_web_model:
            assert web_route is not None
            canonical_prefix, upstream_prefix, is_canonical = web_route
            if is_canonical:
                value["model"] = upstream_prefix + model[len(canonical_prefix):]
            metadata = value.get("client_metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            # Routing is selected only by the persisted host release gate.
            # A client cannot opt itself into an unapproved physical producer.
            metadata = {key: item for key, item in metadata.items()
                        if key not in {"sentra_durable_web", "sentra_turn_capability", "sentra_managed"}}
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
            native_identity=json.loads(request_identity) if request_identity else {}
            correlation=native_identity.get("turn_id") if isinstance(native_identity,dict) else None
            self.server.audit.emit("model.request.started","ok",{
                "correlation_id":correlation,"thread_id":native_identity.get("thread_id"),"model":model,
            })
            goal_present, goal_text = _extract_codex_goal_signal(value.get("input"))
            try:
                transport_mode = self.server.web_transport_mode()
                if transport_mode == "candidate_v2" and path == "/v1/responses":
                    raise PermissionError("candidate Web transport is not activated for production sends")
                if transport_mode == "durable_v2" and path == "/v1/responses":
                    capability = self.server.web_transport.admit_responses(
                        conversation_uri=conversation_uri, request_identity=request_identity, payload=value)
                    metadata = {**metadata, "sentra_durable_web": True}
                else:
                    capability = self.server.turn_authority.issue(
                    conversation_uri=conversation_uri,
                    request_identity=request_identity,
                    goal_text=goal_text,
                    goal_present=goal_present,
                    task_text=_extract_codex_task_text(value.get("input")),
                    subagent_notifications=_extract_codex_subagent_notifications(
                        value.get("input")
                    ),
                    )
            except DurableStateConflict as exc:
                self._json(409, {
                    "error": {
                        "type": "duplicate_turn",
                        "message": str(exc),
                    }
                })
                return
            except (PermissionError, ValueError, RuntimeError) as exc:
                self._json(403, {"error": {"type": "web_admission_denied", "message": str(exc)}})
                return
            except (sqlite3.Error, OSError, ImportError):
                self._json(503, {"error": {"type": "web_admission_unavailable", "automatic_retry": False}})
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
        proxy_status = None
        proxy_failed = True
        try:
            proxy_status = self._proxy(
                "POST",
                self.path,
                body,
                body_reencoded=True,
                rewrite_web_model_namespace=managed_web_model,
                delivery_capability=capability if capability and metadata is not None and metadata.get("sentra_durable_web") is True else None,
                request_correlation_id=gateway_request_id,
            )
            proxy_failed = proxy_status is None or proxy_status >= 400
        finally:
            recorder = getattr(self.server, 'record_inference_outcome', None)
            if callable(recorder):
                recorder(proxy_status)
            self._audit_route("model.gateway.forwarded", "error" if proxy_failed else "ok", {
                "correlation_id": gateway_request_id,
                "path": path,
                "upstream_http_status": proxy_status,
                "elapsed_ms": round((time.monotonic() - gateway_started) * 1000),
                "automatic_retry": False,
            })
            if capability:
                try:
                    evidence = self.server.turn_authority.telemetry_metadata(capability)
                    self.server.audit.emit("model.request.finished", (
                        "completed" if evidence["completion_verified"] else
                        "failed" if proxy_failed else "unverified"
                    ), {
                        **evidence, "model": model, "transport_ok": not proxy_failed,
                    })
                finally:
                    # A full audit disk must not retain a browser or conversation lease.
                    self.server.turn_authority.retire(capability, failed=proxy_failed)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="SENTRA loopback Responses gateway")
    parser.add_argument("--upstream", default=os.getenv("SENTRA_WEB_UPSTREAM", "http://127.0.0.1:17841"))
    parser.add_argument("--port", type=int, default=17842)
    parser.add_argument("--launch-upstream", action="store_true")
    args = parser.parse_args()
    state_root = resolve_gateway_state_root()
    admin_token = os.getenv("SENTRA_GATEWAY_ADMIN_TOKEN", "").strip()
    config = GatewayConfig(upstream=args.upstream, port=args.port, state_root=state_root,
                           admin_token=admin_token,
                           upstream_control_token=os.getenv("SENTRA_WEB_CONTROL_TOKEN", ""),
                           connector_name=os.getenv("SENTRA_CONNECTOR_NAME", "SENTRA"))
    server = GatewayServer(config)
    try:
        if args.launch_upstream:
            server.launcher.start()
        # Observe/recover the upstream even when launched by the desktop app.
        # Adopted/stale processes still cannot be terminated by this watchdog.
        server.start_upstream_watchdog()
        print(f"SENTRA Model Gateway listening on http://127.0.0.1:{server.server_port}/v1", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop_upstream_watchdog()
        server.shutdown() if threading.current_thread() is not threading.main_thread() else None
        server.launcher.stop()
        server.server_close()


if __name__ == "__main__":
    main()
