"""SENTRA Desktop: operational UI + tray for installed Windows product."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Any

from sentra_version import PRODUCT_VERSION

from .agent import pair_agent
from .local_runtime import LocalRuntime
from .product import (
    PROFILE_POLICIES,
    ProductPaths,
    ProductSettings,
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


class SentraDesktop:
    def __init__(self, *, start_hidden: bool = False) -> None:
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
        self.runtime = LocalRuntime(self.paths, self.settings)
        self.web_gateway = None
        self.web_gateway_thread = None
        self.status_labels: dict[str, Any] = {}
        self.tray_icon = None
        self._closing = False
        self._refreshing = False
        self._build()
        self._start_tray()
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        if start_hidden:
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
        ttk.Button(header, text="Start", command=self.start_services).pack(side="right", padx=3)
        ttk.Button(header, text="Stop", command=self.stop_services).pack(side="right", padx=3)
        ttk.Button(header, text="Restart", command=self.restart_services).pack(side="right", padx=3)
        ttk.Button(header, text="Doctor", command=self.refresh_async).pack(side="right", padx=3)

        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.dashboard = ttk.Frame(self.tabs, padding=12)
        self.settings_tab = ttk.Frame(self.tabs, padding=12)
        self.activity_tab = ttk.Frame(self.tabs, padding=12)
        self.audit_tab = ttk.Frame(self.tabs, padding=12)
        self.onboarding_tab = ttk.Frame(self.tabs, padding=12)
        self.web_models_tab = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(self.dashboard, text="Status")
        self.tabs.add(self.settings_tab, text="Workspaces & Policy")
        self.tabs.add(self.activity_tab, text="Jobs & Queue")
        self.tabs.add(self.audit_tab, text="Audit / Diff / Snapshots")
        self.tabs.add(self.onboarding_tab, text="Onboarding")
        self.tabs.add(self.web_models_tab, text="Web Models")
        self._build_dashboard()
        self._build_settings()
        self._build_activity()
        self._build_audit()
        self._build_onboarding()
        self._build_web_models()
        if (self.paths.state_dir / "web-models-enabled").is_file():
            self.root.after(3000, lambda: self.start_web_models(hidden=True))

    def _build_web_models(self) -> None:
        ttk = self.ttk
        ttk.Label(self.web_models_tab, text="ChatGPT Web via SENTRA Model Gateway", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(
            self.web_models_tab,
            text="O launcher upstream mantém o login, Browser Host, modelos, limites e runtime. O Gateway do SENTRA expõe o catálogo e Responses ao Codex.",
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

    def save_web_model_selection(self) -> None:
        from tkinter import messagebox

        model = self.web_model_var.get().strip()
        if not model.startswith("sentra/chatgpt-web/") or model not in self.web_model_catalog_values:
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
                with urlopen("http://127.0.0.1:17842/v1/models", timeout=4) as response:
                    models = json.load(response)
                catalog = [
                    str(model.get("slug") or model.get("id"))
                    for model in (models.get("models") or models.get("data") or [])
                    if isinstance(model, dict) and str(model.get("slug") or model.get("id") or "").startswith("sentra/chatgpt-web/")
                ]
                version = health.get("upstream", {}).get("version", "?")
                route_text = "Codex: rota não verificada"
                if self.web_gateway is not None:
                    try:
                        route = self.web_gateway.launcher.route("status")
                        if route.get("points_to_sentra"):
                            route_text = "Codex: conectado ao Gateway SENTRA"
                        elif route.get("installed") and route.get("active"):
                            route_text = "Codex: rota ativa aponta fora do SENTRA · clique Conectar Codex para migrar"
                        else:
                            route_text = "Codex: conclua o setup na interface Web e clique Conectar Codex"
                    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                        route_text = f"Codex: rota ainda não verificada ({type(exc).__name__})"
                self.root.after(0, lambda: self.web_models_route.configure(text=route_text))
                self.root.after(0, lambda: self._set_web_models_status(f"Gateway ready · upstream {version} · {len(catalog)} modelos Web", catalog))
            except (OSError, ValueError) as exc:
                self.root.after(0, lambda: self._set_web_models_status(f"Gateway offline: {type(exc).__name__}"))
        threading.Thread(target=worker, daemon=True).start()

    def connect_web_models_codex(self) -> None:
        def worker() -> None:
            try:
                if self.web_gateway is None:
                    raise RuntimeError("Inicie a interface Web primeiro")
                route = self.web_gateway.launcher.route("sentra")
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
                if self.web_gateway is None:
                    raise RuntimeError("Inicie a interface Web primeiro")
                route = self.web_gateway.launcher.route("disconnect")
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
                if self.web_gateway is None:
                    raise RuntimeError("Inicie a interface Web primeiro")
                report = self.web_gateway.sentra_doctor(verify_connector=True)
                route = self.web_gateway.launcher.route("status")
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
                self.root.after(0, lambda: self._set_web_models_status(f"Falha ao iniciar Web Models: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def stop_web_models(self) -> None:
        def worker() -> None:
            if self.web_gateway is not None:
                self.web_gateway.launcher.stop()
                self.web_gateway.shutdown()
                self.web_gateway.server_close()
                self.web_gateway = None
                (self.paths.state_dir / "web-models-enabled").unlink(missing_ok=True)
                self.root.after(0, lambda: self._set_web_models_status("Launcher gerenciado encerrado"))
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
        ttk.Button(top, text="Save policy", command=self.save_policy).pack(side="left")
        ttk.Label(
            self.settings_tab,
            text="Safe = read-only tool allowlist + Docker sandbox · Developer = local engineering · Full = all surfaces.",
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
        ttk.Label(self.settings_tab, text="Optional custom tool allowlist (one tool name per line)").pack(anchor="w", pady=(14, 4))
        self.tools_text = self.tk.Text(self.settings_tab, height=8)
        self.tools_text.pack(fill="x")
        self.tools_text.insert("1.0", "\n".join(self.settings.tool_allowlist))
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
            self.onboarding_tab,
            text="Secure MCP Tunnel", font=("Segoe UI", 13, "bold")
        ).pack(anchor="w")
        ttk.Label(
            self.onboarding_tab,
            text="Create a Runtime API key restricted to Tunnels Read + Use and a tunnel_id in OpenAI Platform.",
            wraplength=900,
        ).pack(anchor="w", pady=6)
        form = ttk.Frame(self.onboarding_tab)
        form.pack(fill="x", pady=8)
        ttk.Label(form, text="Tunnel ID").grid(row=0, column=0, sticky="w")
        self.tunnel_id_var = self.tk.StringVar()
        ttk.Entry(form, textvariable=self.tunnel_id_var, width=60).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Label(form, text="Runtime API key").grid(row=1, column=0, sticky="w")
        self.runtime_key_var = self.tk.StringVar()
        ttk.Entry(form, textvariable=self.runtime_key_var, show="•", width=60).grid(row=1, column=1, sticky="ew", padx=6)
        form.columnconfigure(1, weight=1)
        buttons = ttk.Frame(self.onboarding_tab)
        buttons.pack(fill="x", pady=6)
        ttk.Button(buttons, text="Open Platform Tunnels", command=lambda: webbrowser.open("https://platform.openai.com/settings/organization/tunnels")).pack(side="left", padx=3)
        ttk.Button(buttons, text="Open Runtime API Keys", command=lambda: webbrowser.open("https://platform.openai.com/settings/organization/api-keys")).pack(side="left", padx=3)
        ttk.Button(buttons, text="Save with DPAPI", command=self.save_tunnel).pack(side="left", padx=3)
        ttk.Button(buttons, text="Start tunnel", command=self.start_services).pack(side="left", padx=3)
        edge = ttk.LabelFrame(self.onboarding_tab, text="Microsoft Edge extension", padding=10)
        edge.pack(fill="x", pady=16)
        self.edge_path_label = ttk.Label(edge, text=str(self.paths.extension_dir))
        self.edge_path_label.pack(anchor="w")
        ttk.Button(edge, text="Open edge://extensions", command=self.open_edge_extensions).pack(anchor="w", pady=6)
        ttk.Label(
            edge,
            text="Enable Developer mode → Load unpacked → select the edge_extension folder above → open Options and paste the relay token shown below.",
            wraplength=900,
        ).pack(anchor="w")
        self.relay_token_label = ttk.Entry(edge, state="readonly")
        self.relay_token_label.pack(fill="x", pady=5)
        remote = ttk.LabelFrame(self.onboarding_tab, text="Optional Remote Agent pairing", padding=10)
        remote.pack(fill="x", pady=10)
        self.remote_relay_var = self.tk.StringVar()
        self.remote_code_var = self.tk.StringVar()
        ttk.Entry(remote, textvariable=self.remote_relay_var).grid(row=0, column=0, sticky="ew", padx=3)
        ttk.Entry(remote, textvariable=self.remote_code_var).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(remote, text="Pair this device", command=self.pair_remote).grid(row=0, column=2, padx=3)
        remote.columnconfigure(0, weight=2)
        remote.columnconfigure(1, weight=1)
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
        self._refresh_workspaces()

    def add_workspace(self) -> None:
        from tkinter import filedialog
        path = filedialog.askdirectory()
        if path:
            root = str(Path(path).resolve())
            if root not in self.settings.allowed_roots:
                self.settings.allowed_roots.append(root)
                self.settings.workspace_permissions[root] = (
                    ["read"] if self.settings.profile == "Safe"
                    else ["read", "write", "execute"]
                )
                self.settings.save(self.paths.settings)
                self._refresh_workspaces()

    def remove_workspace(self) -> None:
        selected = list(self.workspace_list.curselection())
        for index in reversed(selected):
            root = self.settings.allowed_roots[index]
            del self.settings.allowed_roots[index]
            self.settings.workspace_permissions.pop(root, None)
        self.settings.save(self.paths.settings)
        self._refresh_workspaces()

    def save_policy(self) -> None:
        from tkinter import messagebox
        self.settings.profile = self.profile_var.get()
        custom = [line.strip() for line in self.tools_text.get("1.0", "end").splitlines() if line.strip()]
        self.settings.tool_allowlist = list(dict.fromkeys(custom))
        if self.settings.profile == "Safe":
            for root in self.settings.allowed_roots:
                self.settings.workspace_permissions[root] = ["read"]
        self.settings.save(self.paths.settings)
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
                config = pair_agent(
                    relay, code, os.environ.get("COMPUTERNAME", "SENTRA Device"),
                    self.paths.state_dir / "agent.json",
                    list(self.settings.allowed_roots),
                    self.settings.policy()["process_mode"],
                )
                self.settings.autostart_agent = True
                self.settings.save(self.paths.settings)
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
        if action == "start":
            self.runtime.start_all()
        elif action == "stop":
            self.runtime.stop_all()
        else:
            self.runtime.restart_all()
        self.root.after(250, self.refresh_async)

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
        self.profile_status.configure(text=f"Profile: {status.get('profile', self.settings.profile)}")
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
        try:
            token = self.paths.relay_token.read_text(encoding="utf-8").strip()
            self.relay_token_label.configure(state="normal")
            self.relay_token_label.delete(0, "end")
            self.relay_token_label.insert(0, token)
            self.relay_token_label.configure(state="readonly")
        except OSError:
            pass
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
    args = parser.parse_args(argv)
    return SentraDesktop(start_hidden=args.hidden).run()


if __name__ == "__main__":
    raise SystemExit(main())
