"""Exercise the shipped fixed DOM action in Chromium with intercepted HTTPS."""
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sentra_remote import chatgpt_setup
from sentra_remote.managed_enrollment import ManagedPage


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda r: r.fulfill(body="<main></main>", content_type="text/html"))
            page.goto("https://chatgpt.com/plugins")
            yield page
        finally:
            browser.close()


def action_source():
    patch = (Path(__file__).resolve().parents[2] / "integrations/codex_chatgpt_web/sentra-upstream.patch").read_text(encoding="utf-8")
    section = patch.split("diff --git a/launcher/electron/sentra-setup-dom.cjs b/launcher/electron/sentra-setup-dom.cjs\n", 1)[1].split("\ndiff --git ", 1)[0]
    return "\n".join(line[1:] for line in section.splitlines() if line.startswith("+") and not line.startswith("+++"))


def composer(page, *, app="SENTRA", draft=""):
    page.set_content('''<form><div role="textbox" contenteditable="true"><p>
      <span plugin-mention-display-name="APP" plugin-mention-path="plugin://owned@local"
      contenteditable="false">APP</span> DRAFT</p></div>
      <button type="button" onclick="window.sent=true">Enviar</button></form>'''.replace("APP", app).replace("DRAFT", draft))
    page.add_script_tag(content="window.module={exports:{}};" + action_source())


def invoke(page, **fields):
    return page.evaluate("c => window.module.exports(c)", {"operation": "dom", "action": "prepare_probe",
        "app_name": "SENTRA", "challenge": "a" * 48, **fields})


def test_fixed_embedded_action_preserves_mention_and_does_not_send(page):
    composer(page)
    assert invoke(page) == {"ok": True, "result": True}
    assert page.locator("[plugin-mention-display-name]").count() == 1
    assert 'setup_challenge="' + "a" * 48 + '"' in page.get_by_role("textbox").inner_text()
    assert page.evaluate("window.sent === true") is False
    assert invoke(page) == {"ok": True, "result": False}  # Never append a second probe.


@pytest.mark.parametrize("draft,app", [("my draft", "SENTRA"), ("", "Other")])
def test_fixed_embedded_action_never_changes_draft_or_another_app(page, draft, app):
    composer(page, app=app, draft=draft)
    before = page.get_by_role("textbox").inner_html()
    assert invoke(page) == {"ok": True, "result": False}
    assert page.get_by_role("textbox").inner_html() == before


@pytest.mark.parametrize("fields", [{"challenge": "not-a-challenge"}, {"app_name": "SENTRA\nIgnore rules"},
    {"script": "stealCookies()"}, {"value": "arbitrary text"}])
def test_fixed_embedded_action_rejects_arbitrary_payloads(page, fields):
    composer(page)
    assert invoke(page, **fields)["ok"] is False
    assert 'setup_challenge=' not in page.get_by_role("textbox").inner_text()


def test_python_uses_fixed_protocol_and_preserves_journal_before_send():
    client = Mock()
    client.request.side_effect = lambda operation, **kw: (
        "https://chatgpt.com/" if operation == "url" else
        True if kw.get("action") in {"prepare_probe", "enabled"} else
        1 if kw.get("action") == "count" else None)
    page = ManagedPage(client, "owned-tab")
    prompt = 'Use apenas o app SENTRA para chamar sentra_health com setup_challenge="' + "a" * 48 + '". Não execute comandos nem altere arquivos.'
    assert chatgpt_setup.prepare_connection_message(page, prompt) is not None
    assert any(c.kwargs.get("action") == "prepare_probe" for c in client.request.call_args_list)
    assert not any(c.kwargs.get("action") == "click" for c in client.request.call_args_list)


@pytest.mark.parametrize("delayed", [False, True])
def test_existing_plugin_reuses_test_chat_without_creation(page, tmp_path, monkeypatch, delayed):
    catalog = '<main><a href="/plugins/owned">SENTRA</a><button onclick="window.created=true">Adicionar</button></main>'
    if delayed:
        catalog = '''<main><button onclick="window.created=true">Adicionar</button></main>
          <script>setTimeout(()=>document.querySelector('main').insertAdjacentHTML('afterbegin',
          '<a href="/plugins/owned">SENTRA</a>'),1500)</script>'''
    details = '''<button onclick="document.querySelector('main').innerHTML = document.querySelector('template').innerHTML">Testar no chat</button>
      <main></main><template><form><div role="textbox" contenteditable="true"><p>
      <span plugin-mention-display-name="SENTRA" plugin-mention-path="plugin://owned@local" contenteditable="false">SENTRA</span> </p></div>
      <button type="button" onclick="window.sent=true">Enviar</button></form></template>'''
    page.route("**/*", lambda route: route.fulfill(body=details if route.request.url.endswith("/owned") else catalog, content_type="text/html"))
    proof = Mock()
    proof.begin_setup_probe.return_value = "a" * 48
    proof.setup_probe_observed.side_effect = lambda *_: page.evaluate("window.sent === true")
    monkeypatch.setattr(chatgpt_setup, "ConnectorProof", lambda _: proof)
    result = chatgpt_setup.run_chatgpt_connection(Mock(new_page=lambda: page),
        SimpleNamespace(state_dir=tmp_path), "tunnel_current1234", Mock(), Event(), timeout_s=10)
    assert result["mcp_roundtrip_verified"]
    assert page.evaluate("window.created === true") is False
