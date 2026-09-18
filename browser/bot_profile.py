"""Gerenciador do perfil dedicado do bot ("nosso proprio navegador").

Perfil isolado das abas pessoais do usuario: um diretorio de perfil
persistente do Edge usado apenas pelo bot, com login/sessao proprios.

Contrato de config (secao ``browser`` do YAML):
  - ``bot_profile_dir`` (str, default ``browser_profiles/edge-bot``)
  - ``launch_flags`` (lista de str; default: 3 flags anti-throttling)
  - ``bot_headless`` (bool, default False)

Sem mocks neste modulo: apenas stdlib + PyYAML + Playwright (ao vivo).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

DEFAULT_BOT_PROFILE_DIR = "browser_profiles/edge-bot"
DEFAULT_TARGET_URL = "https://chatgpt.com"
DEFAULT_BROWSER_CHANNEL = "msedge"
DEFAULT_STORAGE_STATE = "auth.json"

# Trio anti-throttling: impede o Chromium de congelar timers/render de abas
# em segundo plano enquanto o bot aguarda respostas longas.
DEFAULT_LAUNCH_FLAGS: list[str] = [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]

BASE_EDGE_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]


def project_root() -> Path:
    """Raiz do projeto (pasta acima de ``browser/``)."""
    return Path(__file__).resolve().parents[1]


def load_config(config_path: Path | str) -> dict:
    """Le um YAML de config e devolve o mapeamento raiz."""
    import yaml

    path = Path(config_path)
    if not path.is_file():
        raise ValueError(f"configuration not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("configuration must be a YAML mapping")
    return data


def _browser_section(config: Optional[dict]) -> dict[str, Any]:
    if config is None:
        return {}
    section = config.get("browser", {})
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ValueError("browser deve ser um mapeamento no config")
    return section


def get_bot_headless(config: Optional[dict] = None) -> bool:
    """Le ``browser.bot_headless`` (bool, default False)."""
    value = _browser_section(config).get("bot_headless", False)
    if not isinstance(value, bool):
        raise ValueError("browser.bot_headless deve ser bool (true/false)")
    return value


def get_launch_flags(config: Optional[dict] = None) -> list[str]:
    """Le ``browser.launch_flags`` (lista); default: trio anti-throttling."""
    section = _browser_section(config)
    if "launch_flags" not in section or section["launch_flags"] is None:
        return list(DEFAULT_LAUNCH_FLAGS)
    raw = section["launch_flags"]
    if not isinstance(raw, list) or any(
        not isinstance(item, str) or not item.strip() for item in raw
    ):
        raise ValueError("browser.launch_flags deve ser uma lista de strings nao vazias")
    return [item.strip() for item in raw]


def get_target_url(config: Optional[dict] = None) -> str:
    """URL do chat (``browser.target_url``, default chatgpt.com)."""
    url = _browser_section(config).get("target_url", DEFAULT_TARGET_URL)
    if not isinstance(url, str) or not url.strip():
        raise ValueError("browser.target_url deve ser uma string nao vazia")
    return url.strip()


def get_browser_channel(config: Optional[dict] = None) -> str:
    """Canal do navegador (``browser.browser_channel``, default msedge)."""
    channel = _browser_section(config).get("browser_channel", DEFAULT_BROWSER_CHANNEL)
    if not isinstance(channel, str) or not channel.strip():
        raise ValueError("browser.browser_channel deve ser uma string nao vazia")
    return channel.strip()


def get_storage_state_path(
    config: Optional[dict] = None, root: Optional[Path | str] = None
) -> Optional[Path]:
    """Caminho do ``storage_state`` (auth.json) quando o arquivo existir.

    Honra ``browser.storage_state_path`` quando presente (compat com o
    config atual); o default e ``auth.json``. Relativo = relativo a raiz
    do projeto. Retorna None quando o arquivo nao existe (perfil segue
    como fonte da sessao).
    """
    base = Path(root).resolve() if root is not None else project_root()
    raw = _browser_section(config).get("storage_state_path", DEFAULT_STORAGE_STATE)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("browser.storage_state_path deve ser uma string nao vazia")
    candidate = Path(raw.strip())
    if not candidate.is_absolute():
        candidate = base / candidate
    if candidate.is_file():
        return candidate.resolve()
    return None


def _is_onedrive_path(resolved: Path) -> bool:
    text = str(resolved).lower()
    if "onedrive" in text:
        return True
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        base = os.environ.get(var)
        if not base:
            continue
        try:
            anchor = Path(base).resolve()
        except Exception:
            continue
        try:
            if resolved == anchor or anchor in resolved.parents:
                return True
        except Exception:
            continue
    return False


def _is_link(path: Path) -> bool:
    """Mesmo padrao de native_bridge/settings.py: symlink ou juncao."""
    try:
        if path.is_symlink():
            return True
    except Exception:
        pass
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            if is_junction():
                return True
        except Exception:
            pass
    return False


def reject_unsafe_profile_dir(path: Path | str) -> Path:
    """Recusa perfil dentro de OneDrive ou sobre symlink/juncao.

    Levanta ValueError com motivo acionavel pelo operador.
    Nao cria nada; apenas valida.
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = project_root() / candidate
    # Inspeciona cada componente existente sem resolver (lexists enxerga
    # symlink quebrado). Mesmo padrao de native_bridge/settings.py.
    chain: list[Path] = [candidate, *candidate.parents]
    for node in chain:
        try:
            exists = os.path.lexists(node)
        except Exception:
            exists = False
        if exists and _is_link(node):
            raise ValueError(
                f"perfil do bot nao pode ser link/juncao: {node} "
                f"(aponte browser.bot_profile_dir para uma pasta local real)"
            )
    try:
        resolved = candidate.resolve()
    except Exception as exc:
        raise ValueError(f"nao foi possivel resolver o perfil do bot: {exc}")
    if _is_onedrive_path(resolved):
        raise ValueError(
            f"perfil do bot dentro de OneDrive nao e permitido: {resolved} "
            f"(o OneDrive corrompe o perfil do Edge; configure "
            f"browser.bot_profile_dir fora do OneDrive, ex. "
            f"%LOCALAPPDATA%/SENTRA/edge-bot)"
        )
    return resolved


