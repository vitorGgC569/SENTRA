#!/usr/bin/env python3
"""Swarm de game design: 10 builders + 10 críticos, MESMOS 20 chats por turnos.

Turno 1: builders propõem (chats novos).
Turno 2: críticos julgam 1 proposta cada (chats novos, proposta anexada).
Turno 3: builders revisam NO MESMO chat (continuação) com a crítica anexada.
Turno 4: críticos re-julgam NO MESMO chat (continuação): APPROVE/REJECT.

Tudo via caminho real (TabPool -> extension -> Edge). Nenhuma simulação:
sem OMA_LIVE_EXTENSION=1, RECUSA. Outputs em runs/<run-id>/turn-N-claims.json
com resume (não repete chat pago). Ritmo via OMA_SWARM_DELAY_S.

Uso:
  OMA_LIVE_EXTENSION=1 python scripts/run_game_swarm.py --run-id RUN-GAME-001 --turn 1
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

N_BUILDERS = 10
ENGINE_VOCAB = """Vocabulário válido da engine (use SÓ estes nomes):
WorldKit: Palette, Build, Grid, Conveyor, Nature, Sky, Land, Threat, Pursuit, Motion, Acoustics, Camera, Vfx, Guidance, Setpiece, Fab, Compose, Mood.
GameKit: Commerce, Chat, Reach, Motion, Pursuit, Rules.
Regras de gameplay: quando/require/então sobre eventos fixos (NÃO invente triggers).
Evidência honesta: marque cada afirmação NOT_VALIDATED/STATIC/RUNTIME/VISUAL/E2E.
Proibido: coordenadas literais em massa, MeshPart de upload, preços confiando no cliente."""

GAME = ("Clone de MECÂNICAS (assets/nome/textos 100%% originais, nada copiado) de um "
        "eating-simulator: comer engorda, barriga maior = mais peso, quebrar fitas dá "
        "cash, comidas melhores, 3 mundos. Nome de trabalho: BELLY_BREAKERS.")
ROLE_BRIEFS = [
    ("Diretor de Design", "visão, nome final original, loop central em 3 frases, pilares, sessão de 10 min, o que CORTAR."),
    ("Sistemas de Comida", "tiers de comida, taxas de ingestão, zonas de alimentação, regras de economia (quando/require/então), tudo server-authoritative."),
    ("Física de Tamanho e Quebra", "escala do corpo por peso, tiers de fita com força exigida, efeitos de quebra (Vfx/Motion), sem confiar em física client-side."),
    ("Mundos e Zonas", "3 mundos com gates por poder, layout com marcos navegáveis (Build/Grid), Nature com seed fixa, sem coordenadas literais em massa."),
    ("Loja e Upgrades", "multiplicadores (ingestão, força, velocidade), preços server-side, sem moeda client-side confiável."),
    ("Pets", "seguir o dono (Pursuit), multiplicadores, raridade com gate de política para itens pagos aleatórios."),
    ("Rebirth e Save", "escada de rebirth, leaderstats, persistência com DataStore real (handle não é save funcional)."),
    ("UI e HUD", "medidor de tamanho, cash, progresso de zona (Compose), rótulos por proximidade, filtro de texto em qualquer texto de jogador."),
    ("Juice", "andar bamboleante procedural com âncora imóvel (Motion+Pursuit), zonas de som (Acoustics), iluminação comedida, câmera que enquadra."),
    ("QA e Release", "cenários de ator (comer→crescer→quebrar→comprar→renascer), orçamentos, plano de evidência por nível, checklist de craft."),
]
BUILDER_BRIEF = """[BUILD-%02d] OMA %s — %s
""" + GAME + """
Sua parte: %s
""" + ENGINE_VOCAB + """
Saída: RESPONSÁVEL + 5 balas + RISCOS (marque NOT_VALIDATED). Compacto."""

CRITIC_BRIEF = """[CRIT-%02d] OMA game design %s. Julgue ESTA proposta (atacar, não agradar):
---
%s
---
Veredito: KILL (sem salvação), REWORK (lista numerada do que mudar) ou PASS.
Critérios: loop diverte 10 min? cabe no vocabulário (sem nomes inventados)?
escopo cabe em 1 build? validação honesta? Resposta curta e dura."""

REVISE_BRIEF = """A crítica abaixo foi feita à sua proposta. Revise o design NO MESMO
escopo e responda com a versão 2 completa e compacta (mesmo formato). Se a
crítica estiver errada num ponto, refute com evidência, não com adjetivo:
---
%s"""

REJUDGE_BRIEF = """Re-julgue a versão 2 abaixo contra sua crítica original. Veredito
final de UMA palavra (APPROVE/REJECT) + 3 balas justificando:
---
%s"""


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="RUN-GAME-001")
    ap.add_argument("--turn", type=int, required=True, help="1..4")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--relay", default="http://127.0.0.1:8765")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()
    if os.environ.get("OMA_LIVE_EXTENSION") != "1":
        print("RECUSADO: caminho exclusivamente real (OMA_LIVE_EXTENSION=1).")
        sys.exit(2)
    if args.turn not in (1, 2, 3, 4):
        print("turn deve ser 1..4")
        sys.exit(2)

    from browser.tab_pool import TabPool
    from orchestrator.projects import standard_conversation_name
    from orchestrator.providers.base import AgentRequest
    from orchestrator.providers.extension_provider import BrowserExtensionProvider

    run_dir = Path("runs") / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    delay = float(os.environ.get("OMA_SWARM_DELAY_S", "0"))
    provider = BrowserExtensionProvider(relay_base=args.relay)
    pool = TabPool(min_tabs=1, max_tabs=args.workers)
    if args.turn in (3, 4):
        # Turnos de continuação rodam em outro processo: adota as conversas
        # criadas pelos turnos 1-2 do MESMO run (claims em disco local).
        src_turn = 1 if args.turn == 3 else 2
        try:
            prior = json.loads((run_dir / f"turn-{src_turn}-claims.json").read_text(encoding="utf-8"))
            n = provider.adopt_conversations([a.get("url") for a in prior["agents"].values()])
            print(f"[game-swarm] {n} conversas do turno {src_turn} adotadas para continuação")
        except Exception as e:
            print(f"[game-swarm] sem base para adoção do turno {src_turn}: {e}")

    def load_turn(n: int) -> dict:
        p = run_dir / f"turn-{n}-claims.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"agents": {}}

    prev = load_turn(args.turn - 1) if args.turn > 1 else {"agents": {}}
    dest = run_dir / f"turn-{args.turn}-claims.json"
    claims = {"run_id": args.run_id, "turn": args.turn, "agents": {}}
    if dest.exists():
        try:
            claims["agents"] = json.loads(dest.read_text(encoding="utf-8"))["agents"]
            print(f"[game-swarm] resume turno {args.turn}: {len(claims['agents'])} prontos")
        except Exception:
            pass

    def save():
        tmp = dest.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(claims, indent=1), encoding="utf-8")
        tmp.replace(dest)

    def build_task(i: int):
        """(task_id, role, prompt, new_chat, url_ou_None). Turno define o pareamento."""
        if args.turn == 1:
            t = f"B-{i + 1:02d}"
            dept, scope = ROLE_BRIEFS[i]
            return t, "EXEC", BUILDER_BRIEF % (i + 1, args.run_id, dept, scope), True, None
        if args.turn == 2:
            src = prev["agents"].get(f"B-{i + 1:02d}", {})
            prop = src.get("raw", "")[:6000] or "(proposta indisponível)"
            t = f"C-{i + 1:02d}"
            return t, "CRIT", CRITIC_BRIEF % (i + 1, args.run_id, prop), True, None
        if args.turn == 3:
            src = load_turn(1)["agents"].get(f"B-{i + 1:02d}", {})
            crit = load_turn(2)["agents"].get(f"C-{i + 1:02d}", {}).get("raw", "")[:3000]
            t = f"B-{i + 1:02d}"
            return t, "EXEC", REVISE_BRIEF % crit, False, src.get("url")
        src = load_turn(2)["agents"].get(f"C-{i + 1:02d}", {})
        rev = load_turn(3)["agents"].get(f"B-{i + 1:02d}", {}).get("raw", "")[:6000]
        t = f"C-{i + 1:02d}"
        return t, "CRIT", REJUDGE_BRIEF % rev, False, src.get("url")

    async def handler(worker, key: str):
        if delay:
            await asyncio.sleep(delay)
        t0 = time.time()
        i = int(key.split("-")[1]) - 1
        tid, role, prompt, new_chat, url = build_task(i)
        cname = standard_conversation_name("EXEC" if role == "EXEC" else "CRIT", i + 1)
        req = AgentRequest(system_prompt=f"Você é {cname}, {role} de game design OMA. Compacto e direto.",
                           user_prompt=prompt, role="executor", timeout=args.timeout,
                           metadata={"task_id": f"{args.run_id}-{tid}-T{args.turn}",
                                     "new_chat": new_chat,
                                     **({"conversation_url": url} if url else {})})
        resp = await provider.execute(req)
        if not resp.success:
            raise RuntimeError(resp.error or "extension failed")
        conv = provider.conversations[f"{args.run_id}-{tid}-T{args.turn}"]
        claims["agents"][tid] = {"role": role, "prompt_sent": prompt,
                                 "conversation": cname, "url": conv.get("conversation_url"),
                                 "worker": conv.get("worker", ""), "raw": resp.content}
        save()
        print(f"[{worker.worker_id}] {tid} {cname} ok ({len(resp.content)} chars, "
              f"{round(time.time() - t0, 1)}s)", flush=True)

    keys = [f"K-{i + 1:02d}" for i in range(N_BUILDERS)
            if f"{'B' if args.turn in (1, 3) else 'C'}-{i + 1:02d}" not in claims["agents"]]
    if not keys:
        print(f"[game-swarm] turno {args.turn} já completo.")
        return
    result = await pool.run_all(keys, handler, timeout_per_task=args.timeout + 120)
    print(f"[game-swarm] turno {args.turn}: completed={len(result['completed'])} "
          f"failed={list(result['failed'])}")
    for tid, err in result["failed"].items():
        print(f"[game-swarm] FAILED {tid}: {str(err)[:2000]}")


if __name__ == "__main__":
    asyncio.run(main())
