"""Measured admission, not a claim that more agents improve quality."""
import math
import time


def evaluate_scale(requested, measurements, policy_hash, now=None):
    if type(requested) is not int or not 5 <= requested <= 8:
        raise ValueError("implemented role catalog supports 5..8 seats, not hundreds")
    now = time.time() if now is None else now
    # Conservative bootstrap; seats 7/8 require recent previous-tier evidence.
    eligible = [m for m in measurements if m.get("live") is True
                and m.get("policy_hash") == policy_hash
                and type(m.get("created_at")) in (int, float)
                and 0 <= now - m["created_at"] <= 7 * 86400
                and m.get("seats_observed", 0) >= requested - 1]
    eligible = list({m["run_id"]: m for m in eligible}.values())
    reasons = []
    latencies = [m["elapsed_s"] for m in eligible
                 if type(m.get("elapsed_s")) in (int, float)
                 and math.isfinite(m["elapsed_s"]) and m["elapsed_s"] > 0]
    success_rate = sum(m.get("success") is True for m in eligible) / len(eligible) if eligible else 0
    p95 = sorted(latencies)[math.ceil(len(latencies) * .95) - 1] if latencies else None
    if requested > 6:
        if len(eligible) < 3:
            reasons.append("at least 3 recent live runs at the previous tier are required")
        if success_rate < .8:
            reasons.append("candidate-ready success rate must be >= 80%")
        if len(latencies) != len(eligible) or p95 is None or p95 > 1800:
            reasons.append("complete latency evidence with p95 <= 1800s is required")
        if any(m.get("uncertain", 1) or m.get("budget_overrun", True)
               or not m.get("identity_complete", False) for m in eligible):
            reasons.append("delivery identity, budget and uncertainty checks must all pass")
    return {"allowed": not reasons, "requested_seats": requested, "samples": len(eligible),
            "success_rate": success_rate, "p95_seconds": p95, "reasons": reasons,
            "scope": "local admission heuristic; not proof of model quality or account quota"}