def resolve_bot_profile_dir(
    config: Optional[dict] = None, root: Optional[Path | str] = None
) -> Path:
    """Resolve, valida e cria o diretorio do perfil dedicado do bot.

    Le ``browser.bot_profile_dir`` (default ``browser_profiles/edge-bot``),
    recusa OneDrive/symlink/juncao e cria a pasta quando valida.
    Devolve o caminho resolvido.
    """
    base = Path(root).resolve() if root is not None else project_root()
    raw = _browser_section(config).get("bot_profile_dir", DEFAULT_BOT_PROFILE_DIR)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("browser.bot_profile_dir deve ser uma string nao vazia")
    candidate = Path(raw.strip())
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = reject_unsafe_profile_dir(candidate)
    resolved.mkdir(parents=True, exist_ok=True)
    if _is_link(resolved):
        raise ValueError(
            f"perfil do bot nao pode ser link/juncao: {resolved}"
        )
    return resolved


def build_launch_args(config: Optional[dict] = None) -> list[str]:
    """Args finais do Edge: base anti-automacao + launch_flags do operador."""
    flags = get_launch_flags(config)
    merged = list(BASE_EDGE_ARGS)
    for flag in flags:
        if flag not in merged:
            merged.append(flag)
    return merged


async def is_logged_in(page: Any) -> bool:
    """Deteccao barata de login: composer visivel = logado.

    Nao preenche, nao clica, nao envia mensagem. Qualquer duvida
    (pagina fechada, DOM ilegivel) = False (operador confere).
    """
    try:
        if page.is_closed():
            return False
    except Exception:
        return False
    # Caminho principal: caixa de texto acessivel do chat.
    try:
        box = page.get_by_role("textbox")
        if await box.count() and await box.first.is_visible():
            return True
    except Exception:
        pass
    for selector in (
        "#prompt-textarea",
        "textarea",
        "[contenteditable='true']",
        "button[data-testid='send-button']",
    ):
        try:
            locator = page.locator(selector)
            if await locator.count() and await locator.first.is_visible():
                return True
        except Exception:
            continue
    return False


