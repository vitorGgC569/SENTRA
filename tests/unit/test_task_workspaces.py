import json,time,uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from test_shell_dot_features import shell
from test_shell_actor_children import _dot,_prepare_parent_turn,_actor_for
from test_orca_worktree_manager import git
from sentra_canvas.task_workspace import binding,for_work_item


def coding_jobs(shell,monkeypatch):
    app,server,scope,call=shell
    monkeypatch.setattr(app._shell_runtime,'_execute',lambda _:None)
    root=Path(app.store.workspace(scope['project_id'])['path'])
    git(root,'init');git(root,'config','user.name','SENTRA Test');git(root,'config','user.email','test@localhost')
    (root/'sample.txt').write_text('base',encoding='utf-8');git(root,'add','sample.txt');git(root,'commit','-m','base')
    jobs=[]
    for i in range(3):
        dot=_dot(call,'Coder'+str(i),**({'canvas_root_dot_id':jobs[0]['dot']['dot_id']} if jobs else {}))
        convo=call('conversation_create',dot_id=dot['dot_id'])
        access=call('access_set',conversation_id=convo['conversation_id'],mode='full')
        files=app._machine_service().configure_workspace_files(workspace_id=scope['project_id'],workspace_root=root,agent_id=dot['agent_id'])
        message=_prepare_parent_turn(app,call,{**dot,**scope},convo['conversation_id'])
        actor,owner,_=_actor_for(app,message,dot,monkeypatch)
        jobs.append({'dot':dot,'conversation':convo,'access':access,'message':message,'actor':actor,'name':'Coder'+str(i),'files':files})
    return app,scope,call,root,jobs


def test_three_jobs_use_their_own_git_files_commands_and_owner_preview(shell,monkeypatch):
    app,scope,call,root,jobs=coding_jobs(shell,monkeypatch)
    original_status=git(root,'status','--porcelain')
    def execute(job):
        result=job['actor'].dispatch('unit',{'action':'isolate_work','workspace':str(root),'value':'','request_key':uuid.uuid4().hex})
        assert result['status']=='ready',result
        selected=binding(app._shell_service(),app._runtime().owner,scope['project_id'],job['conversation']['conversation_id'],job['dot']['agent_id'])
        assert selected and Path(selected['path'])!=root
        access=job['access']
        def physical(cap,args):
            oid='op-worktree-'+uuid.uuid4().hex
            result=app.center_execute(scope['project_id'],access['work_item_id'],access['machine_id'],cap,oid,args,oid)
            assert result['state']=='SUCCEEDED',result
            return result['evidence']
        evidence=physical('computer:file.write',{'action':'edit','path':'sample.txt','content':job['name']})
        assert Path(evidence['path']).parent==Path(selected['path'])
        host=app._machine_service()
        file_job=next(w for w in host.task_catalog(workspace_id=scope['project_id'],agent_ids={job['dot']['agent_id']},
            conversation_id=job['conversation']['conversation_id']) if w['machine_id']==job['files']['machine_id'])
        def file_effect(cap,args):
            oid='file-tree-'+uuid.uuid4().hex
            value=host.dispatch(workspace_id=scope['project_id'],work_item_id=file_job['work_item_id'],
                machine_id=job['files']['machine_id'],capability_id=cap,operation_id=oid,idempotency_key=oid,arguments=args)
            assert value['state']=='SUCCEEDED',value
            return value['evidence']
        read=file_effect('workspace:file.read',{'action':'read','path':'sample.txt'})
        assert read['content']==job['name']
        saved=file_effect('workspace:file.write',{'action':'edit','path':'sample.txt','content':job['name'],'expected_sha256':read['sha256']})
        assert saved['durable_capture'] and app._shell_service().durable.read_artifact(saved['artifact_id'],max_bytes=1000).decode()==job['name']
        process=physical('computer:execute',{'command':'[Environment]::CurrentDirectory'})
        assert process['exit_code']==0 and process['stdout'].strip()==selected['path']
        Path(selected['path'],'nested').mkdir()
        process=physical('computer:execute',{'command':'[Environment]::CurrentDirectory','cwd':'nested'})
        assert process['exit_code']==0 and Path(process['stdout'].strip())==Path(selected['path'],'nested')
        preview=call('project_file_preview',dot_id=job['dot']['dot_id'],conversation_id=job['conversation']['conversation_id'],path='sample.txt')
        assert preview['content']==job['name'] and preview['execution_workspace_id']==selected['execution_workspace_id']
        with pytest.raises(PermissionError):
            from sentra_canvas.task_workspace import file_service
            file_service(app,scope['project_id'],{'space_id':scope['space_id'],'dot_id':job['dot']['dot_id'],
                'conversation_id':job['conversation']['conversation_id'],'execution_workspace_id':'project','path':'sample.txt'})
        return selected
    with ThreadPoolExecutor(max_workers=3) as workers:selected=list(workers.map(execute,jobs))
    assert len({v['path'] for v in selected})==3 and (root/'sample.txt').read_text()=='base'
    assert git(root,'status','--porcelain')==original_status
    for j,s in zip(jobs,selected):
        assert for_work_item(app._shell_service(),app._runtime().owner,j['message']['work_item_id'],j['dot']['agent_id'])['path']==s['path']
    with pytest.raises(PermissionError):binding(app._shell_service(),app._runtime().owner,scope['project_id'],jobs[0]['conversation']['conversation_id'],jobs[1]['dot']['agent_id'])


