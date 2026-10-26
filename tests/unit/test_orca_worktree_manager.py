import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
import pytest
from sentra_runtime.contracts import OperationRequest
from sentra_runtime.effect_boundary import CentralEffectContext,current_effect_context
from workspace.worktrees import WorktreeManager

def git(root,*args):return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()

def test_real_worktrees_are_isolated_and_require_central_context(tmp_path):
    repo=tmp_path/'repository';repo.mkdir();git(repo,'init');git(repo,'config','user.name','SENTRA Test');git(repo,'config','user.email','test@localhost');(repo/'sample.txt').write_text('base');git(repo,'add','sample.txt');git(repo,'commit','-m','base');base=git(repo,'rev-parse','HEAD')
    manager=WorktreeManager(repo,tmp_path/'state')
    requests=[OperationRequest('op-'+str(i),'agent-'+str(i),'host','git:worktree','work-'+str(i),'key-'+str(i),{'dot_id':'dot-'+str(i),'base_commit':base}) for i in range(3)]
    with pytest.raises(PermissionError):manager.create(requests[0])
    records=[]
    # The fixture isolates Git behavior. Production requires a real CP-created
    # CentralEffectContext; no trusted-context factory is exported by the module.
    for request in requests:
        context=object.__new__(CentralEffectContext);context.request=request;context.checkpoint=lambda:None
        token=current_effect_context.set(context)
        try:
            value=manager.create(request);assert manager.create(request)['reused'];records.append(value)
        finally:current_effect_context.reset(token)
    assert len({r['path'] for r in records})==3
    def write(record):Path(record['path'],'sample.txt').write_text(record['dot_id'])
    with ThreadPoolExecutor(max_workers=3) as workers:list(workers.map(write,records))
    assert (repo/'sample.txt').read_text()=='base'
    assert all(Path(r['path'],'sample.txt').read_text()==r['dot_id'] for r in records)
    assert all(manager.inspect(r['worktree_id'])['diff_stat'] for r in records)
    for record in records:git(repo,'worktree','remove','--force',record['path'])


def test_authority_inspection_skips_diff_but_still_rejects_branch_drift(tmp_path, monkeypatch):
    repo=tmp_path/'repository';repo.mkdir();git(repo,'init');git(repo,'config','user.name','SENTRA Test');git(repo,'config','user.email','test@localhost')
    (repo/'sample.txt').write_text('base');git(repo,'add','sample.txt');git(repo,'commit','-m','base');base=git(repo,'rev-parse','HEAD')
    manager=WorktreeManager(repo,tmp_path/'state')
    request=OperationRequest('op-one','agent-one','host','git:worktree','work-one','key-one',{'dot_id':'dot-one','base_commit':base})
    context=object.__new__(CentralEffectContext);context.request=request;context.checkpoint=lambda:None
    token=current_effect_context.set(context)
    try:record=manager.create(request)
    finally:current_effect_context.reset(token)
    (Path(record['path'])/'sample.txt').write_text('changed')
    calls=[];original=manager.git
    def tracked(*args,**kwargs):
        calls.append(args[0]);return original(*args,**kwargs)
    monkeypatch.setattr(manager,'git',tracked)
    authority=manager.inspect(record['worktree_id'],include_diff=False)
    assert authority['path']==record['path'] and 'diff_stat' not in authority
    assert calls==['worktree']
    assert manager.inspect(record['worktree_id'])['diff_stat']
    git(Path(record['path']),'checkout','--detach')
    with pytest.raises(RuntimeError,match='worktree identity drift'):
        manager.inspect(record['worktree_id'],include_diff=False)


def test_authorized_directory_requests_identity_without_presentation_diff(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from sentra_canvas import task_workspace
    seen=[]
    def lookup(control,owner,work,agent,*,include_diff=True):
        seen.append((owner,work,agent,include_diff))
        return {'path':str(tmp_path),'execution_workspace_id':'workspace-1'}
    monkeypatch.setattr(task_workspace,'for_work_item',lookup)
    request=SimpleNamespace(work_item_id='work',principal_id='agent')
    assert task_workspace.directory(None,'owner',request,tmp_path,expected_workspace_id='workspace-1')==tmp_path
    assert seen==[('owner','work','agent',False)]
    with pytest.raises(PermissionError,match='workspace changed'):
        task_workspace.directory(None,'owner',request,tmp_path,expected_workspace_id='other')
