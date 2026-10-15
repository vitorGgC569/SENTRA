"""Native window configuration without opening or closing a real window."""
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock
from contextlib import nullcontext
import pytest

from sentra_canvas import native_app


def test_canvas_pans_do_not_drag_window_and_titlebar_keeps_drag_region(monkeypatch):
    from sentra_canvas import native_single_instance
    monkeypatch.setattr(native_single_instance, 'single_native_window', lambda: nullcontext(True))
    # Real pywebview exposes an event hook with __iadd__, unlike a plain Mock.
    class Shown:
        def __init__(self):
            self.handlers = []
        def __iadd__(self, handler):
            self.handlers.append(handler)
            return self
    shown = Shown()
    closing = Shown()
    window = SimpleNamespace(events=SimpleNamespace(shown=shown, closing=closing))
    webview = SimpleNamespace(create_window=Mock(return_value=window), start=Mock())
    monkeypatch.setitem(sys.modules, "webview", webview)
    from sentra_canvas import native_brand
    identity = Mock()
    monkeypatch.setattr(native_brand, "configure_taskbar_identity", identity)
    order = []
    identity.side_effect = lambda: order.append("identity")
    webview.create_window.side_effect = lambda *args, **kwargs: (order.append("window") or window)
    native_app.launch_native(SimpleNamespace(server_port=1234, secret="synthetic"), serve=False)
    assert order == ["identity", "window"]
    options = webview.create_window.call_args.kwargs
    assert options["easy_drag"] is False
    assert options["frameless"] is True
    html = (Path(native_app.__file__).parent / "static" / "native.html").read_text(encoding="utf-8")
    assert html.count("pywebview-drag-region") == 1
    assert '<div class="title-drag pywebview-drag-region">' in html
    from sentra_canvas.native_brand import apply_native_icon
    assert shown.handlers[0] is apply_native_icon
    assert len(closing.handlers) == 1
    webview.start.assert_called_once()


def test_maximize_configures_working_area_before_changing_window_state(monkeypatch):
    controls = native_app.WindowControls()
    window = Mock()
    window.native = None
    controls._window = window
    configure = Mock()
    monkeypatch.setattr(controls, "_set_maximized_bounds", configure)
    order = []
    configure.side_effect = lambda: order.append("work-area")
    window.maximize.side_effect = lambda: order.append("maximize")
    assert controls.toggle_maximize() is True
    assert order == ["work-area", "maximize"]
    assert controls.toggle_maximize() is False
    window.restore.assert_called_once()
    configure.assert_called_once()


def test_maximize_uses_monitor_relative_bounds_on_negative_monitor(monkeypatch):
    controls = native_app.WindowControls()
    native = SimpleNamespace(Invoke=lambda action: action())
    controls._window = SimpleNamespace(native=native)
    screen = SimpleNamespace(
        Bounds=SimpleNamespace(X=-1920, Y=-143),
        WorkingArea=SimpleNamespace(X=-1896, Y=-123, Width=1896, Height=1012),
    )
    monkeypatch.setitem(sys.modules, 'System', SimpleNamespace(Action=lambda callback: callback))
    monkeypatch.setitem(sys.modules, 'System.Drawing', SimpleNamespace(Rectangle=lambda *bounds: bounds))
    monkeypatch.setitem(sys.modules, 'System.Windows.Forms', SimpleNamespace(
        Screen=SimpleNamespace(FromControl=lambda form: screen)))
    controls._set_maximized_bounds()
    assert native.MaximizedBounds == (24, 20, 1896, 1012)


def test_toggle_uses_real_window_state_after_external_restore(monkeypatch):
    controls = native_app.WindowControls()
    native = SimpleNamespace(WindowState='Normal', Invoke=lambda action: action())
    window = SimpleNamespace(native=native, restore=Mock(), maximize=Mock())
    controls._window = window
    controls._maximized = True
    monkeypatch.setitem(sys.modules, 'System', SimpleNamespace(Action=lambda callback: callback))
    monkeypatch.setitem(sys.modules, 'System.Windows.Forms', SimpleNamespace(
        FormWindowState=SimpleNamespace(Maximized='Maximized')))
    monkeypatch.setattr(controls, '_set_maximized_bounds', Mock())
    assert controls.toggle_maximize() is True
    window.maximize.assert_called_once()
    window.restore.assert_not_called()
    native.WindowState = 'Maximized'
    controls._maximized = False
    assert controls.toggle_maximize() is False
    window.restore.assert_called_once()


def test_native_reauthorize_rotates_owner_without_exposing_secret(monkeypatch, tmp_path):
    from sentra_canvas import broker
    import pytest
    state = tmp_path / "state"
    state.mkdir()
    controls = native_app.WindowControls(state_dir=state)
    window = SimpleNamespace(
        get_current_url=Mock(return_value="http://127.0.0.1:62960/desktop.html?sentra_updated=old"),
        load_url=Mock(),
    )
    controls._window = window
    fresh = SimpleNamespace(server_port=62960, secret="private-rotated-owner-token", runtime_id="fresh")
    monkeypatch.setattr(broker, "read_endpoint", lambda path: fresh if path == state else None)
    result = controls.reauthorize()
    assert result == {"status": "native_window_reloaded", "authenticated_owner": True}
    assert "private-rotated-owner-token" not in str(result)
    window.load_url.assert_called_once_with(
        "http://127.0.0.1:62960/desktop.html#token=private-rotated-owner-token")


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:62960/desktop.html",
    "http://localhost:62960/desktop.html",
    "http://127.0.0.1:62961/desktop.html",
    "http://127.0.0.1:62960/not-sentra.html",
    "http://127.0.0.1:62960@evil.example/desktop.html",
])
def test_native_reauthorize_rejects_untrusted_origin(monkeypatch, tmp_path, url):
    from sentra_canvas import broker
    state = tmp_path / "state"
    state.mkdir()
    controls = native_app.WindowControls(state_dir=state)
    window = SimpleNamespace(get_current_url=lambda: url, load_url=Mock())
    controls._window = window
    monkeypatch.setattr(broker, "read_endpoint", lambda _: SimpleNamespace(
        server_port=62960, secret="private-rotated-owner-token"))
    with pytest.raises(PermissionError):
        controls.reauthorize()
    window.load_url.assert_not_called()


def test_native_reauthorize_requires_verified_broker(monkeypatch, tmp_path):
    from sentra_canvas import broker
    controls = native_app.WindowControls(state_dir=tmp_path)
    controls._window = SimpleNamespace(
        get_current_url=lambda: "http://127.0.0.1:62960/desktop.html",
        load_url=Mock())
    monkeypatch.setattr(broker, "read_endpoint", lambda _: None)
    with pytest.raises(RuntimeError, match="broker owner"):
        controls.reauthorize()
    controls._window.load_url.assert_not_called()
