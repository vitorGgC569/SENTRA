"""Real HTTP, protected drafts and admitted atomic saves; no model generation."""
import hashlib
import json
import uuid
from contextlib import closing
from pathlib import Path
from http.client import RemoteDisconnected
import pytest
from test_shell_dot_features import shell
from test_shell_actor_children import _dot,_prepare_parent_turn,_actor_for
from test_orca_worktree_manager import git
from sentra_canvas.workspace_file_editor import dispatch_editor,validate_draft
from sentra_canvas.full_access import prepare_resources
from test_sentra_runtime_canvas_center_http import request


@pytest.fixture
def editor(shell,monkeypatch):
    app,server,scope,call=shell
    monkeypatch.setattr(app._shell_runtime,'_execute',lambda _:None)
    dot=_dot(call,'Editor');convo=call('conversation_create',dot_id=dot['dot_id'])
    root=Path(app.store.workspace(scope['project_id'])['path'])
    (root/'sample.txt').write_bytes('original ação\r\n'.encode())
    selected={**scope,'dot_id':dot['dot_id'],'conversation_id':convo['conversation_id'],'execution_workspace_id':'project','path':'sample.txt'}
    def get():return dispatch_editor(app,scope['project_id'],'workspace_file_get',{k:v for k,v in selected.items() if k!='project_id'})
    def save(draft,revision):return dispatch_editor(app,scope['project_id'],'workspace_file_draft_save',
        {k:v for k,v in selected.items() if k!='project_id'}|{'draft':draft,'expected_revision':revision})
    def authorize():
        access=call('access_set',conversation_id=convo['conversation_id'],mode='full')
        message=_prepare_parent_turn(app,call,{**dot,**scope},convo['conversation_id'])
        prepare_resources(app._shell_runtime,message,dot)
        return access,message
    def publish(file,content,key=None,expected_status=200):
        code,value=request(server,'/api/shell/bridge',json_body={'action':'dot_computer_action',**scope,
            'dot_id':dot['dot_id'],'conversation_id':convo['conversation_id'],
            'request_key':key or uuid.uuid4().hex,'request':{'action':'machine_execute',**file['editor'],'capability_id':'workspace:file.write',
                'arguments':{'action':'edit','path':'sample.txt','content':content,'expected_sha256':file['sha256'],'execution_workspace_id':file['execution_workspace_id']}}})
        assert code==expected_status,value
        return value['value'] if code==200 else value
    return app,call,root,selected,get,save,authorize,publish


def body(file,content='my private draft 漢字'):
    return {'base_content':file['content'],'base_sha256':file['sha256'],'content':content,'anchor':0,'head':len(content)}


def test_drafts_are_protected_versioned_and_restore_without_execution(editor):
    app,_,root,scope,get,save,_,_=editor
    file=get();assert file['editor'] is None and file['restoration_creates_resources'] is False
    draft=body(file);result=save(draft,0);assert result['saved'] and result['revision']==1
    assert save(draft,0)['revision']==1  # Lost draft ACK can be reconciled by equal content.
    stale=save(body(file,'another window'),0)
    assert stale['conflict'] and stale['draft']==draft and get()['draft']==draft
    control=app._shell_service()
    with closing(control.store.connect('shell')) as db:
        row=db.execute('SELECT body FROM canvas_file_drafts WHERE scope=?',(file['scope'],)).fetchone()
    assert row['body'].startswith(('dpapi:','keyring:')) and 'my private draft' not in row['body']
    assert root.joinpath('sample.txt').read_bytes()==file['content'].encode()
    assert save(None,1)['revision']==2
    assert not save(body(file),1)['saved']  # Clearing keeps revision, preventing ABA.


def test_external_change_and_deletion_preserve_draft(editor):
    _,_,root,_,get,save,_,_=editor
    file=get();draft=body(file);save(draft,0)
    root.joinpath('sample.txt').write_text('another agent',encoding='utf-8')
    changed=get();assert changed['draft_stale'] and changed['draft']==draft
    root.joinpath('sample.txt').unlink()
    missing=get();assert missing['draft']==draft and missing['file_error'] and missing['editor'] is None
    assert save({**draft,'content':'still recoverable','head':0},1)['saved']
    assert not root.joinpath('sample.txt').exists()


def test_save_uses_existing_central_grants_capture_cas_and_no_duplicate_effect(editor):
    app,_,root,_,get,save,authorize,publish=editor
    authorize();file=get();assert file['editor'],file
    save(body(file,'saved by editor'),0)
    key=uuid.uuid4().hex;result=publish(file,'saved by editor',key)
    assert result['state']=='SUCCEEDED' and result['evidence']['durable_capture'],result
    assert result['evidence']['sha256']==hashlib.sha256(b'saved by editor').hexdigest()
    stamp=root.joinpath('sample.txt').stat().st_mtime_ns
    assert publish(file,'saved by editor',key)['state']=='SUCCEEDED'
    assert root.joinpath('sample.txt').stat().st_mtime_ns==stamp
    assert get()['draft']['content']=='saved by editor'  # Physical receipt never silently discards draft.
    stale=publish(file,'must not replace saved bytes')
    assert stale['state']=='FAILED' and stale['error']=='workspace_file_revision_conflict'
    assert root.joinpath('sample.txt').read_text()=='saved by editor'
    # A rejected pre-publication CAS does not strand the machine lease.
    assert publish(get(),'a reviewed follow-up')['state']=='SUCCEEDED'


