"""Bounded, visible ChatGPT app setup. No private APIs, cookies or credentials.

The account owner handles sign-in, safety prompts and authentication. We fill
only unambiguous SENTRA fields, never replace an existing app, and never infer
success from opening a page or from historical MCP traffic.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

from .connector_proof import ConnectorProof

CHATGPT_APPS_URL = "https://chatgpt.com/plugins"


def trusted_chatgpt(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname == "chatgpt.com"
                and parsed.port in (None, 443) and not parsed.username and not parsed.password)
    except ValueError:
        return False


def one_visible(locator):
    visible = locator.filter(visible=True)
    return visible if visible.count() == 1 else None


def prepare_app_form(page, tunnel_id: str, *, actions: set | None = None) -> bool:
    """Fill an exact app form; ambiguous UI and all consent stay with the user."""
    if not trusted_chatgpt(page.url):
        raise ValueError("chatgpt_login_required")
    dialog = one_visible(page.get_by_role("dialog"))
    if dialog is None:
        return False
    field = one_visible(dialog.get_by_role("textbox", name=re.compile(r"^(?:name|nome|app name|nome do app)$", re.I)))
    if field is None:
        return False
    current = field.input_value()
    if current not in ("", "SENTRA"):
        raise ValueError("chatgpt_app_selection_required")
    if not current:
        field.fill("SENTRA", timeout=3000)
    selector = one_visible(dialog.get_by_role("combobox", name=re.compile(r"tunnel|túnel", re.I)))
    if selector is None:
        tunnel_button = one_visible(dialog.get_by_role("button", name=re.compile(r"^(?:Tunnel|Túnel)$", re.I)))
        if tunnel_button is not None and (actions is None or "tunnel" not in actions):
            if actions is not None:
                actions.add("tunnel")
            tunnel_button.click(timeout=3000)
        return False
    options = selector.locator("option")
    labels = [options.nth(i).inner_text().strip() for i in range(options.count())]
    values = [options.nth(i).get_attribute("value") for i in range(options.count())]
    if values.count(tunnel_id) == 1:
        selector.select_option(value=tunnel_id, timeout=3000)
        return True
    matches = [label for label in labels if tunnel_id in label.split() or label == tunnel_id]
    if len(matches) != 1:
        return False
    selector.select_option(label=matches[0], timeout=3000)
    # Creating/authorizing an app may include account-specific policy, OAuth and
    # safety acknowledgements. Never click generic Accept/Allow/Create here.
    return True


def prepare_connection_message(page, prompt: str):
    """Return one send control only in an empty composer with SENTRA selected.

    Existing drafts and ambiguous/app-unbound composers are never overwritten.
    The caller records the attempt *before* clicking, so transport errors cannot
    replay even this read-only test.
    """
    if not trusted_chatgpt(page.url):
        return None
    composer = one_visible(page.locator("#prompt-textarea"))
    if composer is None or composer.inner_text().strip():
        return None
    form = one_visible(page.locator("form").filter(has=page.locator("#prompt-textarea")))
    if form is None or one_visible(form.get_by_role("button", name=re.compile(r"^SENTRA$"))) is None:
        return None
    composer.fill(prompt, timeout=3000)
    send = one_visible(form.get_by_role("button", name=re.compile(r"^(?:Send message|Send|Enviar mensagem|Enviar)$", re.I)))
    return send if send is not None and send.is_enabled() else None


def run_chatgpt_connection(context, paths, tunnel_id, notify, cancelled, *, timeout_s=600):
    from .enrollment_bridge import ExtensionEnrollmentContext
    if isinstance(context, ExtensionEnrollmentContext):
        # The shipped signed extension is Platform-only. Its permissions cannot
        # be expanded without a new signed release; offer a supported browser.
        return {"ok": False, "reason": "chatgpt_browser_required", "tunnel_verified": True}
    proof = ConnectorProof(paths.state_dir)
    challenge = proof.begin_setup_probe(tunnel_id, lifetime=min(timeout_s, 900))
    page = context.new_page()
    notify("progress", "Túnel e MCP verificados. Conecte o app SENTRA no ChatGPT; confirme login e autorização nesta janela.")
    page.goto(CHATGPT_APPS_URL, wait_until="domcontentloaded", timeout=30000)
    prompt = ('Use apenas o app SENTRA para chamar sentra_health com setup_challenge="' + challenge + '". '
              'Não execute comandos nem altere arquivos.')
    notify("verification_prompt", prompt)
    deadline = time.monotonic() + timeout_s
    form_prepared = False
    navigation_clicked = set()
    form_actions = set()
    probe_attempted = False
    while time.monotonic() < deadline:
        if cancelled.is_set() or page.is_closed():
            return {"ok": False, "reason": "chatgpt_setup_cancelled", "tunnel_verified": True}
        # No action or text injection after a navigation to an untrusted origin.
        if not trusted_chatgpt(page.url):
            notify("progress", "Conclua o login e retorne à página de apps do ChatGPT para continuar.")
            page.wait_for_timeout(1000)
            continue
        if not form_prepared and prepare_app_form(page, tunnel_id, actions=form_actions):
            form_prepared = True
            notify("progress", "Nome e túnel preenchidos. Revise a autenticação e confirme a criação/instalação do app no ChatGPT.")
        # A real user-authorized call, carrying this run's one-time challenge,
        # is required. Never approve an account dialog or replay a test turn.
        if proof.setup_probe_observed(challenge, tunnel_id):
            return {"ok": True, "reason": "mcp_roundtrip_verified", "tunnel_verified": True,
                    "mcp_roundtrip_verified": True}
        if not probe_attempted:
            send = prepare_connection_message(page, prompt)
            if send is not None:
                probe_attempted = True
                notify("progress", "Enviando um teste somente de leitura pelo app SENTRA. Se o ChatGPT pedir aprovação, confirme na conta.")
                send.click(timeout=3000)
        if not form_prepared:
            for name in (r"^(?:Add|Adicionar|\+)$", r"^(?:Create MCP App|Create custom MCP server|Add custom MCP server|Criar app MCP|Adicionar servidor MCP personalizado)$"):
                if name in navigation_clicked:
                    continue
                button = one_visible(page.get_by_role("button", name=re.compile(name, re.I)))
                if button is not None:
                    navigation_clicked.add(name)  # Never replay an uncertain click.
                    button.click(timeout=3000)
                    break
        page.wait_for_timeout(1000)
    return {"ok": False, "reason": "chatgpt_call_pending", "tunnel_verified": True}
