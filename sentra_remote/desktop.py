"""SENTRA Desktop: operational UI + tray for installed Windows product."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import tomllib
import webbrowser
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Any

from sentra_version import PRODUCT_VERSION

from .agent import pair_agent
from .onboarding import (
    OPENAI_API_KEYS_URL,
    OPENAI_TUNNELS_URL,
    CHATGPT_PLUGINS_HOME_URL,
    chatgpt_plugin_install_plan,
    build_onboarding_snapshot,
    tutorial_video_path,
)
from .local_runtime import LocalRuntime
from .setup_assistant import SetupAssistant, first_workspace
from .product import (
    PROFILE_POLICIES,
    ProductPaths,
    ProductSettings,
    agent_bootstrap_root,
    configure_tunnel,
    create_snapshot,
    enqueue_task,
    git_diff,
    list_recent_jobs,
    list_snapshots,
    list_tasks,
    load_tunnel_config,
    rollback_snapshot,
    run_next_task,
    sync_agent_policy,
    sync_workspace_registry,
    tail_audit,
)
from .updater import (
    apply_prepared_update,
    fetch_manifest,
    is_newer_version,
    prepare_update,
    rollback_previous_update,
)

def _install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _codex_route_points_to_sentra(config_path: Path | None = None) -> bool:
    """Detect a persisted Codex route that would otherwise point at a dead Gateway."""
    path = config_path
    if path is None:
        codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
        path = codex_home / "config.toml"
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return False
    route = str(data.get("openai_base_url") or "").rstrip("/")
    return route == "http://127.0.0.1:17842/v1"


def _validated_web_models_launcher(install_dir: Path) -> Path:
    install_dir = Path(install_dir).resolve()
    packaged_root = install_dir / "web-models"
    if not packaged_root.is_dir():
        packaged_root = install_dir / "dist" / "web-models"

    launcher = packaged_root / "win-unpacked" / "Codex Web GPT.exe"
    if not launcher.is_file():
        raise RuntimeError("Web Models payload is missing; rebuild the Codex Web integration")

    build_state_path = packaged_root / "integration-build.json"
    if not build_state_path.is_file():
        raise RuntimeError("Web Models integration build metadata is missing")
    try:
        build_state = json.loads(build_state_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Web Models integration build metadata is invalid") from exc

    source_patch = install_dir / "integrations" / "codex_chatgpt_web" / "sentra-upstream.patch"
    packaged_patch = packaged_root / "licenses" / "codex-chatgpt-web" / "sentra-upstream.patch"
    reference_patch = source_patch if source_patch.is_file() else packaged_patch
    if not reference_patch.is_file():
        raise RuntimeError("Web Models integration patch provenance is missing")

    patch_hash = hashlib.sha256(reference_patch.read_bytes()).hexdigest()
    if str(build_state.get("patch_sha256") or "").lower() != patch_hash:
        raise RuntimeError(
            "Web Models payload is stale; rebuild scripts/integrations/Build-CodexChatGPTWebRuntime.ps1"
        )

    source_manifest = install_dir / "integrations" / "codex_chatgpt_web" / "upstream.json"
    if source_manifest.is_file():
        try:
            manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
            expected_files = sorted(str(item) for item in manifest.get("patch_files", []))
            built_files = sorted(str(item) for item in build_state.get("patch_files", []))
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("Web Models integration manifest is invalid") from exc
        if built_files != expected_files:
            raise RuntimeError("Web Models payload patch file set is stale; rebuild the integration")

    return launcher


def _run_hidden(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _quick_start_state(status: dict[str, Any], *, has_tunnel: bool) -> tuple[int, str, str]:
    """Render the shared product-onboarding contract for the Desktop."""
    existing = status.get("onboarding")
    if isinstance(existing, dict) and existing.get("stage"):
        stage = str(existing.get("stage"))
        title = str(existing.get("title") or stage.replace("_", " ").title())
        detail = str(existing.get("detail") or "")
    else:
        normalized = dict(status)
        tunnel = dict(normalized.get("tunnel") or {})
        tunnel["configured"] = bool(
            tunnel.get("configured") or has_tunnel
        )
        normalized["tunnel"] = tunnel
        credentials = dict(normalized.get("credential_storage") or {})
        if has_tunnel:
            credentials.setdefault("configured", True)
        normalized["credential_storage"] = credentials
        snapshot = build_onboarding_snapshot(normalized)
        stage = snapshot.stage
        title = snapshot.title
        detail = snapshot.detail

    if stage == "CONNECT_OPENAI":
        status_credentials = status.get("credential_storage")
        status_credentials = (
            status_credentials
            if isinstance(status_credentials, dict)
            else {}
        )
        status_tunnel = status.get("tunnel")
        status_tunnel = status_tunnel if isinstance(status_tunnel, dict) else {}
        reconnect = bool(
            status_tunnel.get("reauth_required")
            or (
                status_credentials.get("configured")
                and status_credentials.get("ok") is not True
            )
        )
        progress = 45 if reconnect else 35
        if reconnect:
            title = "Reconnect OpenAI"
    else:
        progress = {
            "START_SENTRA": 70,
            "READY": 100,
        }.get(stage, 50)
    if stage == "READY":
        title = "Ready"
    return progress, title, detail


def _internal_deep_link_target(value: str) -> str | None:
    """Resolve only SENTRA-owned navigation links; reject arbitrary URLs."""
    normalized = str(value or "").strip().rstrip("/").lower()
    return {
        "sentra://home": "status",
        "sentra://status": "status",
        "sentra://onboarding": "onboarding",
        "sentra://web-models": "web_models",
        "sentra://openai-enroll": "openai_enroll",
    }.get(normalized)


class SentraDesktop:
    def __init__(
        self,
        *,
        start_hidden: bool = False,
        initial_view: str | None = None,
    ) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = tk.Tk()
        self.root.title(f"SENTRA Desktop {PRODUCT_VERSION}")
        self.root.geometry("1060x760")
        self.root.minsize(900, 650)
        self.paths = ProductPaths.default(_install_dir())
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        self.settings = ProductSettings.load(self.paths.settings)
        # Never grant the entire home directory: only a SENTRA-owned starter folder.
        first_workspace(self.paths, self.settings)
        self.runtime = LocalRuntime(self.paths, self.settings)
        self.setup_assistant = SetupAssistant(self.paths, self.settings, self.runtime)
        self.web_gateway = None
        self.web_gateway_thread = None
        self.status_labels: dict[str, Any] = {}
        self.tray_icon = None
        self._closing = False
        self._refreshing = False
        self.advanced_visible = False
        self.remote_relay_var = self.tk.StringVar()
        self.remote_code_var = self.tk.StringVar()
        self._build()
        if initial_view == "web_models" and not self.advanced_visible:
            self._toggle_advanced_tabs()
        initial_tabs = {
            "status": self.dashboard,
            "onboarding": self.onboarding_tab,
            "web_models": self.web_models_tab,
        }
        if initial_view in initial_tabs:
            self.tabs.select(initial_tabs[initial_view])
        if initial_view == "openai_enroll":
            self.tabs.select(self.onboarding_tab)
            # Consume installer authorization; deep links alone grant nothing.
            self.root.after(900, self.start_openai_browser_enrollment)
        self._start_tray()
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        if start_hidden and initial_view is None:
            self.root.withdraw()
        self.root.after(300, self._autostart)
        self.root.after(1000, self.refresh_async)

    def _build(self) -> None:
        ttk = self.ttk
        header = ttk.Frame(self.root, padding=12)
        header.pack(fill="x")
        ttk.Label(header, text="SENTRA Desktop", font=("Segoe UI", 18, "bold")).pack(side="left")
        self.version_label = ttk.Label(header, text=f"v{PRODUCT_VERSION}")
        self.version_label.pack(side="left", padx=8)
        self.advanced_button = ttk.Button(
            header, text="Show advanced", command=self._toggle_advanced_tabs
        )
        self.advanced_button.pack(side="right", padx=3)
        ttk.Button(header, text="Doctor", command=self.show_doctor).pack(side="right", padx=3)
        ttk.Button(header, text="Start", command=self.start_services).pack(side="right", padx=3)

        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.dashboard = ttk.Frame(self.tabs, padding=12)
        self.settings_tab = ttk.Frame(self.tabs, padding=12)
        self.activity_tab = ttk.Frame(self.tabs, padding=12)
        self.audit_tab = ttk.Frame(self.tabs, padding=12)
        self.onboarding_tab = ttk.Frame(self.tabs, padding=12)
        self.web_models_tab = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(self.onboarding_tab, text="Quick Start")
        self.tabs.add(self.dashboard, text="Status")
        self._build_dashboard()
        self._build_settings()
        self._build_activity()
        self._build_audit()
        self._build_onboarding()
        self._build_web_models()
        self.tabs.select(self.onboarding_tab)
        web_models_enabled = (self.paths.state_dir / "web-models-enabled").is_file()
        # Crash/restart recovery: if Codex still points at :17842, revive the
        # Gateway even when the UI marker was lost. This prevents a persisted
        # route from becoming WinError 10061 after a SENTRA Desktop restart.
        if web_models_enabled or _codex_route_points_to_sentra():
            self.root.after(3000, lambda: self.start_web_models(hidden=True))

    def _toggle_advanced_tabs(self) -> None:
        advanced = (
            (self.settings_tab, "Workspaces & Policy"),
            (self.activity_tab, "Jobs & Queue"),
            (self.audit_tab, "Audit / Diff / Snapshots"),
            (self.web_models_tab, "Web Models"),
        )
        if self.advanced_visible:
            for tab, _label in advanced:
                try:
                    self.tabs.forget(tab)
                except self.tk.TclError:
                    pass
            self.advanced_visible = False
            self.advanced_button.configure(text="Show advanced")
            self.tabs.select(self.onboarding_tab)
            return
        for tab, label in advanced:
            self.tabs.add(tab, text=label)
        self.advanced_visible = True
        self.advanced_button.configure(text="Hide advanced")

    def _build_web_models(self) -> None:
        ttk = self.ttk
        ttk.Label(self.web_models_tab, text="ChatGPT Web via SENTRA Model Gateway", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(
            self.web_models_tab,
            text=("Uso normal: 1) Abrir interface Web e concluir o login; 2) Conectar Codex; "
                  "3) reiniciar o Codex; 4) Verificar conexões. O Codex deve apontar para o "
                  "Gateway SENTRA em 127.0.0.1:17842/v1, nunca diretamente para o sidecar :17841."),
            wraplength=900,
        ).pack(anchor="w", pady=8)
        controls = ttk.Frame(self.web_models_tab)
        controls.pack(anchor="w", pady=8)
        ttk.Button(controls, text="Abrir interface Web", command=self.start_web_models).pack(side="left", padx=3)
        ttk.Button(controls, text="Conectar Codex", command=self.connect_web_models_codex).pack(side="left", padx=3)
        ttk.Button(controls, text="Desconectar Codex", command=self.disconnect_web_models_codex).pack(side="left", padx=3)
        ttk.Button(controls, text="Verificar conexões", command=self.verify_web_models).pack(side="left", padx=3)
        ttk.Button(controls, text="Drain", command=lambda: self.drain_web_models(False)).pack(side="left", padx=3)
        ttk.Button(controls, text="Resume", command=lambda: self.drain_web_models(True)).pack(side="left", padx=3)
        ttk.Button(controls, text="Stop managed launcher", command=self.stop_web_models).pack(side="left", padx=3)
        ttk.Button(controls, text="Refresh", command=self.refresh_web_models).pack(side="left", padx=3)

        model_row = ttk.Frame(self.web_models_tab)
        model_row.pack(fill="x", pady=(4, 8))
        ttk.Label(model_row, text="Modelo Web padrão do SENTRA/OMA").pack(side="left", padx=(0, 8))
        self.web_model_var = self.tk.StringVar(value=self.settings.web_model_name)
        self.web_model_catalog_values: tuple[str, ...] = ()
        self.web_model_picker = ttk.Combobox(
            model_row,
            textvariable=self.web_model_var,
            values=(),
            state="readonly",
            width=48,
        )
        self.web_model_picker.pack(side="left", padx=3)
        ttk.Button(model_row, text="Usar seleção", command=self.save_web_model_selection).pack(side="left", padx=3)
        self.web_model_default = ttk.Label(
            self.web_models_tab,
            text=(
                f"Padrão salvo: {self.settings.web_model_name}"
                if self.settings.web_model_name
                else "Padrão salvo: nenhum · selecione um modelo anunciado pelo Gateway"
            ),
            wraplength=900,
        )
        self.web_model_default.pack(anchor="w", pady=(0, 4))

        self.web_models_status = ttk.Label(self.web_models_tab, text="Gateway: checking…")
        self.web_models_status.pack(anchor="w", pady=8)
        self.web_models_route = ttk.Label(self.web_models_tab, text="Codex: aguardando verificação")
        self.web_models_route.pack(anchor="w", pady=4)
        self.web_models_checks = ttk.Label(self.web_models_tab, text="Login e conector: verifique na interface Web", wraplength=900)
        self.web_models_checks.pack(anchor="w", pady=4)
        self.web_models_catalog = self.tk.Text(self.web_models_tab, height=14, wrap="word")
        self.web_models_catalog.pack(fill="both", expand=True)
        self.web_models_catalog.insert("1.0", "O catálogo aparecerá quando o launcher estiver pronto.")
        self.web_models_catalog.configure(state="disabled")
        self.root.after(1200, self.refresh_web_models)

    def _set_web_models_status(self, status: str, catalog: list[str] | None = None) -> None:
        if self._closing:
            return
        self.web_models_status.configure(text=status)
        if catalog is not None:
            self.web_models_catalog.configure(state="normal")
            self.web_models_catalog.delete("1.0", "end")
            self.web_models_catalog.insert("1.0", "\n".join(catalog) or "Nenhum modelo Web anunciado.")
            self.web_models_catalog.configure(state="disabled")
            self.web_model_catalog_values = tuple(catalog)
            self.web_model_picker.configure(values=self.web_model_catalog_values)
            selected = self.web_model_var.get().strip()
            saved = self.settings.web_model_name.strip()
            if saved in catalog:
                self.web_model_var.set(saved)
            elif selected not in catalog:
                self.web_model_var.set(catalog[0] if catalog else "")
            # Pick a verified advertised model on first run. Never switch a
            # previously selected model or reroute an active Codex session.
            if not saved and catalog:
                self.settings.web_model_name = catalog[0]
                self.settings.save(self.paths.settings)
                saved = catalog[0]
            if saved and saved not in catalog:
                self.web_model_default.configure(
                    text=f"Padrão salvo indisponível no catálogo atual: {saved}"
                )
            elif saved:
                self.web_model_default.configure(text=f"Padrão salvo: {saved}")
            else:
                self.web_model_default.configure(
                    text="Padrão salvo: nenhum · a seleção acima ainda não foi persistida"
                )

    def _web_gateway_admin_token(self) -> str:
        from sentra_model_gateway.gateway import load_or_create_gateway_admin_token

        if self.web_gateway is not None and self.web_gateway.admin_token:
            return str(self.web_gateway.admin_token)
        return load_or_create_gateway_admin_token(self.paths.state_dir)

    def _web_gateway_admin_json(
        self,
        path: str,
        *,
        method: str = "GET",
        timeout: float = 8.0,
    ) -> dict[str, Any]:
        request = Request(
            "http://127.0.0.1:17842" + path,
            data=b"" if method == "POST" else None,
            method=method,
            headers={"Authorization": f"Bearer {self._web_gateway_admin_token()}"},
        )
        with urlopen(request, timeout=timeout) as response:
            value = json.load(response)
        if not isinstance(value, dict):
            raise ValueError("Gateway returned an invalid JSON object")
        return value

    def save_web_model_selection(self) -> None:
        from tkinter import messagebox

        model = self.web_model_var.get().strip()
        allowed_prefixes = ("sentra/chatgpt-web/", "sentra/gemini-web/")
        if not model.startswith(allowed_prefixes) or model not in self.web_model_catalog_values:
            messagebox.showerror(
                "SENTRA Web Models",
                "Selecione um modelo Web anunciado pelo Gateway SENTRA.",
            )
            return
        self.settings.web_model_name = model
        self.settings.save(self.paths.settings)
        os.environ["SENTRA_CODEX_WEB_MODEL"] = model
        self.web_model_default.configure(text=f"Padrão salvo: {model}")
        messagebox.showinfo(
            "SENTRA Web Models",
            "Modelo padrão salvo. Novas instâncias do OMA usarão esta seleção quando "
            "config.yaml não definir um model_name explícito.",
        )

    def refresh_web_models(self) -> None:
        def worker() -> None:
            try:
                with urlopen("http://127.0.0.1:17842/healthz", timeout=2) as response:
                    health = json.load(response)

                models = self._web_gateway_admin_json(
                    "/sentra/model-catalog",
                    timeout=4,
                )

                allowed_prefixes = ("sentra/chatgpt-web/", "sentra/gemini-web/")
                catalog = [
                    str(model.get("slug") or model.get("id"))
                    for model in (models.get("models") or [])
                    if (
                        isinstance(model, dict)
                        and str(model.get("slug") or model.get("id") or "").startswith(allowed_prefixes)
                    )
                ]
                version = health.get("upstream", {}).get("version", "?")
                catalog_status = str(models.get("status") or "")
                status_text = (
                    f"Gateway ready · upstream {version} · {len(catalog)} modelos Web"
                    if catalog
                    else (
                        f"Gateway ready · upstream {version} · aguardando catálogo autenticado do Codex"
                        if catalog_status == "awaiting_codex_catalog"
                        else f"Gateway ready · upstream {version} · catálogo Web vazio"
                    )
                )
                route_text = "Codex: rota não verificada"
                try:
                    route = self._web_gateway_admin_json("/sentra/codex/status")
                    if route.get("points_to_sentra"):
                        route_text = "Codex: conectado ao Gateway SENTRA"
                    elif route.get("installed") and route.get("active"):
                        route_text = "Codex: rota ativa aponta fora do SENTRA · clique Conectar Codex para migrar"
                    else:
                        route_text = "Codex: conclua o setup na interface Web e clique Conectar Codex"
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    route_text = f"Codex: rota ainda não verificada ({type(exc).__name__})"
                self.root.after(0, lambda: self.web_models_route.configure(text=route_text))
                self.root.after(0, lambda: self._set_web_models_status(status_text, catalog))
            except (OSError, ValueError) as exc:
                self.root.after(0, lambda: self._set_web_models_status(f"Gateway offline: {type(exc).__name__}"))
        threading.Thread(target=worker, daemon=True).start()

    def connect_web_models_codex(self) -> None:
        def worker() -> None:
            try:
                route = self._web_gateway_admin_json(
                    "/sentra/codex/connect",
                    method="POST",
                )
                if not route.get("points_to_sentra"):
                    raise RuntimeError("O Codex ainda não aponta para o Gateway SENTRA")
                self.root.after(0, lambda: self.web_models_route.configure(
                    text="Codex: conectado ao Gateway SENTRA · reinicie o Codex para atualizar os modelos"))
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                self.root.after(0, lambda: self.web_models_route.configure(text=f"Codex: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def disconnect_web_models_codex(self) -> None:
        def worker() -> None:
            try:
                route = self._web_gateway_admin_json(
                    "/sentra/codex/disconnect",
                    method="POST",
                )
                active = bool(route.get("active"))
                text = ("Codex: rota anterior restaurada · reinicie o Codex" if not active
                        else "Codex: integração Web desativada · reinicie o Codex")
                self.root.after(0, lambda: self.web_models_route.configure(text=text))
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                self.root.after(0, lambda: self.web_models_route.configure(text=f"Codex: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def verify_web_models(self) -> None:
        def worker() -> None:
            try:
                report = self._web_gateway_admin_json(
                    "/sentra/doctor?verify_connector=1",
                    timeout=15,
                )
                route = self._web_gateway_admin_json("/sentra/codex/status")
                checks = report.get("checks", [])
                summary = " · ".join(
                    f"{item.get('id', 'check')}: {item.get('status', '?')}"
                    for item in checks if isinstance(item, dict)
                )
                route_ok = bool(route.get("installed") and route.get("active") and route.get("points_to_sentra"))
                text = ("Conexões verificadas" if report.get("ok") and route_ok else "Conexões precisam de atenção")
                route_state = "codex-route: ok" if route_ok else "codex-route: fora do SENTRA"
                self.root.after(0, lambda: self.web_models_checks.configure(
                    text=f"{text} · {route_state}" + (f" · {summary}" if summary else "")
                ))
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                self.root.after(0, lambda: self.web_models_checks.configure(text=f"Verificação falhou: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def start_web_models(self, *, hidden: bool = False) -> None:
        def worker() -> None:
            try:
                from sentra_model_gateway.gateway import (
                    GatewayConfig,
                    GatewayServer,
                    load_or_create_gateway_admin_token,
                )
                if self.web_gateway is None:
                    install_dir = _install_dir()
                    checkout = install_dir / "third_party" / "codex-chatgpt-web"
                    packaged = _validated_web_models_launcher(install_dir)
                    admin_token = (
                        os.environ.get("SENTRA_GATEWAY_ADMIN_TOKEN", "").strip()
                        or load_or_create_gateway_admin_token(self.paths.state_dir)
                    )
                    os.environ["SENTRA_GATEWAY_ADMIN_TOKEN"] = admin_token
                    config = GatewayConfig(checkout=checkout,
                                           launcher_executable=packaged if packaged.is_file() else None,
                                           state_root=self.paths.state_dir,
                                           admin_token=admin_token,
                                           upstream_control_token=os.environ.get("SENTRA_WEB_CONTROL_TOKEN", ""),
                                           connector_name=os.environ.get("SENTRA_CONNECTOR_NAME", "SENTRA tunnel"))
                    gateway = GatewayServer(config)
                    self.web_gateway = gateway
                    self.web_gateway_thread = threading.Thread(target=gateway.serve_forever, daemon=True)
                    self.web_gateway_thread.start()
                self.web_gateway.launcher.start(hidden=hidden)
                if not hidden:
                    (self.paths.state_dir / "web-models-enabled").write_text("enabled\n", encoding="utf-8")
                self.root.after(0, lambda: self._set_web_models_status("Launcher iniciado; aguardando login/runtime…"))
                self.root.after(3000, self.refresh_web_models)
            except (OSError, ValueError, RuntimeError) as exc:
                cleanup = self._cleanup_failed_web_models_start()
                suffix = f" · {cleanup}" if cleanup else ""
                message = f"Falha ao iniciar Web Models: {exc}{suffix}"

                def show_failure() -> None:
                    self._set_web_models_status(message)

                self.root.after(0, show_failure)
        threading.Thread(target=worker, daemon=True).start()

    def _cleanup_failed_web_models_start(self) -> str:
        """Rollback Codex routing and tear down a partially started Gateway."""
        gateway = self.web_gateway
        if gateway is None:
            return ""
        notes: list[str] = []
        restored, detail = self._restore_codex_route_before_gateway_stop()
        if restored:
            notes.append("rota Codex restaurada")
        elif detail:
            notes.append(f"rollback da rota falhou: {detail}")
        try:
            gateway.launcher.stop()
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as stop_exc:
            notes.append(f"launcher cleanup: {type(stop_exc).__name__}")
        try:
            gateway.shutdown()
            gateway.server_close()
        except OSError as close_exc:
            notes.append(f"gateway cleanup: {type(close_exc).__name__}")
        finally:
            self.web_gateway = None
            self.web_gateway_thread = None
        return " · ".join(notes)

    def _restore_codex_route_before_gateway_stop(self) -> tuple[bool, str]:
        if self.web_gateway is None:
            return True, ""
        try:
            route = self.web_gateway.launcher.route("status")
            if not route.get("points_to_sentra"):
                return True, ""
            restored = self.web_gateway.launcher.route("disconnect")
            if restored.get("points_to_sentra"):
                return False, "Codex permaneceu apontando para o Gateway SENTRA"
            return True, ""
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)[:300]

    def stop_web_models(self) -> None:
        def worker() -> None:
            if self.web_gateway is not None:
                # Never leave Codex persisted on :17842 after its owner is gone.
                # If rollback cannot be confirmed, keep the Gateway alive.
                restored, detail = self._restore_codex_route_before_gateway_stop()
                if not restored:
                    self.root.after(0, lambda: self._set_web_models_status(
                        "Stop recusado: não foi possível restaurar a rota do Codex"
                        + (f" · {detail}" if detail else "")
                    ))
                    return
                self.web_gateway.launcher.stop()
                self.web_gateway.shutdown()
                self.web_gateway.server_close()
                self.web_gateway = None
                (self.paths.state_dir / "web-models-enabled").unlink(missing_ok=True)
                self.root.after(0, lambda: self._set_web_models_status(
                    "Launcher gerenciado encerrado · Codex restaurado para a rota anterior"
                ))
        threading.Thread(target=worker, daemon=True).start()

    def drain_web_models(self, resume: bool) -> None:
        def worker() -> None:
            try:
                token = self.web_gateway.admin_token if self.web_gateway is not None else ""
                if not token:
                    raise ValueError("Gateway admin token is unavailable; start Web Models first")
                action = "resume" if resume else "drain"
                request = Request(
                    f"http://127.0.0.1:17842/sentra/upstream/{action}",
                    data=b"", method="POST",
                    headers={"Authorization": f"Bearer {token}"},
                )
                with urlopen(request, timeout=8) as response:
                    result = json.load(response)
                accepting = result.get("accepting_turns") is True
                self.root.after(0, lambda: self._set_web_models_status(
                    "Upstream aceitando turnos" if accepting else "Upstream em drain"
                ))
            except (OSError, ValueError) as exc:
                self.root.after(0, lambda: self._set_web_models_status(f"Drain/resume falhou: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def _build_dashboard(self) -> None:
        ttk = self.ttk
        cards = ttk.Frame(self.dashboard)
        cards.pack(fill="x")
        for index, name in enumerate(("MCP", "Tunnel", "Edge", "Sandbox", "Git", "Remote")):
            frame = ttk.LabelFrame(cards, text=name, padding=12)
            frame.grid(row=0, column=index, sticky="nsew", padx=4, pady=4)
            cards.columnconfigure(index, weight=1)
            label = ttk.Label(frame, text="checking…", font=("Segoe UI", 11, "bold"))
            label.pack()
            self.status_labels[name.lower()] = label
        self.profile_status = ttk.Label(self.dashboard, text="")
        self.profile_status.pack(anchor="w", pady=(12, 4))
        self.workspace_status = ttk.Label(self.dashboard, text="")
        self.workspace_status.pack(anchor="w", pady=4)
        self.update_status = ttk.Label(self.dashboard, text="Update: not checked")
        self.update_status.pack(anchor="w", pady=4)
        updates = ttk.Frame(self.dashboard)
        updates.pack(anchor="w", pady=4)
        ttk.Button(updates, text="Check for update", command=self.check_update).pack(side="left", padx=(0, 4))
        ttk.Button(updates, text="Rollback previous version", command=self.rollback_version).pack(side="left")
        self.last_errors = self.tk.Text(self.dashboard, height=12, wrap="word")
        self.last_errors.pack(fill="both", expand=True, pady=(12, 0))
        self.last_errors.insert("1.0", "Recent errors will appear here.")
        self.last_errors.configure(state="disabled")

    def _build_settings(self) -> None:
        ttk = self.ttk
        top = ttk.Frame(self.settings_tab)
        top.pack(fill="x")
        ttk.Label(top, text="Profile:").pack(side="left")
        self.profile_var = self.tk.StringVar(value=self.settings.profile)
        self.profile_box = ttk.Combobox(
            top, textvariable=self.profile_var, values=list(PROFILE_POLICIES), state="readonly", width=18
        )
        self.profile_box.pack(side="left", padx=8)
        ttk.Label(top, text="Filesystem access:").pack(side="left", padx=(18, 0))
        self.access_scope_var = self.tk.StringVar(value=self.settings.access_scope)
        self.access_scope_box = ttk.Combobox(
            top,
            textvariable=self.access_scope_var,
            values=("workspace", "user", "computer"),
            state="readonly",
            width=12,
        )
        self.access_scope_box.pack(side="left", padx=8)
        ttk.Button(top, text="Save policy", command=self.save_policy).pack(side="left")
        ttk.Label(
            self.settings_tab,
            text=("Profiles control tools/processes. Filesystem access is separate: "
                  "workspace = approved folders only; user = your Windows user tree; "
                  "computer = every accessible local/mapped drive. Safe remains read-only."),
            wraplength=900,
        ).pack(anchor="w", pady=8)
        ttk.Label(self.settings_tab, text="Allowed workspaces", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.workspace_list = self.tk.Listbox(self.settings_tab, height=12)
        self.workspace_list.pack(fill="both", expand=True, pady=6)
        self.workspace_list.bind("<<ListboxSelect>>", self._load_workspace_permissions)
        controls = ttk.Frame(self.settings_tab)
        controls.pack(fill="x")
        ttk.Button(controls, text="Add folder", command=self.add_workspace).pack(side="left", padx=3)
        ttk.Button(controls, text="Remove selected", command=self.remove_workspace).pack(side="left", padx=3)
        self.ws_read = self.tk.BooleanVar(value=True)
        self.ws_write = self.tk.BooleanVar(value=True)
        self.ws_execute = self.tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="Read", variable=self.ws_read).pack(side="left", padx=(14, 2))
        ttk.Checkbutton(controls, text="Write", variable=self.ws_write).pack(side="left", padx=2)
        ttk.Checkbutton(controls, text="Execute", variable=self.ws_execute).pack(side="left", padx=2)
        ttk.Button(controls, text="Apply permissions", command=self.apply_workspace_permissions).pack(side="left", padx=3)
        ttk.Button(controls, text="Restart with policy", command=self.restart_services).pack(side="right", padx=3)
        dependencies = ttk.LabelFrame(self.settings_tab, text="Optional tools — install only when needed", padding=8)
        dependencies.pack(fill="x", pady=(10, 4))
        ttk.Button(dependencies, text="Install Git", command=lambda: self.install_dependency("git")).pack(side="left", padx=3)
        ttk.Button(dependencies, text="Install Docker Desktop", command=lambda: self.install_dependency("docker")).pack(side="left", padx=3)
        ttk.Button(dependencies, text="Install Ollama", command=lambda: self.install_dependency("ollama")).pack(side="left", padx=3)
        ttk.Button(dependencies, text="Download local AI model", command=self.download_local_model).pack(side="left", padx=3)
        ttk.Label(
            dependencies,
            text="Requires confirmation. A working Docker daemon is mandatory for sandboxed tasks.",
            wraplength=475,
        ).pack(side="left", padx=9)
        ttk.Label(self.settings_tab, text="Optional custom tool allowlist (one tool name per line)").pack(anchor="w", pady=(14, 4))
        self.tools_text = self.tk.Text(self.settings_tab, height=8)
        self.tools_text.pack(fill="x")
        self.tools_text.insert("1.0", "\n".join(self.settings.tool_allowlist))
        remote = ttk.LabelFrame(self.settings_tab, text="Optional Remote Agent pairing", padding=8)
        remote.pack(fill="x", pady=(12, 0))
        ttk.Label(remote, text="Relay URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(remote, textvariable=self.remote_relay_var).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(remote, text="Pairing code").grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Entry(remote, textvariable=self.remote_code_var, width=18).grid(row=0, column=3, sticky="ew", padx=4)
        ttk.Button(remote, text="Pair this device", command=self.pair_remote).grid(row=0, column=4, padx=4)
        remote.columnconfigure(1, weight=2)
        remote.columnconfigure(3, weight=1)
        self._refresh_workspaces()

    def _build_activity(self) -> None:
        ttk = self.ttk
        pane = ttk.Panedwindow(self.activity_tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        jobs = ttk.LabelFrame(pane, text="MCP jobs", padding=6)
        queue = ttk.LabelFrame(pane, text="Persistent OMA queue", padding=6)
        pane.add(jobs, weight=1)
        pane.add(queue, weight=1)
        self.jobs_tree = ttk.Treeview(jobs, columns=("op", "state", "workspace"), show="headings", height=9)
        for col, title in (("op", "Operation"), ("state", "State"), ("workspace", "Workspace")):
            self.jobs_tree.heading(col, text=title)
        self.jobs_tree.pack(fill="both", expand=True)
        self.queue_tree = ttk.Treeview(queue, columns=("id", "state", "workspace", "prompt"), show="headings", height=8)
        for col, title in (("id", "ID"), ("state", "State"), ("workspace", "Workspace"), ("prompt", "Prompt")):
            self.queue_tree.heading(col, text=title)
        self.queue_tree.pack(fill="both", expand=True)
        form = ttk.Frame(queue)
        form.pack(fill="x", pady=6)
        self.queue_workspace = self.tk.StringVar()
        self.queue_prompt = self.tk.StringVar()
        ttk.Entry(form, textvariable=self.queue_workspace, width=35).pack(side="left", padx=3)
        ttk.Entry(form, textvariable=self.queue_prompt).pack(side="left", fill="x", expand=True, padx=3)
        ttk.Button(form, text="Browse", command=self.choose_queue_workspace).pack(side="left", padx=3)
        ttk.Button(form, text="Enqueue", command=self.add_queue_task).pack(side="left", padx=3)
        ttk.Button(form, text="Run next", command=self.run_queue_next).pack(side="left", padx=3)

    def _build_audit(self) -> None:
        ttk = self.ttk
        controls = ttk.Frame(self.audit_tab)
        controls.pack(fill="x")
        self.audit_workspace = self.tk.StringVar()
        ttk.Entry(controls, textvariable=self.audit_workspace).pack(side="left", fill="x", expand=True, padx=3)
        ttk.Button(controls, text="Browse", command=self.choose_audit_workspace).pack(side="left", padx=3)
        ttk.Button(controls, text="Git diff", command=self.show_diff).pack(side="left", padx=3)
        ttk.Button(controls, text="Snapshot", command=self.snapshot).pack(side="left", padx=3)
        ttk.Button(controls, text="Rollback snapshot", command=self.rollback).pack(side="left", padx=3)
        self.audit_text = self.tk.Text(self.audit_tab, wrap="none")
        self.audit_text.pack(fill="both", expand=True, pady=8)

    def _build_onboarding(self) -> None:
        ttk = self.ttk
        ttk.Label(
            self.onboarding_tab, text="Quick Start", font=("Segoe UI", 16, "bold")
        ).pack(anchor="w")
        ttk.Label(
            self.onboarding_tab,
            text="SENTRA works locally first. Connect ChatGPT, Web Models or Edge only when your task needs them.",
            wraplength=900,
        ).pack(anchor="w", pady=(4, 12))

        self.quick_progress = ttk.Progressbar(self.onboarding_tab, maximum=100, mode="determinate")
        self.quick_progress.pack(fill="x", pady=(0, 6))
        self.quick_status = ttk.Label(
            self.onboarding_tab, text="Checking readiness…", font=("Segoe UI", 12, "bold")
        )
        self.quick_status.pack(anchor="w")
        self.quick_detail = ttk.Label(self.onboarding_tab, text="", wraplength=900)
        self.quick_detail.pack(anchor="w", pady=(2, 6))
        self.start_with_windows = self.tk.BooleanVar(value=self.settings.autostart_desktop)
        ttk.Checkbutton(
            self.onboarding_tab,
            text="Start SENTRA automatically when I sign in to Windows",
            variable=self.start_with_windows,
            command=self.save_start_with_windows,
        ).pack(anchor="w", pady=(2, 8))
        ttk.Button(
            self.onboarding_tab,
            text="Guided ChatGPT connection — videos and quick setup",
            command=self.open_chatgpt_wizard,
        ).pack(anchor="w", pady=(0, 10))
        start_here = ttk.LabelFrame(self.onboarding_tab, text="Start here — no account required", padding=10)
        start_here.pack(fill="x", pady=(4, 10))
        ttk.Button(start_here, text="Open SENTRA Terminal", command=self.open_terminal).pack(side="left", padx=3)
        ttk.Button(start_here, text="Open starter project", command=self.open_starter_project).pack(side="left", padx=3)
        ttk.Button(start_here, text="Add an existing project", command=self.add_workspace).pack(side="left", padx=3)
        ttk.Button(start_here, text="Repair local runtime", command=self.repair_local).pack(side="right", padx=3)
        ttk.Label(
            self.onboarding_tab,
            text="Local MCP needs no OpenAI key. Secure MCP Tunnel is optional and uses a key with All permissions protected by Windows DPAPI.",
            wraplength=900,
        ).pack(anchor="w", pady=(0, 14))

        ttk.Label(self.onboarding_tab, text="1  Installed", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(
            self.onboarding_tab,
            text="SENTRA Desktop, MCP and the secure tunnel client are installed for this Windows user.",
            wraplength=900,
        ).pack(anchor="w", pady=(2, 10))

        ttk.Label(self.onboarding_tab, text="2  Connect ChatGPT (optional)", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(
            self.onboarding_tab,
            text="Create/select a tunnel and a Runtime API key with All permissions.",
            wraplength=900,
        ).pack(anchor="w", pady=(2, 6))
        form = ttk.Frame(self.onboarding_tab)
        form.pack(fill="x", pady=4)
        ttk.Label(form, text="Tunnel ID").grid(row=0, column=0, sticky="w")
        self.tunnel_id_var = self.tk.StringVar()
        ttk.Entry(form, textvariable=self.tunnel_id_var, width=60).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Label(form, text="Runtime API key").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.runtime_key_var = self.tk.StringVar()
        ttk.Entry(form, textvariable=self.runtime_key_var, show="•", width=60).grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        form.columnconfigure(1, weight=1)

        buttons = ttk.Frame(self.onboarding_tab)
        buttons.pack(fill="x", pady=(6, 12))
        ttk.Button(
            buttons,
            text="Open OpenAI Tunnels",
            command=lambda: webbrowser.open(OPENAI_TUNNELS_URL),
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            buttons,
            text="Open Runtime API Keys",
            command=lambda: webbrowser.open(OPENAI_API_KEYS_URL),
        ).pack(side="left", padx=4)
        self.connect_button = ttk.Button(buttons, text="Connect OpenAI & Start", command=self.connect_openai)
        self.connect_button.pack(side="right", padx=4)
        ttk.Button(
            buttons, text="Enable Web Models / Codex",
            command=self.open_web_models_setup,
        ).pack(side="right", padx=5)

        ttk.Label(self.onboarding_tab, text="3  Optional integrations", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(
            self.onboarding_tab,
            text=(
                "When Ready, use SENTRA from the terminal, inside Codex through Web Models, "
                "as an MCP app/plugin in ChatGPT, or through the optional Edge browser plugin."
            ),
            wraplength=900,
        ).pack(anchor="w", pady=(2, 8))

        surfaces = ttk.LabelFrame(
            self.onboarding_tab,
            text="Where you can use SENTRA",
            padding=10,
        )
        surfaces.pack(fill="x", pady=(0, 12))
        self.surface_labels: dict[str, Any] = {}
        for row, (surface_id, title, detail) in enumerate((
            (
                "terminal",
                "Terminal / SENTRA CLI",
                "Use sentra or sentra-cli in a project for local tools, files, jobs and agent workflows.",
            ),
            (
                "chatgpt",
                "ChatGPT / MCP app",
                "ChatGPT reaches the local SENTRA MCP securely through the OpenAI Tunnel.",
            ),
            (
                "codex",
                "Codex / Web Models",
                "Codex uses the local SENTRA Gateway to access managed ChatGPT/Gemini Web models.",
            ),
            (
                "browser",
                "Edge / Browser plugin",
                "Optional extension for workflows that need to operate an eligible existing browser tab.",
            ),
        )):
            ttk.Label(
                surfaces,
                text=title,
                font=("Segoe UI", 10, "bold"),
            ).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=4)
            label = ttk.Label(
                surfaces,
                text=f"Checking… · {detail}",
                wraplength=650,
            )
            label.grid(row=row, column=1, sticky="w", pady=4)
            self.surface_labels[surface_id] = label
        surfaces.columnconfigure(1, weight=1)

        edge = ttk.LabelFrame(self.onboarding_tab, text="Optional browser plugin", padding=10)
        edge.pack(fill="x", pady=(4, 10))
        self.edge_path_label = ttk.Label(edge, text=str(self.paths.extension_dir))
        self.edge_path_label.pack(anchor="w")
        ttk.Button(edge, text="Open Edge extensions", command=self.open_edge_extensions).pack(anchor="w", pady=6)
        ttk.Label(
            edge,
            text=(
                "For browser automation only: enable Developer mode → Load unpacked → select the "
                "edge_extension folder above. Pairing with the local relay is automatic (install-local proof); "
                "do not paste bearer/relay tokens. The principal Edge path adopts only eligible existing tabs."
            ),
            wraplength=900,
        ).pack(anchor="w")
        self.edge_pairing_status = ttk.Label(edge, text="Browser plugin: optional")
        self.edge_pairing_status.pack(anchor="w", pady=5)
    def save_start_with_windows(self) -> None:
        """Persist both the startup preference and the current-user registry entry."""
        from tkinter import messagebox
        from .installer import set_desktop_autostart

        enabled = bool(self.start_with_windows.get())
        previous = self.settings.autostart_desktop
        try:
            set_desktop_autostart(self.paths.install_dir, enabled=enabled)
            self.settings.autostart_desktop = enabled
            self.settings.save(self.paths.settings)
        except (OSError, ValueError, RuntimeError) as exc:
            self.settings.autostart_desktop = previous
            self.start_with_windows.set(previous)
            messagebox.showerror("SENTRA Startup", str(exc))

    def open_setup_video(self, step: str) -> None:
        from tkinter import messagebox

        try:
            video = tutorial_video_path(self.paths.install_dir, step)
            if os.name == "nt":
                os.startfile(str(video))
            else:
                webbrowser.open(video.as_uri())
        except (OSError, ValueError) as exc:
            messagebox.showerror("SENTRA Setup Tutorial", str(exc))

    def open_setup_guide(self) -> None:
        """Show the bundled offline tutorial page; credentials stay in SENTRA."""
        from tkinter import messagebox

        try:
            guide = tutorial_video_path(
                self.paths.install_dir, "tunnel"
            ).parent / "SENTRA_SETUP_GUIDE.html"
            if not guide.is_file():
                raise FileNotFoundError("SENTRA visual setup guide is missing")
            webbrowser.open(guide.resolve().as_uri())
        except (OSError, ValueError) as exc:
            messagebox.showerror("SENTRA Setup Guide", str(exc))

    def finish_chatgpt_plugin_setup(self) -> None:
        """Account handoff: open ChatGPT only after verified local tunnel health."""
        from tkinter import messagebox

        selected_tunnel_id = self.tunnel_id_var.get().strip()

        def worker() -> None:
            try:
                status = self.runtime.status()
                tunnel_id = selected_tunnel_id
                if not tunnel_id and self.paths.tunnel_config.is_file():
                    try:
                        tunnel_data = json.loads(
                            self.paths.tunnel_config.read_text(encoding="utf-8")
                        )
                        tunnel_id = str(tunnel_data.get("tunnel_id") or "").strip()
                    except (OSError, ValueError, TypeError):
                        pass
                plan = chatgpt_plugin_install_plan(
                    status, tunnel_id=tunnel_id
                )

                def complete() -> None:
                    if not plan["ready_to_install"]:
                        messagebox.showwarning("SENTRA Plugin", plan["reason"])
                        return
                    details = "\n".join(
                        f"{i}. {step}" for i, step in enumerate(plan["steps"], 1)
                    )
                    if plan["tunnel_id"]:
                        self.root.clipboard_clear()
                        self.root.clipboard_append(plan["tunnel_id"])
                        self.root.update_idletasks()
                    messagebox.showinfo(
                        "Install SENTRA in ChatGPT",
                        "SENTRA MCP and Secure MCP Tunnel are online.\n\n"
                        "The Tunnel ID has been copied (not the API key).\n\n"
                        + details
                        + "\n\nYou must review and approve the plugin inside ChatGPT.",
                    )
                    webbrowser.open(CHATGPT_PLUGINS_HOME_URL)

                self.root.after(0, complete)
            except (OSError, ValueError, RuntimeError) as exc:
                error_name = type(exc).__name__
                self.root.after(
                    0,
                    lambda: messagebox.showerror(
                        "SENTRA Plugin", f"Unable to check local tunnel: {error_name}"
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def start_openai_browser_enrollment(self) -> None:
        """Automatic creation/capture under one installer or Desktop consent."""
        from tkinter import messagebox
        from .openai_browser_enrollment import OpenAIConsentBrowser
        from .openai_auto_setup import consume_installer_enrollment, recover_enrollment

        previous = getattr(self, "_openai_enrollment_dialog", None)
        if previous is not None and previous.winfo_exists():
            previous.lift()
            return
        allowed = getattr(self, "_openai_enrollment_approved", False) or consume_installer_enrollment(self.paths) or messagebox.askyesno(
            "SENTRA — OpenAI browser enrollment",
            "Open a separate temporary Edge browser for OpenAI Platform?\n\n"
            "Sign in directly in that window. SENTRA will create or select a "
            "tunnel, create a NEW API key with All permissions and no expiration, capture its "
            "one-time reveal, protect it with Windows DPAPI, and start and "
            "verify the local MCP and secure tunnel.\n\n"
            "Authorize this complete automatic configuration?",
        )
        if not allowed:
            return
        self._openai_enrollment_approved = True
        self.settings.autostart_mcp = True
        self.settings.autostart_relay = True
        self.settings.autostart_tunnel = True
        self.settings.save(self.paths.settings)

        tk, ttk = self.tk, self.ttk
        panel = tk.Toplevel(self.root)
        self._openai_enrollment_dialog = panel
        panel.title("SENTRA — Guided browser configuration")
        panel.geometry("685x440")
        panel.minsize(610, 390)
        view = ttk.Frame(panel, padding=18)
        view.pack(fill="both", expand=True)
        ttk.Label(
            view, text="Configure OpenAI with your browser",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w", pady=(0, 10))
        ttk.Label(
            view,
            text=(
                "Sign in to OpenAI Platform in the temporary Edge window. "
                "SENTRA automatically configures the tunnel and a new API key "
                "with All permissions, then verifies the connection."
            ),
            wraplength=610,
        ).pack(anchor="w", pady=(0, 12))

        status = tk.StringVar(value="Opening a temporary, unshared Edge session…")
        ttk.Label(
            view, textvariable=status, wraplength=605,
        ).pack(anchor="w", pady=(2, 12))

        def on_event(event: str, message: str) -> None:
            def apply() -> None:
                if event == "tunnel":
                    self.tunnel_id_var.set(message)
                    status.set(
                        "Tunnel selected. Creating the API key with All permissions…"
                    )
                elif event == "key_page":
                    status.set(message)
                elif event == "configured":
                    self.runtime_key_var.set("")
                    status.set(
                        "New key saved using Windows protection. Verifying the tunnel…"
                    )
                    threading.Thread(
                        target=self._connect_openai_services, daemon=True
                    ).start()
                elif event == "ready":
                    self.runtime_key_var.set("")
                    status.set(message)
                    self.connect_button.configure(state="normal", text="Connected")
                    self.quick_progress["value"] = 100
                    self.quick_status.configure(text="OpenAI tunnel connected")
                    self.quick_detail.configure(text=message)
                    self.refresh_async()
                elif event in {"opened", "progress", "workspace_required"}:
                    status.set(message)
                elif event == "closed":
                    pass  # Keep the final success/failure visible after cleanup.
                else:
                    messages = {
                        "open_official_tunnels_page":
                            "Open OpenAI Platform > Organization > Tunnels, then retry.",
                        "tunnel_not_found":
                            "Open the tunnel details to reveal its ID, then retry.",
                        "tunnel_multiple_visible":
                            "More than one tunnel is shown. Open the desired tunnel details.",
                        "select_tunnel_first":
                            "Detect and select a single tunnel before continuing.",
                        "open_official_api_keys_page":
                            "Open the official API Keys page, then retry.",
                        "new_key_not_found":
                            "Create a NEW key with All permissions and keep its one-time reveal "
                            "dialog open. If only Copy is offered, paste into SENTRA "
                            "Quick Start manually.",
                        "new_key_multiple_visible":
                            "Multiple keys are visible; leave only the new key dialog open.",
                        "playwright_or_edge_unavailable":
                            "Browser automation not packaged or Edge unavailable. "
                            "Use the manual Quick Start instead.",
                        "all_permissions_unavailable":
                            "Platform did not offer or confirm All permissions. Check your organization role.",
                        "platform_ui_needs_attention":
                            "Platform controls changed or access is unavailable. Check the browser and use manual setup.",
                        "login_required": "Sign in to Platform, then restart automatic setup.",
                        "chatgpt_workspace_required":
                            "Select the ChatGPT workspace in Platform. Organization access alone is insufficient for ChatGPT.",
                        "workspace_association_unverified":
                            "OpenAI could not verify the workspace/organization association. Use Contact support in Platform; local SENTRA remains available.",
                        "tunnel_verification_failed":
                            "The new tunnel failed verification. Previous configuration restored; check Doctor.",
                        "manual_recovery_required":
                            "Verification and recovery need attention. An encrypted recovery copy is retained.",
                    }
                    status.set(messages.get(message, "Browser step needs attention: " + message))

            try:
                self.root.after(0, apply)
            except RuntimeError:
                pass

        session = OpenAIConsentBrowser(self.paths, on_event, runtime=self.runtime)
        self._openai_enrollment_session = session
        preflight_cancelled = threading.Event()
        ttk.Label(
            view,
            text="Keep this window open until verification finishes. "
                 "The ChatGPT plugin can then be installed from Quick Start.",
            wraplength=610,
        ).pack(anchor="w", pady=(3, 9))

        def close_enrollment() -> None:
            preflight_cancelled.set()
            session.close()
            panel.destroy()

        ttk.Button(
            view, text="Close temporary browser and return",
            command=close_enrollment,
        ).pack(anchor="w")
        panel.protocol("WM_DELETE_WINDOW", close_enrollment)
        panel.transient(self.root)

        def recover_before_browser() -> None:
            on_event("progress", "Checking saved credentials and interrupted configuration…")
            result = recover_enrollment(self.paths, self.runtime)
            if preflight_cancelled.is_set():
                return
            if result.get("ok"):
                on_event("ready", "Saved credentials reused. MCP and the authenticated OpenAI tunnel are verified.")
            elif result.get("enrollment_needed"):
                session.start(approved=True, automatic=True)
            else:
                on_event("progress", "Saved configuration could not be verified or recovered. "
                         "Automatic setup stopped before creating a new key. Check Doctor or use manual setup.")

        threading.Thread(target=recover_before_browser, daemon=True).start()

    def open_chatgpt_wizard(self) -> None:
        """Small self-contained external-account guide; only SENTRA stores secrets."""
        tk, ttk = self.tk, self.ttk
        dialog = getattr(self, "_chatgpt_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            dialog.focus_force()
            return
        dialog = tk.Toplevel(self.root)
        self._chatgpt_dialog = dialog
        dialog.title("Connect ChatGPT to SENTRA")
        dialog.geometry("700x490")
        dialog.minsize(640, 440)
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Connect ChatGPT", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Optional setup. SENTRA local works without these credentials. "
                 "Use a Runtime API key with All permissions.",
            wraplength=635,
        ).pack(anchor="w", pady=(4, 8))
        tutorial_actions = ttk.Frame(frame)
        tutorial_actions.pack(fill="x", pady=(0, 12))
        ttk.Button(
            tutorial_actions,
            text="Open visual tutorial",
            command=self.open_setup_guide,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            tutorial_actions,
            text="Auto-configure in Edge (with consent)",
            command=self.start_openai_browser_enrollment,
        ).pack(side="left")

        first = ttk.LabelFrame(frame, text="1. Create your OpenAI tunnel", padding=9)
        first.pack(fill="x", pady=5)
        ttk.Button(first, text="Watch the tunnel tutorial", command=lambda: self.open_setup_video("tunnel")).pack(side="left", padx=3)
        ttk.Button(first, text="Open OpenAI Tunnels", command=lambda: webbrowser.open(OPENAI_TUNNELS_URL)).pack(side="left", padx=3)

        second = ttk.LabelFrame(frame, text="2. Create a Runtime API key with All permissions", padding=9)
        second.pack(fill="x", pady=5)
        ttk.Button(second, text="Open API keys", command=lambda: webbrowser.open(OPENAI_API_KEYS_URL)).pack(side="left", padx=3)
        ttk.Label(second, text="Copy Tunnel ID and key only into the fields below.").pack(side="left", padx=10)

        fields = ttk.Frame(frame)
        fields.pack(fill="x", pady=10)
        ttk.Label(fields, text="Tunnel ID").grid(row=0, column=0, sticky="w")
        ttk.Entry(fields, textvariable=self.tunnel_id_var).grid(row=0, column=1, sticky="ew", padx=7)
        ttk.Label(fields, text="Runtime API key").grid(row=1, column=0, sticky="w", pady=7)
        ttk.Entry(fields, textvariable=self.runtime_key_var, show="•").grid(row=1, column=1, sticky="ew", padx=7)
        fields.columnconfigure(1, weight=1)

        third = ttk.LabelFrame(frame, text="3. Verify connection and authorize ChatGPT", padding=9)
        third.pack(fill="x", pady=5)
        ttk.Button(third, text="Watch the connector tutorial", command=lambda: self.open_setup_video("connector")).pack(side="left", padx=3)
        ttk.Label(
            third, text="Video illustrates the external account step; connect the SENTRA MCP, not the Codex Web GPT MCP.",
            wraplength=320,
        ).pack(side="left", padx=7)
        ttk.Label(
            frame,
            text="Keys are protected with Windows DPAPI. The connector approval in ChatGPT is a separate account action.",
            wraplength=635,
        ).pack(anchor="w", pady=8)

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="Close — use SENTRA locally", command=dialog.destroy).pack(side="left")
        ttk.Button(
            actions, text="Finish in ChatGPT",
            command=self.finish_chatgpt_plugin_setup,
        ).pack(side="right", padx=6)
        ttk.Button(actions, text="Connect & Verify", command=self.connect_openai).pack(side="right")
        dialog.transient(self.root)

    def show_doctor(self) -> None:
        from tkinter import messagebox
        def worker() -> None:
            try:
                report = self.setup_assistant.doctor()
                items = report["capabilities"]
                lines = [
                    ("Ready" if item["state"] == "ready" else "Optional" if item["state"] == "optional" else "Attention")
                    + " — " + item["title"] + ": " + item["explanation"]
                    for item in items
                ]
                self.root.after(0, lambda: messagebox.showinfo("SENTRA Doctor", "\n\n".join(lines)))
            except (OSError, ValueError, RuntimeError) as exc:
                self.root.after(0, lambda: messagebox.showerror("SENTRA Doctor", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def install_dependency(self, name: str) -> None:
        from tkinter import messagebox
        title = {"git": "Git", "docker": "Docker Desktop", "ollama": "Ollama"}[name]
        if not messagebox.askyesno(
            "Install optional dependency",
            f"Install {title} using Windows Package Manager (winget)? "
            "This modifies installed software and may request Windows authorization."
        ):
            return

        def worker() -> None:
            try:
                result = self.setup_assistant.install_optional(name, approved=True)
                label = ("Installed or already available." if result.get("ok")
                         else f"Installation needs attention: {result.get('reason') or result.get('detail')}")
                self.root.after(0, lambda: messagebox.showinfo("SENTRA setup", label))
            except (OSError, ValueError, RuntimeError) as exc:
                self.root.after(0, lambda: messagebox.showerror("SENTRA setup", str(exc)))
            self.root.after(0, self.refresh_async)
        threading.Thread(target=worker, daemon=True).start()

    def download_local_model(self) -> None:
        from tkinter import messagebox
        if not messagebox.askyesno(
            "Download local AI model",
            "Download Qwen2.5 0.5B (~400 MB) using Ollama? "
            "It may use additional memory, disk and internet bandwidth. "
            "You can cancel before installation."
        ):
            return

        def worker() -> None:
            try:
                result = self.setup_assistant.install_local_model(approved=True)
                if result.get("ok"):
                    detail = "Local model downloaded. SENTRA CLI can use its local fallback."
                elif result.get("reason") == "install_ollama_first":
                    detail = "Install Ollama first, then retry the model download."
                else:
                    detail = str(result.get("detail") or result.get("reason") or "Model setup failed")
                self.root.after(0, lambda: messagebox.showinfo("SENTRA local AI", detail))
            except (OSError, RuntimeError, ValueError) as exc:
                self.root.after(0, lambda: messagebox.showerror("SENTRA local AI", str(exc)))
            self.root.after(0, self.refresh_async)
        threading.Thread(target=worker, daemon=True).start()

    def open_starter_project(self) -> None:
        from tkinter import messagebox
        try:
            root = first_workspace(self.paths, self.settings)
            subprocess.Popen(["explorer.exe", str(root)])
        except (OSError, ValueError) as exc:
            messagebox.showerror("SENTRA Workspace", str(exc))

    def open_terminal(self) -> None:
        from tkinter import messagebox
        project = first_workspace(self.paths, self.settings)
        binary = self.paths.install_dir / "sentra-cli.exe"
        command = [str(binary)] if binary.is_file() else [sys.executable, "-m", "sentra_cli"]
        try:
            subprocess.Popen(
                ["cmd.exe", "/k", *command],
                cwd=str(project),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("SENTRA Terminal", str(exc))

    def open_web_models_setup(self) -> None:
        if not self.advanced_visible:
            self._toggle_advanced_tabs()
        self.tabs.select(self.web_models_tab)
        self.start_web_models()

    def repair_local(self) -> None:
        from tkinter import messagebox
        def worker() -> None:
            try:
                result = self.setup_assistant.start_local()
                detail = "Local MCP is ready." if result["ok"] else "Local MCP still needs attention. Open Doctor."
                self.root.after(0, lambda: self.quick_detail.configure(text=detail))
            except (OSError, ValueError, RuntimeError) as exc:
                self.root.after(0, lambda: messagebox.showerror("SENTRA Doctor", str(exc)))
            self.root.after(0, self.refresh_async)
        threading.Thread(target=worker, daemon=True).start()

    def _autostart(self) -> None:
        threading.Thread(target=self.runtime.start_all, daemon=True).start()

    def _refresh_workspaces(self) -> None:
        self.workspace_list.delete(0, "end")
        for item in self.settings.allowed_roots:
            permissions = self.settings.workspace_permissions.get(item) or ["read"]
            flags = "".join(letter for name, letter in (("read", "r"), ("write", "w"), ("execute", "x")) if name in permissions)
            self.workspace_list.insert("end", f"{item}  [{flags or 'r'}]")

    def _load_workspace_permissions(self, _event=None) -> None:
        selected = self.workspace_list.curselection()
        if not selected:
            return
        root = self.settings.allowed_roots[selected[0]]
        permissions = set(self.settings.workspace_permissions.get(root) or ["read"])
        self.ws_read.set("read" in permissions)
        self.ws_write.set("write" in permissions)
        self.ws_execute.set("execute" in permissions)

    def apply_workspace_permissions(self) -> None:
        from tkinter import messagebox
        selected = self.workspace_list.curselection()
        if not selected:
            messagebox.showinfo("SENTRA", "Select a workspace first.")
            return
        root = self.settings.allowed_roots[selected[0]]
        permissions = []
        if self.ws_read.get():
            permissions.append("read")
        if self.ws_write.get():
            permissions.append("write")
        if self.ws_execute.get():
            permissions.append("execute")
        if not permissions:
            messagebox.showerror("SENTRA", "A workspace must grant at least Read.")
            return
        if "read" not in permissions:
            permissions.insert(0, "read")
        self.settings.workspace_permissions[root] = permissions
        self.settings.save(self.paths.settings)
        sync_workspace_registry(self.paths, self.settings)
        sync_agent_policy(self.paths, self.settings)
        self._refresh_workspaces()

    def add_workspace(self) -> None:
        from tkinter import filedialog
        path = filedialog.askdirectory()
        if path:
            root = str(Path(path).resolve())
            if root not in self.settings.allowed_roots:
                self.settings.allowed_roots.append(root)
                # Selecting a project authorizes inspection, not writing or
                # executing code. Additional grants use the policy controls.
                self.settings.workspace_permissions[root] = ["read"]
                self.settings.save(self.paths.settings)
                sync_workspace_registry(self.paths, self.settings)
                sync_agent_policy(self.paths, self.settings)
                self._refresh_workspaces()

    def remove_workspace(self) -> None:
        selected = list(self.workspace_list.curselection())
        for index in reversed(selected):
            root = self.settings.allowed_roots[index]
            del self.settings.allowed_roots[index]
            self.settings.workspace_permissions.pop(root, None)
        self.settings.save(self.paths.settings)
        sync_workspace_registry(self.paths, self.settings)
        sync_agent_policy(self.paths, self.settings)
        self._refresh_workspaces()

    def save_policy(self) -> None:
        from tkinter import messagebox
        self.settings.profile = self.profile_var.get().strip()
        self.settings.access_scope = self.access_scope_var.get().strip()
        custom = [line.strip() for line in self.tools_text.get("1.0", "end").splitlines() if line.strip()]
        self.settings.tool_allowlist = list(dict.fromkeys(custom))
        if self.settings.profile == "Safe":
            for root in self.settings.allowed_roots:
                self.settings.workspace_permissions[root] = ["read"]
        self.settings.save(self.paths.settings)
        sync_workspace_registry(self.paths, self.settings)
        sync_agent_policy(self.paths, self.settings)
        self._refresh_workspaces()
        messagebox.showinfo("SENTRA", "Policy saved. Restart services to apply it.")

    def choose_queue_workspace(self) -> None:
        from tkinter import filedialog
        path = filedialog.askdirectory()
        if path:
            self.queue_workspace.set(path)
    def choose_audit_workspace(self) -> None:
        from tkinter import filedialog
        path = filedialog.askdirectory()
        if path:
            self.audit_workspace.set(path)

    def add_queue_task(self) -> None:
        from tkinter import messagebox
        try:
            enqueue_task(self.paths, Path(self.queue_workspace.get()), self.queue_prompt.get())
            self.queue_prompt.set("")
            self.refresh_async()
        except Exception as exc:
            messagebox.showerror("SENTRA queue", str(exc))

    def run_queue_next(self) -> None:
        def worker() -> None:
            run_next_task(self.paths, self.settings)
            self.root.after(0, self.refresh_async)
        threading.Thread(target=worker, daemon=True).start()

    def show_diff(self) -> None:
        from tkinter import messagebox
        try:
            value = git_diff(Path(self.audit_workspace.get()))
            self.audit_text.delete("1.0", "end")
            self.audit_text.insert("1.0", value or "(clean working tree)")
        except Exception as exc:
            messagebox.showerror("SENTRA diff", str(exc))

    def snapshot(self) -> None:
        from tkinter import messagebox
        try:
            result = create_snapshot(self.paths, Path(self.audit_workspace.get()))
            messagebox.showinfo("SENTRA snapshot", f"Created {result['snapshot']} ({result['files']} files)")
            self.refresh_async()
        except Exception as exc:
            messagebox.showerror("SENTRA snapshot", str(exc))
    def rollback(self) -> None:
        from tkinter import messagebox
        snapshots = list_snapshots(self.paths)
        if not snapshots:
            messagebox.showinfo("SENTRA rollback", "No snapshots available.")
            return
        workspace = Path(self.audit_workspace.get())
        snapshot = snapshots[0]
        if not messagebox.askyesno(
            "SENTRA rollback",
            f"Restore latest snapshot?\n{snapshot}\n\nCurrent non-excluded workspace files will be replaced.",
        ):
            return
        try:
            result = rollback_snapshot(snapshot, workspace)
            messagebox.showinfo("SENTRA rollback", f"Restored {result['restored']} files.")
        except Exception as exc:
            messagebox.showerror("SENTRA rollback", str(exc))

    def connect_openai(self) -> None:
        from tkinter import messagebox

        tunnel_id = self.tunnel_id_var.get().strip()
        runtime_key = self.runtime_key_var.get().strip()
        if not tunnel_id or not runtime_key:
            messagebox.showerror(
                "SENTRA Quick Start",
                "Enter both the Tunnel ID and Runtime API key. Use the OpenAI buttons above if you have not created them yet.",
            )
            self.quick_status.configure(text="Connect OpenAI")
            self.quick_detail.configure(text="Both values are required before SENTRA can establish the secure MCP tunnel.")
            self.quick_progress["value"] = 35
            return
        try:
            configure_tunnel(self.paths, tunnel_id, runtime_key)
            self.runtime_key_var.set("")
            self.quick_status.configure(text="Connecting OpenAI…")
            self.quick_detail.configure(text="Credentials are protected with Windows DPAPI. SENTRA is restarting local services now.")
            self.quick_progress["value"] = 65
            self.connect_button.configure(state="disabled", text="Connecting…")
            threading.Thread(target=self._connect_openai_services, daemon=True).start()
        except Exception as exc:
            # Never render transport/provider exception bodies in UI:
            # they can contain a one-time Runtime API key.
            detail = type(exc).__name__
            self.connect_button.configure(state="normal", text="Connect OpenAI & Start")
            messagebox.showerror(
                "SENTRA Quick Start",
                f"{detail}\n\nWhat to do: re-check the Tunnel ID and create a Runtime API key with All permissions, then try again.",
            )

    def _connect_openai_services(self) -> None:
        try:
            verification = self.runtime.connect_and_verify(timeout_s=12.0)
            status = dict(verification.get("status") or {})
            onboarding = verification.get("onboarding")
            if isinstance(onboarding, dict):
                status["onboarding"] = onboarding
            progress, headline, detail = _quick_start_state(
                status,
                has_tunnel=True,
            )
            chatgpt_status = verification.get("chatgpt_onboarding") or {}
            # Local SENTRA readiness is NOT proof that the OpenAI tunnel is
            # authenticated and usable. Show the external verdict separately.
            ready = bool(chatgpt_status.get("ready"))
            if not ready:
                headline = "ChatGPT tunnel needs attention"
                detail = (
                    str(chatgpt_status.get("detail") or "")
                    or "Check the MCP, tunnel authorization and Runtime API key in Doctor."
                )

            def apply() -> None:
                self.connect_button.configure(
                    state="normal",
                    text=(
                        "Connected"
                        if ready
                        else "Retry Connect OpenAI"
                    ),
                )
                self.quick_progress["value"] = progress
                self.quick_status.configure(text=headline)
                self.quick_detail.configure(text=detail)
                self.refresh_async()

            self.root.after(0, apply)
        except Exception as exc:
            detail = type(exc).__name__

            def failed() -> None:
                self.connect_button.configure(state="normal", text="Retry Connect OpenAI")
                self.quick_progress["value"] = 65
                self.quick_status.configure(text="Connection needs attention")
                self.quick_detail.configure(
                    text=f"{detail}. Run Doctor for the failing local service, then retry Connect OpenAI."
                )

            self.root.after(0, failed)

    def save_tunnel(self) -> None:
        from tkinter import messagebox
        try:
            configure_tunnel(self.paths, self.tunnel_id_var.get(), self.runtime_key_var.get())
            self.runtime_key_var.set("")
            messagebox.showinfo("SENTRA", "Tunnel credential stored with Windows DPAPI.")
        except Exception as exc:
            messagebox.showerror("SENTRA tunnel", str(exc))

    def open_edge_extensions(self) -> None:
        try:
            subprocess.Popen(["cmd.exe", "/c", "start", "", "msedge.exe", "edge://extensions"])
        except OSError:
            webbrowser.open("edge://extensions")
    def pair_remote(self) -> None:
        from tkinter import messagebox
        relay, code = self.remote_relay_var.get().strip(), self.remote_code_var.get().strip()
        if not relay or not code:
            messagebox.showerror("SENTRA Remote", "Relay URL and pairing code are required.")
            return

        def worker() -> None:
            try:
                policy = self.settings.policy()
                sync_workspace_registry(self.paths, self.settings)
                config = pair_agent(
                    relay,
                    code,
                    os.environ.get("COMPUTERNAME", "SENTRA Device"),
                    self.paths.state_dir / "agent.json",
                    [str(agent_bootstrap_root(self.paths))],
                    str(policy["process_mode"]),
                    state_root=str(self.paths.state_dir),
                    profile=self.settings.profile,
                    access_scope=self.settings.access_scope,
                    tool_surfaces=[str(item) for item in policy["surfaces"]],
                    tool_allowlist=[str(item) for item in policy.get("tool_allowlist") or ()],
                )
                self.settings.autostart_agent = True
                self.settings.save(self.paths.settings)
                sync_agent_policy(self.paths, self.settings)
                self.root.after(0, lambda: messagebox.showinfo("SENTRA Remote", f"Paired: {config.device_id}"))
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror("SENTRA Remote", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def start_services(self) -> None:
        threading.Thread(target=self._service_action, args=("start",), daemon=True).start()

    def stop_services(self) -> None:
        threading.Thread(target=self._service_action, args=("stop",), daemon=True).start()

    def restart_services(self) -> None:
        self.save_policy()
        threading.Thread(target=self._service_action, args=("restart",), daemon=True).start()

    def _service_action(self, action: str) -> None:
        try:
            if action == "start":
                self.runtime.start_all()
            elif action == "stop":
                self.runtime.stop_all()
            else:
                self.runtime.restart_all()
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            def show_failure() -> None:
                from tkinter import messagebox
                self.quick_progress["value"] = 70
                self.quick_status.configure(text="Setup needs attention")
                self.quick_detail.configure(
                    text="SENTRA could not start all required services. Run Doctor, then retry Connect OpenAI & Start."
                )
                if hasattr(self, "connect_button"):
                    self.connect_button.configure(state="normal")
                messagebox.showerror(
                    "SENTRA Quick Start",
                    f"{detail}\n\nWhat to do: run Doctor. If the tunnel is the failing service, verify the Tunnel ID and Runtime API key with All permissions, then retry.",
                )
            self.root.after(0, show_failure)
            return
        def finished() -> None:
            if hasattr(self, "connect_button"):
                self.connect_button.configure(state="normal")
            self.refresh_async()
        self.root.after(250, finished)

    def check_update(self) -> None:
        from tkinter import messagebox
        url = self.settings.update_manifest_url.strip()
        if not url:
            messagebox.showinfo("SENTRA Update", "No update manifest URL configured.")
            return

        def worker() -> None:
            try:
                manifest = fetch_manifest(url)
                available = str(manifest["version"])
                update = is_newer_version(available, PRODUCT_VERSION)
                text = f"Update: {'available' if update else 'current'} · installed {PRODUCT_VERSION} · remote {available}"
                self.root.after(0, lambda: self.update_status.configure(text=text))
                if update:
                    self.root.after(0, lambda: self._offer_update(url, available))
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror("SENTRA Update", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _offer_update(self, manifest_url: str, version: str) -> None:
        from tkinter import messagebox
        if not getattr(sys, "frozen", False):
            return
        if not messagebox.askyesno("SENTRA Update", f"Install signed update {version}?"):
            return
        try:
            prepared = prepare_update(manifest_url, require_signature=True)
            self.runtime.stop_all()
            apply_prepared_update(prepared, self.paths.install_dir, manifest_url=manifest_url, auto_update=True)
            self.quit()
        except Exception as exc:
            messagebox.showerror("SENTRA Update", str(exc))

    def rollback_version(self) -> None:
        from tkinter import messagebox
        if not getattr(sys, "frozen", False):
            messagebox.showinfo("SENTRA Rollback", "Version rollback is available in an installed build.")
            return
        if not messagebox.askyesno(
            "SENTRA Rollback",
            "Restore the previous installed SENTRA version? The current version will be kept as the next rollback point.",
        ):
            return
        try:
            self.runtime.stop_all()
            rollback_previous_update(self.paths.install_dir)
            self._closing = True
            if self.tray_icon is not None:
                try:
                    self.tray_icon.stop()
                except Exception:
                    pass
            self.root.destroy()
        except Exception as exc:
            messagebox.showerror("SENTRA Rollback", str(exc))

    def refresh_async(self) -> None:
        if self._refreshing or self._closing:
            return
        self._refreshing = True

        def worker() -> None:
            try:
                status = self.runtime.status()
                local_supervision = self.runtime.supervise_local_once(status)
                if any(item.get("state") == "RECOVERING" for item in local_supervision.values()):
                    status = self.runtime.status()
                supervision = self.runtime.supervise_once(status)
                if supervision.get("action") in {"restart_tunnel", "restart_failed"}:
                    status = self.runtime.status()
                status["local_supervisor"] = local_supervision
                status["supervisor"] = {"tunnel": supervision}
                jobs = list_recent_jobs(self.paths)
                tasks = list_tasks(self.paths)
                audit = tail_audit(self.paths, 80)
                errors = self._read_errors()
            except Exception as exc:
                status, jobs, tasks, audit, errors = {}, [], [], [], str(exc)
            self.root.after(0, lambda: self._apply_refresh(status, jobs, tasks, audit, errors))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_refresh(
        self,
        status: dict[str, Any],
        jobs: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        audit: list[dict[str, Any]],
        errors: str,
    ) -> None:
        self._refreshing = False
        status_keys = {
            "mcp": "mcp",
            "tunnel": "tunnel",
            "edge": "edge",
            "sandbox": "sandbox",
            "git": "git",
            "remote": "remote_agent",
        }
        for key, source_key in status_keys.items():
            item = status.get(source_key, {})
            ok = bool(item.get("ok"))
            detail = "✓ Ready" if ok else "✕ Attention"
            self.status_labels[key].configure(text=detail)
        self.profile_status.configure(
            text=(
                f"Profile: {status.get('profile', self.settings.profile)}"
                f"  |  Filesystem: {status.get('access_scope', self.settings.access_scope)}"
            )
        )
        self.workspace_status.configure(text=f"Allowed workspaces: {len(self.settings.allowed_roots)}")
        for tree in (self.jobs_tree, self.queue_tree):
            tree.delete(*tree.get_children())
        for item in jobs:
            self.jobs_tree.insert("", "end", values=(item.get("operation"), item.get("state"), item.get("workspace") or ""))
        for item in tasks:
            self.queue_tree.insert("", "end", values=(item.get("id"), item.get("state"), item.get("workspace"), str(item.get("prompt", ""))[:120]))
        self.audit_text.delete("1.0", "end")
        if audit:
            self.audit_text.insert("1.0", "\n".join(json.dumps(item, ensure_ascii=False) for item in audit))
        self.last_errors.configure(state="normal")
        self.last_errors.delete("1.0", "end")
        self.last_errors.insert("1.0", errors or "No recent errors.")
        self.last_errors.configure(state="disabled")
        tunnel = load_tunnel_config(self.paths)
        if tunnel and not self.tunnel_id_var.get():
            self.tunnel_id_var.set(str(tunnel.get("tunnel_id") or ""))
        progress, headline, next_action = _quick_start_state(
            status,
            has_tunnel=bool(tunnel and tunnel.get("tunnel_id")),
        )
        self.quick_progress["value"] = progress
        self.quick_status.configure(text=headline)
        self.quick_detail.configure(text=next_action)

        onboarding = status.get("onboarding")
        surface_items = (
            onboarding.get("surfaces", [])
            if isinstance(onboarding, dict)
            else []
        )
        for item in surface_items:
            if not isinstance(item, dict):
                continue
            surface_id = str(item.get("id") or "")
            label = getattr(self, "surface_labels", {}).get(surface_id)
            if label is None:
                continue
            ready = bool(item.get("ready"))
            optional = bool(item.get("optional"))
            state_text = "Ready" if ready else ("Optional" if optional else "Needs setup")
            detail = str(item.get("detail") or "")
            label.configure(text=f"{state_text} · {detail}")

        edge_state = status.get("edge", {})
        self.edge_pairing_status.configure(
            text=(
                "Browser plugin: ready"
                if edge_state.get("ok")
                else "Browser plugin: optional · not connected"
            )
        )
        self.root.after(3000, self.refresh_async)

    def _read_errors(self) -> str:
        chunks: list[str] = []
        for path in sorted((self.paths.state_dir / "logs").glob("*.err.log")):
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]
            except OSError:
                continue
            if lines:
                chunks.append(f"[{path.name}]\n" + "\n".join(lines))
        return "\n\n".join(chunks[-5:])

    def _start_tray(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            return
        image = Image.new("RGBA", (64, 64), (28, 28, 32, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 54, 54), outline=(245, 245, 245, 255), width=4)
        draw.text((23, 18), "S", fill=(245, 245, 245, 255))
        menu = pystray.Menu(
            pystray.MenuItem("Open SENTRA", lambda *_: self.root.after(0, self.show)),
            pystray.MenuItem("Start services", lambda *_: self.root.after(0, self.start_services)),
            pystray.MenuItem("Stop services", lambda *_: self.root.after(0, self.stop_services)),
            pystray.MenuItem("Doctor", lambda *_: self.root.after(0, self.refresh_async)),
            pystray.MenuItem("Exit", lambda *_: self.root.after(0, self.quit)),
        )
        self.tray_icon = pystray.Icon("SENTRA Desktop", image, "SENTRA Desktop", menu)
        try:
            self.tray_icon.run_detached()
        except Exception:
            threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self) -> None:
        self.root.withdraw()

    def quit(self) -> None:
        self._closing = True
        if self.web_gateway is not None:
            # Do not exit while Codex still depends on this in-process Gateway.
            restored, detail = self._restore_codex_route_before_gateway_stop()
            if not restored:
                self._closing = False
                self._set_web_models_status(
                    "Saída recusada: Codex ainda depende do Gateway SENTRA"
                    + (f" · {detail}" if detail else "")
                )
                return
            self.web_gateway.launcher.stop()
            self.web_gateway.shutdown()
            self.web_gateway.server_close()
            self.web_gateway = None
        self.runtime.stop_all()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="sentra-desktop")
    parser.add_argument("--hidden", action="store_true")
    parser.add_argument("--open-url", default="")
    args = parser.parse_args(argv)
    initial_view = None
    if args.open_url:
        initial_view = _internal_deep_link_target(args.open_url)
        if initial_view is None:
            parser.error(
                "--open-url accepts only SENTRA home, status, onboarding, "
                "web-models or openai-enroll links"
            )
    return SentraDesktop(
        start_hidden=args.hidden and initial_view is None,
        initial_view=initial_view,
    ).run()


if __name__ == "__main__":
    raise SystemExit(main())
