from pathlib import Path

from sentra_canvas.native_app import WindowControls
from sentra_canvas import native_refresh
from sentra_canvas import native_app


def test_successful_native_broker_update_schedules_owner_verified_navigation(monkeypatch, tmp_path):
    monkeypatch.setattr(WindowControls, "_development_root", lambda self: tmp_path)
    monkeypatch.setattr(native_refresh, "_backend_source_mtime", lambda root: 10)
    controls = WindowControls(state_dir=tmp_path / "state")
    controls._window = object()
    monkeypatch.setattr(controls, "check_update_notification", lambda: {
        "kind": "local_checkout_code", "available": True
    })
    monkeypatch.setattr(native_refresh, "apply_all", lambda root: {
        "status": "local_code_updated", "broker_restarted": True,
        "installed_version_changed": False
    })
    calls = []
    monkeypatch.setattr(controls, "reauthorize", lambda: calls.append("navigate"))
    class InstantTimer:
        def __init__(self, delay, callback):
            assert 0 < delay < 2
            self.callback = callback
            self.daemon = False
        def start(self):
            self.callback()
    monkeypatch.setattr(native_app.threading, "Timer", InstantTimer)
    result = controls.apply_full_updates()
    assert result["native_navigation_scheduled"] is True
    assert calls == ["navigate"]


def test_no_change_never_rotates_owner(monkeypatch, tmp_path):
    monkeypatch.setattr(WindowControls, "_development_root", lambda self: tmp_path)
    monkeypatch.setattr(native_refresh, "_backend_source_mtime", lambda root: 10)
    controls = WindowControls(state_dir=tmp_path / "state")
    monkeypatch.setattr(controls, "check_update_notification", lambda: {
        "kind": "local_checkout_code", "available": False
    })
    monkeypatch.setattr(native_refresh, "apply_all", lambda root: (_ for _ in ()).throw(
        AssertionError("No restart when no update is available")))
    assert controls.apply_full_updates()["status"] == "unchanged"
