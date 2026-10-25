from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sentra_remote.connector_proof import ConnectorProof
from sentra_remote import chatgpt_setup, browser_enrollment_session as sessions


def test_native_selection_bypasses_healthy_web_gateway_and_preserves_selected_model(tmp_path, monkeypatch):
    from sentra_cli.client import ModelClient
    from sentra_cli.config import CLIConfig
    client = ModelClient(CLIConfig(workspace=tmp_path, openai_api_key="test-local-fixture",
                                    auto_start_gateway=True))
    monkeypatch.setattr(client, "probe_health", lambda: {"gateway": True, "openai": True, "local": False})
    web_send = Mock(side_effect=AssertionError("native model must not use Web gateway"))
    monkeypatch.setattr(client, "_responses_stream", web_send)
    monkeypatch.setattr(client, "ensure_gateway_ready", web_send)
    direct = Mock(return_value=iter(["native response"]))
    monkeypatch.setattr(client, "_chat_completions_stream", direct)
    assert "".join(client.chat_stream([{"role": "user", "content": "hello"}], model_override="gpt-6")) == "native response"
    assert direct.call_args.args[3:] == ("gpt-6", "openai")
    assert client.active_model == "gpt-6" and client.active_provider == "openai"
    web_send.assert_not_called()


def test_probe_requires_current_tunnel_exact_fresh_challenge(tmp_path, monkeypatch):
    proof = ConnectorProof(tmp_path)
    tunnel = "tunnel_current1234"
    monkeypatch.setattr(proof, "configured_tunnel_id", lambda: tunnel)
    challenge = proof.begin_setup_probe(tunnel)
    proof.record_tool(authenticated=True)  # Old/general traffic is insufficient.
    assert not proof.setup_probe_observed(challenge, tunnel)
    assert not proof.observe_setup_probe("0" * 48)
    assert not proof.setup_probe_observed(challenge, "tunnel_other12345")
    assert proof.observe_setup_probe(challenge)
    assert proof.setup_probe_observed(challenge, tunnel)
    assert not proof.observe_setup_probe(challenge)  # Single use.
    assert challenge.encode() not in proof.path.read_bytes()


def test_expired_or_changed_tunnel_cannot_confirm_setup(tmp_path, monkeypatch):
    proof = ConnectorProof(tmp_path)
    clock = [1000]
    monkeypatch.setattr("sentra_remote.connector_proof.time.time", lambda: clock[0])
    monkeypatch.setattr(proof, "configured_tunnel_id", lambda: "tunnel_other12345")
    challenge = proof.begin_setup_probe("tunnel_current1234", lifetime=2)
    assert not proof.observe_setup_probe(challenge)
    monkeypatch.setattr(proof, "configured_tunnel_id", lambda: "tunnel_current1234")
    clock[0] += 3
    assert not proof.observe_setup_probe(challenge)
    assert not proof.setup_probe_observed(challenge, "tunnel_current1234")


@pytest.mark.parametrize("url", ["http://chatgpt.com/plugins", "https://chatgpt.com.evil/plugins",
    "https://user@chatgpt.com/plugins", "https://chatgpt.com:444/plugins"])
def test_account_form_never_receives_actions_on_untrusted_origin(url):
    page = Mock(url=url)
    with pytest.raises(ValueError, match="chatgpt_login_required"):
        chatgpt_setup.prepare_app_form(page, "tunnel_current1234")
    page.get_by_role.assert_not_called()


def test_selected_chrome_uses_only_its_dedicated_setup_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "discover_browser_endpoints", lambda: [])
    playwright = Mock()
    sessions.enrollment_context(playwright, tmp_path, Mock(), browser="chrome", allow_setup_profile=True)
    args, kwargs = playwright.chromium.launch_persistent_context.call_args
    assert args == (str(tmp_path / "chrome-automation"),)
    assert kwargs["channel"] == "chrome" and kwargs["headless"] is False


def test_firefox_bridge_does_not_claim_chatgpt_permission(tmp_path):
    from sentra_remote.enrollment_bridge import ExtensionEnrollmentContext
    context = ExtensionEnrollmentContext(Mock(browser_name="firefox"))
    result = chatgpt_setup.run_chatgpt_connection(context, SimpleNamespace(state_dir=tmp_path),
                                                "tunnel_current1234", Mock(), Event())
    assert result == {"ok": False, "reason": "chatgpt_browser_required", "tunnel_verified": True}
    context.client.request.assert_not_called()


def test_ambiguous_app_dialog_is_left_for_account_owner():
    page = Mock(url="https://chatgpt.com/plugins")
    page.get_by_role.return_value.filter.return_value.count.return_value = 2
    assert not chatgpt_setup.prepare_app_form(page, "tunnel_current1234")
    page.get_by_role.return_value.fill.assert_not_called()
    page.get_by_role.return_value.click.assert_not_called()


