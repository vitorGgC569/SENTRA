#!/usr/bin/env python3
"""Prepara e verifica o navegador dedicado do bot (perfil isolado).

Uso do operador:
  python scripts/prepare_browser_bot.py --init           cria/valida o perfil
  python scripts/prepare_browser_bot.py --check-login    abre o bot e confere login
  python scripts/prepare_browser_bot.py --init --check-login   faz os dois

Codigos de saida:
  0 = OK (perfil pronto; com --check-login: logado)
  1 = NAO logado / sessao expirada (apenas --check-login; faca login e repita)
  2 = erro operacional (config invalida, perfil em OneDrive/link, Edge nao abriu)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser import bot_profile


def parse_args(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--config", default=str(ROOT / "config.yaml"),
                     help="YAML de config (padrao: config.yaml do projeto)")
    cli.add_argument("--init", action="store_true",
                     help="Cria/valida a pasta do perfil dedicado do bot")
    cli.add_argument("--check-login", action="store_true",
                     help="Abre o bot e verifica login (nao envia mensagem)")
    cli.add_argument("--timeout-secs", type=float, default=60.0,
                     help="Tempo maximo de navegacao na verificacao (10..300s)")
    return cli.parse_args(argv)


def fail_operational(message: str, hint: str = "") -> int:
    print(f"ERRO operacional: {message}", file=sys.stderr)
    if hint:
        print(f"Acao: {hint}", file=sys.stderr)
    return 2


async def do_check_login(config: dict, timeout_ms: int) -> int:
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return fail_operational(
            "Playwright nao instalado/importavel.",
            "instale dependencias (pip install -r requirements.txt) e repita",
        )
    playwright = None
    context = None
    try:
        try:
            profile_dir = bot_profile.resolve_bot_profile_dir(config, ROOT)
        except ValueError as exc:
            return fail_operational(str(exc))
        playwright = await async_playwright().start()
        try:
            context, page = await bot_profile.launch_bot_context(playwright, config, ROOT)
        except ValueError as exc:
            return fail_operational(str(exc))
        except Exception as exc:
            short = str(exc)[:300].encode("ascii", "ignore").decode("ascii")
            return fail_operational(
                f"Edge nao abriu com o perfil do bot ({short}).",
                "feche outro Edge do bot com o mesmo perfil; confira Edge instalado",
            )
        try:
            try:
                logged = await bot_profile.check_bot_login(
                    page, config=config, timeout_ms=timeout_ms
                )
            except Exception as exc:
                short = str(exc)[:300].encode("ascii", "ignore").decode("ascii")
                return fail_operational(
                    f"navegacao ate o chat falhou ({short}).",
                    "confira internet/URL e repita",
                )
            storage = bot_profile.get_storage_state_path(config, ROOT)
            report = {
                "ok": True,
                "logged_in": bool(logged),
                "profile_dir": str(profile_dir),
                "target_url": bot_profile.get_target_url(config),
                "storage_state": str(storage) if storage else None,
                "headless": bot_profile.get_bot_headless(config),
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if logged:
                print("Bot LOGADO: perfil valido, pode usar.", flush=True)
                return 0
            print("Bot NAO logado: faca login na janela e repita "
                  "(veja docs/BROWSER_BOT.md).", flush=True)
            return 1
        finally:
            try:
                await context.close()
            except Exception:
                pass
    finally:
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                pass


async def main_async(argv=None) -> int:
    args = parse_args(argv)
    if not args.init and not args.check_login:
        print("--init e/ou --check-login exigido (nada a fazer).",
              file=sys.stderr)
        return 2
    if not 10 <= args.timeout_secs <= 300:
        print("--timeout-secs deve ser 10..300.", file=sys.stderr)
        return 2
    try:
        config = bot_profile.load_config(Path(args.config))
    except (ValueError, OSError) as exc:
        return fail_operational(str(exc), "confira --config e o YAML")
    if args.init:
        try:
            profile_dir = bot_profile.resolve_bot_profile_dir(config, ROOT)
            flags = bot_profile.get_launch_flags(config)
            headless = bot_profile.get_bot_headless(config)
            storage = bot_profile.get_storage_state_path(config, ROOT)
        except ValueError as exc:
            return fail_operational(str(exc))
        print(json.dumps({
            "ok": True,
            "profile_dir": str(profile_dir),
            "launch_flags": flags,
            "headless": headless,
            "storage_state": str(storage) if storage else None,
        }, ensure_ascii=False, indent=2), flush=True)
        print(f"Perfil do bot pronto em: {profile_dir}", flush=True)
        if not args.check_login:
            return 0
    return await do_check_login(config, int(args.timeout_secs * 1000))


def main(argv=None) -> int:
    try:
        return asyncio.run(main_async(argv))
    except KeyboardInterrupt:
        print("\nInterrompido pelo operador; nada foi enviado.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
