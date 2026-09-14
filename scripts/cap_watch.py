#!/usr/bin/env python3
"""Vigia de quota do ChatGPT sem gastar quota: sonda só lê o DOM (botão de
envio existe? banner de cap?), nunca envia mensagem.

Uso:
  python scripts/cap_watch.py --once          # uma sonda e sai (0=livre, 1=cap)
  python scripts/cap_watch.py --interval 600  # repete até liberar e avisa
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def probe_once(timeout: int = 90) -> dict:
    from browser.extension_transport import ExtensionTransport
    t = ExtensionTransport()
    return await t.probe_quota(timeout_s=timeout)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=600)
    ap.add_argument("--timeout", type=int, default=90)
    args = ap.parse_args()
    while True:
        try:
            r = await probe_once(args.timeout)
            from browser.outcomes import classify_probe
            state = classify_probe(r)
            free = state == "UI_READY"
            print(f"[{time.strftime('%H:%M:%S')}] send_available={r.get('send_available')} "
                  f"cap={r.get('cap_banner')!r} url={r.get('url')} "
                  f"sw={r.get('sw_version')} cs={r.get('cs_version')} "
                  f"composer={r.get('composer_found')} -> "
                  f"{state} (não comprova envio nem cota)", flush=True)
            if free or args.once:
                sys.exit(0 if free else (1 if state == "ACCOUNT_LIMIT" else 2))
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] sonda falhou: {str(e)[:160]}", flush=True)
            if args.once:
                sys.exit(2)
        await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
