"""Configuration and environment detection for SENTRA CLI."""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

SENTRA_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_GATEWAY = "http://127.0.0.1:17842/v1"


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def default_model(state_root: Path | None = None) -> str:
    configured = os.environ.get("SENTRA_CLI_MODEL", "").strip()
    if configured:
        return configured
    try:
        from sentra_remote.product import ProductPaths, ProductSettings
        install_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SENTRA_ROOT
        settings = (Path(state_root) / "desktop.json" if state_root is not None
                    else ProductPaths.default(install_dir).settings)
        if settings.is_file():
            selected = ProductSettings.load(settings).web_model_name
            if selected:
                return selected
    except (ImportError, OSError, ValueError, RuntimeError, TypeError):
        pass
    from .codex_native import authenticated
    return "sentra/codex/current" if authenticated() else "sentra/chatgpt-web/auto"


def find_maestri_cli() -> str | None:
    """Locate the live Maestri CLI executable without modifying PATH."""
    env_cli = os.environ.get("MAESTRI_CLI")
    if env_cli and Path(env_cli).is_file():
        return str(Path(env_cli).resolve())

    # Prefer the installed Maestri build over PATH: PATH can contain an
    # older unpacked CLI while the live app injects/ships a newer protocol.
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        candidate = (
            Path(local_app_data)
            / "Programs"
            / "Maestri"
            / "resources"
            / "cli"
            / "maestri.exe"
        )
        if candidate.is_file():
            return str(candidate.resolve())

    which_cli = shutil.which("maestri")
    if which_cli and Path(which_cli).is_file():
        return str(Path(which_cli).resolve())
    return None


