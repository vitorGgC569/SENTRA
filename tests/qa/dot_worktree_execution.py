"""Three real model workers edit isolated Git trees, then reopen the broker.

Own source Canvas/state only. No fake actors, models or effects; no publication.
"""
import argparse,hashlib,json,subprocess,sys,threading,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from sentra_canvas.service import Canvas
from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.task_workspace import binding


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=240);args=parser.parse_args()
    output=args.output_dir.resolve();output.mkdir(parents=True,exist_ok=False)
    directory=output/'project';directory.mkdir();app=None;server=None
    report={'status':'running','real_model':True,'model':'sentra/codex/current',
        'manual_grant_calls':0,'automatic_effect_retry':False,'publication_requested':False}
    # Passive diagnostics wrap the real dispatcher/process. No result is mocked.
    import sentra_canvas.shell_runtime as shell_runtime
    from sentra_canvas.shell_actor import ShellActorService
    original_process=shell_runtime.TaskProcess;original_dispatch=ShellActorService.dispatch
    trace_lock=threading.Lock()
    def trace(record):
        with trace_lock:
            with (output/'trace.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(record)+'\n')
    def observed_dispatch(actor,token,payload):
        started=time.monotonic()
        try:
            value=original_dispatch(actor,token,payload)
            trace({'action':payload.get('action'),'seconds':time.monotonic()-started,'bytes':len(json.dumps(value).encode())})
            return value
        except Exception as error:
            trace({'action':payload.get('action'),'error':str(error)[:400],'seconds':time.monotonic()-started});raise
    class ObservedProcess(original_process):
        def __init__(self,command,**options):
            super().__init__(command,**options);trace({'process':self.pid,'cwd':str(options.get('cwd'))})
        def communicate(self,*values,**options):
            result=super().communicate(*values,**options)
            if self.returncode:
                (output/('process-'+str(self.pid)+'.log')).write_bytes((result[0] or b'')[-16000:])
            return result
    shell_runtime.TaskProcess=ObservedProcess;ShellActorService.dispatch=observed_dispatch
    def boot():
        nonlocal app,server
        app=Canvas(directory,state_dir=output/'state/canvas');server=CanvasServer(app,0)
        threading.Thread(target=server.serve_forever,daemon=True).start()
    def close():
        nonlocal app,server
        if server:server.shutdown();server.server_close();server=None
        if app:app.shutdown();app=None
    def git(root,*values):
        return subprocess.run(['git','-C',str(root),*values],check=True,capture_output=True,text=True,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout.strip()
    try:
        boot();pid=app.create_workspace('Worktree_execution')['id'];control=app._shell_service();owner=app._runtime().owner
        run=app._runtime().run(pid)
        if run['state']!='RUNNING':control.durable.transition_run(run['run_id'],owner,'RUNNING')
        sid=app.shell_bridge({'action':'home','project_id':pid})['value']['space']['space_id'];scope={'project_id':pid,'space_id':sid}
        def call(action,**fields):
            return app.shell_bridge({'action':action,**scope,'request_key':uuid.uuid4().hex,**fields})['value']
        root=call('dot_create',name='Coordenador Git',role='coordinator',model=report['model'])
        parent=call('conversation_create',dot_id=root['dot_id']);cid=parent['conversation_id']
        call('access_set',conversation_id=cid,mode='full')
        project=Path(app.store.workspace(pid)['path']);git(project,'init');git(project,'config','user.name','SENTRA QA');git(project,'config','user.email','qa@localhost')
        (project/'.gitignore').write_text('.sentra/\n',encoding='utf-8')
        for i in range(3):(project/f'worker{i}.txt').write_text('base\n',encoding='utf-8')
        git(project,'add','.');git(project,'commit','-m','fixture base');head=git(project,'rev-parse','HEAD')
        tasks=[]
        for i in range(3):
            instruction=(f'Use CANVAS isolate_work sem argumentos para criar sua pasta Git isolada. Consulte CANVAS context depois. '
                f'Em seguida, use CANVAS machine_list e o computador local autorizado para ler o arquivo relativo worker{i}.txt, '
                f'editar SOMENTE este arquivo para o conteúdo exato trabalhador-{i} seguido de quebra de linha, '
                'e reler o arquivo relativo. Use computer:execute sem cwd para informar a pasta atual e conferir que é a pasta '
                'do execution_workspace, não a pasta principal. Registre CANVAS verify_result para a leitura final. '
                'Não crie subagentes, não escreva novos arquivos, não faça commit, merge ou push. '
                'O host prepara Grants/WorkItems; não peça configuração manual. Responda o caminho real e o hash conferido.')
            tasks.append(f'Codificador{i} recebe esta tarefa: {instruction}')
        first=call('message_send',conversation_id=cid,content=(
            'Crie exatamente três Dots trabalhadores Codificador0, Codificador1 e Codificador2, role worker, modelo sentra/codex/current, '
            'via CANVAS coordinator_intent kind create_dot. Delegue uma vez a cada um via CANVAS dispatch. '
            +' '.join(tasks)+' Após as três delegações, responda DELEGACAO_REGISTRADA. Não execute o trabalho deles.'))
        def wait_turn(message):
            deadline=time.monotonic()+args.timeout
            while time.monotonic()<deadline:
                op=app._shell_service().durable.operation_status(message['operation_id'],app._runtime().owner)
                if op['state']=='SUCCEEDED':return op
                if op['state'] in {'FAILED','UNCERTAIN','CANCELLED'}:raise RuntimeError('turn '+op['state']+'; not replayed')
                time.sleep(.5)
            raise TimeoutError('model turn timeout; not replayed')
        wait_turn(first)
        children=[c for c in call('conversation_list',limit=100)['items'] if c.get('parent_conversation_id')==cid]
        assert len(children)==3,children
        dots={d['dot_id']:d for d in call('dot_list',limit=100)['items']};selected=[]
        for convo in children:
            messages=[m for m in call('message_list',conversation_id=convo['conversation_id'])['items'] if m['role']=='user']
            assert len(messages)==1;wait_turn(messages[0]);dot=dots[convo['dot_id']];i=int(dot['name'][-1])
            graph=call('dot_canvas_get',dot_id=root['dot_id'])
            task=next(t for t in graph['tasks'] if t.get('work_item_id')==messages[0]['work_item_id'])
            assert task['lifecycle']['stage']=='verified',task.get('lifecycle')
            item=binding(app._shell_service(),owner,pid,convo['conversation_id'],dot['agent_id']);assert item
            assert Path(item['path'],f'worker{i}.txt').read_text()==f'trabalhador-{i}\n'
            assert git(item['path'],'status','--porcelain').splitlines()==[f'M worker{i}.txt'] or git(item['path'],'status','--porcelain').splitlines()==[f' M worker{i}.txt']
            selected.append(item)
        assert len({s['path'] for s in selected})==3
        value=call('dot_worktree_review',dot_id=root['dot_id'],conversation_ids=[c['conversation_id'] for c in children])
        assert value['state']=='compatible' and not value['publication_performed'],value
        assert git(project,'status','--porcelain')=='' and git(project,'rev-parse','HEAD')==head
        close();boot()
        for previous in selected:
            restored=binding(app._shell_service(),owner,pid,previous['conversation_id'],previous['principal_id'])
            assert restored['path']==previous['path'] and restored['execution_workspace_id']==previous['execution_workspace_id']
        # Introduce a deliberate overlap in this disposable test workspace only.
        Path(selected[0]['path'],'worker2.txt').write_text('conflict A\n',encoding='utf-8')
        Path(selected[1]['path'],'worker2.txt').write_text('conflict B\n',encoding='utf-8')
        conflict=call('dot_worktree_review',dot_id=root['dot_id'],conversation_ids=[s['conversation_id'] for s in selected])
        assert conflict['state']=='conflict' and not conflict['publication_performed'],conflict
        assert git(project,'status','--porcelain')=='' and git(project,'rev-parse','HEAD')==head
        report.update(status='passed',agent_created_workers=3,owner_full_selections=1,worktrees=selected,
            compatible_review=value,conflict_review=conflict,broker_reopened=True,main_repository_unchanged=True,
            children_submitted_once=True,interrupted_inflight_effect_replayed=False,
            all_child_results_verified=True,
            scope='model creates three isolated edits; deliberate overlap and broker reopen are host QA steps')
    except Exception as error:report.update(status='failed',error_type=type(error).__name__,error=str(error)[:1500])
    finally:
        close();report['own_processes_closed']=True
        shell_runtime.TaskProcess=original_process;ShellActorService.dispatch=original_dispatch
        (output/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k not in {'worktrees','compatible_review','conflict_review'}},ensure_ascii=False),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