def test_revoked_grant_does_not_allow_save_or_erase_draft(editor):
    app,_,root,_,get,save,authorize,publish=editor
    authorize();file=get();save(body(file),0)
    control=app._shell_service();owner=app._runtime().owner
    for grant in control.authorization.list_grants(owner)['items']:
        if grant['scope_id']==file['editor']['work_item_id'] and grant['capability']=='workspace:file.write':
            control.authorization_revoke(grant['grant_id'],owner)
    result=publish(file,'denied',expected_status=403)
    assert 'access denied' in result['error'] and root.joinpath('sample.txt').read_bytes()==file['content'].encode()
    assert get()['draft']['content']==body(file)['content'] and get()['editor'] is None


def test_workspace_selector_cannot_redirect_edit_to_another_tree(editor):
    _,_,root,_,get,_,authorize,publish=editor
    authorize();file=get()
    result=publish({**file,'execution_workspace_id':'xws-git-not-this-work'},'denied')
    assert result['state']!='SUCCEEDED' and root.joinpath('sample.txt').read_bytes()==file['content'].encode()


def test_lost_http_confirmation_recovers_receipt_without_repeating_file_write(editor,monkeypatch):
    app,call,root,scope,get,save,authorize,publish=editor
    authorize();file=get();content='one physical publication';save(body(file,content),0)
    original=app.shell_bridge;key=uuid.uuid4().hex;calls=[]
    def lost_reply(payload,**kwargs):
        value=original(payload,**kwargs)
        if payload.get('action')=='dot_computer_action' and payload.get('request_key')==key:
            calls.append(key);raise ConnectionResetError('injected after committed file publication')
        return value
    monkeypatch.setattr(app,'shell_bridge',lost_reply)
    with pytest.raises(RemoteDisconnected):publish(file,content,key)
    stamp=root.joinpath('sample.txt').stat().st_mtime_ns
    args={'action':'edit','path':'sample.txt','content':content,'expected_sha256':file['sha256'],'execution_workspace_id':'project'}
    nested={'space_id':scope['space_id'],**file['editor'],'capability_id':'workspace:file.write','arguments':args}
    fingerprint=hashlib.sha256(json.dumps(['machine_execute',nested],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    result=call('workspace_request_status',dot_id=scope['dot_id'],selector={'action':'dot_computer_action',
        'request_key':key,'fingerprint':fingerprint,'conversation_id':scope['conversation_id']})
    assert result['resolved'] and result['operation']['state']=='SUCCEEDED' and not result['automatic_retry']
    assert calls==[key] and root.joinpath('sample.txt').read_text()==content
    assert root.joinpath('sample.txt').stat().st_mtime_ns==stamp and get()['draft']['content']==content


def test_draft_cannot_cross_dot_conversation_or_workspace(editor):
    app,call,_,scope,get,_,_,_=editor
    other=_dot(call,'Other');foreign=call('conversation_create',dot_id=other['dot_id'])
    params={k:v for k,v in scope.items() if k!='project_id'}
    for change in ({'conversation_id':foreign['conversation_id']},{'dot_id':other['dot_id']},{'execution_workspace_id':'wrong'}):
        with pytest.raises(PermissionError):dispatch_editor(app,scope['project_id'],'workspace_file_get',params|change)
    with pytest.raises(ValueError):dispatch_editor(app,scope['project_id'],'workspace_file_get',params|{'path':'../escape.txt'})


def test_editor_is_pinned_to_the_real_assigned_worktree(editor,monkeypatch):
    app,_,root,scope,get,save,authorize,publish=editor
    git(root,'init');git(root,'config','user.name','Test');git(root,'config','user.email','test@localhost')
    git(root,'add','sample.txt');git(root,'commit','-m','base')
    original=get();save(body(original,'old project draft'),0)
    _,message=authorize();control=app._shell_service();owner=app._runtime().owner
    with closing(control.store.connect('shell')) as db:
        dot=control.shell._entity(db,owner,scope['project_id'],'dot',scope['dot_id'],space_id=scope['space_id'])
    actor,_,_=_actor_for(app,message,dot,monkeypatch)
    result=actor.dispatch('test',{'action':'isolate_work','workspace':str(root),'value':'','request_key':uuid.uuid4().hex})
    assert result['status']=='ready',result
    from sentra_canvas.task_workspace import binding
    selected=binding(control,owner,scope['project_id'],scope['conversation_id'],dot['agent_id'])
    with pytest.raises(PermissionError):get()  # Stale file tabs cannot fall back to project root.
    new=dispatch_editor(app,scope['project_id'],'workspace_file_get',
        {k:v for k,v in scope.items() if k!='project_id'}|{'execution_workspace_id':selected['execution_workspace_id']})
    assert new['draft'] is None and new['editor'] and new['execution_workspace_id']==selected['execution_workspace_id']
    assert publish({**new,'execution_workspace_id':'project'},'wrong target')['state']!='SUCCEEDED'
    result=publish(new,'worktree edit')
    assert result['state']=='SUCCEEDED',result
    assert Path(selected['path'],'sample.txt').read_text()=='worktree edit'
    assert root.joinpath('sample.txt').read_bytes()==original['content'].encode()


@pytest.mark.parametrize('change',[{'base_sha256':'0'*64},{'anchor':True},{'head':10000},{'content':'x'*131073},{'content':'\ud800'},{'grant':'untrusted'}])
def test_malformed_drafts_cannot_enter_protected_store(change):
    draft={'base_sha256':hashlib.sha256(b'base').hexdigest(),'base_content':'base','content':'text','anchor':0,'head':4}
    assert not validate_draft(draft|change)
