"""Real independent Windows desktop window powered by system WebView2.

The application owns the HWND/window lifecycle; no browser tab, Edge profile,
or Maestri application is required.
"""
from __future__ import annotations

import threading
from pathlib import Path


class WindowControls:
    """Minimal native window actions exposed to the local signed-in WebView."""

    def __init__(self, *, state_dir=None):
        # Broker state is selected only by the trusted process launcher.
        # Renderer JS must never choose its credential store or port.
        self._state_dir = Path(state_dir).resolve() if state_dir is not None else None
        # pywebview recursively reflects public objects. Keeping the native
        # Window private prevents exposing its DOM and OS lifecycle methods,
        # whose properties can also block bridge initialization.
        self._window = None
        self._maximized = False
        self._auth_navigation_lock = threading.Lock()
        self._auth_last_target = None
        self._auth_last_attempt = 0.0
        # Bound to the trusted initial native launch, never to a renderer URL.
        self._trusted_launch_port = None
        self._last_verified_port = None
        self._backend_source_baseline_ns = None
        # Record which Python sources the current native window was launched
        # against. Merely having a stale installed EXE is not an update offer.
        root = self._development_root()
        if root is not None:
            from .native_refresh import _backend_source_mtime
            self._backend_source_baseline_ns = _backend_source_mtime(root)

    def minimize(self):
        if self._window is not None:
            self._window.minimize()
        return True

    def toggle_maximize(self):
        if self._window is not None:
            if self._native_maximized():
                self._window.restore()
                self._maximized = False
            else:
                self._set_maximized_bounds()
                self._window.maximize()
                self._maximized = True
        return self._maximized

    def _native_maximized(self):
        import os
        native = getattr(self._window, 'native', None)
        if os.name != 'nt' or native is None:
            return self._maximized
        from System import Action
        from System.Windows.Forms import FormWindowState
        state = []
        native.Invoke(Action(lambda: state.append(native.WindowState == FormWindowState.Maximized)))
        return state[0]

    def _set_maximized_bounds(self):
        # Borderless WinForms windows otherwise cover the taskbar. Compute the
        # working area on the current monitor each time, on the native UI thread.
        import os
        native = getattr(self._window, 'native', None)
        if os.name == 'nt' and native is not None:
            from System import Action
            from System.Drawing import Rectangle
            from System.Windows.Forms import Screen

            def configure():
                screen = Screen.FromControl(native)
                area = screen.WorkingArea
                # WinForms interprets MaximizedBounds relative to the monitor.
                # Absolute negative monitor origins would be applied twice.
                native.MaximizedBounds = Rectangle(
                    area.X - screen.Bounds.X, area.Y - screen.Bounds.Y,
                    area.Width, area.Height,
                )

            native.Invoke(Action(configure))

    def close(self):
        if self._window is not None:
            self._window.destroy()
        return True

    def _development_root(self):
        """Resolve only the authorized local source checkout, not PyInstaller _MEIPASS."""
        import sys
        source = Path(__file__).resolve().parents[1]
        if getattr(sys, "frozen", False):
            installed = Path(sys.executable).resolve().parent
            candidates = [installed.parent] if installed.name.casefold() == "dist" else []
        else:
            candidates = [source]
        return next((p for p in candidates if (p / "sentra_canvas" / "desktop_ui" / "package.json").is_file()
                     and (p / "scripts" / "commander" / "build_canvas.py").is_file()), None)

    def check_update_notification(self):
        """Read-only trigger for a visible, explicitly approved local update."""
        import sys
        root = self._development_root()
        if getattr(sys, "frozen", False) or root is None:
            return {"kind": "installed_release", "available": False,
                    "action": None, "installed_update_available": False,
                    "reason": "Atualizações instaladas exigem um pacote assinado."}
        if self._backend_source_baseline_ns is None:
            return {"kind": "local_checkout_code", "available": False,
                    "action": None, "installed_update_available": False,
                    "reason": "Não foi possível identificar o código carregado na abertura."}
        from .native_refresh import available_local_update
        baseline = self._backend_source_baseline_ns
        # The persistent broker may have been running before this window was
        # opened; compare source timestamps with that verified owner's start.
        from .broker import read_endpoint
        owner_state = self._state_dir or root / ".sentra" / "canvas"
        endpoint = read_endpoint(owner_state)
        if endpoint is not None:
            health = endpoint.request("/api/health")
            started = health.get("runtime_started_at_ns")
            if type(started) is int and started > 0:
                baseline = min(baseline, started)
        return available_local_update(
            root, running_backend_source_ns=baseline)

    def check_full_updates(self):
        root = self._development_root()
        if root is None:
            return {"status": "blocked", "reason": "Esta instalação precisa de um pacote de atualização verificado."}
        from .native_refresh import check_all
        return check_all(root)

    def apply_full_updates(self):
        root = self._development_root()
        if root is None:
            return {"status": "blocked", "reason": "Sem checkout local. Use o atualizador de pacotes assinados."}
        # Avoid rotating the authenticated broker on a no-op click. The
        # detector compares code against both this window and the owner.
        update = self.check_update_notification()
        if update.get("kind") == "local_checkout_code" and not update.get("available"):
            return {"status": "unchanged", "broker_restarted": False,
                    "installed_version_changed": False,
                    "reason": "Código local atualizado; broker preservado."}
        from .native_refresh import apply_all
        result = apply_all(root)
        if result.get("status") == "local_code_updated" and result.get("broker_restarted") is True:
            from .native_refresh import _backend_source_mtime
            self._backend_source_baseline_ns = _backend_source_mtime(root)
            # The JS bridge promise can be stranded when its broker is
            # replaced. Navigation must not depend on that promise resolving.
            # Only the authenticated native owner knows the new bearer.
            if self._window is not None:
                def reattach_owner_after_restart():
                    try:
                        self.reauthorize()
                    except (OSError, RuntimeError, PermissionError, ValueError):
                        # No repeat of apply/POST. The explicit UI watchdog
                        # handles a failed native navigation separately.
                        pass
                timer = threading.Timer(0.5, reattach_owner_after_restart)
                timer.daemon = True
                timer.start()
                result["native_navigation_scheduled"] = True
        return result

    def check_code_updates(self):
        from .native_refresh import check
        root = self._development_root()
        if root is None:
            return {"status": "blocked", "safe": False,
                    "reason": "Nenhum checkout local verificado; atualização instalada requer pacote assinado."}
        return check(root)

    def apply_code_updates(self):
        from .native_refresh import apply
        root = self._development_root()
        if root is None:
            return {"status": "blocked", "reason": "Nenhum checkout local verificado."}
        return apply(root)

    def reauthorize(self):
        """Reattach this native window to the current owner after a broker restart.

        Tokens stay inside Python/OS protected broker state. Neither the
        native API return value nor the DOM receives the bearer. Only the
        already-open trusted loopback SENTRA surface may request reattachment.
        Never submit/retry a failed mutation as part of authentication.
        """
        import time
        from urllib.parse import urlsplit
        from .broker import read_endpoint

        root = self._development_root()
        if self._window is None or (self._state_dir is None and root is None):
            raise RuntimeError("SENTRA native owner binding is unavailable")
        state = self._state_dir if self._state_dir is not None else root / ".sentra" / "canvas"
        endpoint = read_endpoint(state)
        if endpoint is None:
            raise RuntimeError("SENTRA broker owner not verified")
        current = urlsplit(self._window.get_current_url() or "")
        trusted_ports = {endpoint.server_port}
        if type(self._trusted_launch_port) is int and self._trusted_launch_port > 0:
            trusted_ports.add(self._trusted_launch_port)
        if type(self._last_verified_port) is int and self._last_verified_port > 0:
            trusted_ports.add(self._last_verified_port)
        if (current.scheme != "http" or current.hostname != "127.0.0.1"
                or current.port not in trusted_ports
                or current.username is not None or current.password is not None
                or current.path not in {"/desktop.html", "/shell-home.html", "/native.html"}):
            raise PermissionError("Native authentication is confined to the trusted Canvas surface")
        # The native window can still point at the *previous* broker port.
        # An authenticated, verified new owner may be reached on a different
        # port without ever trusting an arbitrary renderer-supplied address.
        with self._auth_navigation_lock:
            if (self._auth_last_target == endpoint.runtime_id
                    and time.monotonic() - self._auth_last_attempt < 5):
                return {"status": "native_reauthorization_in_progress", "authenticated_owner": True}
            # Only the trusted initial navigation may carry the fresh token
            # in a fragment. api.js immediately consumes and removes it.
            address = (f"http://127.0.0.1:{endpoint.server_port}"
                       f"{current.path}#token={endpoint.secret}")
            self._window.load_url(address)
            # The authenticated owner may change ports repeatedly. After a
            # verified navigation the new owner becomes the trusted current
            # port, rather than trusting only the port from initial launch.
            self._last_verified_port = endpoint.server_port
            self._auth_last_target = endpoint.runtime_id
            self._auth_last_attempt = time.monotonic()
            return {"status": "native_window_reloaded", "authenticated_owner": True}

    def select_iso(self):
        if self._window is None:
            return None
        import webview
        selected = self._window.create_file_dialog(webview.FileDialog.OPEN,
            allow_multiple=False, file_types=('Imagens de sistema (*.iso)',))
        if not selected:
            return None
        path = Path(selected[0]).resolve(strict=True)
        if path.suffix.lower() != '.iso' or not path.is_file():
            raise ValueError('Selecione uma imagem ISO existente.')
        return str(path)


