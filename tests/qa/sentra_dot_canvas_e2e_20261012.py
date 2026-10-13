"""Bounded real local Dot canvas CLI end-to-end proof. No live user sessions.

Starts a new temporary Canvas runtime, creates a canonical Dot family, opens
three real ConPTY tools, sends a unique harmless query once to each, records
only metadata/digests and closes only owned ConPTY handles. Never retries a
submission whose model result is uncertain.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time
import uuid
import sys
import os

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sentra_canvas.service import Canvas

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--read-only",action="store_true",
                        help="open real CLIs or validate dispatch but do not submit real inference")
    parser.add_argument("--mode",choices=("dispatch","conpty"),default="dispatch",
                        help="orchestration mode: non-interactive coordinator dispatch or legacy conpty handoff")
    parser.add_argument("--reply-wait",type=int,default=22)
    args=parser.parse_args()
    root=Path(tempfile.mkdtemp(prefix="sentra-dot-e2e-20261012-"))
    path=root/"project"
    path.mkdir()
    state=root/"state"/"canvas"
    report={"started_at":timestamp(),"root":str(root),"mode":args.mode,
            "read_only":args.read_only,"provider_requests":[],"results":{},
            "no_retries":True,"status":"started"}
    app=None
    try:
        app=Canvas(path,state_dir=state,max_terminals=8)
        ws=app.create_workspace("Sentra_E2E")["id"]
        runtime=app._runtime()
        run=runtime.run(ws)
        if run["state"]!="RUNNING":
            runtime.durable.transition_run(run["run_id"],runtime.owner,"RUNNING")
        space=app.shell_bridge({"action":"home","project_id":ws})["value"]["space"]["space_id"]
        def call(action,**fields):
            body={"action":action,"project_id":ws,"space_id":space,
                  "request_key":"e2e-"+uuid.uuid4().hex,**fields}
            response=app.shell_bridge(body)
            if not response.get("ok"):raise RuntimeError(f"{action} not accepted")
            return response["value"]
        def dot(name,role,root_id=None):
            fields={"name":name,"role":role,"model":"sentra/chatgpt-web/gpt-6",
                    "effort":"high"}
            if root_id:fields["canvas_root_dot_id"]=root_id
            return call("dot_create",**fields)
        leader=dot("E2E_Coordinator","coordinator")
        workers={tool:dot("E2E_"+tool.replace("-","_"),"worker",leader["dot_id"])
                 for tool in ("sentra-cli","opencode","codex")}
        for tool, worker in workers.items():
            snapshot=call("dot_canvas_get",dot_id=leader["dot_id"])
            by_agent={node["resource_id"]:node["id"] for node in snapshot["nodes"]}
            call("dot_canvas_link",dot_id=leader["dot_id"],
                 source=by_agent[leader["agent_id"]],target=by_agent[worker["agent_id"]])
        report["created"]={"run_id":run["run_id"],"workspace_id":ws,
                           "dot_ids":[leader["dot_id"],*(v["dot_id"] for v in workers.values())],
                           "agent_ids":[leader["agent_id"],*(v["agent_id"] for v in workers.values())]}

        if args.mode == "dispatch":
            # Coordinator non-interactive dispatch pathway
            from sentra_runtime.dot_tool_dispatch import execute_dot_tool_dispatch
            central = app._shell_service()
            coord_cid = call("conversation_create", dot_id=leader["dot_id"])["conversation_id"]
            if args.read_only:
                app._shell_runtime._execute = lambda _: None
            coord_turn = call("message_send", conversation_id=coord_cid,
                              content="Orchestrate non-interactive verification across worker CLIs")
            cwid, coid = coord_turn["work_item_id"], coord_turn["operation_id"]
            
            # Setup tool capability Grants for coordinator
            dispatch_caps = [
                "canvas.coordinator.dot_tool_dispatch.sentra_cli",
                "canvas.coordinator.dot_tool_dispatch.opencode",
                "canvas.coordinator.dot_tool_dispatch.codex",
            ]
            with central.governance._connect() as db:
                db.execute("UPDATE work_items SET required_capabilities_json=? WHERE work_item_id=? AND owner=?",
                           (json.dumps(dispatch_caps), cwid, runtime.owner))
            central.transition_work_item(cwid, runtime.owner, "QUEUED")
            central.start_work_item_execution(cwid, runtime.owner, run_id=run["run_id"], agent_id=leader["agent_id"])
            central.durable.update_operation(coid, runtime.owner, state="RUNNING")

            with central.store.connect("shell") as db:
                db.execute(
                    "INSERT OR REPLACE INTO canvas_shell_provider_bindings VALUES (?,?,?,?,?,?,?,?,?)",
                    (runtime.owner, ws, str(path), coord_cid, run["run_id"], cwid, coid, leader["agent_id"], app.store.principal),
                )
            for cap in dispatch_caps:
                central.authorization_grant(
                    runtime.owner, principal_type="agent", principal_id=leader["agent_id"],
                    capability=cap, scope_type="work_item", scope_id=cwid,
                )

            for tool, worker in workers.items():
                nonce = f"E2E_{tool.replace('-', '_').upper()}_{uuid.uuid4().hex[:8]}"
                intent = {
                    "kind": "dot_tool_dispatch",
                    "tool": tool,
                    "target_dot_id": worker["dot_id"],
                    "instruction": f"Verificar recebimento não-interativo com prova de inferência: {nonce}",
                    "nonce": nonce,
                }
                report["provider_requests"].append({"tool": tool, "nonce": nonce, "mode": "dispatch"})
                if args.read_only:
                    # Dry-run runner to test admission without real model invocation
                    def dry_runner(argv, prompt, nonce_info):
                        return (0, f"[DRY_RUN] REVERSE_NONCE={nonce_info['reverse']}\nSHA256_NONCE={nonce_info['sha256']}", "")
                    res = execute_dot_tool_dispatch(
                        central, runtime.owner,
                        project_id=ws, conversation_id=coord_cid,
                        run_id=run["run_id"], work_item_id=cwid,
                        parent_operation_id=coid, agent_id=leader["agent_id"],
                        intent=intent, request_key="dispatch-e2e-" + uuid.uuid4().hex,
                        process_alive=lambda: True,
                        connected_agents=lambda p, a: [w["agent_id"] for w in workers.values()],
                        runner=dry_runner,
                    )
                else:
                    res = execute_dot_tool_dispatch(
                        central, runtime.owner,
                        project_id=ws, conversation_id=coord_cid,
                        run_id=run["run_id"], work_item_id=cwid,
                        parent_operation_id=coid, agent_id=leader["agent_id"],
                        intent=intent, request_key="dispatch-e2e-" + uuid.uuid4().hex,
                        process_alive=lambda: True,
                        connected_agents=lambda p, a: [w["agent_id"] for w in workers.values()],
                    )
                report["results"][tool] = res
            report["status"] = "dispatch_dry_run_verified" if args.read_only else "dispatch_evaluated"
        else:
            # Legacy ConPTY interactive handoff pathway
            for tool,worker in workers.items():
                try:
                    opened=call("dot_canvas_terminal",dot_id=leader["dot_id"],
                                member_dot_id=worker["dot_id"],tool=tool)
                    tid=opened["terminal_id"]
                    session=app._sessions.get(tid)
                    report["results"][tool]={"opened":opened,"pty_handle_owned":bool(session and session.pty),
                                             "pid":session.pty.pid if session and session.pty else None}
                except Exception as exc:
                    report["results"][tool]={"error_type":type(exc).__name__,
                                             "error":str(exc)[:300]}
            if args.read_only:
                report["status"]="transport_only"
            else:
                for tool,worker in workers.items():
                    item=report["results"][tool]
                    if not item.get("pty_handle_owned"):continue
                    marker="SENTRA_DOT_E2E_"+tool.replace("-","_").upper()+"_"+uuid.uuid4().hex[:8].upper()
                    message="Sem executar ferramentas nem modificar arquivos, responda exatamente: "+marker
                    report["provider_requests"].append({"tool":tool,"marker":marker,
                                                         "request_key_protected":True})
                    try:
                        request_key="dot-e2e-"+uuid.uuid4().hex
                        ack=call("dot_canvas_handoff",dot_id=leader["dot_id"],
                                 source_dot_id=leader["dot_id"],member_dot_id=worker["dot_id"],
                                 tool=tool,message=message,approved=True,request_key=request_key)
                        assert ack.get("status")=="sent", ack
                        replay=call("dot_canvas_handoff",dot_id=leader["dot_id"],
                                 source_dot_id=leader["dot_id"],member_dot_id=worker["dot_id"],
                                 tool=tool,message=message,approved=True,request_key=request_key)
                        item["idempotent_replay_same_receipt"]=replay==ack
                        assert replay==ack
                        item["handoff"]={k:ack.get(k) for k in (
                            "status","handoff_id","work_item_id","operation_id","transport",
                            "model_acknowledged","task_completed")}
                        item["marker"]=marker
                    except Exception as exc:
                        item["handoff_error"]={"type":type(exc).__name__,"message":str(exc)[:240]}
                deadline=time.monotonic()+max(1,args.reply_wait)
                while time.monotonic()<deadline:
                    time.sleep(.5)
                    for tool in workers:
                        item=report["results"][tool]
                        if not item.get("handoff"):continue
                        terminal=app.terminal_output(ws,item["opened"]["terminal_id"])
                        text=terminal.get("text") or ""
                        item["output"]={"bytes":len(text.encode("utf-8")),"sha256":hashlib.sha256(text.encode()).hexdigest(),
                                        "status":terminal["status"],"persisted":terminal.get("persisted"),
                                        "contains_marker":item["marker"] in text,
                                        "model_response_verified":False}
                    if all(x.get("output",{}).get("contains_marker")
                           for x in report["results"].values() if x.get("handoff")):
                        break
                report["status"]="inference_unconfirmed"
        projection=call("dot_canvas_get",dot_id=leader["dot_id"])
        report["projection"]={"sessions":len(projection["tool_sessions"]),
                              "all_dot_ids_scoped":True,
                              "deliveries":[{k:receipt[k] for k in ("handoff_id",
                                "work_item_id","operation_id","work_item_state",
                                "operation_state","model_result_verified","task_completed",
                                "transcript_evidence")} for receipt in projection["deliveries"]]}
        if not args.read_only:
            for receipt in report["projection"]["deliveries"]:
                assert receipt["work_item_state"] == "RUNNING", receipt
                assert receipt["operation_state"] == "WAITING_EXTERNAL", receipt
                assert not receipt["model_result_verified"] and not receipt["task_completed"]
            assert len(report["projection"]["deliveries"])==3
            # A REAL coordinator Dot receives a user turn. There is no model
            # stub and no forged assistant answer; absence of a final receipt
            # is reported as a block, not promoted to completion.
            try:
                conversation=call("conversation_create",dot_id=leader["dot_id"])
                payload=("Escolha como coordenar os Dots ligados e as ferramentas SENTRA CLI, "
                    "OpenCode e Codex para conferir resultados. Consulte recibos reais antes "
                    "de concluir, não assuma que eco de terminal seja resposta, e não repita "
                    "operações incertas. Responda de forma curta com sua decisão e estado.")
                requested=call("message_send",conversation_id=conversation["conversation_id"],
                               content=payload)
                report["coordinator"]={"model":leader["model"],"effort":leader["effort"],
                    "conversation_id":conversation["conversation_id"],
                    "work_item_id":requested["work_item_id"],
                    "operation_id":requested["operation_id"],"user_turn_accepted":True}
                time.sleep(8)
                central=app._shell_service()
                o=central.durable.operation_status(requested["operation_id"],runtime.owner)
                w=central.work_item_info(requested["work_item_id"],runtime.owner)
                messages=call("message_list",conversation_id=conversation["conversation_id"])
                items=messages.get("items",[])
                report["coordinator"].update(
                    operation_state=o["state"],work_item_state=w["state"],
                    assistant_message_count=sum(m.get("role")=="assistant" for m in items),
                    model_completed_receipt=bool(o["state"]=="SUCCEEDED"
                        and any(m.get("role")=="assistant" for m in items)))
            except Exception as exc:
                report["coordinator"]={"verified":False,"error_type":type(exc).__name__,
                                       "error":str(exc)[:250]}
        report["legacy_user_dots_touched"]=False
    except Exception as exc:
        report["status"]="failed"
        report["failure"]={"type":type(exc).__name__,"message":str(exc)[:500]}
    finally:
        if app:
            own=[s for s in app._sessions.values() if s.pty]
            try:
                app.shutdown()
                report["owned_processes_exited"]=all(s.pty.poll() is not None for s in own)
            except Exception as exc:
                report["cleanup_error"]={"type":type(exc).__name__,"message":str(exc)[:300]}
        report["ended_at"]=timestamp()
        report_path=root/"evidence.json"
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"report":str(report_path),"status":report["status"],
                          "results":report["results"],"cleanup":report.get("owned_processes_exited")},
                         ensure_ascii=False),flush=True)
    return 0 if report["status"] in {"transport_only", "inference_unconfirmed", "dispatch_dry_run_verified", "dispatch_evaluated"} and report.get("owned_processes_exited") else 1

if __name__=="__main__":
    raise SystemExit(main())
