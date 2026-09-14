#!/usr/bin/env python3
"""Supervisor de operação contínua: roda `main.py --resume` em ciclos até
orçamento de tempo, N ciclos ociosos seguidos, ou candidato pronto (para
promoção humana explícita — nunca autopromove).

Cada ciclo é um processo separado; estado sobrevive via checkpoints/resume.
Progresso = (completed_tasks, candidate_hash) do handoff.json.
Uso:
  python scripts/loop_forever.py --job-id R1 --workspace . --hours 4 --idle-limit 3 --
      --prompt "objetivo" --sandbox docker
Tudo após `--` vai para cada ciclo do main.py (com --resume adicionado).
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def read_handoff(workspace: Path, job_id: str):
    path = workspace / "runs" / job_id / "handoff.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def progress_of(handoff):
    if not handoff:
        return (0, "")
    return (handoff.get("completed_tasks", 0), handoff.get("candidate_hash", ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--hours", type=float, default=4.0)
    ap.add_argument("--idle-limit", type=int, default=3)
    ap.add_argument("extra", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    extra = [a for a in args.extra if a != "--"]
    workspace = Path(args.workspace).resolve()
    deadline = time.time() + max(0.1, args.hours) * 3600
    idle, cycle = 0, 0
    first = read_handoff(workspace, args.job_id)
    if first and first.get("status") in {"CANDIDATE_READY", "APPLIED"}:
        print(f"[loop] STOP: já {first['status']} — aguardando promoção humana explícita.",
              flush=True)
        return 0
    last = progress_of(first)
    print(f"[loop] job={args.job_id} budget={args.hours}h idle-limit={args.idle_limit} "
          f"start={last}", flush=True)
    while True:
        if time.time() >= deadline:
            print("[loop] STOP: orçamento de tempo esgotado.", flush=True)
            return 0
        if idle >= args.idle_limit:
            print(f"[loop] STOP: {idle} ciclos ociosos seguidos.", flush=True)
            return 0
        cycle += 1
        cmd = [sys.executable, "-B", "main.py", "--job-id", args.job_id,
               "--workspace", str(workspace), "--resume", *extra]
        print(f"[loop] ciclo {cycle}...", flush=True)
        proc = subprocess.run(cmd)
        handoff = read_handoff(workspace, args.job_id)
        if handoff and handoff.get("status") in {"CANDIDATE_READY", "APPLIED"}:
            print(f"[loop] STOP: {handoff['status']} — aguardando promoção humana explícita.",
                  flush=True)
            print(f"[loop] handoff: {handoff.get('handoff_path')}", flush=True)
            return 0
        now = progress_of(handoff)
        if proc.returncode != 0:
            print(f"[loop] ciclo {cycle} falhou (exit={proc.returncode}); paro fail-closed.",
                  flush=True)
            return proc.returncode
        if now == last:
            idle += 1
            print(f"[loop] ciclo {cycle} sem progresso (ocioso {idle}/{args.idle_limit}).",
                  flush=True)
        else:
            idle = 0
            print(f"[loop] ciclo {cycle} progresso {last} -> {now}.", flush=True)
        last = now


if __name__ == "__main__":
    sys.exit(main())
