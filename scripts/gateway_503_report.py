"""Sanitized SENTRA model outage evidence from the authoritative local gateway audit.

Never reads or prints prompts, request bodies, cookies, tokens, or arbitrary event details.
This is read-only and cannot replay /v1/responses.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path


ACTIONS = {
    "model.gateway.received",
    "model.gateway.forwarded",
    "model.gateway.upstream_5xx",
    "model.gateway.transport_error",
}


def parse_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when.astimezone(timezone.utc) if when.tzinfo else None


def sanitized_report(path: Path, *, since_minutes: int = 30, max_lines: int = 100_000,
                     error_limit: int = 12, now: datetime | None = None) -> dict:
    if not (1 <= since_minutes <= 24 * 60):
        raise ValueError("since_minutes must be within 1 day")
    if not (1 <= max_lines <= 1_000_000):
        raise ValueError("max_lines out of range")
    stamp = now or datetime.now(timezone.utc)
    since = stamp - timedelta(minutes=since_minutes)
    # Deque stores a bounded tail; opening in text mode never mutates the original log.
    with Path(path).open("r", encoding="utf-8", errors="replace") as stream:
        lines = deque(stream, maxlen=max_lines)
    by_request = {}
    forwarded = Counter()
    for line in lines:
        if '"action":"model.gateway.' not in line:
            continue
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        action = event.get("action")
        if action not in ACTIONS:
            continue
        when = parse_timestamp(event.get("timestamp"))
        if when is None or when < since or when > stamp + timedelta(minutes=2):
            continue
        details = event.get("details")
        if not isinstance(details, dict):
            continue
        cid = details.get("correlation_id")
        if not isinstance(cid, str) or len(cid) != 16 or any(char not in "0123456789abcdef" for char in cid):
            continue
        trace = by_request.setdefault(cid, {"request_id": cid, "at_utc": when.isoformat(),
                                            "forwarded_status": None, "upstream_ray": None,
                                            "transport_failure_phase": None})
        if action == "model.gateway.forwarded":
            status = details.get("upstream_http_status")
            if type(status) is int and 100 <= status <= 599:
                trace["forwarded_status"] = status
                forwarded[str(status)] += 1
            elif status is None:
                forwarded["unknown"] += 1
        elif action == "model.gateway.upstream_5xx":
            ray = details.get("cf_ray")
            if isinstance(ray, str) and len(ray) < 40:
                trace["upstream_ray"] = ray
        elif action == "model.gateway.transport_error":
            phase = details.get("failure_phase")
            if phase in {"connect", "request_or_headers", "upstream_connect",
                         "upstream_headers", "stream_or_downstream_delivery", "unknown"}:
                trace["transport_failure_phase"] = phase

    problem = sorted((trace for trace in by_request.values()
                      if (trace["forwarded_status"] is not None
                          and trace["forwarded_status"] >= 500)
                      or trace["transport_failure_phase"] is not None),
                     key=lambda trace: trace["at_utc"], reverse=True)
    total = sum(forwarded.values())
    return {
        "window_minutes": since_minutes,
        "sampled_forwarded_requests": total,
        "http_status_counts": dict(sorted(forwarded.items())),
        "upstream_5xx_rate_percent": (round(
            100 * sum(count for status, count in forwarded.items()
                      if status.isdigit() and int(status) >= 500) / total, 1
        ) if total else None),
        "latest_errors": problem[:error_limit],
        "automatic_retry_performed_by_report": False,
        "note": "HTTP upstream errors are not proof that a POST may be replayed.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=Path(".sentra/mcp-audit.jsonl"))
    parser.add_argument("--since-minutes", type=int, default=30)
    parser.add_argument("--max-lines", type=int, default=100_000)
    parser.add_argument("--error-limit", type=int, default=12)
    args = parser.parse_args(argv)
    value = sanitized_report(args.audit, since_minutes=args.since_minutes,
                             max_lines=args.max_lines, error_limit=args.error_limit)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
