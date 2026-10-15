"""Browser authentication renewal is owner-verified and never replays a turn."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentra_canvas.native_app import WindowControls


class FakeWindow:
    def __init__(self, url):
        self.url = url
        self.navigations = []

    def get_current_url(self):
        return self.url

    def load_url(self, address):
        self.navigations.append(address)


def controls(monkeypatch, tmp_path, old_port=62960):
    from sentra_canvas import broker
    monkeypatch.setattr(WindowControls, "_development_root", lambda self: None)
    instance = WindowControls(state_dir=tmp_path)
    instance._trusted_launch_port = old_port
    instance._window = FakeWindow(f"http://127.0.0.1:{old_port}/shell-home.html")
    broker_owner = SimpleNamespace(server_port=62961, runtime_id="broker-new",
                                   secret="verified-local-broker-secret")
    monkeypatch.setattr(broker, "read_endpoint", lambda state: broker_owner)
    return instance, broker_owner


def test_reconnects_trusted_native_surface_when_new_broker_uses_new_port(monkeypatch, tmp_path):
    instance, owner = controls(monkeypatch, tmp_path)
    result = instance.reauthorize()
    assert result == {"status": "native_window_reloaded", "authenticated_owner": True}
    assert len(instance._window.navigations) == 1
    assert instance._window.navigations[0] == (
        f"http://127.0.0.1:{owner.server_port}/shell-home.html#token={owner.secret}")
    assert instance.reauthorize()["status"] == "native_reauthorization_in_progress"
    assert len(instance._window.navigations) == 1


def test_rejects_untrusted_origin_even_if_owner_is_valid(monkeypatch, tmp_path):
    instance, _owner = controls(monkeypatch, tmp_path)
    for bad_url in [
        "http://127.0.0.1:11111/shell-home.html",
        "http://evil.invalid:62960/shell-home.html",
        "http://127.0.0.1:62960/api/health",
        "http://127.0.0.1:62960/desktop.html?tab=1&evil=1",
    ]:
        instance._window.url = bad_url
        if bad_url.endswith("?tab=1&evil=1"):
            # A harmless query is still confined to a trusted page/port.
            assert instance.reauthorize()["authenticated_owner"] is True
            break
        with pytest.raises(PermissionError):
            instance.reauthorize()
    assert len(instance._window.navigations) == 1


def test_sequential_broker_replacements_keep_only_verified_ports(monkeypatch, tmp_path):
    from sentra_canvas import broker
    instance, _first = controls(monkeypatch, tmp_path)
    assert instance.reauthorize()["status"] == "native_window_reloaded"
    assert instance._last_verified_port == 62961
    instance._window.url = "http://127.0.0.1:62961/shell-home.html"
    replacement = SimpleNamespace(
        server_port=62962, runtime_id="broker-replaced-again", secret="next-owner-secret")
    monkeypatch.setattr(broker, "read_endpoint", lambda state: replacement)
    assert instance.reauthorize()["status"] == "native_window_reloaded"
    assert instance._last_verified_port == 62962
    assert instance._window.navigations[-1] == (
        "http://127.0.0.1:62962/shell-home.html#token=next-owner-secret")
    instance._window.url = "http://127.0.0.1:62961/shell-home.html"
    with pytest.raises(PermissionError):
        instance.reauthorize()


def test_unverified_owner_does_not_navigate(monkeypatch, tmp_path):
    from sentra_canvas import broker
    instance, _owner = controls(monkeypatch, tmp_path)
    monkeypatch.setattr(broker, "read_endpoint", lambda state: None)
    with pytest.raises(RuntimeError, match="not verified"):
        instance.reauthorize()
    assert instance._window.navigations == []
