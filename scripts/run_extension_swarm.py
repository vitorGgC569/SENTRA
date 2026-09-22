#!/usr/bin/env python3
"""Swarm REAL via extensão: N conversas lógicas por um controller adotado.

Caminho: OMA -> BrowserExtensionProvider -> relay local
      -> Edge Extension (1 tab ChatGPT existente/inativa) -> conversas por ID.

Exige (sem fallback, sem simulação):
  OMA_LIVE_EXTENSION=1
  relay rodando em --relay (o próprio script pode subir um efêmero com --relay-ephemeral)
  Edge com edge_extension/ carregada e logado no site alvo.

Exemplo:
  python scripts/run_extension_swarm.py --tasks 6 --workers 2 --project-id PRJ-0041 --run-id RUN-0001
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    ap = argparse.ArgumentParser(description="OMA real browser swarm via Edge extension")
    ap.add_argument("--tasks", type=int, default=6)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--relay", default="http://127.0.0.1:8765")
    ap.add_argument("--relay-ephemeral", action="store_true",
                    help="sobe um relay efêmero neste processo (extensão deve apontar p/ ele)")
    ap.add_argument("--project-id", default="PRJ-0041")
    ap.add_argument("--run-id", default="RUN-0001")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    if os.environ.get("OMA_LIVE_EXTENSION") != "1":
        print("RECUSADO: este script só opera o caminho real (OMA_LIVE_EXTENSION=1). "
              "Sem extensão real conectada, nada é executado — nenhuma simulação.")
        sys.exit(2)
    if not (1 <= args.tasks <= 500 and 1 <= args.workers <= 8):
        print("Limites: --tasks 1..500, --workers 1..8 (pool pequeno, muitas conversas).")
        sys.exit(2)

    from browser.tab_pool import TabPool
    from orchestrator.projects import OmaProject, standard_conversation_name
    from orchestrator.providers.base import AgentRequest
    from orchestrator.providers.extension_provider import BrowserExtensionProvider

    relay_server = None
    if args.relay_ephemeral:
        from native_bridge.relay import RelayServer
        from native_bridge.settings import relay_settings
        from urllib.parse import urlparse
        parts = urlparse(args.relay)
        relay_server = RelayServer(host=parts.hostname or "127.0.0.1",
                                   port=parts.port or 8765,
                                   token=relay_settings(Path(__file__).resolve().parent.parent)[0],
                                   extension_dir=str(Path(__file__).resolve().parent.parent / "edge_extension")).start()
        print(f"[swarm] relay efêmero em {args.relay}")

    project = OmaProject(project_id=args.project_id,
                         remote_name=f"{args.project_id} live swarm", domain="research")
    run = project.new_run(args.run_id, objective=f"live swarm {args.tasks} chats")
    provider = BrowserExtensionProvider(relay_base=args.relay)
    pool = TabPool(min_tabs=1, max_tabs=args.workers)

    roles = ["EXEC"] * (args.tasks // 2) + ["CRIT"] * (args.tasks - args.tasks // 2)
    task_ids = [f"T-{i + 1:03d}" for i in range(args.tasks)]
    for i, tid in enumerate(task_ids):
        run.add_session(f"S-{tid}", role="EXECUTOR" if roles[i] == "EXEC" else "CRITIC")

    async def handler(worker, task_id):
        idx = task_ids.index(task_id)
        cname = standard_conversation_name(roles[idx], idx + 1)
        req = AgentRequest(
            system_prompt=(f"Você faz parte da execução OMA {args.run_id}. "
                           f"Esta conversa é {cname}. Responda com protocolo OMA."),
            user_prompt=f"[{cname}] tarefa {task_id}: apresente-se em 1 linha e aguarde.",
            role="executor", timeout=args.timeout,
            metadata={"task_id": task_id, "new_chat": True})
        resp = await provider.execute(req)
        if not resp.success:
            raise RuntimeError(resp.error or "extension failed")
        conv = provider.conversations[task_id]
        run.attach_conversation(f"S-{task_id}", cname,
                                remote_url=conv.get("conversation_url"),
                                remote_id=conv.get("conversation_id"))
        print(f"[{worker.worker_id}] {task_id} -> {cname} {conv.get('conversation_url')}",
              flush=True)

    t0 = time.time()
    result = await pool.run_all(task_ids, handler, timeout_per_task=args.timeout + 60)
    elapsed = round(time.time() - t0, 2)
    out = {"project": args.project_id, "run": args.run_id, "tasks": args.tasks,
           "workers": args.workers, "elapsed_s": elapsed,
           "completed": result["completed"], "failed": result["failed"],
           "conversations": provider.conversations}
    dest = Path("runs") / args.run_id / "extension_swarm.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[swarm] completed={len(result['completed'])} failed={len(result['failed'])} "
          f"elapsed={elapsed}s saved={dest}")
    if relay_server:
        relay_server.stop()


if __name__ == "__main__":
    asyncio.run(main())
