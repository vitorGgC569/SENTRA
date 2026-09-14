#!/usr/bin/env python3
"""OMA operational CLI: doctor -> relay -> isolated run -> handoff -> explicit promotion."""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def load_config(config_path: Path) -> dict:
    import yaml
    if not config_path.is_file():
        raise ValueError(f"configuration not found: {config_path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("configuration must be a YAML mapping")
    return data


def parser():
    cli = argparse.ArgumentParser(description="OMA: agentes -> gateway -> testes -> contexto para a central")
    action = cli.add_mutually_exclusive_group()
    action.add_argument("--doctor", action="store_true", help="Verifica dependências e conexão, sem chamar modelos")
    action.add_argument("--relay", action="store_true", help="Inicia relay autenticado e persistente; Ctrl+C encerra")
    action.add_argument("--demo", action="store_true", help="Demonstração offline: modelos roteirizados, testes reais")
    action.add_argument("--promote", metavar="RUN_ID", help="Aplica candidato aprovado após repetir os testes")
    action.add_argument("--status", action="store_true", help="Mostra estado/contexto persistido da run")
    action.add_argument("--queue", choices=["import", "run", "status", "inbox", "import-final", "ack", "abandon"],
                        help="MASTER_QUEUE persistente; run executa no máximo uma tarefa")
    cli.add_argument("--manifest", help="MASTER_QUEUE.json do operador (somente --queue import)")
    cli.add_argument("--context-digest", help="Hash exato lido pela IA central, para --queue ack")
    cli.add_argument("--consumer", help="Identificador do consumidor central que leu o contexto")
    cli.add_argument("--reason", help="Motivo auditável para abandonar uma tarefa interrompida")
    action.add_argument("--reconcile", action="store_true",
                        help="Lista assentos travados da run com evidência forense; não envia mensagens")
    action.add_argument("--supervise", action="store_true",
                        help="Mastiga MASTER_QUEUE 24/7 com watchdog; Ctrl+C ou runs/SUPERVISOR.stop encerra")
    cli.add_argument("--drop-seat", metavar="SEAT",
                     help="Com --reconcile: descarta a intenção incerta de um assento travado "
                          "(ex. RUN-X:validator.logic). O próximo envio abre chat novo; sem replay")
    cli.add_argument("--relay-db", help="SQLite do relay para forense (padrão: ./.oma/relay.sqlite3)")
    cli.add_argument("--job-id", help="Identificador da run (gerado quando omitido)")
    cli.add_argument("--prompt", help="Objetivo concreto da implementação")
    cli.add_argument("--workspace", help="Repositório alvo; padrão: diretório atual")
    cli.add_argument("--config", default=str(PROJECT_ROOT / "config.yaml"))
    cli.add_argument("--provider", choices=["extension", "local", "openai"], help="Provedor dos workers")
    cli.add_argument("--reviewer", choices=["extension", "local", "openai"], help="Revisor interno; não é a IA central")
    cli.add_argument("--workers", type=int, help="Tarefas concorrentes; padrão conservador: 1")
    cli.add_argument("--max-rounds", type=int, help="Máximo de tentativas de tarefas por run")
    cli.add_argument("--resume", action="store_true", help="Retoma --job-id, preservando orçamento e checkpoints")
    cli.add_argument("--trust-workspace", action="store_true",
                     help="Autoriza executar testes do projeto no host; cópia de arquivos NÃO isola o sistema operacional")
    cli.add_argument("--sandbox", choices=["host", "docker"], help="Docker: testes sem rede e sem escrita no host")
    cli.add_argument("--sandbox-image", help="Imagem local confiável; use o ID registrado para retomar/promover")
    cli.add_argument("--allow-protected", action="store_true",
                     help="Aprovação explícita de componentes protegidos, somente com --promote")
    cli.add_argument("--mock", action="store_true", help="Alias de --demo; nunca representa execução live")
    cli.add_argument("--max-iterations", type=int, default=None,
                     help="Com --supervise: encerra após N itens executados (padrão: ilimitado)")
    cli.add_argument("--idle-exit-secs", type=float, default=300,
                     help="Com --supervise: segundos ociosos até sair sozinho (padrão: 300; 0 = nunca)")
    cli.add_argument("--mode", choices=["oma", "legacy"], default="oma", help=argparse.SUPPRESS)
    return cli


async def doctor(config, workspace, *, worker=None, reviewer=None):
    from urllib.request import Request, urlopen
    checks = []
    for name in ("yaml", "pytest", "git", "openai"):
        checks.append({"check": f"python:{name}", "ok": importlib.util.find_spec(name) is not None})
    checks.append({"check": "python>=3.11", "ok": sys.version_info >= (3,11)})
    checks.append({"check": "workspace", "ok": workspace.is_dir(), "path": str(workspace)})
    from workspace.docker_runner import prepare_execution, settings
    execution = settings(config.get("validation", {}).get("execution"))
    if execution["backend"] == "docker":
        try:
            resolved = await prepare_execution(execution)
            checks.append({"check": "docker_sandbox", "ok": True, **resolved})
        except (ValueError, OSError) as exc:
            checks.append({"check": "docker_sandbox", "ok": False, "reason": str(exc),
                           "action": "python -B scripts/prepare_docker.py --build --smoke"})
    routing = config.get("routing", {})
    names = {worker or routing.get("worker","extension"), reviewer or routing.get("reviewer",worker or "extension")}
    names.update(routing.get("roles", {}).values())
    if routing.get("fallback"):
        names.add(routing["fallback"])
    if "extension" in names:
        from browser.extension_transport import ExtensionTransport, _get
        transport = ExtensionTransport(config.get("browser", {}).get("relay_base","http://127.0.0.1:8765"))
        try:
            health = await transport.health()
            await asyncio.to_thread(_get, transport.base+"/auth/check",5,transport.token)
            checks.append({"check": "relay_authenticated", "ok": True})
            checks.append({"check": "edge_workers", "ok": bool(health.get("workers_online")),
                           "workers": health.get("workers_online",[])})
        except Exception as exc:
            checks.append({"check": "relay_authenticated", "ok": False, "reason": type(exc).__name__,
                           "action": "python main.py --relay; depois parear e ativar a extensão"})
    if "local" in names:
        import os
        local = config.get("local_model",{})
        def models():
            key = os.environ.get(local.get("api_key_env","OMA_LOCAL_API_KEY"),local.get("api_key","local"))
            request = Request(local.get("base_url","http://127.0.0.1:11434/v1").rstrip("/")+"/models",
                              headers={"Authorization": "Bearer "+key})
            with urlopen(request, timeout=5) as response:
                return json.load(response)
        try:
            data = await asyncio.to_thread(models)
            available = [item["id"] for item in data.get("data",[])]
            model = local.get("model_name","qwen2.5:0.5b-instruct-q4_K_M")
            checks.append({"check": "local_model", "ok": model in available, "configured_model": model,
                           "available_models": available})
        except Exception as exc:
            checks.append({"check": "local_model", "ok": False, "reason": type(exc).__name__})
    return {"ok": all(check["ok"] for check in checks), "checks": checks,
            "note": "Diagnóstico de conexão; não executa testes nem comprova uma conversa no Edge."}


async def serve_relay(config):
    from urllib.parse import urlparse
    from native_bridge.relay import RelayServer
    from native_bridge.settings import relay_settings
    base = config.get("browser",{}).get("relay_base","http://127.0.0.1:8765")
    address = urlparse(base)
    token, path, database = relay_settings(PROJECT_ROOT)
    server = RelayServer(host=address.hostname or "127.0.0.1", port=address.port or 8765,
                         token=token, db_path=database, extension_dir=PROJECT_ROOT/"edge_extension").start()
    print(f"Relay: {base}\nToken para parear nas opções da extensão: {path}\nBanco: {database}\nCtrl+C encerra.", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await asyncio.to_thread(server.stop)


async def main_async(argv=None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    if args.mode == "legacy":
        raise ValueError("o modo legacy não integra as garantias atuais; use o caminho OMA")
    if args.workers is not None and not 1 <= args.workers <= 8:
        raise ValueError("--workers deve ser 1..8")
    if args.max_rounds is not None and args.max_rounds < 1:
        raise ValueError("--max-rounds deve ser positivo")
    if args.max_iterations is not None and args.max_iterations < 1:
        raise ValueError("--max-iterations deve ser positivo")
    if args.idle_exit_secs is not None and args.idle_exit_secs < 0:
        raise ValueError("--idle-exit-secs deve ser >= 0 (0 = nunca sai por ociosidade)")
    if args.allow_protected and not args.promote:
        raise ValueError("--allow-protected só pode ser usado com --promote")
    config = load_config(Path(args.config).resolve())
    if args.sandbox or args.sandbox_image:
        execution = config.setdefault("validation", {}).setdefault("execution", {})
        if args.sandbox:
            execution["backend"] = args.sandbox
        if args.sandbox_image:
            execution["image"] = args.sandbox_image
    workspace = Path(args.workspace or ".").resolve()
    if args.queue:
        from orchestrator.master_queue import MasterQueue
        queue = MasterQueue(workspace)
        if args.queue == "import":
            if not args.manifest:
                raise ValueError("--queue import exige --manifest")
            result = queue.ingest(json.loads(Path(args.manifest).read_text(encoding="utf-8-sig")), config)
        elif args.queue == "run":
            result = await queue.run_next(trust_workspace=args.trust_workspace)
        elif args.queue == "status":
            result = queue.status()
        elif args.queue == "inbox":
            result = queue.inbox()
        elif args.queue == "import-final":
            result = queue.import_final(args.job_id)
        elif args.queue == "ack":
            result = queue.acknowledge(args.job_id, args.context_digest, args.consumer)
        else:
            result = queue.abandon(args.job_id, args.reason)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if isinstance(result, dict) and result.get("status") in {"FAILED", "BLOCKED"} else 0
    if args.supervise:
        from orchestrator.supervisor import Supervisor
        supervisor = Supervisor(workspace, max_iterations=args.max_iterations,
                                idle_exit_secs=args.idle_exit_secs,
                                trust_workspace=args.trust_workspace)
        result = await supervisor.serve()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("failed", 0) == 0 and result.get("stalled", 0) == 0 else 1
    if args.doctor:
        result = await doctor(config, workspace, worker=args.provider, reviewer=args.reviewer)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 2
    if args.relay:
        await serve_relay(config)
        return 0
    from orchestrator.persistence import PersistenceStore
    if args.status:
        if not args.job_id:
            raise ValueError("--status exige --job-id")
        path = workspace / "runs" / args.job_id
        # Validate ID before reading paths, without creating a run for a typo.
        import re
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.job_id) or not path.is_dir():
            raise ValueError("run não encontrada")
        store = PersistenceStore(args.job_id, workspace/"runs")
        data = store._load_json(store.run_dir/"handoff.json",{}) or store.load_run_metadata()
        from orchestrator.conversation_pool import inspect_conversations
        data = {**data, "conversation_pool": inspect_conversations(store.run_dir, args.job_id)}
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if args.reconcile:
        if not args.job_id:
            raise ValueError("--reconcile exige --job-id")
        from orchestrator.reconcile import blocked_seats, drop_seat, relay_jobs_for_task
        path = workspace / "runs" / args.job_id
        import re
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.job_id) or not path.is_dir():
            raise ValueError("run não encontrada")
        stuck = blocked_seats(path)
        db = Path(args.relay_db) if args.relay_db else (PROJECT_ROOT / ".oma" / "relay.sqlite3")
        report = {"run_id": args.job_id, "blocked_seats": []}
        for entry in stuck:
            task_id = entry.get("task_id") or ""
            since = (entry.get("updated") or 0) - 3600
            entry["relay_jobs"] = relay_jobs_for_task(db, task_id, since_ts=since) if task_id else []
            report["blocked_seats"].append(entry)
        if args.drop_seat:
            if not any(e["seat"] == args.drop_seat for e in stuck):
                raise ValueError(f"assento '{args.drop_seat}' não está travado; nada a reconciliar")
            record = drop_seat(path, args.drop_seat,
                               reason="operator discard of stale intent; next send opens a fresh chat, no replay")
            report["dropped"] = record
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    from orchestrator.configuration import build_router, close_router, engine_options
    from orchestrator.runtime import IntegratedRun, promote_candidate
    options = engine_options(config, args.max_rounds, args.workers)
    demo = args.demo or args.mock
    if not demo and options["execution"]["backend"] == "host" and not args.trust_workspace:
        raise ValueError("use --sandbox docker; testes no host exigem --trust-workspace; use --demo para experimentar")
    if args.promote:
        result = await promote_candidate(workspace, args.promote, allow_protected=args.allow_protected,
                                          commands=options["validation_commands"], profiles=options["command_profiles"],
                                          timeout=options["test_timeout"], execution=options["execution"],
                                          allowed_patch_paths=options["allowed_patch_paths"])
    else:
        if args.resume and not args.job_id:
            raise ValueError("--resume exige --job-id")
        if demo and args.resume:
            raise ValueError("retome a demo com --resume --trust-workspace, sem --demo")
        run_id = args.job_id or "run-" + uuid.uuid4().hex[:12]
        if demo:
            workspace = Path(args.workspace).resolve() if args.workspace else PROJECT_ROOT / ".oma" / ("demo-"+uuid.uuid4().hex[:8])
            if workspace.exists() and any(workspace.iterdir()):
                raise ValueError("--demo exige um diretório vazio/novo, para não modificar arquivos existentes")
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace/"math_utils.py").write_text("# Offline demonstration fixture\n",encoding="utf-8")
            print("DEMO OFFLINE: modelos roteirizados; filesystem, gateway, subprocessos e testes reais.")
            objective = "Implement factorial and verify zero, positive and negative inputs"
            # Do not run arbitrary operator profiles in the generated demonstration.
            options["validation_commands"], options["command_profiles"] = ["[[TEST|all]]"], {}
            # Scripted providers create no remote chats and consume no quota.
            # Exercise the fixed-seat path without imposing live-browser waits.
            options["inter_call_delay_s"] = 0
        else:
            objective = args.prompt
            if args.resume and not objective:
                store = PersistenceStore(run_id, workspace/"runs")
                objective = store._load_json(store.run_dir/"snapshot.json",{}).get("objective")
            if not objective:
                raise ValueError("informe um objetivo concreto em --prompt")
            if args.resume:
                store = PersistenceStore(run_id, workspace/"runs")
                existing = store._load_json(store.run_dir/"handoff.json",{})
                if existing.get("status") in {"CANDIDATE_READY","APPLIED"}:
                    if existing.get("objective") != objective:
                        raise ValueError("resume objective differs from saved handoff")
                    print(f"Status: {existing['status']}\nContexto para a central: {existing['handoff_path']}\nNenhuma chamada de modelo necessária.")
                    return 0
            diagnostics = await doctor(config, workspace, worker=args.provider, reviewer=args.reviewer)
            if not diagnostics["ok"]:
                print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
                return 2
        router = build_router(config, worker=args.provider, reviewer=args.reviewer, mock=demo)
        print(f"Run: {run_id}\nWorkspace: {workspace}\nWorkers: {router.primary_name}; revisor interno: {router.providers['master'].model_name}")
        try:
            result = await IntegratedRun(workspace, run_id, objective, router, resume=args.resume, **options).run()
        finally:
            await close_router(router)
    print(f"\nStatus: {result['status']}\nTarefas: {result['completed_tasks']}/{result['total_tasks']}")
    print(f"Contexto para a central: {result['handoff_path']}\nPatch: {result['patch_path']}")
    for error in result.get("errors",[]):
        print(f"Pendência: {error}")
    return 0 if result["status"] in {"CANDIDATE_READY","APPLIED"} else (130 if result["status"] == "CANCELLED" else 1)


def main():
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8",errors="replace")
        sys.stderr.reconfigure(encoding="utf-8",errors="replace")
    try:
        code = asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nInterrompido. Use --resume para retomar uma run; nenhum candidato foi autopromovido.")
        code = 130
    except Exception as exc:
        print(f"ERRO: {exc}",file=sys.stderr)
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
