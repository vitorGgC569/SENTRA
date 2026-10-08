"""Real independent Windows desktop window powered by system WebView2.

The application owns the HWND/window lifecycle; no browser tab, Edge profile,
or Maestri application is required.
"""
from __future__ import annotations

import threading


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
                self._window.maximize()
            self._maximized = not self._maximized
        return self._maximized

    def close(self):
        if self._window is not None:
            self._window.destroy()
        return True


def launch_native(server, *, serve=True) -> None:
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "pywebview is required for the native SENTRA desktop. "
            "Install pywebview or use --no-open for API-only mode."
        ) from exc
    url = f"http://127.0.0.1:{server.server_port}/native.html#token={server.secret}"
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
        controls = WindowControls()
        window = webview.create_window(
            "SENTRA",
            url=url,
            js_api=controls,
            width=1280,
            height=760,
            min_size=(1024,650),
            maximized=False,
            frameless=True,
            # Only .pywebview-drag-region in the titlebar moves the HWND.
            # Global easy_drag consumes canvas pans and terminal selections.
            easy_drag=False,
            background_color="#18181a",
            resizable=True,
            text_select=True,
            zoomable=False,
        )
        controls._window = window
        webview.start(gui="edgechromium", debug=False, private_mode=True)
    finally:
        if thread is not None:
            server.shutdown()
            thread.join(timeout=4)
