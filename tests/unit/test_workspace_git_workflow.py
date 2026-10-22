"""Actual SQLite admission and disposable Git repositories; no production refs."""
from pathlib import Path
import uuid
import pytest
from test_shell_dot_features import shell,dot
from test_orca_worktree_manager import git
from workspace.git_workflow import plan,execute,validate_args


@pytest.fixture
def git_job(shell):
    app,_server,scope,call=shell
    actor=dot(call,'Reviewed Git');conversation=call('conversation_create',dot_id=actor['dot_id'])
    root=Path(app.store.workspace(scope['project_id'])['path'])
    git(root,'init');git(root,'config','user.name','Test');git(root,'config','user.email','test@localhost')
    (root/'base.txt').write_text('original\n');git(root,'add','base.txt');git(root,'commit','-m','base')
    machine=app.center_configure_machine(scope['project_id'],actor['agent_id'],'git-worktrees',provider_config={'dot_id':actor['dot_id']})
    runtime=app._runtime();control=runtime.control;host=app._machine_service()
    work=control.create_work_item(runtime.run(scope['project_id'])['run_id'],runtime.owner,
        objective='Review explicit Git steps',assignee_agent_id=actor['agent_id'],required_capabilities=machine['capabilities'],
        metadata={**scope,'workspace_id':scope['project_id'],'machine_id':machine['machine_id'],'conversation_id':conversation['conversation_id']})
    control.start_work_item_execution(work['work_item_id'],runtime.owner,run_id=work['run_id'],agent_id=actor['agent_id'])
    def dispatch(capability,args):
        oid='reviewed-git-'+uuid.uuid4().hex
        return host.dispatch(workspace_id=scope['project_id'],work_item_id=work['work_item_id'],machine_id=machine['machine_id'],
            capability_id=capability,operation_id=oid,idempotency_key=oid,arguments=args)
    for cap in machine['capabilities']:
        control.authorization.grant(runtime.owner,principal_type='agent',principal_id=actor['agent_id'],capability=cap,scope_type='work_item',scope_id=work['work_item_id'])
    result=dispatch('git:worktree',{'dot_id':actor['dot_id'],'base_commit':git(root,'rev-parse','HEAD')})
    assert result['state']=='SUCCEEDED',result
    item=result['evidence']
    from workspace.worktrees import WorktreeManager
    manager=WorktreeManager(root,control.durable.root/'git-worktrees'/machine['machine_id'])
    yield app,root,manager,item,dispatch
    target=Path(item['path'])
    if target.exists():git(root,'worktree','remove','--force',str(target))


def step(manager,item,dispatch,capability,**fields):
    review=plan(manager,item['worktree_id'])
    result=dispatch(capability,{'worktree_id':item['worktree_id'],'expected_snapshot_sha256':review['snapshot_sha256'],**fields})
    assert result['state']=='SUCCEEDED',result
    return result['evidence']


def test_new_binary_commit_merge_publish_and_clean_checkout(git_job,tmp_path):
    app,root,manager,item,dispatch=git_job;target=Path(item['path']);base=git(root,'rev-parse','HEAD')
    (target/'base.txt').write_text('reviewed\n');(target/'new.txt').write_text('new reviewed file\n');(target/'image.bin').write_bytes(b'\0binary\xff')
    review=plan(manager,item['worktree_id'])
    assert {r['path'] for r in review['files']}=={'base.txt','new.txt','image.bin'}
    assert next(r for r in review['files'] if r['path']=='image.bin')['binary'] is True
    assert next(r for r in review['files'] if r['path']=='new.txt')['preview']==(target/'new.txt').read_bytes().decode()
    committed=step(manager,item,dispatch,'git:commit',files=['base.txt','new.txt','image.bin'],message='Reviewed files')
    assert git(root,'rev-parse','HEAD')==base and git(target,'status','--porcelain')==''
    assert git(target,'show','HEAD:new.txt')=='new reviewed file'
    assert committed['commit']==git(target,'rev-parse','HEAD')
    remote=tmp_path/'remote.git';remote.mkdir();git(remote,'init','--bare');git(target,'remote','add','approved-local',str(remote))
    published=step(manager,item,dispatch,'git:publish',remote='approved-local')
    assert published['verified'] and git(remote,'rev-parse','refs/heads/'+item['branch'])==committed['commit']
    merged=step(manager,item,dispatch,'git:merge')
    assert merged['head']==committed['commit'] and (root/'image.bin').read_bytes()==b'\0binary\xff'
    cleaned=step(manager,item,dispatch,'git:cleanup')
    assert cleaned['verified'] and not target.exists() and git(root,'rev-parse','refs/heads/'+item['branch'])==committed['commit']
    assert app._shell_service().execution_workspace_info(item['execution_workspace_id'],app._runtime().owner)['state']=='DISCARDED'


