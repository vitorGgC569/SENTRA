"""Cold startup must wait for health, resume once, and report current state."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sentra_remote import installer, local_runtime
from sentra_remote.product import ProductPaths, ProductSettings


@pytest.fixture
def cold(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    runtime = local_runtime.LocalRuntime(
        ProductPaths(tmp_path / "install", tmp_path / "state"), ProductSettings())
    clock = SimpleNamespace(now=0.0)
    def sleep(seconds):
        assert 0 <= seconds <= 0.2
        clock.now += seconds
    monkeypatch.setattr(local_runtime, "time", SimpleNamespace(
        monotonic=lambda: clock.now, sleep=sleep))
    monkeypatch.setattr(local_runtime, "load_tunnel_config", lambda _: {})
    monkeypatch.setattr(local_runtime, "tunnel_credential_storage", lambda _: {"ok": True})
    runtime.start_all = Mock(return_value={"mcp": {"ok": True},
        "tunnel": {"ok": False, "reason": "mcp_not_ready"}})
    runtime.start_tunnel = Mock(return_value={"ok": True, "pid": 123})
    return runtime, clock


def test_clean_install_waits_for_delayed_mcp_and_leaves_tunnel_unconfigured(cold):
    runtime, clock = cold
    runtime.status = lambda: {"mcp": {"ok": clock.now >= 55.0}, "tunnel": {"ok": False}}
    result = runtime.connect_and_verify(timeout_s=installer.SERVICE_STARTUP_TIMEOUT_S)
    assert 55.0 <= clock.now < 55.3
    assert result["core_ready"] is True
    assert result["chatgpt_onboarding"]["ready"] is False
    runtime.start_all.assert_called_once()
    runtime.start_tunnel.assert_not_called()


def test_mcp_timeout_stays_a_failure_with_bounded_wait(cold):
    runtime, clock = cold
    runtime.status = lambda: {"mcp": {"ok": False}, "tunnel": {"ok": False}}
    result = runtime.connect_and_verify(timeout_s=7.0)
    assert clock.now == pytest.approx(7.0)
    assert result["core_ready"] is False
    runtime.start_tunnel.assert_not_called()


def test_delayed_mcp_resumes_tunnel_once_and_waits_for_actual_tunnel_health(cold, monkeypatch):
    runtime, clock = cold
    monkeypatch.setattr(local_runtime, "load_tunnel_config", lambda _: {"tunnel_id": "fixture"})
    runtime.status = lambda: {"mcp": {"ok": clock.now >= 40},
                             "tunnel": {"ok": clock.now >= 50}}
    result = runtime.connect_and_verify(timeout_s=installer.SERVICE_STARTUP_TIMEOUT_S)
    assert 50 <= clock.now < 50.3
    assert result["chatgpt_onboarding"]["ready"] is True
    runtime.start_tunnel.assert_called_once()
    assert result["started"]["tunnel"]["pid"] == 123


@pytest.mark.parametrize("guard", ["mcp_identity", "mcp_policy", "credential", "reauth", "disabled", "other_failure"])
def test_deferred_tunnel_never_bypasses_health_or_credential_guards(cold, monkeypatch, guard):
    runtime, clock = cold
    monkeypatch.setattr(local_runtime, "load_tunnel_config", lambda _: {"tunnel_id": "fixture"})
    monkeypatch.setattr(local_runtime, "tunnel_credential_storage", lambda _: {"ok": guard != "credential"})
    if guard == "disabled":
        runtime.settings.autostart_tunnel = False
    if guard == "other_failure":
        runtime.start_all.return_value["tunnel"]["reason"] = "duplicate_tunnel_processes"
    runtime.status = lambda: {
        "mcp": {"ok": guard not in ("mcp_identity", "mcp_policy"),
                "detail": "instance_id_mismatch" if guard == "mcp_identity" else "runtime_policy_mismatch"},
        "tunnel": {"ok": False, "reauth_required": guard == "reauth"}}
    result = runtime.connect_and_verify(timeout_s=1.0)
    assert result["chatgpt_onboarding"]["ready"] is False
    runtime.start_tunnel.assert_not_called()
    assert clock.now == pytest.approx(1.0)


@pytest.mark.parametrize("raises", [False, True])
def test_failed_deferred_tunnel_is_not_retried_or_reported_as_healthy(cold, monkeypatch, raises):
    runtime, _ = cold
    monkeypatch.setattr(local_runtime, "load_tunnel_config", lambda _: {"tunnel_id": "fixture"})
    runtime.status = lambda: {"mcp": {"ok": True}, "tunnel": {"ok": False}}
    if raises:
        runtime.start_tunnel.side_effect = RuntimeError("PRIVATE_CREDENTIAL_CANARY")
    else:
        runtime.start_tunnel.return_value = {"ok": False, "reason": "mcp_not_ready"}
    result = runtime.connect_and_verify(timeout_s=2.0)
    runtime.start_tunnel.assert_called_once()
    assert result["chatgpt_onboarding"]["ready"] is False
    assert "CANARY" not in repr(result)


@pytest.mark.parametrize("initial,current", [(False, True), (True, False)])
def test_final_refresh_updates_health_without_losing_display_or_plugin(cold, initial, current):
    runtime, _ = cold
    runtime.status = lambda: {"mcp": {"ok": initial}}
    result = runtime.connect_and_verify(timeout_s=0.1)
    result.update(display_required=True, web_models_required=True, codex_plugin={"ready": True})
    result["status"]["display"] = {"ok": True}
    result["checks"].append({"id": "display", "required": True, "ok": True})
    runtime.start_all.reset_mock()
    runtime.status = lambda: {"mcp": {"ok": current}}
    runtime.refresh_verification(result)
    assert result["core_ready"] is current
    assert result["status"]["display"]["ok"] is True
    assert result["display_required"] and result["web_models_required"]
    assert result["codex_plugin"] == {"ready": True}
    checks = {check["id"]: check for check in result["checks"]}
    assert checks["mcp"]["ok"] is current and checks["display"]["ok"] is True
    runtime.start_all.assert_not_called()
    runtime.start_tunnel.assert_not_called()
