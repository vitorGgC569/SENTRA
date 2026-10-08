"""Local SENTRA durable Run command line interface."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from sentra_mcp.services.durable import DurableRunService
from .local_runtime import LocalRuntime
from .product import ProductPaths, ProductSettings, configure_tunnel


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

    swarm = top.add_parser(
        "swarm",
        help="Create and run persistent ChatGPT+Gemini collaboration cycles",
    )
    swarm_sub = swarm.add_subparsers(dest="action", required=True)

    swarm_create = swarm_sub.add_parser(
        "create",
        help="Create one durable Goal with persistent multi-provider Agents",
    )
    swarm_create.add_argument("--goal", required=True)
    swarm_create.add_argument("--workspace")
    swarm_create.add_argument("--run-id")
    swarm_create.add_argument(
        "--profile",
        choices=["balanced", "lean"],
        default="balanced",
        help="balanced=7 specialists; lean=1 ChatGPT + 1 Gemini smoke/low-cost cycle",
    )
    swarm_create.add_argument("--acceptance", action="append", default=[])
    swarm_create.add_argument("--constraint", action="append", default=[])

    swarm_status = swarm_sub.add_parser("status", help="Show swarm state and chat bindings")
    swarm_status.add_argument("run_id")

    swarm_list = swarm_sub.add_parser("list", help="List persistent swarm Runs")
    swarm_list.add_argument("--limit", type=int, default=100)

    swarm_chats = swarm_sub.add_parser("chats", help="Show durable chat bindings for a swarm")
    swarm_chats.add_argument("run_id")

    swarm_pause = swarm_sub.add_parser("pause", help="Pause before the next model turn")
    swarm_pause.add_argument("run_id")

    swarm_resume = swarm_sub.add_parser("resume", help="Resume a paused/recovering swarm")
    swarm_resume.add_argument("run_id")

    swarm_reconcile = swarm_sub.add_parser(
        "reconcile",
        help="Reconcile durable swarm turns without automatically replaying prompts",
    )
    swarm_reconcile.add_argument("run_id")
    swarm_reconcile.add_argument("--stale-after", type=float, default=120.0)

    swarm_cancel = swarm_sub.add_parser(
        "cancel",
        help="Cancel orchestration; ambiguous provider effects are never replayed",
    )
    swarm_cancel.add_argument("run_id")

    swarm_cleanup = swarm_sub.add_parser(
        "cleanup",
        help="Delete verified-deletable managed chats; retain unsupported providers explicitly",
    )
    swarm_cleanup.add_argument("run_id")
    swarm_cleanup.add_argument("--timeout", type=int, default=30)

    def add_swarm_run_args(command):
        command.add_argument("--rounds", type=int, default=1)
        command.add_argument("--timeout", type=int, default=180)
        command.add_argument(
            "--execute",
            action="store_true",
            help="Run OMA implementation/test using swarm context; promotion remains manual",
        )
        command.add_argument(
            "--config",
            default=str(Path(__file__).resolve().parents[1] / "config.yaml"),
        )
        command.add_argument("--worker")
        command.add_argument("--reviewer")
        command.add_argument("--sandbox", choices=["docker", "host"], default="docker")
        command.add_argument("--trust-workspace", action="store_true")

    swarm_run = swarm_sub.add_parser(
        "run",
        help="Run bounded collaboration rounds; optionally execute OMA until Quality Gate",
    )
    swarm_run.add_argument("run_id")
    add_swarm_run_args(swarm_run)

    swarm_continue = swarm_sub.add_parser(
        "continue",
        help="Continue an existing persistent swarm without recreating its Agents",
    )
    swarm_continue.add_argument("run_id")
    add_swarm_run_args(swarm_continue)

    swarm_start = swarm_sub.add_parser(
        "start",
        help="Create a swarm and immediately run collaboration rounds",
    )
    swarm_start.add_argument("--goal", required=True)
    swarm_start.add_argument("--workspace")
    swarm_start.add_argument("--run-id")
    swarm_start.add_argument(
        "--profile",
        choices=["balanced", "lean"],
        default="balanced",
        help="balanced=7 specialists; lean=1 ChatGPT + 1 Gemini smoke/low-cost cycle",
    )
    swarm_start.add_argument("--acceptance", action="append", default=[])
    swarm_start.add_argument("--constraint", action="append", default=[])
    add_swarm_run_args(swarm_start)

    service = top.add_parser(
        "service",
        help="Operate the singleton local MCP/relay/tunnel runtime",
    )
    service.add_argument(
        "action",
        choices=[
            "start", "stop", "restart", "status",
            "start-tunnel", "stop-tunnel", "restart-tunnel", "configure-tunnel",
        ],
    )
    service.add_argument(
        "--install-dir",
        help="SENTRA install/source directory; defaults to ProductPaths.default()",
    )
    service.add_argument("--tunnel-id")
    service.add_argument(
        "--runtime-key-env",
        default="CONTROL_PLANE_API_KEY",
        help="Environment variable containing the Runtime API key for configure-tunnel",
    )
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
    import asyncio

    args = _parser().parse_args(argv)
    state_root = _state_root(args.state_dir)
    try:
        if args.domain == "service":
            install_dir = (
                Path(args.install_dir).expanduser().resolve()
                if args.install_dir
                else ProductPaths.default().install_dir
            )
            paths = (
                ProductPaths(install_dir, state_root)
                if args.state_dir
                else ProductPaths.default(install_dir)
            )
            settings = ProductSettings.load(paths.settings)
            runtime = LocalRuntime(paths, settings)
            if args.action == "start":
                result = runtime.start_all()
            elif args.action == "stop":
                runtime.stop_all()
                result = {"ok": True, "stopped": True}
            elif args.action == "restart":
                result = runtime.restart_all()
            elif args.action == "status":
                result = runtime.status()
            elif args.action == "start-tunnel":
                result = {"tunnel": runtime.start_tunnel()}
            elif args.action == "stop-tunnel":
                result = {"ok": runtime.stop("tunnel"), "stopped": "tunnel"}
            elif args.action == "restart-tunnel":
                runtime.stop("tunnel")
                result = {"tunnel": runtime.start_tunnel()}
            elif args.action == "configure-tunnel":
                if not args.tunnel_id:
                    raise ValueError("--tunnel-id is required for configure-tunnel")
                runtime_key = os.environ.get(args.runtime_key_env, "")
                configure_tunnel(paths, args.tunnel_id, runtime_key)
                result = {
                    "ok": True,
                    "configured": True,
                    "tunnel_id": args.tunnel_id,
                }
            else:
                raise ValueError("unsupported service action")
        elif args.domain == "swarm":
            from orchestrator.swarm_cycle import (
                DEFAULT_SWARM_AGENTS,
                LEAN_SWARM_AGENTS,
                PersistentSwarm,
            )

            swarm = PersistentSwarm(state_root)
            try:
                if args.action in {"create", "start"}:
                    workspace = (
                        str(Path(args.workspace).expanduser().resolve())
                        if args.workspace
                        else None
                    )
                    agents = (
                        LEAN_SWARM_AGENTS
                        if args.profile == "lean"
                        else DEFAULT_SWARM_AGENTS
                    )
                    created = swarm.create(
                        args.goal,
                        workspace=workspace,
                        run_id=args.run_id,
                        agents=agents,
                        acceptance_criteria=list(args.acceptance or []),
                        constraints=list(args.constraint or []),
                    )
                    if args.action == "create":
                        result = created
                    else:
                        result = asyncio.run(
                            swarm.run_until_gate(
                                created["run_id"],
                                max_rounds=args.rounds,
                                timeout_s=args.timeout,
                                execute=bool(args.execute),
                                config_path=Path(args.config),
                                worker=args.worker,
                                reviewer=args.reviewer,
                                sandbox=args.sandbox,
                                trust_workspace=bool(args.trust_workspace),
                            )
                        )
                elif args.action == "status":
                    result = swarm.status(args.run_id)
                elif args.action == "list":
                    result = swarm.list_runs(args.limit)
                elif args.action == "chats":
                    result = swarm.chats(args.run_id)
                elif args.action == "pause":
                    result = swarm.pause(args.run_id)
                elif args.action == "resume":
                    result = swarm.resume(args.run_id)
                elif args.action == "reconcile":
                    result = swarm.reconcile(
                        args.run_id,
                        stale_after_s=args.stale_after,
                    )
                elif args.action == "cancel":
                    result = swarm.cancel(args.run_id)
                elif args.action == "cleanup":
                    result = asyncio.run(
                        swarm.cleanup(args.run_id, timeout_s=args.timeout)
                    )
                elif args.action in {"run", "continue"}:
                    result = asyncio.run(
                        swarm.run_until_gate(
                            args.run_id,
                            max_rounds=args.rounds,
                            timeout_s=args.timeout,
                            execute=bool(args.execute),
                            config_path=Path(args.config),
                            worker=args.worker,
                            reviewer=args.reviewer,
                            sandbox=args.sandbox,
                            trust_workspace=bool(args.trust_workspace),
                        )
                    )
                else:
                    raise ValueError("unsupported swarm action")
            finally:
                swarm.close()
        elif args.domain == "run":
            service = DurableRunService(state_root)
            try:
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
            finally:
                service.close()
        else:
            raise ValueError("unsupported domain")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (FileNotFoundError, PermissionError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
