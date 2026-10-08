"""Model transport for SENTRA CLI.

The SENTRA Web gateway speaks the OpenAI Responses protocol. Direct OpenAI and
local providers are chat-completions fallbacks and are only considered before a
Web turn is sent, never after an uncertain Web delivery.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Generator
from sentra_mcp.errors import sanitize_error

from .config import CLIConfig, SENTRA_ROOT


class ProviderHTTPError(RuntimeError):
    def __init__(
        self,
        provider: str,
        status: int | None,
        detail: str,
    ) -> None:
        self.provider = provider
        self.status = status
        self.detail = sanitize_error(detail)
        label = f"HTTP {status}" if status is not None else "transport error"
        super().__init__(f"{provider}: {label}: {self.detail}")


class ProviderAdmissionError(RuntimeError):
    pass


class ModelClient:
    """SENTRA Responses client with fail-closed delivery semantics."""

    def __init__(self, config: CLIConfig) -> None:
        self.config = config
        self.active_provider = "unknown"
        self.active_model = config.model
        self.last_error: str | None = None
        self.last_delivery_state = "not_submitted"
        self.on_delivery = None
        self.on_usage = None
        self.on_before_provider = None
        # One logical Codex thread per CLI process. Every Responses request gets
        # a distinct native turn id so tool-round follow-ups cannot collide in
        # the Gateway's duplicate-turn / retry budget authority.
        self._session_id = uuid.uuid4().hex
        self._thread_id = f"sentra-cli-thread-{self._session_id}"
        self._conversation_uri = (
            f"conversation://sentra-cli/{self._session_id}"
        )

    def bind_conversation(self, session_id: str) -> None:
        from sentra_core.conversations import valid_session_id
        self._session_id = valid_session_id(session_id)
        self._thread_id = f"sentra-cli-thread-{self._session_id}"
        self._conversation_uri = f"conversation://sentra-cli/{self._session_id}"
        self.last_error = None
        self.last_delivery_state = "not_submitted"

    def _delivery(self, provider: str, ident: str, state: str) -> None:
        if state=="submitted" and self.on_before_provider is not None:
            try:self.on_before_provider(provider)
            except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:
                raise ProviderAdmissionError(sanitize_error(exc)) from exc
        if self.on_delivery is not None:
            self.on_delivery(provider, ident, state)
        self.last_delivery_state = state

    def _usage(self,provider,ident,model,usage):
        if self.on_usage is not None and usage:
            self.on_usage(provider,ident,model,usage)

    @staticmethod
    def _decode_json(raw: bytes) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8", errors="replace") or "{}")
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}

    @staticmethod
    def _error_detail(raw: bytes) -> str:
        data = ModelClient._decode_json(raw)
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("type")
            if message:
                return str(message)
        if isinstance(error, str) and error:
            return error
        text = raw.decode("utf-8", errors="replace").strip()
        return text[:1000] if text else "request failed"

    def _gateway_origin(self) -> str:
        base = self.config.gateway_url.rstrip("/")
        return base[:-3] if base.endswith("/v1") else base

    def gateway_status(self) -> dict[str, Any]:
        url = self._gateway_origin() + "/healthz"
        status_code: int | None = None
        payload: dict[str, Any] = {}
        transport_error: str | None = None
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "sentra-cli"},
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                status_code = int(resp.status)
                payload = self._decode_json(resp.read())
        except urllib.error.HTTPError as exc:
            status_code = int(exc.code)
            payload = self._decode_json(exc.read())
        except Exception as exc:
            transport_error = f"{type(exc).__name__}: {exc}"

        reachable = status_code is not None
        ready = bool(
            status_code == 200
            and payload.get("status") == "ok"
            and payload.get("ready") is True
        )
        catalog = payload.get("catalog")
        catalog_ready = bool(
            isinstance(catalog, dict)
            and catalog.get("status") == "ready"
            and catalog.get("models")
        )
        upstream = payload.get("upstream")
        upstream_status = (
            upstream.get("status")
            if isinstance(upstream, dict)
            else None
        )
        turn_ready = bool(
            reachable
            and upstream_status == "ok"
            and isinstance(upstream, dict)
            and upstream.get("accepting_turns") is True
        )
        return {
            "reachable": reachable,
            "ready": ready,
            "turn_ready": turn_ready,
            "status_code": status_code,
            "catalog_ready": catalog_ready,
            "upstream_status": upstream_status,
            "launcher": payload.get("launcher"),
            "error": transport_error or payload.get("error"),
            "payload": payload,
        }

    def _local_available(self) -> bool:
        try:
            req = urllib.request.Request(
                self.config.local_base_url.rstrip("/") + "/models",
                headers={
                    "Authorization": f"Bearer {self.config.local_api_key}",
                    "User-Agent": "sentra-cli",
                },
            )
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def probe_health(self) -> dict[str, Any]:
        gateway = self.gateway_status()
        return {
            "gateway": bool(gateway["turn_ready"]),
            "gateway_reachable": bool(gateway["reachable"]),
            "gateway_status": gateway,
            "browser_host": self._browser_host_ready(),
            "openai": bool(
                self.config.openai_api_key
                or os.environ.get("OPENAI_API_KEY")
            ),
            "local": self._local_available(),
        }

    def list_models(self) -> list[str]:
        from .codex_native import authenticated
        native_models=["sentra/codex/current"] if authenticated() else []
        url = self.config.gateway_url.rstrip("/") + "/models"
        headers = {
            "Authorization": f"Bearer {self.config.gateway_api_key}",
            "User-Agent": "sentra-cli",
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                payload = self._decode_json(resp.read())
        except urllib.error.HTTPError as exc:
            if native_models:return native_models
            raise ProviderHTTPError(
                "gateway",
                int(exc.code),
                self._error_detail(exc.read()),
            ) from exc
        except Exception as exc:
            if native_models:return native_models
            raise ProviderHTTPError(
                "gateway", None, f"{type(exc).__name__}: {exc}"
            ) from exc

        items = payload.get("data")
        if not isinstance(items, list):
            items = payload.get("models")
        result: list[str] = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                model = item.get("id") or item.get("slug")
                if isinstance(model, str) and model and model not in result:
                    result.append(model)
        return result+[model for model in native_models if model not in result]

    def _gateway_admin_post(
        self,
        path: str,
        *,
        timeout: float = 20.0,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        tokens = self.config.gateway_admin_tokens
        if not tokens:
            return False, "gateway admin token unavailable"

        url = self._gateway_origin() + path
        body = (
            json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            if json_body is not None
            else b""
        )
        last_detail = "unauthorized"
        for index, token in enumerate(tokens):
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "sentra-cli",
            }
            if json_body is not None:
                headers["Content-Type"] = "application/json"
            else:
                headers["Content-Length"] = "0"
            req = urllib.request.Request(
                url,
                data=body,
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = self._decode_json(resp.read())
                    detail = str(
                        payload.get("source")
                        or payload.get("status")
                        or f"HTTP {resp.status}"
                    )
                    return 200 <= resp.status < 300, detail
            except urllib.error.HTTPError as exc:
                raw = exc.read()
                last_detail = (
                    f"HTTP {exc.code}: {self._error_detail(raw)}"
                )
                if exc.code == 401 and index + 1 < len(tokens):
                    continue
                return False, last_detail
            except Exception as exc:
                return False, f"{type(exc).__name__}: {exc}"
        return False, last_detail

    def _interrupt_web_turn(self, turn_id: str) -> tuple[bool, str]:
        """Cancel exactly one delivered Web turn after a local deadline."""
        return self._gateway_admin_post(
            "/sentra/upstream/interrupt-turn",
            timeout=3.0,
            json_body={
                "threadId": self._thread_id,
                "turnId": turn_id,
            },
        )

    def _reap_orphan_web_turns(self) -> tuple[bool, str]:
        """Fail-closed fallback: reap only browser leases with zero HTTP owners."""
        return self._gateway_admin_post(
            "/sentra/upstream/reap-orphans",
            timeout=5.0,
        )

    def _interrupt_or_reap_web_turn(
        self,
        turn_id: str,
    ) -> tuple[bool, str]:
        cancelled, detail = self._interrupt_web_turn(turn_id)
        # A targeted interrupt can be acknowledged before the physical browser
        # lease disappears. Ask the Gateway to reap only if it can prove there
        # are zero HTTP owners; otherwise the fail-closed reaper refuses.
        reaped, reap_detail = self._reap_orphan_web_turns()
        if reaped:
            return True, f"target={detail}; reap={reap_detail}"
        if cancelled:
            return True, f"target={detail}; reap_skipped={reap_detail}"
        return False, f"target={detail}; reap={reap_detail}"

    @staticmethod
    def _creation_flags() -> int:
        if os.name != "nt":
            return 0
        return (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )

    @staticmethod
    def _web_runtime_cli_path() -> Path | None:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            base = SENTRA_ROOT / "dist"

        runtime_bin = (
            base
            / "web-models"
            / "win-unpacked"
            / "resources"
            / "runtime"
            / "bin"
        )
        candidates = (
            runtime_bin / "codex-chatgpt-web.cmd",
            runtime_bin / "codex-chatgpt-web",
        )
        return next((item for item in candidates if item.is_file()), None)

    @staticmethod
    def _headless_pid_path() -> Path:
        home = Path(os.environ.get("USERPROFILE") or Path.home())
        return home / ".sentra" / "web-models" / "cli-headless-upstream.pid"

    @staticmethod
    def _upstream_ready() -> bool:
        url = os.environ.get(
            "SENTRA_WEB_UPSTREAM",
            "http://127.0.0.1:17841",
        ).rstrip("/") + "/healthz"
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "sentra-cli"},
            )
            with urllib.request.urlopen(request, timeout=2.0) as response:
                payload = ModelClient._decode_json(response.read())
                return bool(
                    response.status == 200
                    and payload.get("status") == "ok"
                    and payload.get("accepting_turns", True)
                )
        except Exception:
            return False

    @staticmethod
    def _browser_relay_token_file() -> Path | None:
        """Find the token that authenticates against the relay actually on 8765."""
        raw_candidates = [
            os.environ.get("SENTRA_BROWSER_RELAY_TOKEN_FILE", "").strip(),
            str(SENTRA_ROOT / ".sentra" / "browser" / "relay-token"),
            str(Path(os.environ.get("USERPROFILE") or Path.home()) / ".sentra" / "browser" / "relay-token"),
        ]
        seen: set[str] = set()
        for raw in raw_candidates:
            if not raw:
                continue
            candidate = Path(raw).expanduser().resolve()
            key = os.path.normcase(str(candidate))
            if key in seen or not candidate.is_file():
                continue
            seen.add(key)
            try:
                token = candidate.read_text(encoding="utf-8").strip()
                if not token:
                    continue
                request = urllib.request.Request(
                    "http://127.0.0.1:8765/auth/check",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "User-Agent": "sentra-cli",
                    },
                )
                with urllib.request.urlopen(request, timeout=1.5) as response:
                    if response.status == 200:
                        return candidate
            except Exception:
                continue
        return None

    @staticmethod
    def _browser_host_executable_path() -> Path:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            base = SENTRA_ROOT / "dist"
        return (
            base
            / "web-models"
            / "win-unpacked"
            / "Codex Web GPT.exe"
        )

    @staticmethod
    def _browser_descriptor_path() -> Path:
        home_override = os.environ.get("CODEX_CHATGPT_WEB_HOME", "").strip()
        if home_override:
            core_home = Path(home_override).expanduser().resolve()
        else:
            home_value = os.environ.get("USERPROFILE") or os.environ.get("HOME")
            if home_value:
                home = Path(home_value)
            else:
                try:
                    home = Path.home()
                except RuntimeError:
                    return (
                        SENTRA_ROOT
                        / ".sentra"
                        / "web-models"
                        / "unavailable-launcher-browser.json"
                    )
            core_home = home / ".codex-chatgpt-web"
        return core_home / "runtime" / "launcher-browser.json"

    @staticmethod
    def _pid_running(pid: int) -> bool:
        if not isinstance(pid, int) or pid < 1:
            return False
        if os.name == "nt":
            try:
                import ctypes

                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.OpenProcess.argtypes = (
                    ctypes.c_ulong,
                    ctypes.c_int,
                    ctypes.c_ulong,
                )
                kernel.OpenProcess.restype = ctypes.c_void_p
                kernel.GetExitCodeProcess.argtypes = (
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_ulong),
                )
                kernel.GetExitCodeProcess.restype = ctypes.c_int
                kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
                kernel.CloseHandle.restype = ctypes.c_int
                handle = kernel.OpenProcess(0x1000, False, pid)
                if not handle:
                    return False
                try:
                    exit_code = ctypes.c_ulong()
                    return bool(
                        kernel.GetExitCodeProcess(
                            handle,
                            ctypes.byref(exit_code),
                        )
                        and exit_code.value == 259
                    )
                finally:
                    kernel.CloseHandle(handle)
            except Exception:
                return False
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except OSError:
            return False

    def _browser_host_ready(self) -> bool:
        descriptor = self._browser_descriptor_path()
        try:
            data = json.loads(descriptor.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        pid = data.get("pid")
        endpoint = str(data.get("endpoint") or "")
        helper = data.get("helper")
        if not (
            data.get("version") == 3
            and data.get("kind") == "codex-web-gpt-launcher"
            and isinstance(pid, int)
            and self._pid_running(pid)
            and endpoint.startswith("http://127.0.0.1:")
            and isinstance(helper, dict)
        ):
            return False
        expected = self._browser_host_executable_path()
        observed = Path(str(helper.get("executable") or "")).expanduser()
        script = Path(str(helper.get("script") or "")).expanduser()
        try:
            if observed.resolve() != expected.resolve() or not script.is_file():
                return False
        except OSError:
            return False

        # Adopt an already-running compatible launcher even when SENTRA did not
        # create it. Ownership remains external: we only consume its private
        # loopback browser descriptor and never stop that process.
        try:
            request = urllib.request.Request(
                endpoint.rstrip("/") + "/json/version",
                headers={"User-Agent": "sentra-cli"},
            )
            with urllib.request.urlopen(request, timeout=1.5) as response:
                payload = self._decode_json(response.read())
                websocket = str(payload.get("webSocketDebuggerUrl") or "")
                return bool(
                    response.status == 200
                    and websocket.startswith("ws://127.0.0.1:")
                )
        except Exception:
            return False

    def _wait_browser_host_turn_ready(
        self,
        timeout_s: float | None = None,
    ) -> tuple[bool, str]:
        """Wait until the launcher finishes its startup session refresh.

        The browser descriptor and CDP endpoint are published slightly before
        the launcher completes refreshAuthentication(). A first turn sent in
        that narrow window is rejected as "busy with session refresh". Probe
        the launcher's existing owner-only session endpoint before any prompt
        is submitted, so recovery stays fail-closed and never replays a turn.
        """
        budget = (
            min(max(self.config.gateway_start_timeout_s, 1.0), 45.0)
            if timeout_s is None
            else max(0.0, timeout_s)
        )
        deadline = time.monotonic() + budget
        last_detail = "browser host has not published a turn-ready session"

        while time.monotonic() < deadline:
            descriptor = self._browser_descriptor_path()
            try:
                data = json.loads(descriptor.read_text(encoding="utf-8"))
                control = data.get("control")
                endpoint = (
                    str(control.get("endpoint") or "")
                    if isinstance(control, dict)
                    else ""
                )
                token = (
                    str(control.get("token") or "")
                    if isinstance(control, dict)
                    else ""
                )
            except (OSError, ValueError, TypeError):
                endpoint = ""
                token = ""

            if (
                endpoint.startswith("http://127.0.0.1:")
                and len(token) >= 40
            ):
                request = urllib.request.Request(
                    endpoint.rstrip("/") + "/v1/session/inspect",
                    data=b'{"detectCapabilities":false}',
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "User-Agent": "sentra-cli",
                    },
                    method="POST",
                )
                try:
                    remaining = max(0.1, deadline - time.monotonic())
                    with urllib.request.urlopen(
                        request,
                        timeout=min(5.0, remaining),
                    ) as response:
                        payload = self._decode_json(response.read())
                        if (
                            response.status == 200
                            and payload.get("authenticated") is True
                            and payload.get("temporary") is True
                        ):
                            return True, "ready"
                        last_detail = "launcher session evidence is incomplete"
                except urllib.error.HTTPError as exc:
                    detail = self._error_detail(exc.read())
                    lowered = detail.casefold()
                    if (
                        int(exc.code) in {400, 409, 423, 503}
                        and (
                            "busy" in lowered
                            or "session refresh" in lowered
                            or "not ready" in lowered
                        )
                    ):
                        last_detail = "launcher is finishing session refresh"
                    else:
                        return False, f"session probe HTTP {int(exc.code)}"
                except Exception as exc:
                    last_detail = (
                        "session probe "
                        + type(exc).__name__
                    )

            time.sleep(0.25)

        return False, last_detail

    @staticmethod
    def _turn_authority_token() -> str:
        direct = os.environ.get("SENTRA_TURN_AUTHORITY_TOKEN", "").strip()
        if len(direct) >= 32:
            return direct
        try:
            from sentra_remote.product import ProductPaths

            install_root = (
                Path(sys.executable).resolve().parent
                if getattr(sys, "frozen", False)
                else SENTRA_ROOT
            )
            state_root = ProductPaths.default(install_root).state_dir
            token_path = state_root / "web-models" / "turn-authority.token"
            token = token_path.read_text(encoding="utf-8").strip()
            return token if len(token) >= 32 else ""
        except (OSError, ValueError, TypeError):
            return ""

    def _spawn_browser_host(self) -> str:
        if self._browser_host_ready():
            return "browser-host already ready"
        executable = self._browser_host_executable_path()
        if not executable.is_file():
            return "browser-host error=packaged Electron launcher not found"

        env = os.environ.copy()
        env["SENTRA_BROWSER_HOST_ONLY"] = "1"
        env["SENTRA_MANAGED_TUNNEL"] = "1"
        env["SENTRA_WEB_GATEWAY_URL"] = self.config.gateway_url
        turn_authority_token = self._turn_authority_token()
        if turn_authority_token:
            env["SENTRA_TURN_AUTHORITY_TOKEN"] = turn_authority_token
        relay_token_file = self._browser_relay_token_file()
        if relay_token_file is not None:
            env["SENTRA_BROWSER_RELAY_TOKEN_FILE"] = str(relay_token_file)

        build_state = executable.parent.parent / "integration-build.json"
        try:
            metadata = json.loads(build_state.read_text(encoding="utf-8-sig"))
            patch_hash = str(metadata.get("patch_sha256") or "").strip()
            if patch_hash:
                env["SENTRA_INTEGRATION_PATCH_SHA256"] = patch_hash
        except (OSError, ValueError, TypeError):
            pass

        try:
            process = subprocess.Popen(
                [str(executable), "--hidden"],
                cwd=str(executable.parent),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=self._creation_flags(),
            )
        except Exception as exc:
            return f"browser-host error={type(exc).__name__}: {exc}"

        deadline = time.monotonic() + min(
            max(self.config.gateway_start_timeout_s, 1.0),
            60.0,
        )
        while time.monotonic() < deadline:
            if self._browser_host_ready():
                return f"browser-host pid={process.pid}"
            if process.poll() is not None:
                return f"browser-host exited={process.returncode}"
            time.sleep(0.25)
        # A healthy Electron process may still be materializing its packaged
        # runtime after a live build. Do not mislabel that state as a crash.
        return f"browser-host starting pid={process.pid}"

    def _stop_browser_host(self) -> str:
        descriptor = self._browser_descriptor_path()
        try:
            data = json.loads(descriptor.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return "browser-host-not-owned"

        if data.get("sentraManaged") is not True:
            return "browser-host-not-owned"
        pid = data.get("pid")
        helper = data.get("helper")
        if not isinstance(pid, int) or pid < 1 or not isinstance(helper, dict):
            return "browser-host-descriptor-invalid"

        expected = self._browser_host_executable_path()
        observed = Path(str(helper.get("executable") or "")).expanduser()
        try:
            if observed.resolve() != expected.resolve():
                return "browser-host-refused=executable-mismatch"
        except OSError:
            return "browser-host-refused=executable-mismatch"

        if not self._pid_running(pid):
            try:
                descriptor.unlink()
            except OSError:
                pass
            return "browser-host-pid-stale"

        try:
            if os.name == "nt":
                inspect = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        (
                            "$p=Get-CimInstance Win32_Process -Filter "
                            f"'ProcessId={pid}'; if($p){{$p.ExecutablePath}}"
                        ),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5.0,
                    creationflags=getattr(
                        subprocess,
                        "CREATE_NO_WINDOW",
                        0,
                    ),
                )
                actual = inspect.stdout.strip()
                if (
                    inspect.returncode != 0
                    or not actual
                    or os.path.normcase(str(Path(actual).resolve()))
                    != os.path.normcase(str(expected.resolve()))
                ):
                    return "browser-host-refused=process-mismatch"
                stopped = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15.0,
                    creationflags=getattr(
                        subprocess,
                        "CREATE_NO_WINDOW",
                        0,
                    ),
                )
                if stopped.returncode != 0 and self._pid_running(pid):
                    detail = (
                        stopped.stderr.strip()
                        or stopped.stdout.strip()
                        or f"exit={stopped.returncode}"
                    )
                    return "browser-host-stop-error=" + detail
                detail = f"browser-host-stopped pid={pid}"
            else:
                proc_exe = Path(f"/proc/{pid}/exe")
                try:
                    actual_path = proc_exe.resolve()
                except OSError:
                    return "browser-host-refused=process-mismatch"
                if actual_path != expected.resolve():
                    return "browser-host-refused=process-mismatch"
                os.kill(pid, 15)
                detail = f"browser-host-stopped pid={pid}"
        except Exception as exc:
            return f"browser-host-stop-error={type(exc).__name__}: {exc}"

        try:
            current = json.loads(descriptor.read_text(encoding="utf-8"))
            if current.get("pid") == pid:
                descriptor.unlink()
        except (OSError, ValueError, TypeError):
            pass
        return detail

    @staticmethod
    def _spawn_gateway() -> str:
        try:
            if getattr(sys, "frozen", False):
                command = [sys.executable, "--gateway-service"]
                cwd = str(Path(sys.executable).resolve().parent)
            else:
                command = [
                    sys.executable,
                    "-B",
                    "-m",
                    "sentra_model_gateway.gateway",
                ]
                cwd = str(SENTRA_ROOT)
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=ModelClient._creation_flags(),
            )
            return f"gateway pid={process.pid}"
        except Exception as exc:
            return f"gateway error={type(exc).__name__}: {exc}"

    def _spawn_headless_upstream(self) -> str:
        if self._upstream_ready():
            return "upstream already ready"

        cli = self._web_runtime_cli_path()
        if cli is None:
            return "upstream error=packaged runtime CLI not found"

        runtime_root = cli.parent.parent
        bun = runtime_root / "runtime" / (
            "bun.exe" if os.name == "nt" else "bun"
        )
        app = runtime_root / "app" / "cli.js"
        if bun.is_file() and app.is_file():
            command = [str(bun), str(app), "serve"]
            cwd = runtime_root
            executable = bun
        else:
            command = [str(cli), "serve"]
            cwd = cli.parent
            executable = cli

        env = os.environ.copy()
        authority_origin = self._gateway_origin()
        env["SENTRA_WEB_GATEWAY_URL"] = authority_origin + "/v1"
        env["SENTRA_TURN_AUTHORITY_URL"] = authority_origin
        env["SENTRA_MANAGED_TUNNEL"] = "1"
        env["SENTRA_GEMINI_WEB_ENABLED"] = "1"
        turn_authority_token = self._turn_authority_token()
        if turn_authority_token:
            env["SENTRA_TURN_AUTHORITY_TOKEN"] = turn_authority_token
        relay_token_file = self._browser_relay_token_file()
        if relay_token_file is not None:
            env["SENTRA_BROWSER_RELAY_TOKEN_FILE"] = str(relay_token_file)

        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=self._creation_flags(),
                start_new_session=(os.name != "nt"),
            )
            pid_path = self._headless_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(
                json.dumps(
                    {
                        "pid": process.pid,
                        "executable": str(executable.resolve()),
                        "started_at": time.time(),
                    },
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            return f"upstream pid={process.pid}"
        except Exception as exc:
            return f"upstream error={type(exc).__name__}: {exc}"

    @staticmethod
    def _process_matches_runtime(pid: int, executable: str) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            command = (
                "$p=Get-CimInstance Win32_Process -Filter "
                f"'ProcessId={pid}'; "
                "if($p){$p.ExecutablePath; $p.CommandLine}"
            )
            try:
                completed = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        command,
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5.0,
                    creationflags=getattr(
                        subprocess,
                        "CREATE_NO_WINDOW",
                        0,
                    ),
                )
            except Exception:
                return False
            observed = completed.stdout.lower()
            return (
                str(Path(executable).resolve()).lower() in observed
                and "serve" in observed
            )

        proc_cmdline = Path(f"/proc/{pid}/cmdline")
        try:
            observed = proc_cmdline.read_bytes().replace(b"\0", b" ").decode(
                "utf-8",
                errors="replace",
            )
        except OSError:
            return False
        return str(Path(executable).resolve()) in observed and "serve" in observed

    def _stop_headless_upstream(self) -> str:
        pid_path = self._headless_pid_path()
        try:
            state = json.loads(pid_path.read_text(encoding="utf-8"))
            pid = int(state["pid"])
            executable = str(state["executable"])
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return "headless-upstream-not-owned"

        if not self._process_matches_runtime(pid, executable):
            try:
                pid_path.unlink()
            except OSError:
                pass
            return "headless-upstream-pid-stale"

        try:
            if os.name == "nt":
                completed = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15.0,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                detail = (
                    completed.stdout.strip()
                    or completed.stderr.strip()
                    or f"exit={completed.returncode}"
                )
            else:
                os.kill(pid, 15)
                detail = f"terminated pid={pid}"
        except Exception as exc:
            detail = f"stop error={type(exc).__name__}: {exc}"
        finally:
            try:
                pid_path.unlink()
            except OSError:
                pass
        return detail

    def ensure_gateway_ready(
        self,
        wait_s: float | None = None,
    ) -> dict[str, Any]:
        initial = self.gateway_status()
        if initial["turn_ready"]:
            return {**initial, "action": "already-turn-ready"}

        budget = (
            self.config.gateway_start_timeout_s
            if wait_s is None
            else max(0.0, wait_s)
        )
        actions: list[str] = []
        if not initial["reachable"]:
            actions.append(self._spawn_gateway())
        if not self._upstream_ready():
            actions.append(self._spawn_headless_upstream())

        deadline = time.monotonic() + budget
        latest = initial
        while time.monotonic() < deadline:
            time.sleep(0.5)
            latest = self.gateway_status()
            if latest["turn_ready"]:
                break
        return {
            **latest,
            "action": "; ".join(actions) or "headless-runtime-already-starting",
        }

    def stop_gateway_runtime(self) -> dict[str, Any]:
        actions = [
            self._stop_headless_upstream(),
            self._stop_browser_host(),
        ]
        status = self.gateway_status()

        # Stop a legacy launcher-owned runtime if one already exists. This
        # endpoint never starts Electron; it is cleanup-only.
        if status["reachable"]:
            ok, detail = self._gateway_admin_post("/sentra/launcher/stop")
            if ok:
                actions.append(f"legacy-launcher-stop ({detail})")
            elif detail != "gateway admin token unavailable":
                actions.append(f"legacy-stop-warning ({detail})")

        time.sleep(0.5)
        return {
            **self.gateway_status(),
            "action": "; ".join(actions),
        }

    def _next_turn_metadata(
        self,
    ) -> tuple[str, str, dict[str, Any]]:
        """Build the native Codex identity required by managed Web turns."""
        turn_id = f"sentra-cli-turn-{uuid.uuid4().hex}"
        workspace = str(self.config.workspace)
        native = {
            "request_kind": "turn",
            "thread_id": self._thread_id,
            "turn_id": turn_id,
            "agent_name": "/root",
            "sandbox_mode": "workspace-write",
            "workspaces": {workspace: {}},
        }
        encoded = json.dumps(
            native,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        transport = {
            "client_metadata": {
                "sentra_conversation_uri": self._conversation_uri,
                "x-codex-turn-metadata": encoded,
            },
            "prompt_cache_key": self._thread_id,
        }
        return encoded, turn_id, transport

    @staticmethod
    def _xml_text(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _native_responses_input(
        self,
        messages: list[dict[str, Any]],
        turn_id: str,
    ) -> list[dict[str, Any]]:
        """Render chat history as native Codex items plus trusted environment."""
        current_user = max(
            (
                index
                for index, message in enumerate(messages)
                if message.get("role") == "user"
            ),
            default=-1,
        )
        workspace = str(self.config.workspace)
        environment_text = (
            "<environment_context>\n"
            f"<cwd>{self._xml_text(workspace)}</cwd>\n"
            "<workspace_roots>\n"
            f"<root>{self._xml_text(workspace)}</root>\n"
            "</workspace_roots>\n"
            "<sandbox_mode>workspace-write</sandbox_mode>\n"
            "</environment_context>"
        )
        result: list[dict[str, Any]] = []

        for index, message in enumerate(messages):
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "")
            stable_id = message.get("id") or uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{self._session_id}:{index}:{role}:{content}",
            ).hex

            if index == current_user:
                result.append(
                    {
                        "type": "message",
                        "id": f"env_{turn_id}",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": environment_text,
                            }
                        ],
                        "internal_chat_message_metadata_passthrough": {
                            "turn_id": turn_id,
                            "content_item_kinds": [
                                "environments.environment_context"
                            ],
                        },
                    }
                )

            if role == "assistant":
                item_content = [
                    {"type": "output_text", "text": content}
                ]
            else:
                item_content = [{"type": "input_text", "text": content}]

            item: dict[str, Any] = {
                "type": "message",
                "id": f"msg_{stable_id}",
                "role": role,
                "content": item_content,
            }
            if index == current_user:
                item["internal_chat_message_metadata_passthrough"] = {
                    "turn_id": turn_id,
                }
            result.append(item)

        return result

    @staticmethod
    def _extract_response_text(response: dict[str, Any]) -> str:
        pieces: list[str] = []
        for item in response.get("output") or []:
            if not isinstance(item, dict):
                continue
            for part in item.get("content") or []:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "output_text"
                    and isinstance(part.get("text"), str)
                ):
                    pieces.append(part["text"])
        return "".join(pieces)

    def _responses_stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
    ) -> Generator[str, None, None]:
        (
            turn_metadata,
            turn_id,
            transport_metadata,
        ) = self._next_turn_metadata()
        payload = {
            "model": model,
            "input": self._native_responses_input(messages, turn_id),
            "max_output_tokens": self.config.max_output_tokens,
            "store": False,
            "stream": True,
            **transport_metadata,
        }
        url = self.config.gateway_url.rstrip("/") + "/responses"
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self.config.gateway_api_key}",
            "User-Agent": "sentra-cli",
            "x-codex-turn-metadata": turn_metadata,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        self._delivery("gateway", turn_id, "submitted")
        try:
            response = urllib.request.urlopen(
                req,
                timeout=self.config.timeout_s,
            )
        except urllib.error.HTTPError as exc:
            self._delivery("gateway", turn_id, "rejected" if exc.code in {400,401,403,404,405,413,422,429} else "uncertain")
            raise ProviderHTTPError(
                "gateway",
                int(exc.code),
                self._error_detail(exc.read()),
            ) from exc
        except Exception as exc:
            self._delivery("gateway", turn_id, "uncertain")
            cancelled, cancel_detail = self._interrupt_or_reap_web_turn(
                turn_id
            )
            suffix = (
                f"; interrupt={cancel_detail}"
                if cancelled
                else f"; interrupt_failed={cancel_detail}"
            )
            raise ProviderHTTPError(
                "gateway",
                None,
                f"{type(exc).__name__}: {exc}{suffix}",
            ) from exc

        current_event: str | None = None
        emitted = False
        completed = False
        deadline = time.monotonic() + max(self.config.timeout_s, 0.1)
        try:
            with response:
                for raw_line in response:
                    if time.monotonic() >= deadline:
                        cancelled, cancel_detail = (
                            self._interrupt_or_reap_web_turn(turn_id)
                        )
                        suffix = (
                            f"; interrupt={cancel_detail}"
                            if cancelled
                            else f"; interrupt_failed={cancel_detail}"
                        )
                        raise ProviderHTTPError(
                            "gateway",
                            None,
                            (
                                "turn deadline exceeded after "
                                f"{self.config.timeout_s:.1f}s"
                                + suffix
                            ),
                        )
                    line = raw_line.decode(
                        "utf-8", errors="replace"
                    ).rstrip("\r\n")
                    if not line:
                        current_event = None
                        continue
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_text = line[5:].strip()
                    if data_text == "[DONE]":
                        completed = True
                        break
                    try:
                        data = json.loads(data_text)
                    except ValueError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    event_type = str(
                        data.get("type") or current_event or ""
                    )
                    if event_type == "response.output_text.delta":
                        delta = data.get("delta")
                        if isinstance(delta, str) and delta:
                            emitted = True
                            yield delta
                    elif event_type == "response.completed":
                        completed = True
                        completed_response = data.get("response")
                        if isinstance(completed_response,dict):
                            from sentra_core.provider_usage import normalize_usage
                            self._usage("gateway",turn_id,model,normalize_usage(completed_response.get("usage")))
                        if not emitted and isinstance(completed_response, dict):
                            text = self._extract_response_text(completed_response)
                            if text:
                                emitted = True
                                yield text
                    elif event_type in {"response.failed", "error"}:
                        detail = data.get("error") or data
                        raise ProviderHTTPError(
                            "gateway", None, str(detail)[:1000]
                        )
            if not emitted:
                raise ProviderHTTPError(
                    "gateway", None, "response completed without output text"
                )
            if not completed:
                raise ProviderHTTPError("gateway", None, "response stream ended before completion")
            self._delivery("gateway", turn_id, "completed")
        except ProviderHTTPError:
            self._delivery("gateway", turn_id, "uncertain")
            raise
        except Exception as exc:
            self._delivery("gateway", turn_id, "uncertain")
            cancelled, cancel_detail = self._interrupt_or_reap_web_turn(
                turn_id
            )
            suffix = (
                f"; interrupt={cancel_detail}"
                if cancelled
                else f"; interrupt_failed={cancel_detail}"
            )
            raise ProviderHTTPError(
                "gateway",
                None,
                f"{type(exc).__name__}: {exc}{suffix}",
            ) from exc

    def _chat_completions_stream(
        self,
        base_url: str,
        api_key: str,
        messages: list[dict[str, Any]],
        model: str,
        provider: str,
    ) -> Generator[str, None, None]:
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if provider=="openai":payload["stream_options"]={"include_usage":True}
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "sentra-cli",
            },
            method="POST",
        )
        request_id = "sentra-cli-direct-" + uuid.uuid4().hex
        self._delivery(provider, request_id, "submitted")
        try:
            response = urllib.request.urlopen(
                req,
                timeout=self.config.timeout_s,
            )
        except urllib.error.HTTPError as exc:
            self._delivery(provider, request_id, "rejected" if exc.code in {400,401,403,404,405,413,422,429} else "uncertain")
            raise ProviderHTTPError(
                provider,
                int(exc.code),
                self._error_detail(exc.read()),
            ) from exc
        except Exception as exc:
            self._delivery(provider, request_id, "uncertain")
            raise ProviderHTTPError(
                provider, None, f"{type(exc).__name__}: {exc}"
            ) from exc

        deadline = time.monotonic() + max(self.config.timeout_s, 0.1)
        reported_usage={}
        try:
            with response:
                for raw_line in response:
                    if time.monotonic() >= deadline:
                        raise ProviderHTTPError(
                            provider,
                            None,
                            (
                                "turn deadline exceeded after "
                                f"{self.config.timeout_s:.1f}s"
                            ),
                        )
                    line = raw_line.decode(
                        "utf-8", errors="replace"
                    ).strip()
                    if not line.startswith("data:"):
                        continue
                    data_text = line[5:].strip()
                    if data_text == "[DONE]":
                        self._usage(provider,request_id,model,reported_usage)
                        self._delivery(provider, request_id, "completed")
                        return
                    try:
                        event = json.loads(data_text)
                    except ValueError:
                        continue
                    if isinstance(event.get("usage"),dict):
                        from sentra_core.provider_usage import normalize_usage
                        reported_usage=normalize_usage(event["usage"])
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield content
            raise ProviderHTTPError(provider, None, "response stream ended before completion")
        except ProviderHTTPError:
            self._delivery(provider, request_id, "uncertain")
            raise
        except Exception as exc:
            self._delivery(provider, request_id, "uncertain")
            raise ProviderHTTPError(
                provider, None, f"{type(exc).__name__}: {exc}"
            ) from exc

    def chat_stream(
        self,messages: list[dict[str,Any]],tools: list[dict[str,Any]]|None=None,
        model_override: str|None=None,
    ) -> Generator[str,None,None]:
        try:
            yield from self._chat_stream(messages,tools,model_override)
        except ProviderAdmissionError as exc:
            self.last_error=sanitize_error(exc)
            yield "\nProvider request blocked before submission: "+self.last_error+"\n"

    def _chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model_override: str | None = None,
    ) -> Generator[str, None, None]:
        """Stream one turn using Web first, then pre-send fallbacks only."""
        del tools
        self.last_delivery_state = "not_submitted"
        self.last_error = None
        model = model_override or self.config.model
        if model.startswith("sentra/codex/"):
            from .codex_native import generate,NativeModelError
            self.active_provider="codex-cli"
            self.active_model=model
            try:
                yield generate(self.config,messages,model,self._delivery,usage_callback=self._usage)
            except (NativeModelError,OSError,ValueError) as exc:
                self.last_error=sanitize_error(exc)
                yield "\nNative Codex turn failed and was not replayed automatically: "+self.last_error+"\n"
            return
        health = self.probe_health()
        pre_send_errors: list[str] = []

        is_chatgpt_web = (
            model.startswith("sentra/chatgpt-web/")
            or model.startswith("chatgpt-web/")
        )
        browser_host_ready = not is_chatgpt_web
        if is_chatgpt_web:
            browser_host_ready = self._browser_host_ready()
            if not browser_host_ready:
                action = (
                    self._spawn_browser_host()
                    if self.config.auto_start_gateway
                    else "auto-start disabled"
                )
                if self.config.auto_start_gateway:
                    browser_host_ready, readiness_detail = (
                        self._wait_browser_host_turn_ready()
                    )
                    if not browser_host_ready:
                        pre_send_errors.append(
                            "chatgpt browser host: "
                            + action
                            + "; "
                            + readiness_detail
                        )
                else:
                    pre_send_errors.append(
                        "chatgpt browser host: " + action
                    )

        if not health["gateway"] and self.config.auto_start_gateway:
            status = self.ensure_gateway_ready()
            health["gateway"] = bool(status["turn_ready"])
            health["gateway_reachable"] = bool(status["reachable"])
            health["gateway_status"] = status

        if health["gateway"] and browser_host_ready:
            self.active_provider = "gateway"
            self.active_model = model
            try:
                yield from self._responses_stream(messages, model)
                self.last_error = None
                return
            except ProviderHTTPError as exc:
                self.last_error = str(exc)
                yield (
                    "\nSENTRA Web turn failed and was not replayed "
                    f"automatically: {exc}\n"
                )
                return
        openai_key = (
            self.config.openai_api_key
            or os.environ.get("OPENAI_API_KEY", "")
        )
        if openai_key:
            self.active_provider = "openai"
            self.active_model = self.config.fallback_model
            try:
                yield from self._chat_completions_stream(
                    self.config.openai_base_url,
                    openai_key,
                    messages,
                    self.config.fallback_model,
                    "openai",
                )
                self.last_error = None
                return
            except ProviderHTTPError as exc:
                if self.last_delivery_state != "rejected":
                    self.last_error = str(exc)
                    yield f"\nOpenAI turn failed and was not replayed automatically: {exc}\n"
                    return
                pre_send_errors.append(str(exc))

        if health["local"]:
            self.active_provider = "local"
            self.active_model = self.config.local_model_name
            try:
                yield from self._chat_completions_stream(
                    self.config.local_base_url,
                    self.config.local_api_key,
                    messages,
                    self.config.local_model_name,
                    "local",
                )
                self.last_error = None
                return
            except ProviderHTTPError as exc:
                pre_send_errors.append(str(exc))

        gateway_status = health.get("gateway_status") or {}
        detail = gateway_status.get("error")
        status_code = gateway_status.get("status_code")
        if not detail and status_code:
            detail = f"HTTP {status_code}"
        message = (
            "Erro de comunicação: não foi possível concluir a chamada. "
            f"Gateway: {detail or 'not ready'}."
        )
        if pre_send_errors:
            message += " Fallbacks: " + " | ".join(pre_send_errors)
        self.last_error = message
        yield "\n" + message + "\n"
