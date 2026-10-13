"""Real independent Windows desktop window powered by system WebView2.

The application owns the HWND/window lifecycle; no browser tab, Edge profile,
or Maestri application is required.
"""
from __future__ import annotations

import threading
from pathlib import Path


class WindowControls:
    """Minimal native window actions exposed to the local signed-in WebView."""

    def __init__(self):
        # pywebview recursively reflects public objects. Keeping the native
        # Window private prevents exposing its DOM and OS lifecycle methods,
        # whose properties can also block bridge initialization.
        self._window = None
        self._maximized = False

    def minimize(self):
        if self._window is not None:
            self._window.minimize()
        return True

    def toggle_maximize(self):
        if self._window is not None:
            if self._maximized:
                self._window.restore()
            else:
                self._set_maximized_bounds()
                self._window.maximize()
            self._maximized = not self._maximized
        return self._maximized

    def _set_maximized_bounds(self):
        # Borderless WinForms windows otherwise cover the taskbar. Compute the
        # working area on the current monitor each time, on the native UI thread.
        import os
        native = getattr(self._window, 'native', None)
        if os.name == 'nt' and native is not None:
            from System import Action
            from System.Windows.Forms import Screen

            def configure():
                native.MaximizedBounds = Screen.FromControl(native).WorkingArea

            native.Invoke(Action(configure))

    def close(self):
        if self._window is not None:
            self._window.destroy()
        return True

    def check_code_updates(self):
        # Only the local native bridge can ask the host for source/build status.
        from .native_refresh import check
        return check(Path(__file__).resolve().parents[1])

    def apply_code_updates(self):
        # No arbitrary commands, paths, approvals or provider actions supplied by JS.
        from .native_refresh import apply
        return apply(Path(__file__).resolve().parents[1])

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


def launch_native(server, *, serve=True, surface: str | None = None) -> None:
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
        controls = WindowControls()
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
        webview.start(gui="edgechromium", debug=False, private_mode=True)
    finally:
        if thread is not None:
            server.shutdown()
            thread.join(timeout=4)
        lease.__exit__(None, None, None)