def test_account_setup_only_finishes_after_new_probe_is_observed(tmp_path, monkeypatch):
    proof = Mock()
    proof.begin_setup_probe.return_value = "a" * 48
    proof.setup_probe_observed.side_effect = [False, True]
    monkeypatch.setattr(chatgpt_setup, "ConnectorProof", lambda _: proof)
    prepare = Mock(return_value=True)
    monkeypatch.setattr(chatgpt_setup, "prepare_app_form", prepare)
    page = Mock(url="https://chatgpt.com/plugins")
    page.is_closed.return_value = False
    context = Mock(new_page=lambda: page)
    notify = Mock()
    result = chatgpt_setup.run_chatgpt_connection(context, SimpleNamespace(state_dir=tmp_path),
        "tunnel_current1234", notify, Event(), timeout_s=5)
    assert result["ok"] and result["mcp_roundtrip_verified"]
    assert proof.setup_probe_observed.call_count == 2
    assert prepare.call_count == 1
    assert prepare.call_args.args == (page, "tunnel_current1234")
    page.get_by_role.assert_not_called()  # No automatic account approval or send.
    assert sum(call.args[0] == "verification_prompt" for call in notify.call_args_list) == 1


def test_closing_account_window_keeps_verified_tunnel_and_is_not_success(tmp_path, monkeypatch):
    proof = Mock()
    proof.begin_setup_probe.return_value = "a" * 48
    monkeypatch.setattr(chatgpt_setup, "ConnectorProof", lambda _: proof)
    page = Mock()
    page.is_closed.return_value = True
    result = chatgpt_setup.run_chatgpt_connection(Mock(new_page=lambda: page),
        SimpleNamespace(state_dir=tmp_path), "tunnel_current1234", Mock(), Event(), timeout_s=5)
    assert result == {"ok": False, "reason": "chatgpt_setup_cancelled", "tunnel_verified": True}


@pytest.fixture
def account_page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.fulfill(body="<main></main>", content_type="text/html"))
            page.goto(chatgpt_setup.CHATGPT_APPS_URL)
            yield page
        finally:
            browser.close()


@pytest.mark.parametrize("existing", ["", "tunnel_current1234"])
def test_current_account_tunnel_field_preserves_consent(account_page, existing):
    account_page.set_content('''<section role="dialog">
      <label>Nome<input id="name"></label><input aria-label="ID do túnel">
      <select aria-label="Autenticação"><option>OAuth</option><option>Sem autenticação</option></select>
      <label><input type="checkbox">Entendo e quero continuar</label>
      <button onclick="window.created=true">Criar como plugin</button></section>''')
    field = account_page.get_by_role("textbox", name="ID do túnel")
    field.fill(existing)
    assert chatgpt_setup.prepare_app_form(account_page, "tunnel_current1234")
    assert field.input_value() == "tunnel_current1234"
    assert account_page.locator("#name").input_value() == "SENTRA"
    assert account_page.get_by_role("combobox").input_value() == "OAuth"
    assert not account_page.get_by_role("checkbox").is_checked()
    assert account_page.evaluate("window.created === true") is False


def test_current_account_tunnel_field_does_not_replace_another_app(account_page):
    account_page.set_content('''<section role="dialog"><label>Nome<input value="SENTRA"></label>
      <input aria-label="Tunnel ID" value="tunnel_other12345"></section>''')
    with pytest.raises(ValueError, match="chatgpt_app_selection_required"):
        chatgpt_setup.prepare_app_form(account_page, "tunnel_current1234")
    assert account_page.get_by_role("textbox", name="Tunnel ID").input_value() == "tunnel_other12345"


def test_account_add_navigation_accepts_current_menuitem(account_page, tmp_path, monkeypatch):
    html = '''<button onclick="document.querySelector('menu').hidden=false">Adicionar</button>
      <menu role="menu" hidden><button role="menuitem" onclick="window.opened=true">
      Adicionar servidor MCP personalizado</button></menu>'''
    account_page.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html"))
    proof = Mock()
    proof.begin_setup_probe.return_value = "a" * 48
    proof.setup_probe_observed.side_effect = [False, False, True]
    monkeypatch.setattr(chatgpt_setup, "ConnectorProof", lambda _: proof)
    result = chatgpt_setup.run_chatgpt_connection(Mock(new_page=lambda: account_page),
        SimpleNamespace(state_dir=tmp_path), "tunnel_current1234", Mock(), Event(), timeout_s=10)
    assert result["mcp_roundtrip_verified"]
    assert account_page.evaluate("window.opened === true")