async def is_login_wall(page: Any) -> bool:
    """Heuristica do "muro de login" (nao logado). Nao envia nada."""
    try:
        url = str(getattr(page, "url", "") or "").lower()
    except Exception:
        url = ""
    if any(token in url for token in ("/auth/login", "login.openai", "auth.openai")):
        return True
    for selector in (
        "a[href*='auth/login']",
        "button:has-text('Log in')",
        "button:has-text('Sign up')",
        "button:has-text('Entrar')",
    ):
        try:
            locator = page.locator(selector)
            if await locator.count() and await locator.first.is_visible():
                # So e muro se nao houver composer junto.
                if not await is_logged_in(page):
                    return True
        except Exception:
            continue
    return False


async def check_bot_login(
    page: Any,
    target_url: Optional[str] = None,
    config: Optional[dict] = None,
    timeout_ms: int = 30000,
) -> bool:
    """Navega ao chat e diz se ha sessao valida. Nunca envia mensagem."""
    url = (target_url or get_target_url(config)).strip()
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    return await is_logged_in(page)


async def launch_persistent_with_cookies(
    playwright: Any,
    profile_dir: "Path | str",
    *,
    channel: str = DEFAULT_BROWSER_CHANNEL,
    headless: bool = False,
    viewport: Optional[dict] = None,
    locale: str = "pt-BR",
    timezone_id: str = "America/Sao_Paulo",
    args: Optional[list] = None,
    storage_state_path: Optional["Path | str"] = None,
):
    """Abre contexto persistente tolerando canais sem suporte a storage_state.

    O canal msedge rejeita o kwarg ``storage_state`` no
    ``launch_persistent_context``; nesse caso abre sem ele e injeta os
    cookies do arquivo via ``add_cookies`` (mesma origem, mesma sessão).
    """
    import json

    storage = Path(storage_state_path) if storage_state_path else None
    if storage is not None and not storage.exists():
        storage = None
    base_kwargs: dict = {
        "channel": channel,
        "headless": headless,
        "viewport": viewport or {"width": 1280, "height": 800},
        "locale": locale,
        "timezone_id": timezone_id,
        "args": args or [],
    }
    try:
        return await playwright.chromium.launch_persistent_context(
            str(profile_dir),
            storage_state=str(storage) if storage else None,
            **base_kwargs,
        )
    except TypeError:
        pass
    context = await playwright.chromium.launch_persistent_context(
        str(profile_dir), **base_kwargs)
    if storage is not None:
        try:
            data = json.loads(storage.read_text(encoding="utf-8"))
            cookies = data.get("cookies", []) if isinstance(data, dict) else []
            if cookies:
                await context.add_cookies(cookies)
        except Exception:
            pass
    return context


async def launch_bot_context(playwright: Any, config: Optional[dict] = None,
                             root: Optional[Path | str] = None):
    """Abre o contexto persistente do bot (perfil dedicado, Edge real).

    Aplica ``storage_state`` (auth.json) quando o arquivo existir.
    Devolve ``(context, page)``; o chamador deve fechar o contexto.
    """
    profile_dir = resolve_bot_profile_dir(config, root)
    base = Path(root).resolve() if root is not None else project_root()
    storage = get_storage_state_path(config, base)
    context = await launch_persistent_with_cookies(
        playwright,
        profile_dir,
        channel=get_browser_channel(config),
        headless=get_bot_headless(config),
        args=build_launch_args(config),
        storage_state_path=str(storage) if storage else None,
    )
    pages = list(context.pages)
    page = pages[0] if pages else await context.new_page()
    try:
        page.set_default_timeout(30000)
    except Exception:
        pass
    return context, page
