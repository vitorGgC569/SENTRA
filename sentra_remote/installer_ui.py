"""Native, scrollable presentation for the SENTRA installation workflow."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

BG = "#ffffff"
INK = "#101b32"
MUTED = "#5d6c84"
BLUE = "#0875ed"
LINE = "#e3eaf3"


class Card(tk.Canvas):
    """Rounded border around real, keyboard-accessible native controls."""

    def __init__(self, parent, *, padding=20):
        super().__init__(parent, background=BG, highlightthickness=0, borderwidth=0)
        self.body = tk.Frame(self, background=BG)
        self.padding = padding
        self.border = self.create_polygon(0, 0, 1, 1, fill=BG, outline=LINE, smooth=True)
        self.slot = self.create_window(padding, padding, window=self.body, anchor="nw")
        self.bind("<Configure>", self._resize)
        self.body.bind("<Configure>", self._content_changed)

    def _content_changed(self, _event=None):
        self.configure(height=self.body.winfo_reqheight() + self.padding * 2)

    def _resize(self, event):
        w, h, r = event.width - 1, event.height - 1, 16
        self.coords(self.border, r, 1, w-r, 1, w, 1, w, r, w, h-r, w, h,
                    w-r, h, r, h, 1, h, 1, h-r, 1, r, 1, 1)
        self.itemconfigure(self.slot, width=max(1, w - self.padding * 2))


def build(wizard):
    root = wizard.root
    root.configure(background=BG)
    width = min(1180, root.winfo_screenwidth() - 80)
    height = min(900, root.winfo_screenheight() - 90)
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2 - 20)
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.minsize(880, 640)
    from .installer_appearance import apply_window_identity, dot_image, theme_controller
    apply_window_identity(root)
    root.option_add("*Font", "{Segoe UI} 10")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=INK)
    style.configure("TEntry", padding=7, fieldbackground=BG, foreground=INK,
                    bordercolor="#cbd6e5", lightcolor="#cbd6e5", darkcolor="#cbd6e5")
    style.map("TEntry", bordercolor=[("focus", BLUE)])
    style.configure("TCombobox", padding=6, fieldbackground=BG, foreground=INK,
                    background="#f7f9fd", bordercolor="#cbd6e5", arrowsize=14)
    style.map("TCombobox", fieldbackground=[("readonly", BG)], foreground=[("readonly", INK)])
    style.configure("TCheckbutton", background=BG, foreground=INK, padding=(0, 4))
    style.map("TCheckbutton", background=[("active", BG)], indicatorbackground=[("selected", BLUE)])
    style.configure("Setup.TButton", padding=(14, 9), background=BG, foreground=INK,
                    bordercolor="#d3ddeb", lightcolor=BG, darkcolor=BG, focuscolor=BLUE)
    style.map("Setup.TButton", background=[("active", "#f0f6ff"), ("disabled", "#f5f7fa")])
    style.configure("Primary.TButton", padding=(22, 10), background=BLUE, foreground=BG,
                    bordercolor=BLUE, lightcolor=BLUE, darkcolor=BLUE, font=("Segoe UI", 10, "bold"))
    style.map("Primary.TButton", background=[("disabled", "#a5c9f4"), ("active", "#0064d5")],
              foreground=[("disabled", BG)])
    style.configure("Setup.Horizontal.TProgressbar", troughcolor="#e6ebf2", background=BLUE,
                    bordercolor="#e6ebf2", lightcolor=BLUE, darkcolor=BLUE, thickness=8)
    style.configure("Vertical.TScrollbar", background="#d5deeb", troughcolor=BG,
                    bordercolor=BG, arrowcolor=MUTED)

    sidebar = tk.Canvas(root, width=224, background="#f6f9fe", highlightthickness=0)
    sidebar.pack(side="left", fill="y")
    sidebar.create_line(223, 0, 223, 2000, fill=LINE)
    sidebar.create_text(30, 36, anchor="w", text="SENTRA", fill=INK, font=("Segoe UI", 13, "bold"))
    sidebar.create_text(30, 62, anchor="w", text="CONFIGURAÇÃO", fill=MUTED, font=("Segoe UI", 8))
    wizard._step_shapes = []
    wizard._step_numbers = []
    for index, (title, subtitle) in enumerate((
        ("Instalar", "Configure o SENTRA local"),
        ("Conectar OpenAI", "Obrigatório · GPT6-WEB"),
        ("Pronto", "Conclua a configuração"),
    )):
        y = 132 + index * 94
        if index < 2:
            sidebar.create_line(42, y+20, 42, y+74, fill="#d6e2f3")
        wizard._step_shapes.append(sidebar.create_oval(24, y-18, 60, y+18, outline="", fill="#dfe7f2"))
        wizard._step_numbers.append(sidebar.create_text(42, y, text=str(index+1), fill=INK, font=("Segoe UI", 11, "bold")))
        sidebar.create_text(78, y-5, anchor="w", text=title, fill=INK, font=("Segoe UI", 10, "bold"))
        sidebar.create_text(78, y+18, anchor="w", text=subtitle, fill=MUTED, font=("Segoe UI", 8))
    wave = sidebar.create_oval(-380, 480, 300, 1160, fill="#edf4ff", outline="")
    sidebar.tag_lower(wave)
    wave2 = sidebar.create_oval(-420, 600, 230, 1290, fill="#e3efff", outline="")
    sidebar.tag_lower(wave2)
    sidebar.create_text(30, 444, anchor="w", text="SEU AMBIENTE, PRONTO", fill=MUTED, font=("Segoe UI", 8, "bold"))

    right = tk.Frame(root, background=BG)
    right.pack(side="left", fill="both", expand=True)
    footer = tk.Frame(right, background=BG, padx=28, pady=16)
    footer.pack(side="bottom", fill="x")
    ttk.Button(footer, text="▷  Tutorial em vídeo", style="Setup.TButton",
               command=wizard._open_setup_tutorial).pack(side="left")

    def cancel():
        if str(wizard.install_button.cget("state")) == "disabled":
            messagebox.showinfo("SENTRA Setup", "Aguarde a etapa em andamento terminar antes de fechar o instalador.", parent=root)
        else:
            root.destroy()

    wizard.install_button = ttk.Button(footer, text="Instalar e configurar  →", style="Primary.TButton", command=wizard._primary_action)
    wizard.install_button.pack(side="right")
    ttk.Button(footer, text="Cancelar", style="Setup.TButton", command=cancel).pack(side="right", padx=(0, 10))
    root.protocol("WM_DELETE_WINDOW", cancel)

    viewport = tk.Canvas(right, background=BG, highlightthickness=0)
    scrollbar = ttk.Scrollbar(right, orient="vertical", command=viewport.yview)
    scrollbar.pack(side="right", fill="y")
    viewport.pack(fill="both", expand=True)
    viewport.configure(yscrollcommand=scrollbar.set)
    content = tk.Frame(viewport, background=BG, padx=28, pady=26)
    slot = viewport.create_window(0, 0, window=content, anchor="nw")
    wraps = []

    def resize(event):
        viewport.itemconfigure(slot, width=event.width)
        for label, offset in wraps:
            label.configure(wraplength=max(220, event.width-offset))

    def scroll(_event=None):
        viewport.configure(scrollregion=viewport.bbox("all"))

    viewport.bind("<Configure>", resize)
    content.bind("<Configure>", scroll)

    def wheel(event):
        if event.widget.winfo_toplevel() == root and viewport.bbox("all")[3] > viewport.winfo_height():
            viewport.yview_scroll(-int(event.delta / 120), "units")

    root.bind("<MouseWheel>", wheel, add="+")

    def label(parent, text=None, *, size=10, bold=False, muted=False, wrap=False, **options):
        item = tk.Label(parent, text=text, background=BG, foreground=MUTED if muted else INK,
                        font=("Segoe UI", size, "bold" if bold else "normal"), anchor="w", justify="left", **options)
        if wrap:
            item.configure(wraplength=650)
            wraps.append((item, 108))
        return item

    header = tk.Frame(content, background=BG)
    header.pack(fill="x", pady=(0, 22))
    wizard._theme = "dark"
    def toggle_theme():
        wizard._theme = "light" if wizard._theme == "dark" else "dark"
        wizard._theme_color = wizard._apply_theme(wizard._theme)
        theme_button.configure(text="Tema claro" if wizard._theme == "dark" else "Tema escuro")
        refresh()

    theme_button = ttk.Button(header, text="Tema claro", style="Setup.TButton", command=toggle_theme)
    theme_button.pack(side="right", anchor="n", padx=(12, 0))
    wizard._dot_artwork = dot_image(root)
    brand = tk.Label(header, image=wizard._dot_artwork, background=BG, borderwidth=0)
    brand.pack(side="right", padx=(16, 14))
    label(header, "SENTRA Setup", size=25, bold=True).pack(anchor="w")
    label(header, "Um clique para preparar seu ambiente de trabalho.", size=11, muted=True).pack(anchor="w", pady=(4, 0))

    local = Card(content)
    local.pack(fill="x", pady=(0, 14))
    label(local.body, "Instalar SENTRA", size=12, bold=True).pack(anchor="w")
    local_summary = tk.StringVar()
    label(local.body, textvariable=local_summary, muted=True, wrap=True).pack(anchor="w", pady=(6, 0))

    def summarize(*_args):
        scope = {"computer": "computador", "user": "usuário", "workspace": "workspace"}.get(wizard.access_scope.get(), wizard.access_scope.get())
        tools = " Todas as ferramentas habilitadas." if wizard.profile.get() == "Full" else " Ferramentas conforme o perfil selecionado."
        local_summary.set("Verificamos os arquivos, preparamos os componentes, criamos os atalhos e abrimos o SENTRA. "
                          "Não é necessário instalar Python ou Node.\n"
                          f"Perfil {wizard.profile.get()} e acesso ao {scope}.{tools}")

    wizard.profile.trace_add("write", summarize)
    wizard.access_scope.trace_add("write", summarize)
    summarize()

    connection = Card(content)
    connection.pack(fill="x", pady=(0, 14))
    connection_header = tk.Frame(connection.body, background=BG)
    connection_header.pack(fill="x")
    label(connection_header, "Conectar à OpenAI", size=12, bold=True).pack(side="left")
    label(connection_header, "OPCIONAL · MODELOS WEB", size=8, muted=True).pack(side="left", padx=12)
    wizard.openai_toggle = ttk.Button(connection_header, text="Configuração manual  ⌄", style="Setup.TButton", command=wizard._toggle_openai)
    wizard.openai_toggle.pack(side="right")
    label(connection.body, "O GPT6-WEB precisa do túnel conectado. O Setup configura a conexão pelo DOM do navegador. Login e autorização do plugin são feitos na sua conta.", muted=True, wrap=True).pack(anchor="w", pady=(4, 0))
    details = tk.Frame(connection.body, background=BG)
    fields = tk.Frame(details, background=BG)
    fields.pack(fill="x")
    fields.columnconfigure(1, weight=1)
    label(fields, "Tunnel ID").grid(row=0, column=0, sticky="w", padx=(0, 18), pady=5)
    tunnel_entry = ttk.Entry(fields, textvariable=wizard.tunnel_id)
    tunnel_entry.grid(row=0, column=1, sticky="ew", pady=5)
    label(fields, "Runtime API key").grid(row=1, column=0, sticky="w", padx=(0, 18), pady=5)
    key_row = tk.Frame(fields, background=BG)
    key_row.grid(row=1, column=1, sticky="ew", pady=5)
    key_entry = ttk.Entry(key_row, textvariable=wizard.runtime_key, show="•")
    key_entry.pack(side="left", fill="x", expand=True)

    def reveal():
        visible = bool(key_entry.cget("show"))
        key_entry.configure(show="" if visible else "•")
        show_key.configure(text="Ocultar" if visible else "Mostrar")

    show_key = ttk.Button(key_row, text="Mostrar", style="Setup.TButton", command=reveal)
    show_key.pack(side="right", padx=(8, 0))
    links = tk.Frame(details, background=BG)
    links.pack(fill="x", pady=(8, 8))
    from sentra_remote.onboarding import OPENAI_TUNNELS_URL, OPENAI_API_KEYS_URL
    ttk.Button(links, text="↗  OpenAI Tunnels", style="Setup.TButton", command=lambda: webbrowser.open(OPENAI_TUNNELS_URL)).pack(side="left", padx=(0, 8))
    ttk.Button(links, text="↗  Runtime API Keys", style="Setup.TButton", command=lambda: webbrowser.open(OPENAI_API_KEYS_URL)).pack(side="left")
    consent = ttk.Checkbutton(connection.body, text="Conectar minha conta automaticamente pelo navegador", variable=wizard.browser_setup_var)
    consent.pack(anchor="w")
    from .browser_enrollment_session import setup_browser_choices
    wizard.browser_choices = setup_browser_choices()
    preferred = next(iter(wizard.browser_choices))
    wizard.browser_choice = tk.StringVar(value=preferred)
    label(connection.body, "Navegador da configuração", muted=True).pack(anchor="w", pady=(8, 4))
    browser_selector = ttk.Combobox(connection.body, state="readonly", textvariable=wizard.browser_choice,
                                   values=list(wizard.browser_choices), width=39)
    browser_selector.pack(anchor="w")
    label(connection.body, "O navegador integrado mantém as contas conectadas e reaparece quando você precisa entrar ou autorizar. Navegadores externos são uma opção avançada.", muted=True, wrap=True, size=9).pack(anchor="w", pady=(4, 0))
    wizard.connection_test_prompt = ""
    wizard.copy_connection_test = ttk.Button(connection.body, text="Copiar teste de conexão",
        command=lambda: (root.clipboard_clear(), root.clipboard_append(wizard.connection_test_prompt)))
    connect_button = ttk.Button(connection.body, text="Configurar / verificar conexão", style="Setup.TButton",
                                command=wizard._primary_action)
    connect_button.pack(anchor="w", pady=(6, 0))
    models_button = ttk.Button(details, text="Diagnóstico dos modelos Web (avançado)", style="Setup.TButton",
                               command=wizard._open_web_models)
    models_button.pack(anchor="w", pady=(6, 0))
    label(connection.body, "Ao marcar, você autoriza criar ou selecionar o túnel e criar uma chave com todas as permissões, sem expiração. A chave é protegida neste Windows. Login e verificações da conta permanecem com você.", muted=True, wrap=True, size=9).pack(anchor="w", pady=(4, 0))
    wizard.openai_fields = [details]
    wizard.openai_expanded = False

    ready = Card(content, padding=16)
    ready.pack(fill="x", pady=(0, 14))
    wizard._ready_heading = label(ready.body, "Pronto para instalar", size=11, bold=True)
    wizard._ready_heading.pack(anchor="w")
    display_status = tk.StringVar(value="Instale o aplicativo. A conexão Web pode ser configurada agora ou depois.")
    label(ready.body, textvariable=display_status, muted=True, wrap=True).pack(anchor="w", pady=(4, 8))
    wizard.progress_bar = ttk.Progressbar(ready.body, variable=wizard.progress_value, maximum=100, style="Setup.Horizontal.TProgressbar")
    wizard.progress_bar.pack(fill="x")
    wizard.connect_hint = label(ready.body, "A conexão só será considerada pronta após verificar MCP e túnel. Seus projetos são preservados.", muted=True, wrap=True, size=9)
    wizard.connect_hint.pack(anchor="w", pady=(8, 0))

    advanced = Card(content, padding=16)
    advanced.pack(fill="x")
    wizard.advanced_button = ttk.Button(advanced.body, text="⚙  Opções avançadas  ⌄", style="Setup.TButton", command=wizard._toggle_advanced)
    wizard.advanced_button.pack(anchor="w")
    wizard.advanced_frame = tk.Frame(advanced.body, background=BG)
    form = wizard.advanced_frame
    form.columnconfigure(1, weight=1)
    controls = [tunnel_entry, key_entry, show_key, consent, connect_button, models_button, browser_selector]

    def browse(variable):
        chosen = filedialog.askdirectory(parent=root, title="Escolher pasta", initialdir=variable.get() or None)
        if chosen:
            variable.set(chosen)

    for row, (title, variable) in enumerate((("Pasta de instalação", wizard.install_dir), ("Workspace inicial", wizard.workspace))):
        label(form, title).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 16))
        entry = ttk.Entry(form, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=5)
        button = ttk.Button(form, text="Procurar…", style="Setup.TButton", command=lambda var=variable: browse(var))
        button.grid(row=row, column=2, padx=(8, 0), pady=5)
        controls.extend((entry, button))
    for row, (title, variable, choices) in enumerate((("Perfil", wizard.profile, ("Safe", "Developer", "Full")), ("Acesso a arquivos", wizard.access_scope, ("workspace", "user", "computer"))), start=2):
        label(form, title).grid(row=row, column=0, sticky="w", pady=5)
        combo = ttk.Combobox(form, textvariable=variable, values=choices, state="readonly")
        combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
        controls.append(combo)
    for row, (title, variable) in enumerate((("Instalar Git agora (opcional)", wizard.git_var), ("Instalar Docker Desktop agora (opcional)", wizard.docker_var)), start=4):
        check = ttk.Checkbutton(form, text=title, variable=variable)
        check.grid(row=row, column=0, columnspan=3, sticky="w")
        controls.append(check)
    label(form, "Git e Docker também podem ser instalados sob demanda.", muted=True, size=9).grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
    def refresh(*_args):
        busy = str(wizard.install_button.cget("state")) == "disabled"
        percent = wizard.progress_value.get()
        state_text = wizard.status.get()
        connecting = wizard._installed or state_text.startswith(("Connecting OpenAI", "Step 2 of 3"))
        active = 2 if percent == 100 else (1 if busy and connecting else 0)
        for i, shape in enumerate(wizard._step_shapes):
            sidebar.itemconfigure(shape, fill=wizard._theme_color(BLUE if i == active else "#dfe7f2"))
            sidebar.itemconfigure(wizard._step_numbers[i], fill="#ffffff" if i == active else wizard._theme_color(INK))
        for control in controls:
            control.state(["disabled"] if busy else ["!disabled"])
        if busy:
            key_entry.configure(show="•")
            show_key.configure(text="Mostrar")
        translations = {
            "Install SENTRA — local use works without OpenAI": "Instale o SENTRA; a conexão Web é opcional.",
            "Preparing installation": "Preparando a instalação…",
            "Installing SENTRA components": "Instalando os componentes do SENTRA…",
            "Installing secure tunnel client": "Instalando o cliente de conexão segura…",
            "Applying local settings": "Aplicando as configurações locais…",
            "Connecting OpenAI secure tunnel": "Conectando o túnel seguro da OpenAI…",
            "Registering SENTRA for this Windows user": "Criando atalhos e registrando o SENTRA…",
            "Connect & Verify": "Iniciando e verificando os serviços…",
            "Ready": "Serviços verificados. Configuração concluída.",
            "Installed — local services need attention": "Instalado. Os serviços locais precisam de atenção.",
            "SENTRA installed. Local tools are available; connect ChatGPT later if desired.": "SENTRA instalado. As ferramentas locais estão disponíveis.",
        }
        display_status.set(translations.get(state_text, state_text))
        wizard._ready_heading.configure(text="Instalação concluída" if percent == 100 else ("Configurando o SENTRA…" if busy else "Pronto para instalar"))
        button_text = wizard.install_button.cget("text")
        if button_text == "Finish":
            wizard.install_button.configure(text="Concluir  ✓")
        elif button_text == "Retry Connect OpenAI":
            wizard.install_button.configure(text="Tentar conexão novamente  →")

    def schedule(*_args):
        root.after_idle(refresh)

    wizard._apply_theme = theme_controller(root, style)
    wizard._theme_color = wizard._apply_theme("dark")
    wizard.status.trace_add("write", schedule)
    wizard.progress_value.trace_add("write", schedule)
    refresh()
