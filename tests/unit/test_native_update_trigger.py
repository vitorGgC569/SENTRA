"""Local update notification is read-only and cannot claim an installed update."""
from pathlib import Path
from sentra_canvas import native_refresh as refresh
from sentra_canvas.native_app import WindowControls


def test_source_trigger_distinguishes_frontend_and_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(refresh, "version_status", lambda root: {
        "frontend_stale": False, "frontend_source_time_ns": 100,
    })
    monkeypatch.setattr(refresh, "_backend_source_mtime", lambda root: 250)
    unchanged = refresh.available_local_update(tmp_path, running_backend_source_ns=250)
    assert unchanged["available"] is False
    assert unchanged["action"] is None
    assert unchanged["installed_update_available"] is False

    backend = refresh.available_local_update(tmp_path, running_backend_source_ns=180)
    assert backend["available"] is True
    assert backend["action"] == "apply_full_updates"
    assert backend["backend_changed"] is True
    assert backend["requires_confirmation"] is True

    monkeypatch.setattr(refresh, "version_status", lambda root: {
        "frontend_stale": True, "frontend_source_time_ns": 400,
    })
    frontend = refresh.available_local_update(tmp_path, running_backend_source_ns=250)
    assert frontend["available"] is True
    assert frontend["action"] == "apply_code_updates"
    assert frontend["installed_update_available"] is False

    both = refresh.available_local_update(tmp_path, running_backend_source_ns=180)
    assert both["action"] == "apply_full_updates"
    assert both["revision"] == "400:250"


def test_native_window_only_offers_a_verified_local_code_change(tmp_path, monkeypatch):
    monkeypatch.setattr(WindowControls, "_development_root", lambda self: tmp_path)
    clock = {"source": 100}
    monkeypatch.setattr(refresh, "_backend_source_mtime", lambda root: clock["source"])
    monkeypatch.setattr(refresh, "version_status", lambda root: {
        "frontend_stale": False, "frontend_source_time_ns": 10,
    })
    controls = WindowControls()
    assert controls.check_update_notification()["available"] is False
    clock["source"] = 150
    offer = controls.check_update_notification()
    assert offer["action"] == "apply_full_updates"
    assert offer["installed_update_available"] is False
    assert offer["requires_confirmation"] is True

    # An unsuccessful updater cannot reset the baseline or falsely clear an offer.
    monkeypatch.setattr(refresh, "apply_all", lambda root: {"status": "blocked"})
    assert controls.apply_full_updates()["status"] == "blocked"
    assert controls.check_update_notification()["available"] is True

    monkeypatch.setattr(refresh, "apply_all", lambda root: {
        "status": "local_code_updated", "broker_restarted": True})
    assert controls.apply_full_updates()["status"] == "local_code_updated"
    assert controls.check_update_notification()["available"] is False


def test_installed_window_never_offers_unverified_download(monkeypatch):
    monkeypatch.setattr(WindowControls, "_development_root", lambda self: None)
    controls = WindowControls()
    result = controls.check_update_notification()
    assert result["available"] is False
    assert result["action"] is None
    assert result["kind"] == "installed_release"

def test_old_broker_triggers_even_if_window_opened_after_code_changed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from sentra_canvas import broker
    monkeypatch.setattr(WindowControls, "_development_root", lambda self: tmp_path)
    monkeypatch.setattr(refresh, "_backend_source_mtime", lambda root: 300)
    monkeypatch.setattr(refresh, "version_status", lambda root: {
        "frontend_stale": False, "frontend_source_time_ns": 100,
    })
    controls = WindowControls(state_dir=tmp_path / "canvas")
    # The new window loaded current files, but the authenticated broker
    # predates them. This still requires a deliberate coordinated update.
    monkeypatch.setattr(broker, "read_endpoint", lambda state: SimpleNamespace(
        request=lambda path: {"runtime_started_at_ns": 220}))
    offer = controls.check_update_notification()
    assert offer["available"] is True
    assert offer["action"] == "apply_full_updates"
    assert offer["backend_changed"] is True

def test_frozen_executable_never_offers_checkout_rebuild(monkeypatch, tmp_path):
    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(WindowControls, "_development_root", lambda self: tmp_path)
    controls = WindowControls()
    result = controls.check_update_notification()
    assert result["available"] is False
    assert result["action"] is None
    assert result["kind"] == "installed_release"
