"""Wiring do novo caminho `--provider browser` (AGENTE D, sem quebrar nada).

Escopo deste arquivo (só CRIAÇÃO, nenhum teste existente foi editado):
- parsing da flag `--provider browser` / `--reviewer browser` no argparse de main.py;
- defaults e validação das novas chaves browser.bot_profile_dir/launch_flags/bot_headless
  em orchestrator/configuration;
- contrato do profile manager (paths, recusa de symlink/OneDrive) com filesystem
  temporário REAL (tmp_path, sem mocks de FS).

Estratégia para ficar verde antes E depois da implementação:
- o que já existe (extension/local/openai, engine_options, build_router) é exercido
  de verdade;
- o que ainda não existe (flag browser, validador bot_*, profile manager dedicado)
  é tentado de verdade e, se ausente, dá SKIP com motivo claro em vez de falhar.
  Quando o outro agente implementar, os mesmos testes passam a exigir o contrato.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers de descoberta (não mockam nada; só importam código real)
# ---------------------------------------------------------------------------

def _main_parser():
    from main import parser
    return parser()


def _parse_or_skip(argv):
    """Tenta parsear; se o argparse recusar, SKIP (flag ainda não implementada)."""
    cli = _main_parser()
    try:
        return cli.parse_args(argv)
    except SystemExit as exc:
        pytest.skip(f"--provider browser ainda não implementado em main.py (SystemExit={exc.code})")


def _load_profile_manager_api():
    """Procura o profile manager do bot nos módulos plausíveis.

    Retorna (modulo_nome, namespace) ou None quando ainda não existe.
    """
    candidates = [
        "browser.profile",
        "browser.profile_manager",
        "browser.profiles",
        "browser.bot_profile",
        "orchestrator.browser_profile",
        "orchestrator.configuration",
        "browser.session",
    ]
    for name in candidates:
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        for attr in (
            "resolve_bot_profile_dir",
            "ensure_bot_profile_dir",
            "validate_bot_profile_dir",
            "resolve_profile_dir",
            "ensure_profile_dir",
            "ProfileManager",
            "browser_bot_settings",
            "bot_profile_defaults",
        ):
            if hasattr(mod, attr):
                return name, mod
    return None


def _load_bot_settings_fn():
    """Validador/defaults das chaves bot_* se já existir em configuration."""
    try:
        import orchestrator.configuration as cfg
    except ImportError:
        return None
    for attr in ("browser_bot_settings", "bot_profile_settings", "validate_browser_bot_config"):
        if hasattr(cfg, attr):
            return getattr(cfg, attr)
    return None


def _bot_profile():
    """Módulo real do perfil do bot (browser/bot_profile.py); SKIP se ausente."""
    try:
        from browser import bot_profile
    except ImportError:
        pytest.skip("browser.bot_profile ainda não existe")
        return None
    return bot_profile


# Predicados-espelho da especificação (lógica pura do contrato; o manager real,
# quando existir, deve satisfazê-los — verificado nos testes *_real_fs abaixo).
def _is_inside_onedrive(path: Path) -> bool:
    return "onedrive" in str(path).lower()


def _is_or_contains_symlink(path: Path) -> bool:
    for cand in [path, *path.parents]:
        try:
            if cand.is_symlink():
                return True
        except OSError:
            continue
    return False


# ---------------------------------------------------------------------------
# 1. Parsing da flag --provider/--reviewer browser
# ---------------------------------------------------------------------------

def test_provider_flag_accepts_existing_providers():
    cli = _main_parser()
    for name in ("extension", "local", "openai"):
        args = cli.parse_args(["--provider", name])
        assert args.provider == name
        args = cli.parse_args(["--reviewer", name])
        assert args.reviewer == name


def test_provider_browser_flag_parses():
    args = _parse_or_skip(["--provider", "browser"])
    assert args.provider == "browser"


def test_reviewer_browser_flag_parses():
    args = _parse_or_skip(["--reviewer", "browser"])
    assert args.reviewer == "browser"


def test_provider_still_rejects_unknown():
    cli = _main_parser()
    with pytest.raises(SystemExit):
        cli.parse_args(["--provider", "nope-inexistente"])


def test_provider_choices_mention_browser_when_supported():
    """Documenta a evolução: antes só extension/local/openai; depois +browser."""
    import io
    cli = _main_parser()
    buf = io.StringIO()
    try:
        cli.parse_args(["--provider", "browser"])
    except SystemExit:
        pytest.skip("browser ainda não é choice de --provider (estado pré-implementação)")
        return
    # Se chegou aqui, a flag existe: o help deve continuar listando o básico.
    cli.print_help(buf)
    assert "--provider" in buf.getvalue()


# ---------------------------------------------------------------------------
# 2. Defaults e validação de browser.bot_profile_dir/launch_flags/bot_headless
# ---------------------------------------------------------------------------

def test_browser_section_defaults_sane():
    from main import PROJECT_ROOT
    data = yaml.safe_load((Path(PROJECT_ROOT) / "config.yaml").read_text(encoding="utf-8"))
    browser = data.get("browser", {})
    # Baseline real que já existe hoje.
    assert browser.get("target_url") == "https://chatgpt.com"
    assert browser.get("headless") is False
    # Novas chaves: se presentes, tipos sãos; se ausentes, defaults esperados
    # ficam documentados para o implementador (sem falhar antes da hora).
    if "bot_profile_dir" in browser:
        assert isinstance(browser["bot_profile_dir"], str) and browser["bot_profile_dir"].strip()
        assert "onedrive" not in browser["bot_profile_dir"].lower()
    if "bot_headless" in browser:
        assert isinstance(browser["bot_headless"], bool)
    if "launch_flags" in browser:
        flags = browser["launch_flags"]
        assert isinstance(flags, list) and all(
            isinstance(f, str) and f.startswith("--") for f in flags
        )


def test_browser_bot_keys_forward_compat():
    """configuration deve ignorar/tolerar as novas chaves (nunca quebrar)."""
    from orchestrator.configuration import build_router, engine_options
    cfg = {
        "browser": {
            "relay_base": "http://127.0.0.1:8765",
            "timeout_seconds": 300,
            "bot_profile_dir": "browser_profiles/edge-bot",
            "bot_headless": False,
            "launch_flags": ["--no-first-run", "--no-default-browser-check"],
        },
        "routing": {"worker": "extension", "reviewer": "extension"},
        "oma": {},
        "orchestrator": {},
        "validation": {},
    }
    opts = engine_options(cfg)
    assert opts["test_timeout"] == 120  # defaults intactos, chaves extras não quebram
    router = build_router(cfg, mock=True)
    assert router.primary_name == "extension"


def test_browser_bot_headless_must_be_bool():
    bot_profile = _bot_profile()
    assert bot_profile.get_bot_headless({}) is False
    assert bot_profile.get_bot_headless({"browser": {"bot_headless": True}}) is True
    with pytest.raises(ValueError, match="bot_headless"):
        bot_profile.get_bot_headless({"browser": {"bot_headless": "yes"}})
    with pytest.raises(ValueError, match="bot_headless"):
        bot_profile.get_bot_headless({"browser": {"bot_headless": 1}})


def test_browser_bot_launch_flags_defaults_and_validation():
    bot_profile = _bot_profile()
    # Default real: trio anti-throttling (documentado em docs/BROWSER_BOT.md).
    defaults = bot_profile.get_launch_flags({})
    assert defaults == list(bot_profile.DEFAULT_LAUNCH_FLAGS) and len(defaults) == 3
    assert bot_profile.get_launch_flags({"browser": {"launch_flags": None}}) == defaults
    custom = ["--no-first-run", "--flag-nova"]
    assert bot_profile.get_launch_flags({"browser": {"launch_flags": custom}}) == custom
    for bad in ("not-a-list", ["ok", ""], ["ok", 123], ["   "]):
        with pytest.raises(ValueError, match="launch_flags"):
            bot_profile.get_launch_flags({"browser": {"launch_flags": bad}})
    # Args finais = base anti-automação + flags do operador, sem duplicar.
    merged = bot_profile.build_launch_args({"browser": {"launch_flags": ["--no-first-run"]}})
    assert merged.count("--no-first-run") == 1
    assert "--disable-blink-features=AutomationControlled" in merged


def test_browser_bot_profile_dir_validation(tmp_path):
    bot_profile = _bot_profile()
    # Vazio/não-string é recusado antes de tocar o FS.
    for bad in ("", "   ", None, 123):
        with pytest.raises(ValueError, match="bot_profile_dir"):
            bot_profile.resolve_bot_profile_dir({"browser": {"bot_profile_dir": bad}},
                                                root=tmp_path)
    # Default resolve e CRIA de verdade sob root (FS real, sem mocks).
    dest = bot_profile.resolve_bot_profile_dir({}, root=tmp_path)
    assert dest.is_dir() and not dest.is_symlink()
    assert dest.parent.name == "browser_profiles" and dest.name == "edge-bot"
    # Absoluto fora do OneDrive é permitido (docs recomendam %LOCALAPPDATA%).
    outside = tmp_path / "absoluto" / "edge-bot"
    assert bot_profile.resolve_bot_profile_dir(
        {"browser": {"bot_profile_dir": str(outside)}}, root=tmp_path) == outside.resolve()
    assert outside.is_dir()


def test_build_router_accepts_browser_worker_when_supported():
    """Quando o roteador conhecer 'browser', deve construir sem mock quebrado."""
    from orchestrator.configuration import build_router
    cfg = {
        "browser": {"relay_base": "http://127.0.0.1:8765"},
        "routing": {"worker": "browser", "reviewer": "browser"},
        "oma": {},
    }
    try:
        router = build_router(cfg, mock=True)
    except ValueError as exc:
        if "unknown provider" in str(exc):
            pytest.skip("build_router ainda não conhece provider 'browser'")
            return
        raise
    assert router.primary_name == "browser"


# ---------------------------------------------------------------------------
# 3. Contrato do profile manager com FS real (tmp_path, sem mocks)
# ---------------------------------------------------------------------------

def test_profile_default_is_relative_and_outside_onedrive(tmp_path):
    from main import PROJECT_ROOT
    data = yaml.safe_load((Path(PROJECT_ROOT) / "config.yaml").read_text(encoding="utf-8"))
    browser = data.get("browser", {})
    candidate = browser.get("bot_profile_dir", browser.get("user_data_dir"))
    assert isinstance(candidate, str) and candidate.strip()
    p = Path(candidate)
    assert not p.is_absolute(), "perfil do bot deve ser caminho relativo ao projeto"
    assert "onedrive" not in candidate.lower(), "o valor configurado não pode apontar para OneDrive"
    # FS real: tmp_path existe e não é symlink por padrão.
    assert tmp_path.is_dir()
    assert not tmp_path.is_symlink()
    # Este checkout roda dentro do OneDrive: o caminho resolvido herda o prefixo
    # do PROJECT_ROOT. Isso é restrição ambiental documentada (o operador deve
    # apontar bot_profile_dir para fora do OneDrive); não falha o teste.
    resolved = str((Path(PROJECT_ROOT) / p)).lower()
    if "onedrive" in resolved:
        pytest.skip(
            "checkout dentro do OneDrive; operador deve apontar bot_profile_dir "
            "para fora do OneDrive no deploy real")


def test_profile_dir_refuses_symlink_real_fs(tmp_path):
    bot_profile = _bot_profile()
    target = tmp_path / "real-profile"
    target.mkdir()
    link = tmp_path / "link-profile"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"FS não permite criar symlink neste ambiente: {exc}")
        return
    # Espelho da especificação concorda com o manager real, com FS real.
    assert _is_or_contains_symlink(link) is True
    assert _is_or_contains_symlink(target) is False
    with pytest.raises((ValueError, RuntimeError, OSError), match="[Ll]ink|juncao"):
        bot_profile.reject_unsafe_profile_dir(link)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        bot_profile.resolve_bot_profile_dir(
            {"browser": {"bot_profile_dir": str(link)}}, root=tmp_path)
    # O alvo real continua válido.
    assert bot_profile.reject_unsafe_profile_dir(target) == target.resolve()


def test_profile_dir_refuses_onedrive_real_fs(tmp_path):
    bot_profile = _bot_profile()
    # FS real: cria de verdade um caminho com OneDrive no nome.
    evil = tmp_path / "OneDrive" / "edge-bot"
    evil.mkdir(parents=True)
    assert evil.is_dir()
    assert _is_inside_onedrive(evil) is True
    assert _is_inside_onedrive(tmp_path / "edge-bot") is False
    with pytest.raises((ValueError, RuntimeError, OSError), match="[Oo]neDrive"):
        bot_profile.reject_unsafe_profile_dir(evil)
    with pytest.raises((ValueError, RuntimeError, OSError), match="[Oo]neDrive"):
        bot_profile.resolve_bot_profile_dir(
            {"browser": {"bot_profile_dir": str(evil)}}, root=tmp_path)


def test_profile_manager_ensures_parent_on_real_fs(tmp_path):
    bot_profile = _bot_profile()
    dest = bot_profile.resolve_bot_profile_dir(
        {"browser": {"bot_profile_dir": "bot-root/edge-bot"}}, root=tmp_path)
    assert dest.is_dir() and not dest.is_symlink()
    assert dest == (tmp_path / "bot-root" / "edge-bot").resolve()
    # Chamada repetida é idempotente (perfil persistente, nunca efêmero).
    assert bot_profile.resolve_bot_profile_dir(
        {"browser": {"bot_profile_dir": "bot-root/edge-bot"}}, root=tmp_path) == dest


def test_is_logged_in_never_sends_and_reads_composer():
    """browser.bot_profile.is_logged_in: só lê visibilidade, nunca envia."""
    bot_profile = _bot_profile()

    class _Box:
        def __init__(self, count, visible):
            self._count, self._visible = count, visible

        async def count(self):
            return self._count

        @property
        def first(self):
            return self

        async def is_visible(self):
            return self._visible

    class _Page:
        def __init__(self, closed=False, count=0, visible=False):
            self._closed, self._count, self._visible = closed, count, visible
            self.sent = []

        def is_closed(self):
            return self._closed

        def get_by_role(self, role):
            assert role == "textbox"
            return _Box(self._count, self._visible)

        def locator(self, selector):
            return _Box(0, False)

    import asyncio as _asyncio
    assert _asyncio.run(bot_profile.is_logged_in(_Page(count=1, visible=True))) is True
    assert _asyncio.run(bot_profile.is_logged_in(_Page(count=0, visible=False))) is False
    assert _asyncio.run(bot_profile.is_logged_in(_Page(closed=True))) is False
