#!/usr/bin/env python3
"""Calibra budgets a partir de dados REAIS de runs (nunca de chute).

Agrega uso de tokens por papel somente de providers reais (browser-*),
ignorando mocks. Emite p50/p95 e budgets recomendados (p95 x 1.5).
Uso: python scripts/calibrate_budgets.py [--save runs/budget-calibration.json]
"""
import argparse
import glob
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REAL_PREFIXES = ("browser-",)
SAFETY = 1.5


def _load(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def _toks(tu):
    tu = tu or {}
    return (tu.get("input_tokens") or 0) + (tu.get("output_tokens") or 0)


def collect(root="."):
    per_role = defaultdict(list)
    mocked = defaultdict(list)
    run_totals = []
    pats = [f"{root}/runs/*/validations.json",
            f"{root}/.oma/self-improvement/*/repository/runs/*/validations.json",
            f"{root}/runs/*/candidates.json",
            f"{root}/.oma/self-improvement/*/repository/runs/*/candidates.json",
            f"{root}/runs/*/metrics.json",
            f"{root}/.oma/self-improvement/*/repository/runs/*/metrics.json"]
    for pat in pats:
        for f in glob.glob(pat):
            d = _load(f)
            if d is None:
                continue
            if f.endswith("validations.json"):
                reps = d if isinstance(d, list) else d.get("reports", d.get("validations", []))
                for r in reps:
                    tot = _toks(r.get("token_usage"))
                    if tot <= 0:
                        continue
                    model = ((r.get("token_usage") or {}).get("model") or "")
                    role = r.get("validator_role", "?")
                    (per_role if model.startswith(REAL_PREFIXES) else mocked)[role].append(tot)
            elif f.endswith("candidates.json"):
                items = d if isinstance(d, list) else []
                for c in items:
                    tot = _toks(c.get("token_usage"))
                    if tot <= 0:
                        continue
                    model = ((c.get("token_usage") or {}).get("model") or "")
                    role = f"candidate:{c.get('created_by', '?')}"
                    (per_role if model.startswith(REAL_PREFIXES) else mocked)[role].append(tot)
            elif f.endswith("metrics.json"):
                tm = _toks((d.get("tokens_master") or {}))
                ts = _toks((d.get("tokens_secondary") or {}))
                if tm + ts > 0:
                    run_totals.append({"run": f, "master": tm, "secondary": ts,
                                       "tasks": d.get("tasks_total", 0)})
    return per_role, mocked, run_totals


def pct(vals, p):
    if not vals:
        return 0
    s = sorted(vals)
    return s[min(int(len(s) * p / 100), len(s) - 1)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default="runs/budget-calibration.json")
    args = ap.parse_args()
    per_role, mocked, run_totals = collect()
    table = {}
    for role in sorted(per_role):
        vals = per_role[role]
        table[role] = {"n": len(vals), "p50": pct(vals, 50), "p95": pct(vals, 95),
                       "max": max(vals),
                       "recommended_call_budget": int(pct(vals, 95) * SAFETY)}
    out = {"per_role_real": table,
           "mocked_samples_excluded": {k: len(v) for k, v in mocked.items()},
           "run_totals": run_totals,
           "method": "p95 x 1.5 sobre providers reais; mocks excluídos"}
    # Sugestão de task budget: soma dos papéis de 1 wave + margem.
    v = [table[r]["recommended_call_budget"] for r in table if r.startswith("validator.")]
    e = [table[r]["recommended_call_budget"] for r in table if "executor" in r or "repair" in r]
    if v:
        out["suggested_task_budget"] = int((sum(sorted(v, reverse=True)[:4]) + sum(e)) * 1.5) if e else int(sum(sorted(v, reverse=True)[:4]) * 1.5)
    Path(args.save).parent.mkdir(parents=True, exist_ok=True)
    Path(args.save).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"{'papel':<32}{'n':>5}{'p50':>10}{'p95':>10}{'max':>10}{'budget':>10}")
    for role, row in table.items():
        print(f"{role:<32}{row['n']:>5}{row['p50']:>10}{row['p95']:>10}{row['max']:>10}{row['recommended_call_budget']:>10}")
    print("mocks excluídos:", dict(out["mocked_samples_excluded"]))
    print("suggested_task_budget:", out.get("suggested_task_budget"))
    print("salvo em", args.save)


if __name__ == "__main__":
    main()
