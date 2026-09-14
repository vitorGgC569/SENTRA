#!/usr/bin/env python3
"""Repair loop live para claims Goldbach: re-promptea agentes com testemunhas
ruins, anexando as linhas exatas a corrigir. Mescla V1 boas + V2 corrigidas.

Uso: OMA_LIVE_EXTENSION=1 python scripts/repair_math_claims.py --run-id RUN-GOLD-002 [--batch-index 1]
Sem OMA_LIVE_EXTENSION=1: RECUSA.
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
WITNESS_RE = re.compile(r"(\d+)\s*:\s*(\d+)\s*,\s*(\d+)")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="RUN-GOLD-002")
    ap.add_argument("--batch-index", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--relay", default="http://127.0.0.1:8765")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()
    if os.environ.get("OMA_LIVE_EXTENSION") != "1":
        print("RECUSADO: caminho exclusivamente real (OMA_LIVE_EXTENSION=1).")
        sys.exit(2)

    from browser.tab_pool import TabPool
    from orchestrator.providers.base import AgentRequest
    from orchestrator.providers.extension_provider import BrowserExtensionProvider
    from research.goldbach.verifier import sieve

    is_prime = sieve(100002)
    run_dir = Path("runs") / args.run_id
    files = sorted(run_dir.glob("batch-*-claims.json"))
    if args.batch_index is not None:
        files = [run_dir / f"batch-{args.batch_index:02d}-claims.json"]

    targets = []  # (file, tid, agent, bad_ns)
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        for tid, a in data["agents"].items():
            if a["role"] != "EXEC" or "repair_rounds" in a:
                continue
            lo, hi = a["range"]
            bad = []
            for m in WITNESS_RE.finditer(a.get("raw", "")):
                n, p, q = map(int, m.groups())
                if lo <= n <= hi and n % 2 == 0 and not (p + q == n and is_prime[p] and is_prime[q]):
                    bad.append(n)
            if bad:
                targets.append((f, tid, a, sorted(set(bad))))
    if not targets:
        print("[repair] nenhum agente com testemunha ruim. Nada a fazer.")
        return
    print(f"[repair] {len(targets)} agentes precisam de repair: {[t[1] for t in targets]}")

    provider = BrowserExtensionProvider(relay_base=args.relay)
    pool = TabPool(min_tabs=1, max_tabs=args.workers)

    async def handler(worker, key: str):
        fpath, tid, a, bad_ns = next(t for t in targets if t[1] == key)
        lo, hi = a["range"]
        bad_list = "\n".join(str(n) for n in bad_ns)
        prompt = (f"{a.get('conversation', '[EXEC]')} REPAIR OMA {args.run_id}. Você errou a "
                  f"primalidade nestes {len(bad_ns)} valores de n (p ou q composto):\n{bad_list}\n"
                  f"Para CADA n listado, confira a primalidade com cuidado (teste divisores!) "
                  f"e responda SOMENTE as linhas corrigidas n:p,q — uma por linha, sem resto.")
        req = AgentRequest(system_prompt="Corrija apenas as linhas listadas. Sem prosa.",
                           user_prompt=prompt, role="repair", timeout=args.timeout,
                           metadata={"task_id": f"{tid}-R1", "new_chat": True})
        resp = await provider.execute(req)
        if not resp.success:
            raise RuntimeError(resp.error or "repair failed")
        # Mescla: linhas boas da V1 + linhas corrigidas da V2 para os n ruins.
        good = {}
        for m in WITNESS_RE.finditer(a["raw"]):
            n, p, q = map(int, m.groups())
            if lo <= n <= hi and n % 2 == 0 and p + q == n and is_prime[p] and is_prime[q]:
                good[n] = f"{n}:{p},{q}"
        fixed = 0
        for m in WITNESS_RE.finditer(resp.content):
            n, p, q = map(int, m.groups())
            if n in set(bad_ns) and p + q == n and is_prime[p] and is_prime[q]:
                good[n] = f"{n}:{p},{q}"
                fixed += 1
        data = json.loads(fpath.read_text(encoding="utf-8"))
        data["agents"][tid]["raw_v1"] = a["raw"]
        data["agents"][tid]["raw"] = "\n".join(good[n] for n in sorted(good))
        data["agents"][tid]["repair_rounds"] = 1
        data["agents"][tid]["repair_url"] = provider.conversations[f"{tid}-R1"]["conversation_url"]
        tmp = fpath.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(fpath)
        print(f"[{worker.worker_id}] {tid} repair: {fixed}/{len(bad_ns)} corrigidas", flush=True)

    result = await pool.run_all([t[1] for t in targets], handler,
                                timeout_per_task=args.timeout + 120)
    print(f"[repair] completed={len(result['completed'])} failed={list(result['failed'])}")


if __name__ == "__main__":
    asyncio.run(main())