def test_conflict_review_is_read_only_scoped_and_survives_reopening_authority(shell,monkeypatch):
    app,scope,call,root,jobs=coding_jobs(shell,monkeypatch);entries=[]
    for job in jobs:
        job['actor'].dispatch('unit',{'action':'isolate_work','workspace':str(root),'value':'','request_key':uuid.uuid4().hex})
        selected=binding(app._shell_service(),app._runtime().owner,scope['project_id'],job['conversation']['conversation_id'])
        Path(selected['path'],'sample.txt').write_text(job['name'],encoding='utf-8');entries.append(selected)
    before=git(root,'status','--porcelain');head=git(root,'rev-parse','HEAD')
    value=call('dot_worktree_review',dot_id=jobs[0]['dot']['dot_id'],conversation_ids=[j['conversation']['conversation_id'] for j in jobs])
    assert value['state']=='conflict' and value['worktrees'][1]['state']=='conflict',value
    assert value['unchecked_worktrees']==1 and value['publication_performed'] is False
    assert len(value['resources'])==3
    # A newly opened central authority reads the same durable assignment and diff.
    from sentra_mcp.services.control_plane import ControlPlaneService
    control=app._shell_service()
    reopened=ControlPlaneService.from_store(control.durable.state_root)
    try:restored=binding(reopened,app._runtime().owner,scope['project_id'],jobs[0]['conversation']['conversation_id'])
    finally:reopened.context.close();reopened.durable.close()
    assert restored['execution_workspace_id']==entries[0]['execution_workspace_id']
    assert Path(restored['path'],'sample.txt').read_text()=='Coder0'
    assert git(root,'status','--porcelain')==before and git(root,'rev-parse','HEAD')==head
    assert (root/'sample.txt').read_text()=='base'
    with pytest.raises(PermissionError):
        from sentra_canvas.task_workspace import review
        review(app,scope['project_id'],{'dot_id':jobs[0]['dot']['dot_id'],'space_id':scope['space_id'],
            'conversation_ids':[jobs[1]['conversation']['conversation_id']]},allowed_dot_ids={jobs[0]['dot']['dot_id']})


def test_binding_drift_never_falls_back_to_main_repository(shell,monkeypatch):
    app,scope,call,root,jobs=coding_jobs(shell,monkeypatch);job=jobs[0]
    job['actor'].dispatch('unit',{'action':'isolate_work','workspace':str(root),'value':'','request_key':uuid.uuid4().hex})
    selected=binding(app._shell_service(),app._runtime().owner,scope['project_id'],job['conversation']['conversation_id'])
    git(root,'worktree','remove','--force',selected['path'])
    oid='drift-'+uuid.uuid4().hex
    with pytest.raises((PermissionError,FileNotFoundError,RuntimeError)):
        app.center_execute(scope['project_id'],job['access']['work_item_id'],job['access']['machine_id'],
            'computer:file.write',oid,{'action':'edit','path':'sample.txt','content':'wrong fallback'},oid)
    assert (root/'sample.txt').read_text()=='base'


@pytest.mark.skipif(__import__('os').name!='nt',reason='real ConPTY')
def test_new_terminal_uses_bound_directory_without_moving_existing_session(shell,monkeypatch):
    app,scope,call,root,jobs=coding_jobs(shell,monkeypatch);job=jobs[0];actor=job['actor']
    existing=app.create_terminal(scope['project_id'],'ExistingRoot','powershell')
    actor.dispatch('unit',{'action':'isolate_work','workspace':str(root),'value':'','request_key':uuid.uuid4().hex})
    app._agent_tokens['unit']=(scope['project_id'],'shell:'+job['message']['operation_id'])
    monkeypatch.setattr(app._shell_runtime.actors,'subject',actor.subject)
    try:
        context=actor.dispatch('unit',{'action':'context','workspace':str(root)})
        json.dumps(context)
        git_machine=next(m for m in context['machine_catalog']['machines'] if m['kind']=='git-worktrees')
        assert git_machine['actions']=={} and 'git:worktree' in git_machine['capabilities']
        assert context['execution_workspace']['conversation_id']==job['conversation']['conversation_id']
    finally:app._agent_tokens.pop('unit',None)
    host=app._machine_service();catalog=host.task_catalog(workspace_id=scope['project_id'],agent_ids={job['dot']['agent_id']},conversation_id=job['conversation']['conversation_id'])
    work=next(w for w in catalog if 'terminal:start' in w['capabilities'])
    def dispatch(cap,args):
        oid='op-terminal-tree-'+uuid.uuid4().hex
        return host.dispatch(workspace_id=scope['project_id'],work_item_id=work['work_item_id'],machine_id=work['machine_id'],
            capability_id=cap,operation_id=oid,idempotency_key=oid,arguments=args)
    value=dispatch('terminal:start',{'name':'InWorktree','shell':'powershell'})
    assert value['state']=='SUCCEEDED',value
    terminal=value['evidence'].get('terminal_id') or value['evidence'].get('payload',{}).get('terminal_id')
    try:
        app.terminal_input(scope['project_id'],terminal,"[IO.File]::WriteAllText((Join-Path (Get-Location) 'terminal-location.txt'), (Get-Location).Path)\r")
        selected=binding(app._shell_service(),app._runtime().owner,scope['project_id'],job['conversation']['conversation_id'])
        evidence=Path(selected['path'])/'terminal-location.txt';deadline=time.monotonic()+10
        while not evidence.exists() and time.monotonic()<deadline:time.sleep(.1)
        assert evidence.read_text()==selected['path']
        assert not (root/'terminal-location.txt').exists() and app.store.resource('terminals',existing['id'],scope['project_id'])['status']=='running'
    finally:
        app.terminal_close(scope['project_id'],terminal);app.terminal_close(scope['project_id'],existing['id'])
