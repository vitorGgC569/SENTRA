"""Real model: one owner full selection, two agent-created Dots, broker reopen.

No manual Grants, mocked models, filesystem effects or repeated submissions.
Pause/reopen occurs at the durable checkpoint before final consolidation.
"""
import argparse,csv,hashlib,json,sys,threading,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from sentra_canvas.service import Canvas
from sentra_canvas.__main__ import CanvasServer


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=240);args=parser.parse_args()
    output=args.output_dir.resolve();output.mkdir(parents=True,exist_ok=False)
    directory=output/'project';directory.mkdir()
    app=None;server=None;report={'status':'running','model':'sentra/codex/current',
        'real_model':True,'manual_grant_calls':0,'automatic_effect_retry':False}
    def boot():
        nonlocal app,server
        app=Canvas(directory,state_dir=output/'state/canvas');server=CanvasServer(app,0)
        threading.Thread(target=server.serve_forever,daemon=True).start()
    def close():
        nonlocal app,server
        if server:server.shutdown();server.server_close();server=None
        if app:app.shutdown();app=None
    def wait(check,label):
        deadline=time.monotonic()+args.timeout
        while time.monotonic()<deadline:
            value=check()
            if value:return value
            time.sleep(.4)
        raise TimeoutError(label+'; no submission repeated')
    try:
        boot();pid=app.create_workspace('Full_Dot_recovery')['id']
        control=app._shell_service();owner=app._runtime().owner
        run=app._runtime().run(pid)
        if run['state']!='RUNNING':app._runtime().durable.transition_run(run['run_id'],owner,'RUNNING')
        sid=app.shell_bridge({'action':'home','project_id':pid})['value']['space']['space_id']
        scope={'project_id':pid,'space_id':sid}
        def call(action,**fields):
            return app.shell_bridge({'action':action,**scope,'request_key':uuid.uuid4().hex,**fields})['value']
        root=call('dot_create',name='Coordenador',role='coordinator',model=report['model'])
        parent=call('conversation_create',dot_id=root['dot_id']);cid=parent['conversation_id']
        profile=call('access_set',conversation_id=cid,mode='full')
        project=Path(app.store.workspace(pid)['path'])
        data=[{'region':['Norte','Sul','Leste'][i%3],'amount':((i*7)%19)+1} for i in range(60)]
        with (project/'vendas.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['region','amount']);w.writeheader();w.writerows(data)
        totals={key:sum(r['amount'] for r in data if r['region']==key) for key in ['Norte','Sul','Leste']}
        expected={'total':sum(totals.values()),'rows':len(data),'by_region':totals}
        common=' Consulte CANVAS machine_list; use os IDs reais e computer:file.read/write ou computer:execute. O acesso completo já foi selecionado e o host prepara sua autorização. Não use arquivos simulados. '
        aggregation='Leia vendas.csv neste projeto, calcule total e soma por region. Grave agregacao.json como JSON com chaves total e by_region, sem markdown. Confira relendo o arquivo. Não crie subagentes.'+common
        audit='Leia vendas.csv neste projeto, confira o número de registros e total dos valores. Grave auditoria.json como JSON com chaves rows e total, sem markdown. Confira relendo o arquivo. Não crie subagentes.'+common
        first=call('message_send',conversation_id=cid,content=(
            'Tarefa de conciliação de vendas: crie exatamente dois Dots trabalhadores chamados Agregador e Auditor, ambos com modelo sentra/codex/current e role worker. '
            'Use CANVAS coordinator_intent com kind create_dot, name, role worker, model e instructions para cada um; o host conecta os Dots. '
            'Envie uma tarefa para cada um via CANVAS dispatch|nome|instrução. Agregador recebe: '+aggregation+
            ' Auditor recebe: '+audit+' Depois de entregar ambas, responda apenas DELEGACAO_REGISTRADA. '
            'Não execute as tarefas deles nem invente resultados. A consolidação será feita após a retomada.'))
        def completed(message):
            op=app._shell_service().durable.operation_status(message['operation_id'],app._runtime().owner)
            if op['state'] in {'FAILED','UNCERTAIN','CANCELLED'}:
                raise RuntimeError('turn '+op['state']+'; not replayed')
            return op if op['state']=='SUCCEEDED' else None
        wait(lambda:completed(first),'real coordinator delegation')
        conversations=call('conversation_list',limit=100)['items']
        children=[c for c in conversations if c.get('parent_conversation_id')==cid]
        assert len(children)==2,children
        child_turns=[]
        for c in children:
            user=[r for r in call('message_list',conversation_id=c['conversation_id'])['items'] if r['role']=='user']
            assert len(user)==1
            child_turns.append(user[0]);wait(lambda m=user[0]:completed(m),'real child result')
            assert call('access_status',conversation_id=c['conversation_id'])['full_source']['work_item_id']==profile['work_item_id']
        a=json.loads((project/'agregacao.json').read_text(encoding='utf-8'))
        b=json.loads((project/'auditoria.json').read_text(encoding='utf-8'))
        assert a['total']==expected['total'] and a['by_region']==totals and b['total']==expected['total'] and b['rows']==60
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [project/'agregacao.json',project/'auditoria.json']}
        # The user pauses at a known checkpoint. Do not pretend this exercises
        # replay of an in-flight physical effect, which must stay uncertain.
        app.run_control(pid,'pause')
        checkpoint={'conversation_id':cid,'children':[c['conversation_id'] for c in children],
            'child_operations':[t['operation_id'] for t in child_turns],'files':before,'stage':'awaiting_consolidation'}
        (output/'checkpoint.json').write_text(json.dumps(checkpoint,indent=2),encoding='utf-8')
        close();boot()
        assert app._runtime().run(pid)['state']=='PAUSED'
        assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [project/'agregacao.json',project/'auditoria.json']}
        assert call('access_status',conversation_id=cid)['mode']=='full'
        app.run_control(pid,'resume')
        final=call('message_send',conversation_id=cid,content=(
            'Continue a tarefa interrompida usando CANVAS children e os resultados já existentes. Não crie Dots nem envie novas tarefas. '
            'Leia agregacao.json e auditoria.json, compare totais e confira vendas.csv. Grave conciliacao.json com '
            'as chaves total, rows, by_region e verified (true somente se a comparação real passar). Releia o arquivo para conferir. '
            'Após reler, use CANVAS verify_result com os operation_ids reais dessas leituras para registrar a evidência de integridade. Informe o caminho e os resultados conferidos na conversa.'+common))
        wait(lambda:completed(final),'real final consolidation after reopen')
        result=json.loads((project/'conciliacao.json').read_text(encoding='utf-8'))
        assert result['total']==expected['total'] and result['rows']==60 and result['by_region']==totals and result['verified'] is True,result
        for c in children:
            assert len([r for r in call('message_list',conversation_id=c['conversation_id'])['items'] if r['role']=='user'])==1
        dots=call('dot_list',limit=100)['items'];assert len(dots)==3
        graph=call('dot_canvas_get',dot_id=root['dot_id'])
        final_task=next(t for t in graph['tasks'] if t.get('work_item_id')==final['work_item_id'])
        assert final_task['lifecycle']['stage']=='verified',final_task['lifecycle']
        report['final_verification']=final_task['verification']
        report.update(status='passed',owner_full_selections=1,agent_created_dots=2,
            permanent_conversations=checkpoint['children']+[cid],broker_reopened=True,
            interruption_checkpoint='awaiting_consolidation',interrupted_inflight_effect_replayed=False,
            child_instructions=2,children_duplicated=False,expected=expected,
            verified_artifacts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [project/'agregacao.json',project/'auditoria.json',project/'conciliacao.json']})
    except Exception as error:
        report.update(status='failed',error_type=type(error).__name__,error=str(error)[:600])
    finally:
        close();report['own_processes_closed']=True
        (output/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
