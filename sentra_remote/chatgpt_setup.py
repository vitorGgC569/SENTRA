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


def prepare_tunnel_auth(dialog):
    # The official tunnel authenticates access; this local MCP endpoint does
    # not implement a second OAuth server. Only select its explicit None option.
    candidates = []
    selectors = dialog.locator("select")
    for index in range(selectors.count()):
        selector = selectors.nth(index)
        options = selector.locator("option")
        labels = [options.nth(i).inner_text().strip() for i in range(options.count())]
        matches = [label for label in labels if re.fullmatch(r"(?:None|No authentication|Sem autenticação)", label, re.I)]
        if len(matches) == 1:
            candidates.append((selector, matches[0]))
    if len(candidates) != 1:
        return False
    candidates[0][0].select_option(label=candidates[0][1], timeout=3000)
    return True


def prepare_app_form(page, tunnel_id: str, *, actions: set | None = None, app_name: str = "SENTRA") -> bool:
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
    if current not in ("", app_name):
        raise ValueError("chatgpt_app_selection_required")
    if not current:
        field.fill(app_name, timeout=3000)
        if actions is not None:
            actions.add("new_app")
    new_app = not current or (actions is not None and "new_app" in actions)
    selector = one_visible(dialog.get_by_role("combobox", name=re.compile(r"tunnel|túnel", re.I)))
    if selector is None:
        # Current ChatGPT uses a free-text tunnel ID, alongside suggestions
        # from the account. Only fill the ID already verified by LocalRuntime;
        # never choose a similarly named suggestion or replace another ID.
        tunnel_field = one_visible(dialog.get_by_role("textbox", name=re.compile(r"^(?:Tunnel ID|ID do túnel)$", re.I)))
        if tunnel_field is not None:
            current_tunnel = tunnel_field.input_value().strip()
            if current_tunnel not in ("", tunnel_id):
                raise ValueError("chatgpt_app_selection_required")
            if not current_tunnel:
                tunnel_field.fill(tunnel_id, timeout=3000)
            return prepare_tunnel_auth(dialog) if new_app else True
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
        return prepare_tunnel_auth(dialog) if new_app else True
    matches = [label for label in labels if tunnel_id in label.split() or label == tunnel_id]
    if len(matches) != 1:
        return False
    selector.select_option(label=matches[0], timeout=3000)
    # Creating/authorizing an app may include account-specific policy, OAuth and
    # safety acknowledgements. Never click generic Accept/Allow/Create here.
    return prepare_tunnel_auth(dialog) if new_app else True


def prepare_connection_message(page, prompt: str, *, app_name: str = "SENTRA"):
    """Return one send control only in an empty composer with SENTRA selected.

    Existing drafts and ambiguous/app-unbound composers are never overwritten.
    The caller records the attempt *before* clicking, so transport errors cannot
    replay even this read-only test.
    """
    if not trusted_chatgpt(page.url):
        return None
    from .managed_enrollment import ManagedPage
    if isinstance(page, ManagedPage):
        match = re.fullmatch(r'Use apenas o app ' + re.escape(app_name) +
            r' para chamar sentra_health com setup_challenge="([a-f0-9]{48})"\. Não execute comandos nem altere arquivos\.', prompt)
        if match is None or not page.prepare_probe(app_name, match[1]):
            return None
        send = one_visible(page.get_by_role("button", name=re.compile(r"^(?:Send message|Send|Enviar mensagem|Enviar)$", re.I)))
        return send if send is not None and send.is_enabled() else None
    composer = one_visible(page.locator("#prompt-textarea"))
    if composer is None:
        composer = one_visible(page.get_by_role("textbox").filter(
            has=page.locator('[plugin-mention-display-name]')))
    if composer is None:
        return None
    form = one_visible(page.locator("form").filter(has=composer))
    if form is None:
        return None
    mention = one_visible(composer.locator('[plugin-mention-display-name]'))
    if mention is not None:
        keyboard = getattr(page, "keyboard", None)
        if keyboard is None:
            # The embedded setup DOM protocol deliberately has no generic
            # keyboard injection. Keep the owner's mention and draft intact;
            # the visible verification instructions remain the fallback.
            return None
        # The modern composer stores the selected app as a noneditable mention.
        # Preserve it and refuse any other text rather than overwrite a draft.
        path = mention.get_attribute("plugin-mention-path") or ""
        if (mention.get_attribute("plugin-mention-display-name") != app_name
                or mention.get_attribute("contenteditable") != "false"
                or not path.startswith("plugin://")
                or composer.inner_text().strip() != mention.inner_text().strip()):
            return None
        composer.focus()
        composer.press("Control+End")
        keyboard.insert_text(" " + prompt)
    else:
        if composer.inner_text().strip() or one_visible(form.get_by_role("button", name=re.compile("^" + re.escape(app_name) + "$"))) is None:
            return None
        composer.fill(prompt, timeout=3000)
    send = one_visible(form.get_by_role("button", name=re.compile(r"^(?:Send message|Send|Enviar mensagem|Enviar)$", re.I)))
    return send if send is not None and send.is_enabled() else None


