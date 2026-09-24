"""Local SENTRA durable Run command line interface."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from sentra_mcp.services.durable import DurableRunService
from .product import ProductPaths


def _state_root(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return ProductPaths.default().state_dir


def _owner_for(service: DurableRunService, run_id: str) -> str:
    with service.lock:
        row = service.db.execute(
            "SELECT owner FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
    if row is None:
        raise FileNotFoundError("run not found")
    return str(row["owner"])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentra",
        description="SENTRA durable execution CLI",
    )
    parser.add_argument(
        "--state-dir",
        help="Override SENTRA state directory (default: SENTRA_STATE_DIR or ~/.sentra)",
    )
    top = parser.add_subparsers(dest="domain", required=True)
    run = top.add_parser("run", help="Inspect or resume durable Runs")
    sub = run.add_subparsers(dest="action", required=True)
    resume = sub.add_parser("resume", help="Reconstruct durable Run context")
    resume.add_argument("run_id")

    status = sub.add_parser("status", help="Show complete durable Run state")
    status.add_argument("run_id")

    events = sub.add_parser("events", help="Read append-only Run events")
    events.add_argument("run_id")
    events.add_argument("--offset", type=int, default=0)
    events.add_argument("--limit", type=int, default=100)

    reconcile = sub.add_parser(
        "reconcile",
        help="Compare desired and observed state without replaying side effects",
    )
    reconcile.add_argument("run_id")
    reconcile.add_argument("--stale-after", type=float, default=120.0)

    listing = sub.add_parser("list", help="List all locally persisted Runs")
    listing.add_argument("--limit", type=int, default=100)
    return parser


def _list_all(service: DurableRunService, limit: int) -> dict[str, Any]:
    if not 1 <= limit <= 1000:
        raise ValueError("--limit must be 1..1000")
    with service.lock:
        rows = service.db.execute(
            "SELECT * FROM runs ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        items = [
            service._run_info_locked(row, include_details=False)
            for row in rows
        ]
        total = int(service.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
    return {
        "items": items,
        "page": {
            "offset": 0,
            "limit": limit,
            "returned": len(items),
            "total": total,
            "next_offset": len(items) if len(items) < total else None,
        },
    }
def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = DurableRunService(_state_root(args.state_dir))
    try:
        if args.domain != "run":
            raise ValueError("unsupported domain")
        if args.action == "list":
            result = _list_all(service, args.limit)
        else:
            owner = _owner_for(service, args.run_id)
            if args.action == "resume":
                result = service.resume(args.run_id, owner)
            elif args.action == "status":
                result = service.run_status(args.run_id, owner)
            elif args.action == "events":
                result = service.events(
                    args.run_id,
                    owner,
                    offset=args.offset,
                    limit=args.limit,
                )
            elif args.action == "reconcile":
                result = service.reconcile(
                    args.run_id,
                    owner,
                    stale_after_s=args.stale_after,
                )
            else:
                raise ValueError("unsupported run action")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (FileNotFoundError, PermissionError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