def resolve_surface() -> str:
    """Shell-first surface resolution with Canvas fallback.

    Home/Dots/Spaces/conversations are the primary experience; the existing
    Canvas becomes the internal orchestration view. When Prisma ships the
    shell bundle (shell-home.html), hosts prefer it; otherwise the current
    desktop bundle remains authoritative. Never a second backend.
    """
    static = Path(__file__).parent / "static"
    for name in ("shell-home.html", "desktop.html", "native.html"):
        if (static / name).is_file():
            return name
    return "desktop.html"


def staged_update_note() -> dict[str, str]:
    """Display note for staged product updates (Vitra-owned, read-only)."""
    return {
        "apply_on": "app_exit",
        "conpty_policy": "never_interrupt_live_sessions",
        "failure_policy": "remain_on_functional_version_and_allow_rollback",
    }


def launch_native(server, *, serve=True, surface: str | None = None, state_dir=None) -> None:
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "pywebview is required for the native SENTRA desktop. "
            "Install pywebview or use --no-open for API-only mode."
        ) from exc
    surface = surface or resolve_surface()
    if surface not in {"shell-home.html", "desktop.html", "native.html"}:
        raise ValueError("unknown SENTRA display surface")
    if not (Path(__file__).parent / "static" / surface).is_file():
        surface = "desktop.html" if (Path(__file__).parent / "static" / "desktop.html").is_file() else "native.html"
    url = f"http://127.0.0.1:{server.server_port}/{surface}#token={server.secret}"
    from .native_single_instance import single_native_window
    lease = single_native_window()
    if not lease.__enter__():
        lease.__exit__(None, None, None)
        return
    thread = None
    if serve:
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval":0.2},
            name="sentra-canvas-loopback",
            daemon=True,
        )
        thread.start()
    try:
        from .native_brand import configure_taskbar_identity
        configure_taskbar_identity()
        controls = WindowControls(state_dir=state_dir)
        controls._trusted_launch_port = server.server_port
        window = webview.create_window(
            "SENTRA",
            url=url,
            js_api=controls,
            width=1440,
            height=900,
            min_size=(1024,650),
            maximized=False,
            frameless=True,
            # Only .pywebview-drag-region in the titlebar moves the HWND.
            # Global easy_drag consumes canvas pans and terminal selections.
            easy_drag=False,
            background_color="#121212",
            resizable=True,
            text_select=True,
            zoomable=False,
        )
        controls._window = window
        # An .exe's embedded icon does not automatically become the icon of
        # pywebview's native WinForms HWND (or its taskbar button).
        from .native_brand import apply_native_icon
        window.events.shown += apply_native_icon
        from .native_single_instance import mark_native_window, unmark_native_window
        window.events.shown += lambda: mark_native_window(window)
        window.events.closing += lambda: unmark_native_window(window)
        webview.start(gui="edgechromium", debug=False, private_mode=True)
    finally:
        if thread is not None:
            server.shutdown()
            thread.join(timeout=4)
        lease.__exit__(None, None, None)
