#!/usr/bin/env python3
"""Swarm de 100 agentes (50 EXEC + 50 CRIT) — verificação Goldbach até 100.002.

Caminho 100% real: TabPool -> BrowserExtensionProvider -> relay -> Edge Extension
-> conversas reais. Cada agente cobre 500 pares; claims salvos em JSON com URLs
para revalidação determinística (scripts/check_math_claims.py).

Uso (10 batches x 10 chats, 4 workers):
  OMA_LIVE_EXTENSION=1 python scripts/run_math_swarm.py --batch-index 0
  ... (0..9)
Sem OMA_LIVE_EXTENSION=1: RECUSA (sem simulação).
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

N_AGENTS = 100
N_EXEC = 50
RANGE_START, RANGE_END = 4, 100002
PROJECT_ID = "PRJ-GOLDBACH"


async def main() -> None:
    ap = argparse.ArgumentParser(description="OMA math swarm: Goldbach 100 agents")
    ap.add_argument("--batch-index", type=int, required=True, help="0..9")
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--relay", default="http://127.0.0.1:8765")
    ap.add_argument("--run-id", default="RUN-GOLD-001")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    if os.environ.get("OMA_LIVE_EXTENSION") != "1":
        print("RECUSADO: caminho exclusivamente real (OMA_LIVE_EXTENSION=1).")
        sys.exit(2)

    from browser.tab_pool import TabPool
    from orchestrator.projects import OmaProject, standard_conversation_name
    from orchestrator.providers.base import AgentRequest
    from orchestrator.providers.extension_provider import BrowserExtensionProvider
    from research.goldbach.verifier import split_ranges

    from urllib.parse import urlparse
    from native_bridge.relay import RelayServer
    from native_bridge.settings import relay_settings
    import urllib.request as _url
    import json as _json
    parts = urlparse(args.relay)
    # Sonda antes de subir: no Windows dois relays ligam na mesma porta
    # (SO_REUSEADDR) e cada um tem sua própria fila — jobs submetidos num e
    # poluídos no outro morrem de inanição. Nunca duplique relay.
    _external = False
    try:
        _h = _json.loads(_url.urlopen(args.relay.rstrip("/") + "/health",
                                      timeout=5).read())
        if _h.get("ok"):
            _external = True
            print(f"[math-swarm] relay externo em uso (uptime={_h.get('uptime_s')}s, "
                  f"online={_h.get('workers_online')}); efêmero dispensado")
    except Exception:
        pass
    if not _external:
        extension_dir = Path(__file__).resolve().parent.parent / "edge_extension"
        try:
            RelayServer(host=parts.hostname or "127.0.0.1",
                        port=parts.port or 8765,
                        token=relay_settings(Path(__file__).resolve().parent.parent)[0],
                        extension_dir=str(extension_dir)).start()
            print(f"[math-swarm] relay efêmero em {args.relay} (extensão deve apontar p/ ele)")
        except OSError:
            print(f"[math-swarm] usando relay externo em {args.relay}")

    ranges = split_ranges(RANGE_START, RANGE_END, N_AGENTS)
    idxs = list(range(args.batch_index * args.batch_size,
                      min(N_AGENTS, (args.batch_index + 1) * args.batch_size)))

    project = OmaProject(project_id=PROJECT_ID,
                         remote_name="Goldbach Research 100 agents", domain="math")
    run = project.new_run(args.run_id, "Goldbach verification to 100002")
    provider = BrowserExtensionProvider(relay_base=args.relay)
    pool = TabPool(min_tabs=1, max_tabs=args.workers)

    def role_of(i: int) -> str:
        return "EXEC" if i < N_EXEC else "CRIT"

    def prompt_for(i: int) -> str:
        a, b = ranges[i]
        n_pairs = (b - a) // 2 + 1
        cname = standard_conversation_name(role_of(i), (i % N_EXEC) + 1)
        if role_of(i) == "EXEC":
            first, last = a, b
            return (f"[{cname}] OMA Goldbach {args.run_id}. Tarefa EXCLUSIVA: pares n "
                    f"de {a} a {b}. Para CADA um dos {n_pairs} pares, ache primos p<=q "
                    f"com p+q=n. A primeira linha deve ser '{first}:...' e a ÚLTIMA "
                    f"'{last}:...'. Total exato de {n_pairs} linhas, uma por par, "
                    f"formato n:p,q — sem explicações, sem texto extra, sem outras faixas.")
        return (f"[{cname}] OMA Goldbach {args.run_id}. Tente FALSIFICAR a conjectura "
                f"nos pares de {a} a {b}: procure n par SEM decomposição p+q em primos. "
                f"Se achar, responda 'COUNTEREXAMPLE:n'. Senão responda 'HOLDS:{a}-{b}' "
                f"seguido de 3 linhas de testemunha 'n:p,q'.")

    dest = Path("runs") / args.run_id / f"batch-{args.batch_index:02d}-claims.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    progress_log = dest.parent / "progress.log"
    claims: dict = {"run_id": args.run_id, "batch": args.batch_index, "agents": {}}
    # Resume: execuções mortas no meio não perdem progresso nem repetem chats pagos.
    if dest.exists():
        try:
            prior = json.loads(dest.read_text(encoding="utf-8"))
            claims["agents"] = prior.get("agents", {})
            print(f"[math-swarm] resume: {len(claims['agents'])} agentes já concluídos, pulando")
        except Exception:
            pass

    def _save_claims() -> None:
        tmp = dest.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(claims, indent=1), encoding="utf-8")
        tmp.replace(dest)

    def _log_progress(line: str) -> None:
        with open(progress_log, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {line}\n")

    for tid, saved in claims["agents"].items():
        # Restaura mapeamento de conversas dos concluídos (auditoria/Projects).
        try:
            i0 = int(tid.split("-")[1]) - 1
            c0 = standard_conversation_name(role_of(i0), (i0 % N_EXEC) + 1)
            run.add_session(f"S-{tid}", role="EXECUTOR" if role_of(i0) == "EXEC" else "CRITIC")
            run.attach_conversation(f"S-{tid}", c0,
                                    remote_url=saved.get("url"),
                                    remote_id=saved.get("url", "").rstrip("/").split("/")[-1]
                                    if saved.get("url") else None)
            provider.conversations[tid] = {
                "conversation_id": saved.get("url", "").rstrip("/").split("/")[-1]
                if saved.get("url") else None,
                "conversation_url": saved.get("url"),
                "worker": saved.get("worker", "resumed")}
        except Exception:
            pass

    # Freio de ritmo via env (ex. OMA_SWARM_DELAY_S=30); não muda a CLI.
    _delay = float(os.environ.get("OMA_SWARM_DELAY_S", "0"))
    async def handler(worker, task_id: str):
        if _delay > 0:
            await asyncio.sleep(_delay)
        t_start = time.time()
        i = int(task_id.split("-")[1]) - 1
        cname = standard_conversation_name(role_of(i), (i % N_EXEC) + 1)
        run.add_session(f"S-{task_id}", role="EXECUTOR" if role_of(i) == "EXEC" else "CRITIC")
        sys_p = (f"Você é {cname}, agente da pesquisa OMA {args.run_id}. "
                 f"Saída em formato estrito, sem prosa.")
        usr_p = prompt_for(i)
        req = AgentRequest(
            system_prompt=sys_p,
            user_prompt=usr_p, role="executor", timeout=args.timeout,
            metadata={"task_id": task_id, "new_chat": True})
        prompt_sent = (usr_p if (usr_p.strip() == sys_p.strip() or (sys_p and sys_p in usr_p))
                       else f"{sys_p}\n\n{usr_p}")
        resp = await provider.execute(req)
        if not resp.success:
            raise RuntimeError(resp.error or "extension failed")
        conv = provider.conversations[task_id]
        run.attach_conversation(f"S-{task_id}", cname,
                                remote_url=conv.get("conversation_url"),
                                remote_id=conv.get("conversation_id"))
        claims["agents"][task_id] = {
            "role": role_of(i), "range": list(ranges[i]),
            "conversation": cname, "url": conv.get("conversation_url"),
            "worker": conv.get("worker", ""), "raw": resp.content,
            "prompt_sent": prompt_sent,
        }
        _save_claims()  # incremental: kill no meio não perde nada
        dt = round(time.time() - t_start, 1)
        print(f"[{worker.worker_id}] {task_id} {cname} ok ({len(resp.content)} chars, {dt}s)",
              flush=True)
        _log_progress(f"OK {task_id} {cname} range={ranges[i]} chars={len(resp.content)} "
                      f"dt={dt}s worker={worker.worker_id} url={conv.get('conversation_url')}")

    task_ids = [f"T-{i + 1:03d}" for i in idxs if f"T-{i + 1:03d}" not in claims["agents"]]
    if not task_ids:
        print(f"[math-swarm] batch={args.batch_index} já completo ({len(claims['agents'])} claims)")
        return
    t0 = time.time()
    result = await pool.run_all(task_ids, handler, timeout_per_task=args.timeout + 120)
    elapsed = round(time.time() - t0, 2)
    _save_claims()
    print(f"[math-swarm] batch={args.batch_index} completed={len(result['completed'])} "
          f"elapsed={elapsed}s claims={dest}")
    for tid, err in result["failed"].items():
        print(f"[math-swarm] FAILED {tid}: {err[:220]}")
        _log_progress(f"FAIL {tid} {err[:220]}")


if __name__ == "__main__":
    asyncio.run(main())
