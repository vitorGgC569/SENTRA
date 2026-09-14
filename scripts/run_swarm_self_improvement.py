#!/usr/bin/env python3
"""Orquestra 50 chats (25 críticos + 25 implementadores) via SelfImprovementEngine.

Modo padrão (offline/determinístico): sem LLM externo; cada chat emite 2-4
diretivas do protocolo executadas pelo CommandGateway sobre o repo real
(somente leitura/busca/status/diff — nenhum PATCH no repo real neste modo).

Modo live (OMA_SWARM_LIVE=1): usa o ModelRouter real (local + Edge) para gerar
as diretivas de cada chat. Exige Ollama/Edge configurados; 50 chats reais
podem levar dezenas de minutos.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from repository.gateway import CommandGateway
from self_improvement.engine import SelfImprovementEngine


async def main() -> None:
    ap = argparse.ArgumentParser(description="OMA self-improvement swarm (50 chats)")
    ap.add_argument("--root", default=None,
                    help="repositório alvo (default: o próprio projeto)")
    ap.add_argument("--critics", type=int, default=25)
    ap.add_argument("--implementers", type=int, default=25)
    ap.add_argument("--focus", default=None,
                    help="preset de foco (ex. bridge: extensão+relay+pool)")
    ap.add_argument("--final-test", default="[[TEST|all]]",
                    help="comando final de consolidação (ex. [[TEST|unit]])")
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    # Gateway opera sobre o alvo; o código da engine é o deste projeto.
    gw = CommandGateway(root)
    sess = gw.open_session()
    print(f"[swarm] session={sess.session_id} root={root}")

    router = None
    if os.environ.get("OMA_SWARM_LIVE") == "1":
        from orchestrator.agents.router import ModelRouter
        from orchestrator.providers.mock_provider import MockProvider
        try:
            from orchestrator.providers.local_provider import LocalModelProvider
            local = LocalModelProvider()
            router = ModelRouter(providers={"primary": local, "master": local},
                                 primary_provider_name="primary",
                                 fallback_provider_name="master")
            print("[swarm] LIVE mode: LocalModelProvider")
        except Exception as e:
            print(f"[swarm] live requested but unavailable ({e}); fallback to deterministic")
            router = None
    else:
        print("[swarm] deterministic mode (50 chats x gateway, sem LLM externo)")

    engine = SelfImprovementEngine(gw, router=router)
    t0 = time.time()
    focus_label = args.focus or "geral"
    result = await engine.orchestrate_swarm(
        sess.session_id,
        f"Analisar [{focus_label}] em {root}: atacar fragilidades e propor melhorias "
        f"concretas via protocolo (leitura/busca)",
        n_critics=args.critics, n_implementers=args.implementers, max_concurrency=10,
        focus=args.focus, final_test=args.final_test,
    )
    eff = gw.efficiency_report()
    payload = {
        "focus": args.focus,
        "total_chats": result.total_chats,
        "critics": result.critics,
        "implementers": result.implementers,
        "directives_executed": result.directives_executed,
        "patches_applied": result.patches_applied,
        "tests_pass": result.tests_pass,
        "tests_fail": result.tests_fail,
        "elapsed_s": result.elapsed_s,
        "efficiency": eff,
        "audit_events": len(gw.audit),
    }
    out_dir = root / "runs" / f"swarm-{time.strftime('%Y%m%d-%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "swarm_result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("=" * 60)
    print(f"[swarm] chats={result.total_chats} (critics={result.critics}, "
          f"implementers={result.implementers})")
    print(f"[swarm] directives={result.directives_executed} patches={result.patches_applied} "
          f"tests_pass={result.tests_pass} elapsed={result.elapsed_s}s")
    print(f"[swarm] efficiency={json.dumps(eff)} audit={len(gw.audit)}")
    print(f"[swarm] saved to {out_dir / 'swarm_result.json'}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
