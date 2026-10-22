"""Read-only convergence, adapted from ORCA coordinator-dag-convergence.ts.

Copyright (c) 2026 Lovecast Inc. MIT; vendor/orca/LICENSE.
SENTRA distinguishes settled from successful and never mutates gates here.
"""
def convergence(tasks):
    states=[str((task.get('lifecycle') or {}).get('stage') or task.get('state',task.get('status','unknown'))).lower() for task in tasks]
    terminal={'completed','succeeded','failed','cancelled','canceled','expired','verified'}
    settled=bool(states) and all(state in terminal for state in states)
    blocked=bool(states) and all(state in terminal|{'blocked','waiting_approval','waiting_confirmation'} for state in states) and not settled
    return {'phase':'empty' if not states else 'settled' if settled else 'blocked' if blocked else 'active',
            'all_settled':settled,'all_succeeded':settled and all(s in {'completed','succeeded','verified'} for s in states),
            'all_results_verified':bool(tasks) and all((t.get('lifecycle') or {}).get('evidence_verified') is True for t in tasks),
            'failed_count':states.count('failed'),'blocked_count':sum(s in {'blocked','waiting_approval','waiting_confirmation'} for s in states),
            'read_only':True}
