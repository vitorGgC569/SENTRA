#!/usr/bin/env python3
"""Revalidação determinística dos claims do swarm Goldbach (software decide).

Lê runs/<run-id>/batch-*-claims.json, verifica cada testemunha (p+q=n, primos
via peneira) e cada veredito de crítico. Escreve o relatório Master.
Uso: python scripts/check_math_claims.py --run-id RUN-GOLD-001
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WITNESS_RE = re.compile(r"(\d+)\s*:\s*(\d+)\s*,\s*(\d+)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="RUN-GOLD-001")
    args = ap.parse_args()

    from research.goldbach.verifier import sieve

    run_dir = Path("runs") / args.run_id
    files = sorted(run_dir.glob("batch-*-claims.json"))
    if not files:
        print(f"nenhum claim em {run_dir}")
        sys.exit(2)
    is_prime = sieve(100002)
    stats = {"agents": 0, "exec": 0, "crit": 0, "witness_ok": 0, "witness_bad": 0,
             "pairs_covered": set(), "counterexample_claims": [], "holds": 0,
             "failed_agents": [], "out_of_scope_valid": 0, "scope_drift_agents": []}
    bad_samples = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        for tid, a in data["agents"].items():
            stats["agents"] += 1
            raw = a.get("raw", "")
            if a["role"] == "EXEC":
                stats["exec"] += 1
                lo, hi = a["range"]
                seen = set()
                drift = None
                for m in WITNESS_RE.finditer(raw):
                    n, p, q = map(int, m.groups())
                    arith_ok = (p + q == n and n >= 4 and is_prime[p] and is_prime[q])
                    if not arith_ok:
                        stats["witness_bad"] += 1
                        if len(bad_samples) < 10:
                            bad_samples.append(f"{tid} {n}:{p},{q}")
                        continue
                    if lo <= n <= hi and n % 2 == 0:
                        seen.add(n)
                        stats["witness_ok"] += 1
                    else:
                        stats["out_of_scope_valid"] += 1
                        if drift is None and n % 2 == 0:
                            drift = (lo, n)
                if drift:
                    stats["scope_drift_agents"].append(
                        f"{tid} alvo={lo}-{hi} produziu_desde={drift[1]}")
                stats["pairs_covered"] |= seen
            else:
                stats["crit"] += 1
                m = re.search(r"COUNTEREXAMPLE\s*:\s*(\d+)", raw)
                if m:
                    n = int(m.group(1))
                    lo, hi = a["range"]
                    valid = lo <= n <= hi and n % 2 == 0
                    # contraexemplo real exigiria: sem testemunha (verificado abaixo)
                    from research.goldbach.verifier import goldbach_witness
                    real = valid and goldbach_witness(n, is_prime) is None
                    stats["counterexample_claims"].append(
                        {"agent": tid, "n": n, "real": real})
                elif f"HOLDS:{a['range'][0]}-{a['range'][1]}" in raw.replace(" ", ""):
                    stats["holds"] += 1
    rep = {
        "run_id": args.run_id,
        "agents": stats["agents"], "executors": stats["exec"], "critics": stats["crit"],
        "witness_ok": stats["witness_ok"], "witness_bad": stats["witness_bad"],
        "pairs_covered": len(stats["pairs_covered"]), "pairs_total": 50000,
        "coverage_pct": round(100 * len(stats["pairs_covered"]) / 50000, 2),
        "holds_verdicts": stats["holds"],
        "counterexample_claims": stats["counterexample_claims"],
        "bad_witness_samples": bad_samples,
        "out_of_scope_valid": stats["out_of_scope_valid"],
        "scope_drift_agents": stats["scope_drift_agents"],
    }
    dest = run_dir / "master-report.json"
    dest.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print("=" * 60)
    print(f"[master] agents={rep['agents']} exec={rep['executors']} crit={rep['critics']}")
    print(f"[master] testemunhas OK={rep['witness_ok']} INVÁLIDAS={rep['witness_bad']} "
          f"FORA_DO_ESCOPO_MAS_VÁLIDAS={rep['out_of_scope_valid']}")
    print(f"[master] cobertura={rep['pairs_covered']}/50000 ({rep['coverage_pct']}%)")
    print(f"[master] HOLDS={rep['holds_verdicts']} contraexemplos_reais="
          f"{sum(1 for c in rep['counterexample_claims'] if c['real'])}")
    print(f"[master] relatório: {dest}")
    print("=" * 60)


if __name__ == "__main__":
    main()
