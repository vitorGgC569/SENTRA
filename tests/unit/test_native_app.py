"""Native window configuration without opening or closing a real window."""
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from sentra_canvas import native_app


def test_canvas_pans_do_not_drag_window_and_titlebar_keeps_drag_region(monkeypatch):
    # Real pywebview exposes an event hook with __iadd__, unlike a plain Mock.
    class Shown:
        handler = None
        def __iadd__(self, handler):
            self.handler = handler
            return self
    shown = Shown()
    window = SimpleNamespace(events=SimpleNamespace(shown=shown))
    webview = SimpleNamespace(create_window=Mock(return_value=window), start=Mock())
    monkeypatch.setitem(sys.modules, "webview", webview)
    native_app.launch_native(SimpleNamespace(server_port=1234, secret="synthetic"), serve=False)
    options = webview.create_window.call_args.kwargs
    assert options["easy_drag"] is False
    assert options["frameless"] is True
    html = (Path(native_app.__file__).parent / "static" / "native.html").read_text(encoding="utf-8")
    assert html.count("pywebview-drag-region") == 1
    assert '<div class="title-drag pywebview-drag-region">' in html
    from sentra_canvas.native_brand import apply_native_icon
    assert shown.handler is apply_native_icon
    webview.start.assert_called_once()
