"""Explicit real-model acceptance for permanent shell Dot conversations.

Own state/processes only. Three turns, one child handoff, no retry on uncertainty.
Run: python tests/qa/shell_dot_collaboration.py --output-dir <new-directory>
"""
import argparse
from contextlib import closing
import hashlib,json,sys,threading,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from sentra_canvas.service import Canvas
from sentra_canvas.__main__ import CanvasServer
from sentra_core.conversations import ConversationStore


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,required=True);parser.add_argument('--timeout',type=int,default=90);args=parser.parse_args()
    output=args.output_dir.resolve();output.mkdir(parents=True,exist_ok=False)
    project=output/'project';project.mkdir()
    app=Canvas(project,state_dir=output/'state/canvas');server=CanvasServer(app,0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    report={'status':'running','model':'sentra/codex/current','real_model':True,'automatic_retry':False}
    def wait(check,label):
        deadline=time.monotonic()+args.timeout
        while time.monotonic()<deadline:
            value=check()
            if value:return value
            time.sleep(.2)
        raise TimeoutError(label+'; no request repeated')
    try:
        pid=app.create_workspace('Dot_collaboration')['id'];runtime=app._runtime();control=app._shell_service();owner=runtime.owner
        run=runtime.run(pid)
        if run['state']!='RUNNING':runtime.durable.transition_run(run['run_id'],owner,'RUNNING')
        sid=app.shell_bridge({'action':'home','project_id':pid})['value']['space']['space_id']
        scope={'project_id':pid,'space_id':sid}
        def call(action,**fields):return app.shell_bridge({'action':action,**scope,'request_key':uuid.uuid4().hex,**fields})['value']
        root=call('dot_create',name='Coordinator',role='coordinator',model=report['model'])
        child=call('dot_create',name='Reviewer',role='worker',model=report['model'],canvas_root_dot_id=root['dot_id'])
        parent=call('conversation_create',dot_id=root['dot_id']);child_convo=call('conversation_create',dot_id=child['dot_id'],parent_conversation_id=parent['conversation_id'])
        graph=call('dot_canvas_get',dot_id=root['dot_id']);nodes={n['resource_id']:n['id'] for n in graph['nodes'] if n['kind']=='agent'}
        call('dot_canvas_link',dot_id=root['dot_id'],source=nodes[root['agent_id']],target=nodes[child['agent_id']])
        marker='DOT_COLLAB_'+uuid.uuid4().hex[:10].upper()
        payload=json.dumps({'conversation_id':child_convo['conversation_id'],'content':'Responda exatamente '+marker+' 42. Calcule 6 vezes 7, sem ferramentas.'},ensure_ascii=False)
        # Pause the owned Run while preparing its explicit owner approvals;
        # root model turns otherwise start immediately under their existing policy.
        runtime.durable.transition_run(run['run_id'],owner,'PAUSED')
        first=call('message_send',conversation_id=parent['conversation_id'],content='Use a ferramenta Canvas para executar exatamente o comando child_reply|'+payload+'. Envie uma única instrução para a conversa filha indicada. Depois responda que a instrução foi entregue; não invente o resultado do filho.')
        call('turn_permission_grant',conversation_id=parent['conversation_id'],work_item_id=first['work_item_id'],capabilities=['canvas.coordinator.handoff'],ttl_seconds=300)
        runtime.durable.transition_run(run['run_id'],owner,'RUNNING')
        def child_message():
            parent_state=control.durable.operation_status(first['operation_id'],owner)
            if parent_state['state'] in {'UNCERTAIN','FAILED','CANCELLED'}:
                report['parent_failure']=parent_state.get('error')
                raise RuntimeError('parent turn '+parent_state['state']+'; not replayed')
            rows=call('message_list',conversation_id=child_convo['conversation_id'])['items']
            return next((r for r in rows if r['role']=='user'),None)
        incoming=wait(child_message,'real parent handoff')
        call('turn_permission_grant',conversation_id=child_convo['conversation_id'],work_item_id=incoming['work_item_id'],capabilities=['model:invoke'],ttl_seconds=300)
        def answer(cid,operation_id,contains):
            state=control.durable.operation_status(operation_id,owner)['state']
            if state in {'UNCERTAIN','FAILED','CANCELLED'}:raise RuntimeError('model turn '+state+'; no retry')
            rows=call('message_list',conversation_id=cid)['items']
            found=next((r for r in rows if r['role']=='assistant' and r.get('operation_id')==operation_id and contains in r['content']),None)
            return found if found and state=='SUCCEEDED' else None
        child_answer=wait(lambda:answer(child_convo['conversation_id'],incoming['operation_id'],marker+' 42'),'real child inference')
        wait(lambda:control.durable.operation_status(first['operation_id'],owner)['state']=='SUCCEEDED','parent handoff answer')
        final=call('message_send',conversation_id=parent['conversation_id'],content='Consulte a ferramenta Canvas com o comando children. Leia a resposta da conversa filha e informe exatamente o marcador e o número que o filho respondeu. Não envie outra tarefa nem invente dados.')
        consolidated=wait(lambda:answer(parent['conversation_id'],final['operation_id'],marker+' 42'),'real parent consolidation')
        children=call('message_list',conversation_id=child_convo['conversation_id'])['items']
        assert len([r for r in children if r['role']=='user'])==1
        grants=control.authorization.list_grants(owner,principal_type='agent',principal_id=child['agent_id'])['items']
        assert not any(g['scope_id']==incoming['work_item_id'] and g['capability'].startswith('canvas.coordinator.') for g in grants)
        with app._shell_runtime.conversations._connect() as db:
            receipts=[dict(r) for r in db.execute("SELECT conversation_id,state FROM calls WHERE kind='provider' AND state='completed' AND conversation_id IN (?,?)",(parent['conversation_id'],child_convo['conversation_id']))]
        assert {r['conversation_id'] for r in receipts}=={parent['conversation_id'],child_convo['conversation_id']}
        report.update(status='passed',permanent_conversations=[parent['conversation_id'],child_convo['conversation_id']],child_messages=1,child_inherits_coordination=False,completed_provider_receipts=len(receipts),child_answer_sha256=hashlib.sha256(child_answer['content'].encode()).hexdigest(),parent_answer_sha256=hashlib.sha256(consolidated['content'].encode()).hexdigest())
    except Exception as error:report.update(status='failed',error_type=type(error).__name__,error=str(error)[:500])
    finally:
        server.shutdown();server.server_close();app.shutdown();report['own_processes_closed']=True
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