def test_discard_preserves_unselected_file_and_protected_draft(git_job):
    app,root,manager,item,dispatch=git_job;target=Path(item['path'])
    (target/'base.txt').write_text('changed');(target/'new.txt').write_text('keep')
    from sentra_canvas.workspace_file_editor import dispatch_editor
    control=app._shell_service();owner=app._runtime().owner;metadata=control.work_item_info(item['work_item_id'],owner)['metadata']
    scope={'space_id':metadata['space_id'],'dot_id':item['dot_id'],'conversation_id':item['conversation_id'],
        'execution_workspace_id':item['execution_workspace_id'],'path':'base.txt'}
    before=dispatch_editor(app,metadata['workspace_id'],'workspace_file_get',scope)
    draft={'base_sha256':before['sha256'],'base_content':before['content'],'content':'my protected typing','anchor':0,'head':0}
    assert dispatch_editor(app,metadata['workspace_id'],'workspace_file_draft_save',{**scope,'expected_revision':0,'draft':draft})['saved']
    step(manager,item,dispatch,'git:discard',files=['base.txt'])
    assert (target/'base.txt').read_text()=='original\n' and (target/'new.txt').read_text()=='keep'
    assert (root/'base.txt').read_text()=='original\n'
    after=dispatch_editor(app,metadata['workspace_id'],'workspace_file_get',scope)
    assert after['draft']==draft and after['draft_stale'] is True


def test_stale_review_cannot_commit_newer_bytes(git_job):
    _app,root,manager,item,dispatch=git_job;target=Path(item['path'])
    (target/'base.txt').write_text('reviewed');review=plan(manager,item['worktree_id']);head=git(target,'rev-parse','HEAD')
    (target/'base.txt').write_text('unreviewed')
    result=dispatch('git:commit',{'worktree_id':item['worktree_id'],'expected_snapshot_sha256':review['snapshot_sha256'],'files':['base.txt'],'message':'Must refuse'})
    assert result['state']=='FAILED' and git(target,'rev-parse','HEAD')==head and (target/'base.txt').read_text()=='unreviewed'


def test_captured_commit_excludes_concurrent_edit_and_revocation_denies_next_step(git_job,monkeypatch):
    import workspace.git_workflow as workflow
    app,_root,manager,item,dispatch=git_job;target=Path(item['path']);(target/'base.txt').write_text('reviewed')
    review=plan(manager,item['worktree_id']);original=workflow._file;count=0
    def edit_after_capture(root,relative):
        nonlocal count
        captured=original(root,relative);count+=1
        if count==2:(target/'base.txt').write_text('new unreviewed edit')
        return captured
    monkeypatch.setattr(workflow,'_file',edit_after_capture)
    result=dispatch('git:commit',{'worktree_id':item['worktree_id'],'expected_snapshot_sha256':review['snapshot_sha256'],'files':['base.txt'],'message':'Captured reviewed bytes'})
    assert result['state']=='SUCCEEDED',result
    assert git(target,'show','HEAD:base.txt')=='reviewed' and (target/'base.txt').read_text()=='new unreviewed edit'
    control=app._shell_service();owner=app._runtime().owner
    grant=next(g for g in control.authorization.list_grants(owner,principal_id=item['principal_id'])['items'] if g['capability']=='git:commit')
    control.authorization.revoke(grant['grant_id'],owner)
    with pytest.raises(PermissionError):dispatch('git:commit',{'worktree_id':item['worktree_id'],'expected_snapshot_sha256':plan(manager,item['worktree_id'])['snapshot_sha256'],'files':['base.txt'],'message':'Revoked'})


