"""Local checkout update is distinct from signed, staged installed release."""
from pathlib import Path
from types import SimpleNamespace

from sentra_canvas import native_refresh as refresh


def test_check_all_detects_outdated_native_executable(tmp_path, monkeypatch):
    (tmp_path / "sentra_canvas").mkdir()
    source = tmp_path / "sentra_canvas" / "shell_dot_vm.py"
    source.write_text("ready = True\n", encoding="utf-8")
    (tmp_path / "dist").mkdir()
    exe = tmp_path / "dist" / "sentra-canvas.exe"
    exe.write_bytes(b"old-native")
    import os
    base = exe.stat().st_mtime_ns
    os.utime(source, ns=(base + 5_000_000, base + 5_000_000))
    monkeypatch.setattr(refresh, "check", lambda _: {"safe": True, "frontend_stale": False})
    status = refresh.check_all(tmp_path)
    assert status["native_executable_stale"] is True
    assert status["installed_update_available"] is False
    assert status["installed_version_changed"] is False
    assert status["kind"] == "local_checkout_update"


def test_apply_all_refuses_busy_ledger_and_never_restarts(monkeypatch, tmp_path):
    monkeypatch.setattr(refresh, "check_all", lambda _: {
        "safe": False, "reason": "active owner operations", "frontend_stale": False
    })
    monkeypatch.setattr(refresh, "apply", lambda _: (_ for _ in ()).throw(
        AssertionError("should not build when busy")))
    value = refresh.apply_all(tmp_path)
    assert value["status"] == "blocked"
    assert "active owner operations" in value["reason"]


def test_apply_all_restarts_verified_broker_without_touching_vms(monkeypatch, tmp_path):
    from sentra_canvas import broker
    import sys
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(refresh, "check_all", lambda _: {
        "safe": True, "frontend_stale": False, "native_executable_stale": True
    })
    monkeypatch.setattr(refresh, "_canvas_runtime_idle", lambda _: True)
    events = []
    old = SimpleNamespace(server_port=65430, runtime_id="old", request=lambda path, body=None:
        events.append(("old", path)) or {"requested": True})
    new = SimpleNamespace(server_port=65430, runtime_id="new", request=lambda path, body=None:
        events.append(("new", path)) or {"ok": True})
    sequence = iter([old, None])
    monkeypatch.setattr(broker, "read_endpoint", lambda path: next(sequence))
    monkeypatch.setattr(broker, "connect_or_start", lambda *args, **kwargs:
        events.append(("connect", "new-owner")) or new)
    value = refresh.apply_all(tmp_path)
    assert value["status"] == "local_code_updated"
    assert value["broker_restarted"] is True
    assert value["installed_version_changed"] is False
    assert value["external_services_unchanged"] is True
    assert events == [("old", "/api/runtime/shutdown"),
                      ("connect", "new-owner"), ("new", "/api/health")]


def test_apply_all_never_claims_full_release(monkeypatch, tmp_path):
    from sentra_canvas import broker
    monkeypatch.setattr(refresh, "check_all", lambda _: {
        "safe": True, "frontend_stale": False, "native_executable_stale": True
    })
    monkeypatch.setattr(refresh, "_canvas_runtime_idle", lambda _: True)
    old = SimpleNamespace(server_port=65430, runtime_id="same", request=lambda *_args, **_kwargs: {"requested": True})
    sequence = iter([old, None])
    monkeypatch.setattr(broker, "read_endpoint", lambda _: next(sequence))
    new = SimpleNamespace(server_port=65430, runtime_id="same", request=lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(broker, "connect_or_start", lambda *_a, **_kw: new)
    status = refresh.apply_all(tmp_path)
    assert status["status"] == "uncertain"
    assert status["installed_version_changed"] is False
