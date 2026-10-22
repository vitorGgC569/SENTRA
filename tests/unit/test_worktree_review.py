"""Git patch rehearsal only; physical admission is covered in task_workspaces."""
import io
import hashlib
import os
import tarfile
from pathlib import Path
import pytest
from sentra_runtime.contracts import OperationRequest
from sentra_runtime.effect_boundary import CentralEffectContext,current_effect_context
from workspace.worktrees import WorktreeManager
from workspace.worktree_review import preview,_extract
from sentra_executors.rpa import AuthorizedPaths,atomic_output
from test_orca_worktree_manager import git


@pytest.fixture
def trees(tmp_path):
    repo=tmp_path/'repo';repo.mkdir();git(repo,'init');git(repo,'config','user.name','Test');git(repo,'config','user.email','test@localhost')
    for i in range(3):Path(repo,f'file{i}.txt').write_text('base\n',encoding='utf-8')
    git(repo,'add','.');git(repo,'commit','-m','base');base=git(repo,'rev-parse','HEAD');entries=[]
    for i in range(3):
        manager=WorktreeManager(repo,tmp_path/f'manager{i}')
        request=OperationRequest('op-'+str(i),'agent-'+str(i),'host','git:worktree','work-'+str(i),'key-'+str(i),{'dot_id':'dot-'+str(i),'base_commit':base})
        context=object.__new__(CentralEffectContext);context.request=request;context.checkpoint=lambda:None
        token=current_effect_context.set(context)
        try:item=manager.create(request)
        finally:current_effect_context.reset(token)
        entries.append((manager,item))
    yield repo,entries
    for _,item in entries:git(repo,'worktree','remove','--force',item['path'])


def test_three_compatible_changes_never_modify_live_repository(trees):
    repo,entries=trees
    for i,(_,item) in enumerate(entries):Path(item['path'],f'file{i}.txt').write_text('worker '+str(i)+'\n',encoding='utf-8')
    head=git(repo,'rev-parse','HEAD');refs=git(repo,'show-ref');status=git(repo,'status','--porcelain')
    result=preview(entries)
    assert result['state']=='compatible' and len(result['worktrees'])==3,result
    assert not result['publication_performed'] and not result['base_diverged']
    assert git(repo,'rev-parse','HEAD')==head and git(repo,'show-ref')==refs and git(repo,'status','--porcelain')==status
    assert all(Path(repo,f'file{i}.txt').read_text()=='base\n' for i in range(3))
    assert all(not list(manager.state.glob('review-*')) for manager,_ in entries)


def test_untracked_and_binary_changes_are_never_called_compatible(trees):
    _,entries=trees;path=Path(entries[0][1]['path'])
    (path/'new.txt').write_text('new')
    result=preview(entries);assert result['state']=='needs_review' and 'untracked' in result['reason']
    (path/'new.txt').unlink();(path/'file0.txt').write_bytes(b'\x00binary\x00')
    result=preview(entries);assert result['state']=='needs_review' and 'binary' in result['reason']


def test_atomic_edits_are_reviewable_without_deleting_persistent_locks(trees):
    repo,entries=trees
    retained=[]
    for i,(_,item) in enumerate(entries):
        root=Path(item['path']).resolve();target=root/f'file{i}.txt'
        atomic_output(AuthorizedPaths((str(root),),(str(root),)),str(target),
            lambda temporary:temporary.write_text('atomic worker\n',encoding='utf-8'),
            lambda temporary:None,overwrite=True)
        retained.extend(root.glob('.sentra-output-locks/*.lock'))
    head=git(repo,'rev-parse','HEAD');status=git(repo,'status','--porcelain')
    result=preview(entries)
    assert result['state']=='compatible',result
    assert [r['internal_metadata_count'] for r in result['worktrees']]==[1,1,1]
    assert all(r['internal_metadata'][0]['sha256']==hashlib.sha256(b'0').hexdigest()
        for r in result['worktrees'])
    assert len(retained)==3 and all(lock.read_bytes()==b'0' for lock in retained)
    assert git(repo,'rev-parse','HEAD')==head and git(repo,'status','--porcelain')==status
    assert not result['publication_performed']


@pytest.mark.parametrize('kind',['wrong-name','wrong-target','empty','oversized','changed','unknown-neighbor'])
def test_unknown_lock_files_are_not_hidden_from_review(trees,kind):
    _,entries=trees;root=Path(entries[0][1]['path']).resolve()
    key=hashlib.sha256(os.path.normcase(str(root/'file0.txt')).encode('utf-8')).hexdigest()
    directory=root/'.sentra-output-locks';directory.mkdir()
    lock=directory/(key+'.lock')
    lock.write_bytes({'empty':b'','oversized':b'00','changed':b'1'}.get(kind,b'0'))
    if kind=='wrong-name':lock.rename(directory/'notes.txt')
    if kind=='wrong-target':lock.rename(directory/('f'*64+'.lock'))
    if kind=='unknown-neighbor':(directory/'notes.txt').write_text('do not hide me')
    result=preview(entries)
    assert result['state']=='needs_review' and not result['publication_performed'],result


def test_tracked_lock_namespace_requires_explicit_review(trees):
    _,entries=trees;root=Path(entries[0][1]['path'])
    directory=root/'.sentra-output-locks';directory.mkdir()
    (directory/'user.txt').write_text('tracked content')
    git(root,'add','.sentra-output-locks/user.txt')
    result=preview(entries)
    assert result['state']=='needs_review' and 'tracked atomic-lock' in result['reason']


def test_metadata_change_during_rehearsal_invalidates_result(trees,monkeypatch):
    import workspace.worktree_review as review
    _,entries=trees;root=Path(entries[0][1]['path']).resolve()
    atomic_output(AuthorizedPaths((str(root),),(str(root),)),str(root/'file0.txt'),
        lambda temporary:temporary.write_text('updated\n'),lambda temporary:None,overwrite=True)
    lock=next(root.glob('.sentra-output-locks/*.lock'))
    def change_after_capture(snapshot,scratch):
        _extract(snapshot,scratch)
        lock.write_bytes(b'1')
    monkeypatch.setattr(review,'_extract',change_after_capture)
    result=preview(entries)
    assert result['state']=='stale' and not result['automatic_retry']


def test_base_drift_is_explicit_even_when_patch_rehearsal_is_compatible(trees):
    repo,entries=trees;(repo/'unrelated.txt').write_text('new base');git(repo,'add','unrelated.txt');git(repo,'commit','-m','advance')
    result=preview(entries)
    assert result['state']=='compatible' and result['base_diverged'] and not result['publication_performed']


@pytest.mark.parametrize('name,kind',[('../escape',tarfile.REGTYPE),('C:/escape',tarfile.REGTYPE),('.git/config',tarfile.REGTYPE),('.git /config',tarfile.REGTYPE),('.sentra-output-locks/notes',tarfile.REGTYPE),('NUL',tarfile.REGTYPE),('secret',tarfile.SYMTYPE)])
def test_archive_paths_and_links_are_refused(tmp_path,name,kind):
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w') as archive:
        entry=tarfile.TarInfo(name);entry.type=kind;entry.size=0;entry.linkname='../escape';archive.addfile(entry)
    root=tmp_path/'scratch';root.mkdir()
    with pytest.raises((ValueError,PermissionError)):_extract(output.getvalue(),root)
    assert list(root.iterdir())==[]