def run_chatgpt_connection(context, paths, tunnel_id, notify, cancelled, *, timeout_s=600, app_name="SENTRA"):
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
    if not re.fullmatch(r'SENTRA(?: [\w .-]{1,70})?', app_name):
        raise ValueError("chatgpt_app_selection_required")
    prompt = ('Use apenas o app ' + app_name + ' para chamar sentra_health com setup_challenge="' + challenge + '". '
              'Não execute comandos nem altere arquivos.')
    notify("verification_prompt", prompt)
    deadline = time.monotonic() + timeout_s
    form_prepared = False
    navigation_clicked = set()
    form_actions = set()
    probe_attempted = False
    existing_app = False
    existing_checked = False
    test_chat_opened = False
    inventory_settles_at = time.monotonic() + 4
    while time.monotonic() < deadline:
        if cancelled.is_set() or page.is_closed():
            return {"ok": False, "reason": "chatgpt_setup_cancelled", "tunnel_verified": True}
        # No action or text injection after a navigation to an untrusted origin.
        if not trusted_chatgpt(page.url):
            notify("progress", "Conclua o login e retorne à página de apps do ChatGPT para continuar.")
            page.wait_for_timeout(1000)
            continue
        if proof.setup_probe_observed(challenge, tunnel_id):
            return {"ok": True, "reason": "mcp_roundtrip_verified", "tunnel_verified": True,
                    "mcp_roundtrip_verified": True}
        if not existing_checked:
            # Reuse is proven by this run's fresh challenge, never by a matching
            # display name alone. Never edit/reinstall an existing account app.
            installed = one_visible(page.locator("main").get_by_role("link", name=re.compile("^" + re.escape(app_name) + "$")))
            add = one_visible(page.get_by_role("button", name=re.compile(r"^(?:Add|Adicionar|\+)$", re.I)))
            if installed is not None:
                existing_checked = existing_app = True
                installed.click(timeout=3000)
                notify("progress", "Encontrei o app instalado. Verificando a conexão deste computador sem recriá-lo.")
                continue
            loading = one_visible(page.get_by_text(re.compile(r"^(?:Carregando plugins[.…]*|Loading plugins[.…]*)$", re.I)))
            if (one_visible(page.get_by_role("dialog")) is not None or
                    (add is not None and loading is None and time.monotonic() >= inventory_settles_at)):
                existing_checked = True
            else:
                page.wait_for_timeout(500)
                continue
        if not existing_app and not form_prepared and prepare_app_form(page, tunnel_id, actions=form_actions,
                **({"app_name": app_name} if app_name != "SENTRA" else {})):
            form_prepared = True
            notify("progress", "Nome e túnel preenchidos. Revise a autenticação e confirme a criação/instalação do app no ChatGPT.")
        if form_prepared and not existing_app:
            installed = one_visible(page.locator("main").get_by_role("link", name=re.compile("^" + re.escape(app_name) + "$")))
            if installed is not None:
                existing_app = True
                installed.click(timeout=3000)
                continue
        # A real user-authorized call, carrying this run's one-time challenge,
        # is required. Never approve an account dialog or replay a test turn.
        if not test_chat_opened:
            test = one_visible(page.get_by_role("button", name=re.compile(r"^(?:Test in chat|Try in chat|Testar no chat)$", re.I)))
            if test is not None:
                test_chat_opened = True
                test.click(timeout=3000)
                continue
        if not probe_attempted:
            send = prepare_connection_message(page, prompt, app_name=app_name)
            if send is not None:
                probe_attempted = True
                notify("progress", "Enviando um teste somente de leitura pelo app SENTRA. Se o ChatGPT pedir aprovação, confirme na conta.")
                send.click(timeout=3000)
        if not existing_app and not form_prepared:
            for name in (r"^(?:Add|Adicionar|\+)$", r"^(?:Create MCP App|Create custom MCP server|Add custom MCP server|Criar app MCP|Adicionar servidor MCP personalizado)$"):
                if name in navigation_clicked:
                    continue
                button = one_visible(page.get_by_role("button", name=re.compile(name, re.I)))
                if button is None:
                    button = one_visible(page.get_by_role("menuitem", name=re.compile(name, re.I)))
                if button is not None:
                    navigation_clicked.add(name)  # Never replay an uncertain click.
                    button.click(timeout=3000)
                    break
        page.wait_for_timeout(1000)
    return {"ok": False, "reason": "chatgpt_call_pending", "tunnel_verified": True}