@dataclass
class CLIConfig:
    workspace: Path = field(
        default_factory=lambda: Path(
            os.environ.get("SENTRA_WORKSPACE") or "."
        ).resolve()
    )
    gateway_url: str = os.environ.get("SENTRA_GATEWAY_URL", _DEFAULT_GATEWAY)
    gateway_api_key: str = os.environ.get(
        "SENTRA_CLI_GATEWAY_API_KEY",
        os.environ.get("SENTRA_CODEX_WEB_API_KEY", "sentra-local"),
    )
    model: str | None = None
    reasoning_effort: str = field(
        default_factory=lambda: os.environ.get("SENTRA_CLI_REASONING_EFFORT", "low").strip().lower()
    )
    fallback_model: str = os.environ.get(
        "SENTRA_CLI_FALLBACK_MODEL", "gpt-4o"
    )
    openai_base_url: str = os.environ.get(
        "OPENAI_BASE_URL", "https://api.openai.com/v1"
    )
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    local_base_url: str = "http://127.0.0.1:11434/v1"
    local_api_key: str = "local"
    local_model_name: str = "qwen2.5:0.5b-instruct-q4_K_M"
    timeout_s: float = 120.0
    gateway_start_timeout_s: float = 120.0
    max_output_tokens: int = 4096
    max_tool_rounds: int = 8
    auto_start_gateway: bool = field(
        default_factory=lambda: _env_bool("SENTRA_CLI_AUTO_START_GATEWAY", True)
    )

    maestri_pipe: str | None = None
    maestri_socket: str | None = None
    maestri_terminal_id: str | None = None
    maestri_workspace_id: str | None = None
    maestri_cli_path: str | None = None

    trust_workspace: bool = True
    use_docker: bool = False
    session_id: str | None = None
    resume_session: bool = False
    state_root: Path | None = None

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).resolve()
        if self.state_root is None:
            configured = os.environ.get("SENTRA_STATE_DIR", "").strip()
            if configured:
                self.state_root = Path(configured).expanduser().resolve()
            elif getattr(sys, "frozen", False):
                from sentra_remote.product import ProductPaths
                self.state_root = ProductPaths.default(Path(sys.executable).resolve().parent).state_dir
            else:
                self.state_root = self.workspace / ".sentra"
        else:
            self.state_root = Path(self.state_root).expanduser().resolve()
        if self.model is None:
            self.model = default_model(self.state_root)
        if self.reasoning_effort not in {"low", "medium", "high", "xhigh"}:
            raise ValueError("reasoning effort must be low, medium, high or xhigh")
        self.maestri_pipe = self.maestri_pipe or os.environ.get("MAESTRI_PIPE")
        self.maestri_socket = (
            self.maestri_socket or os.environ.get("MAESTRI_SOCKET")
        )
        self.maestri_terminal_id = (
            self.maestri_terminal_id
            or os.environ.get("MAESTRI_TERMINAL_ID")
        )
        self.maestri_workspace_id = (
            self.maestri_workspace_id
            or os.environ.get("MAESTRI_WORKSPACE_ID")
        )
        if self.maestri_cli_path is None:
            self.maestri_cli_path = find_maestri_cli()
        self._load_sentra_config()
        self._load_api_key_from_codex_auth()

    def _load_api_key_from_codex_auth(self) -> None:
        """Load only a real API key; never reuse Codex OAuth as OpenAI API auth."""
        if self.openai_api_key == "none":
            self.openai_api_key = ""
            return
        if self.openai_api_key:
            return
        try:
            home = Path(os.environ.get("USERPROFILE") or Path.home())
            auth_json = home / ".codex" / "auth.json"
            if not auth_json.is_file():
                return
            auth_data = json.loads(auth_json.read_text(encoding="utf-8"))
            key = auth_data.get("OPENAI_API_KEY")
            if isinstance(key, str) and key.strip():
                self.openai_api_key = key.strip()
        except (OSError, ValueError, TypeError, RuntimeError):
            return

    def _load_sentra_config(self) -> None:
        config_path = SENTRA_ROOT / "config.yaml"
        if not config_path.is_file():
            return
        try:
            import yaml

            data = yaml.safe_load(
                config_path.read_text(encoding="utf-8")
            ) or {}
            if not isinstance(data, dict):
                return
            local = data.get("local_model", {})
            if isinstance(local, dict):
                self.local_base_url = str(
                    local.get("base_url") or self.local_base_url
                )
                self.local_model_name = str(
                    local.get("model_name") or self.local_model_name
                )
                self.local_api_key = str(
                    local.get("api_key") or self.local_api_key
                )
            codex_web = data.get("codex_web", {})
            if isinstance(codex_web, dict):
                if self.gateway_url == _DEFAULT_GATEWAY:
                    self.gateway_url = str(
                        codex_web.get("base_url") or self.gateway_url
                    )
                if self.gateway_api_key == "sentra-local":
                    self.gateway_api_key = str(
                        codex_web.get("api_key") or self.gateway_api_key
                    )
        except Exception:
            return

    @property
    def gateway_admin_tokens(self) -> tuple[str, ...]:
        """Known admin tokens in authority order, for state-root migration."""
        env_token = os.environ.get("SENTRA_GATEWAY_ADMIN_TOKEN", "").strip()
        if env_token:
            return (env_token,)

        candidates: list[Path] = []
        try:
            from sentra_remote.product import ProductPaths

            install_root = (
                Path(sys.executable).resolve().parent
                if getattr(sys, "frozen", False)
                else SENTRA_ROOT
            )
            candidates.append(
                ProductPaths.default(install_root).state_dir
                / "web-models"
                / "gateway-admin.token"
            )
        except (ImportError, OSError, RuntimeError):
            pass

        try:
            home = Path(os.environ.get("USERPROFILE") or Path.home())
            candidates.append(
                home / ".sentra" / "web-models" / "gateway-admin.token"
            )
        except RuntimeError:
            pass

        seen_paths: set[Path] = set()
        seen_tokens: set[str] = set()
        tokens: list[str] = []
        for token_path in candidates:
            try:
                resolved = token_path.expanduser().resolve()
            except OSError:
                continue
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            try:
                token = resolved.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if token and token not in seen_tokens:
                seen_tokens.add(token)
                tokens.append(token)
        return tuple(tokens)

    @property
    def gateway_admin_token(self) -> str:
        tokens = self.gateway_admin_tokens
        return tokens[0] if tokens else ""

    @property
    def maestri_transport(self) -> str | None:
        return self.maestri_pipe or self.maestri_socket

    @property
    def is_in_maestri(self) -> bool:
        return bool(self.maestri_terminal_id and self.maestri_transport)
