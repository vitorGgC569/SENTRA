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
