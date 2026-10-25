from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

from sentra_remote.managed_enrollment import ManagedEnrollmentContext, wait_for_platform_login


def test_two_setup_pages_use_one_owned_embedded_session_and_fixed_commands(tmp_path):
    calls = []
    def control(action, value):
        calls.append((action, value))
        return {"ok": True, "result": "session-123" if value["operation"] == "open" else True}
    launcher = Mock(runtime_control=control)
    context = ManagedEnrollmentContext(SimpleNamespace(), launcher=launcher)
    first, second = context.new_page(), context.new_page()
    assert first.tab == second.tab == "session-123"
    second.get_by_role("textbox", name="Name").fill("SENTRA")
    command = calls[-1][1]
    assert command["operation"] == "dom" and command["dom_action"] == "fill"
    assert "script" not in command and "cookies" not in command
    first.close()
    assert not context.closed  # Closing a stage doesn't log out the shared profile.
    context.close(); context.close()
    assert sum(value["operation"] == "open" for _, value in calls) == 1
    assert sum(value["operation"] == "close" for _, value in calls) == 1
    launcher.start.assert_called_once_with(hidden=True, browser_host_only=True)


def test_platform_waits_for_user_login_instead_of_closing_on_auth_redirect():
    page = Mock(url="https://auth.openai.com/login")
    page.is_closed.return_value = False
    page.wait_for_timeout.side_effect = lambda _: setattr(page, "url", "https://platform.openai.com/settings/organization/tunnels")
    notify = Mock()
    wait_for_platform_login(page, Event(), notify, timeout_s=2)
    notify.assert_called_once()
    page.goto.assert_not_called()


def test_readiness_retries_but_uncertain_open_is_never_replayed():
    calls = []
    def control(action, value):
        calls.append(value["operation"])
        if value["operation"] == "open":
            raise TimeoutError("response lost after possible open")
        return {"ok": True, "result": True}
    import pytest
    with pytest.raises(TimeoutError):
        ManagedEnrollmentContext(SimpleNamespace(), launcher=Mock(runtime_control=control))
    assert calls == ["status", "open"]


def test_double_click_account_setup_does_not_create_two_enrollments(tmp_path, monkeypatch):
    import time
    from sentra_remote.account_setup import start_account_setup, setup_status
    from sentra_remote.product import ProductPaths
    from sentra_remote import openai_auto_setup
    entered, finish = Event(), Event()
    count = []
    def enrollment(paths, notify, **kwargs):
        count.append(1); entered.set(); finish.wait(2)
        return {"ok": True, "mcp_roundtrip_verified": True, "reason": "mcp_roundtrip_verified"}
    monkeypatch.setattr(openai_auto_setup, "run_setup_enrollment", enrollment)
    paths = ProductPaths(tmp_path / "install", tmp_path / "state")
    start_account_setup(paths)
    assert entered.wait(1)
    assert start_account_setup(paths)["running"] is True
    finish.set()
    deadline = time.monotonic() + 2
    while setup_status(paths)["running"] and time.monotonic() < deadline:
        time.sleep(.01)
    assert setup_status(paths)["state"] == "verified"
    assert len(count) == 1
