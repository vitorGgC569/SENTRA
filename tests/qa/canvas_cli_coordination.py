"""Reproducible Windows QA: one real CLI recruits and coordinates two workers.

From the repository (no build or UI launch):
  python tests/qa/canvas_cli_coordination.py --model sentra/codex/current
Against an integrated installed build (both backend and CLI):
  python tests/qa/canvas_cli_coordination.py --install-dir C:/path/to/SENTRA
Only override the CLI, retaining the source backend:
  $env:SENTRA_QA_CLI_EXE = 'C:/path/to/sentra-cli.exe'
  python tests/qa/canvas_cli_coordination.py

Uses existing authentication. Default inference requires an assistant response AND
a completed provider receipt. --skip-inference is transport-only QA and records
that distinction. Every invocation owns a NEW state directory, never a live UI.
The JSON report, exact commands, effect files and protected histories are kept.
Timeouts fail without retransmitting or resuming uncertain calls.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.broker import read_endpoint
from sentra_canvas.owned_process import TaskProcess
from sentra_canvas.service import Canvas
from sentra_core.conversations import ConversationStore


def wait(check,label,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=check()
        if result:return result
        time.sleep(.1)
    raise TimeoutError(label+"; not retransmitted")


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def owns_pid(process,pid):
    """One-file frozen apps publish their child PID, not the bootloader PID."""
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.IsProcessInJob.argtypes=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)]
    kernel.IsProcessInJob.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,pid)  # QUERY_LIMITED_INFORMATION
    if not handle:return False
    try:
        member=wintypes.BOOL()
        return bool(kernel.IsProcessInJob(handle,process.job.handle,ctypes.byref(member)) and member.value)
    finally:kernel.CloseHandle(handle)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--install-dir",type=Path,help="directory with sentra-canvas.exe and sentra-cli.exe")
    parser.add_argument("--cli-exe",type=Path,default=os.environ.get("SENTRA_QA_CLI_EXE"))
    parser.add_argument("--model",default="sentra/codex/current")
    parser.add_argument("--timeout",type=int,default=180,help="single inference deadline; never retry")
    parser.add_argument("--output-dir",type=Path,help="must not exist; retained QA evidence directory")
    parser.add_argument("--skip-inference",action="store_true",help="explicit transport-only QA")
    args=parser.parse_args(argv)
    if os.name!="nt":parser.error("Windows ConPTY/DPAPI required")
    if args.timeout<1:parser.error("positive timeout required")
    cli=args.cli_exe.resolve(strict=True) if args.cli_exe else None
    install=args.install_dir.resolve(strict=True) if args.install_dir else None
    if install:
        installed_cli=(install/"sentra-cli.exe").resolve(strict=True)
        if cli and cli!=installed_cli:parser.error("installed backend uses its own sibling CLI; omit --cli-exe")
        cli=installed_cli
        backend=(install/"sentra-canvas.exe").resolve(strict=True)
    output=args.output_dir.resolve() if args.output_dir else Path(tempfile.gettempdir())/("sentra-canvas-qa-"+uuid.uuid4().hex[:12])
    output.mkdir(parents=True,exist_ok=False)
    project=output/"project";project.mkdir()
    state=output/"state"/"canvas"
    report={"started_utc":datetime.now(timezone.utc).isoformat(),"output_dir":str(output),
            "model":args.model,"mode":"installed" if install else "source-backend",
            "cli_executable":str(cli) if cli else "source Python CLI",
            "inference_required":not args.skip_inference,"status":"running","commands":[]}
    if cli:report["cli_sha256"]=file_hash(cli)
    if install:report["backend_sha256"]=file_hash(backend)
    app=None;server=None;thread=None;process=None;endpoint=None;sessions=[]
    code=1
    try:
        if install:
            launch=[str(backend),"--root",str(project),"--state-dir",str(state),"--no-open"]
            report["backend_launch"]=launch
            process=TaskProcess(launch,cwd=project,stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            def own_endpoint():
                if process.poll() is not None:raise RuntimeError("QA backend exited before publishing")
                value=read_endpoint(state)
                if value and not owns_pid(process,value.pid):raise RuntimeError("endpoint is not this QA process tree")
                return value
            endpoint=wait(own_endpoint,"QA installed broker startup")
        else:
            app=Canvas(project,state_dir=state,max_terminals=4)
            if cli:app._cli_command=lambda arguments:[str(cli),*arguments]
            server=CanvasServer(app)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            endpoint=server

        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def api(path,body=None):
            request=urllib.request.Request(f"http://127.0.0.1:{endpoint.server_port}"+path,
                data=None if body is None else json.dumps(body).encode(),
                headers={"Authorization":"Bearer "+endpoint.secret,"Content-Type":"application/json"})
            with opener.open(request,timeout=8) as response:return json.load(response)
        ws=api("/api/workspaces",{"name":"qa_coordination"})
        ident=ws["id"];workspace=Path(ws["path"])
        coordinator=api("/api/agents",{"ws":ident,"name":"coordinator","model":args.model,
                                      "role":"coordinator","start":True})
        terminal=coordinator["terminal_id"]
        conversations=ConversationStore(state.parent)
        def graph():return api("/api/graph?ws="+ident)
        def history(agent):
            try:return conversations.history_window(agent["conversation_id"])["messages"]
            except PermissionError:return []  # ConPTY child has not opened its session yet.
        def command(value):
            directive="[[CANVAS|"+value+"]]"
            report["commands"].append(directive)
            api("/api/terminal/input",{"ws":ident,"id":terminal,"data":directive+"\r"})
            # The durable tool result confirms execution in the originating CLI.
            def completed():
                messages=history(coordinator)
                index=next((i for i,m in enumerate(messages) if m["content"]==directive),None)
                if index is None:return False
                result=next((m["content"] for m in messages[index+1:]
                             if m["role"]=="user" and m["content"].startswith("[TOOL RESULT]\n")),None)
                if not result:return False
                parsed=json.loads(result.removeprefix("[TOOL RESULT]\n"))
                if isinstance(parsed,dict) and parsed.get("status")=="uncertain":
                    raise RuntimeError("uncertain coordination result; not retransmitted")
                return parsed
            return wait(completed,"CLI command "+value.split("|",1)[0])

        results=[command("create_agent|"+name+"|"+args.model+"|worker") for name in ("worker_a","worker_b")]
        workers=[r["resource"] for r in results]
        nodes=[r["node_id"] for r in results]
        snapshot=graph()
        assert len(snapshot["agents"])==3 and len(snapshot["terminals"])==3
        assert len({t["pid"] for t in snapshot["terminals"]})==3
        origin=next(n for n in snapshot["nodes"] if n["kind"]=="agent" and n["resource_id"]==coordinator["id"])
        assert all(r["link"]["source"]==origin["id"] and not r["model_acknowledged"] for r in results)
        api("/api/terminal/close",{"ws":ident,"id":terminal,"confirm":True})
        old_terminal=terminal
        coordinator=api("/api/agent/restart",{"ws":ident,"id":coordinator["id"]})
        terminal=coordinator["terminal_id"]
        assert terminal!=old_terminal
        listed=command("list")
        assert {n["id"] for n in listed}==set(nodes)
        report["coordinator_restart"]={"old_terminal_id":old_terminal,"new_terminal_id":terminal,
                                       "connections_retained":True,"workers_duplicated":False}
        pair=command("connect|"+nodes[0]+"|"+nodes[1])
        assert pair["link"]["source"]==nodes[0] and pair["link"]["target"]==nodes[1]
        team=command("create_team|qa_team|"+coordinator["id"]+"|"+",".join(nodes))
        for index,node in enumerate(nodes):
            marker="SENTRA_REAL_CLI_EFFECT_"+str(index)
            ack=command("dispatch|"+node+"|[[W|worker_"+str(index)+".txt|"+marker+"]]")
            assert ack["status"]=="sent" and not ack["model_acknowledged"]
            effect=workspace/("worker_"+str(index)+".txt")
            wait(effect.is_file,"worker physical effect")
            assert effect.read_text()==marker
        checked=command("check|"+nodes[1])
        assert "SENTRA_REAL_CLI_EFFECT_1" in checked["text"] and checked["persisted"]
        report.update(workspace=str(workspace),workspace_id=ident,coordinator=coordinator,
                      workers=workers,node_ids=nodes,team=team["resource"],terminal_pids=[t["pid"] for t in graph()["terminals"] if t["status"]=="running"],
                      transport_and_effects="passed",inference="skipped" if args.skip_inference else "pending")
        if not args.skip_inference:
            marker="SENTRA_INFERENCE_"+uuid.uuid4().hex[:12].upper()
            prompt="Responda exatamente "+marker+" 42. Calcule 6 vezes 7 mentalmente; uma linha, sem ferramentas ou diretivas."
            command("dispatch|"+nodes[0]+"|"+prompt)
            def inferred():
                status=conversations.status(workers[0]["conversation_id"])
                if status["uncertain_calls"] or status["state"] in {"provider_error","uncertain","interrupted"}:
                    raise RuntimeError("worker inference failed or uncertain; not retransmitted; inspect protected history")
                response=next((m for m in history(workers[0]) if m["role"]=="assistant" and m["content"].strip()==marker+" 42"),None)
                if not response or status["state"]!="completed":return False
                with sqlite3.connect(conversations.path) as db:
                    receipts=db.execute("""SELECT operation,provider_id,state FROM calls
                        WHERE conversation_id=? AND kind='provider' AND state='completed'""",
                        (workers[0]["conversation_id"],)).fetchall()
                if not receipts:return False
                return {"assistant_response":response["content"],"role":response["role"],
                        "completed_provider_receipts":[{"provider":r[0],"id":r[1],"state":r[2]} for r in receipts]}
            evidence=wait(inferred,"real worker model inference",args.timeout)
            checked=command("check|"+nodes[0])
            assert marker in checked["text"]
            report.update(inference="passed",inference_evidence=evidence)
        report["handoffs"]=api("/api/graph/handoffs?ws="+ident)
        assert all(h["status"]=="sent" for h in report["handoffs"])
        with sqlite3.connect(state/"canvas.sqlite3") as db:
            requests=db.execute("SELECT request_key,status FROM canvas_agent_requests").fetchall()
        assert requests and all(r[1] in {"started","created","connected"} for r in requests)
        report["persistent_requests"]=[{"request_key":r[0],"status":r[1]} for r in requests]
        report["status"]="passed"
        code=0
    except Exception as exc:
        report.update(status="failed",error_type=type(exc).__name__,error=str(exc)[:800])
    finally:
        try:
            if app:sessions=list(app._sessions.values())
            if process and endpoint:
                try:
                    endpoint.request("/api/runtime/shutdown",{"confirm":True})
                    process.communicate(timeout=20)
                finally:
                    if process.poll() is None:
                        process.terminate_tree();process.communicate(timeout=10)
            elif server:
                server.shutdown();thread.join(5);server.server_close()
            if app:app.shutdown()
            if process and process.poll() is None:
                process.terminate_tree();process.communicate(timeout=10)
            assert all(s.pty.poll() is not None for s in sessions)
            if "coordinator" in report:
                saved=conversations.history_window(report["coordinator"]["conversation_id"])["messages"]
                assert any("create_agent|worker_a" in m["content"] for m in saved)
                report["history_preserved"]=True
            report["qa_processes_closed"]=True
        except Exception as exc:
            report.update(status="failed",cleanup_error=type(exc).__name__)
            code=1
            if process and process.poll() is None:
                process.terminate_tree();process.communicate(timeout=10)
        report["finished_utc"]=datetime.now(timezone.utc).isoformat()
        (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        (output/"commands.txt").write_text("\n".join(report["commands"])+"\n",encoding="utf-8")
        print(json.dumps({"status":report["status"],"inference":report.get("inference"),
                          "report":str(output/"report.json")},ensure_ascii=False),flush=True)
    return code


if __name__=="__main__":sys.exit(main())