def test_cleanup_refuses_ignored_files_before_fencing_or_deleting(git_job):
    app,root,manager,item,dispatch=git_job;target=Path(item['path'])
    exclude=Path(git(root,'rev-parse','--path-format=absolute','--git-path','info/exclude'));exclude.write_text('private.cache\n')
    (target/'private.cache').write_text('keep ignored data')
    review=plan(manager,item['worktree_id']);assert review['ignored_paths']==['private.cache']
    result=dispatch('git:cleanup',{'worktree_id':item['worktree_id'],'expected_snapshot_sha256':review['snapshot_sha256']})
    assert result['state']=='FAILED' and (target/'private.cache').read_text()=='keep ignored data'
    assert app._shell_service().execution_workspace_info(item['execution_workspace_id'],app._runtime().owner)['state']=='READY'


def test_cleanup_keeps_clean_worktree_while_private_editor_draft_exists(git_job):
    app,_root,manager,item,dispatch=git_job
    from sentra_canvas.workspace_file_editor import dispatch_editor
    control=app._shell_service();owner=app._runtime().owner;metadata=control.work_item_info(item['work_item_id'],owner)['metadata']
    scope={'space_id':metadata['space_id'],'dot_id':item['dot_id'],'conversation_id':item['conversation_id'],
        'execution_workspace_id':item['execution_workspace_id'],'path':'base.txt'}
    before=dispatch_editor(app,metadata['workspace_id'],'workspace_file_get',scope)
    draft={'base_sha256':before['sha256'],'base_content':before['content'],'content':'private unsaved work','anchor':0,'head':0}
    saved=dispatch_editor(app,metadata['workspace_id'],'workspace_file_draft_save',{**scope,'expected_revision':0,'draft':draft})
    assert saved['saved']
    review=plan(manager,item['worktree_id']);assert review['checkout_clean']
    result=dispatch('git:cleanup',{'worktree_id':item['worktree_id'],'expected_snapshot_sha256':review['snapshot_sha256']})
    assert result['state']=='FAILED' and Path(item['path']).exists()
    assert control.execution_workspace_info(item['execution_workspace_id'],owner)['state']=='READY'
    assert dispatch_editor(app,metadata['workspace_id'],'workspace_file_get',scope)['draft']==draft
    assert dispatch_editor(app,metadata['workspace_id'],'workspace_file_draft_save',{**scope,'expected_revision':saved['revision'],'draft':None})['saved']
    assert step(manager,item,dispatch,'git:cleanup')['verified']


def test_uncertain_push_is_not_reported_success_or_replayed(git_job,monkeypatch,tmp_path):
    import workspace.git_workflow as workflow
    _app,_root,manager,item,dispatch=git_job;target=Path(item['path']);remote=tmp_path/'remote.git';remote.mkdir();git(remote,'init','--bare');git(target,'remote','add','approved-local',str(remote))
    original=workflow._run;calls=[]
    def lost_ack(manager,path,*args,**kwargs):
        value=original(manager,path,*args,**kwargs)
        if args and args[0]=='push':calls.append(args);raise TimeoutError('Lost acknowledgement after remote changed')
        return value
    monkeypatch.setattr(workflow,'_run',lost_ack)
    review=plan(manager,item['worktree_id'])
    result=dispatch('git:publish',{'worktree_id':item['worktree_id'],'expected_snapshot_sha256':review['snapshot_sha256'],'remote':'approved-local'})
    assert result['state']=='UNCERTAIN' and len(calls)==1
    assert git(remote,'rev-parse','refs/heads/'+item['branch'])==review['head']


@pytest.mark.parametrize('fields',[{'worktree_id':'x','expected_snapshot_sha256':'a'*64,'files':['file.txt'],'message':'ok'},
    {'worktree_id':'a'*24,'expected_snapshot_sha256':'b'*64,'files':['../escape'],'message':'ok'},
    {'worktree_id':'a'*24,'expected_snapshot_sha256':'b'*64,'files':['.env'],'message':'ok'},
    {'worktree_id':'a'*24,'expected_snapshot_sha256':'b'*64,'files':['file.txt'],'message':'ok','grant_id':'forged'}])
def test_exact_git_steps_reject_authority_and_path_overrides(fields):
    with pytest.raises((ValueError,PermissionError)):validate_args('git:commit',fields)


@pytest.mark.parametrize('url,display',[
    ('https://user:secret@example.com/repo.git?token=hidden','https://example.com/repo.git'),
    ('git@example.com:owner/repo.git','example.com:owner/repo.git'),
    ('ext::arbitrary-command',None),('custom::remote-helper',None),('https://host:bad/repo',None)])
def test_remote_review_shows_destination_without_credentials_or_executable_helpers(url,display):
    from workspace.git_workflow import _remote_display
    assert _remote_display(url)==display
