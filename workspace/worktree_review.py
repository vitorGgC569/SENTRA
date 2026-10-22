"""Bounded conflict rehearsal in disposable files; never changes a live index/ref."""
import hashlib
import io
import os
from pathlib import Path,PureWindowsPath
import subprocess
import tarfile
import tempfile

MAX_PATCH=8*1024*1024
MAX_ARCHIVE=32*1024*1024


def _git(manager,cwd,args,*,limit=MAX_PATCH,stdin=None):
    env={k:v for k,v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update(GIT_TERMINAL_PROMPT='0',LC_ALL='C')
    # Spool stdout to disk so an unexpectedly large tree cannot exhaust memory.
    with tempfile.TemporaryFile() as output:
        result=subprocess.run(['git','-c','core.hooksPath='+str(manager.hooks),
            '-c','core.fsmonitor=false','-C',str(cwd),*args],input=stdin,stdout=output,
            stderr=subprocess.PIPE,env=env,timeout=45,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        size=output.tell()
        if size>limit:raise ValueError('review size budget exceeded')
        output.seek(0)
        return result.returncode,output.read(),result.stderr[:8192]


def _checked(manager,cwd,args,limit=MAX_PATCH):
    code,out,_=_git(manager,cwd,args,limit=limit)
    if code:raise RuntimeError('Git could not read the review snapshot')
    return out


def _patch(manager,path,base):
    if _checked(manager,path,['ls-files','--others','--exclude-standard','-z']):
        raise ValueError('untracked files require explicit file review before integration')
    patch=_checked(manager,path,['diff','--binary','--no-ext-diff','--no-textconv',base,'--'])
    if any(flag in patch for flag in (b'GIT binary patch',b'Binary files ',b' mode 120000',b' mode 160000')):
        raise ValueError('binary files, symbolic links and submodules require explicit review')
    return patch


def _extract(snapshot,root):
    total=0
    with tarfile.open(fileobj=io.BytesIO(snapshot),mode='r:') as archive:
        for index,entry in enumerate(archive):
            if index>=4096:raise ValueError('review file-count budget exceeded')
            parts=entry.name.replace('\\','/').split('/')
            if (PureWindowsPath(entry.name).is_reserved() or any(p in {'.','..'} or ':' in p
                    or p.rstrip(' .').lower() in {'.git','.sentra'} for p in parts)):
                raise ValueError('repository archive contains a reserved path')
            target=(root/entry.name).resolve()
            if not target.is_relative_to(root):raise PermissionError('archive path escaped review directory')
            if entry.isdir():target.mkdir(parents=True,exist_ok=True);continue
            if not entry.isfile():raise ValueError('repository archive contains a symbolic link or unsupported entry')
            total+=entry.size
            if total>MAX_ARCHIVE:raise ValueError('expanded review size budget exceeded')
            target.parent.mkdir(parents=True,exist_ok=True)
            source=archive.extractfile(entry)
            if source is None:raise ValueError('archive file content is unavailable')
            with source,target.open('xb') as output:
                while data:=source.read(65536):output.write(data)


def preview(entries):
    """Apply tracked text deltas in order to a common base, entirely in scratch."""
    if not 1<=len(entries)<=8:raise ValueError('select one to eight worktrees')
    manager=entries[0][0];worktrees=[item for _,item in entries]
    if any(other.common!=manager.common for other,_ in entries):raise PermissionError('review spans different repositories')
    bases={item['base_commit'] for item in worktrees}
    if len(bases)!=1:raise ValueError('worktrees use different bases; a structured rebase decision is required')
    base=next(iter(bases));head=manager.git('rev-parse','HEAD').strip()
    patches=[]
    for own_manager,item in entries:
        # Recheck each physical identity immediately before capturing its diff.
        actual=own_manager.inspect(item['worktree_id'])
        if actual['path']!=item['path'] or actual['base_commit']!=base:raise PermissionError('worktree review identity changed')
        try:patch=_patch(own_manager,item['path'],base)
        except ValueError as error:
            return {'state':'needs_review','reason':str(error),'worktree_id':item['worktree_id'],
                'publication_performed':False,'base_commit':base}
        patches.append(patch)
    snapshot=_checked(manager,manager.repository,['archive','--format=tar',base],MAX_ARCHIVE)
    records=[]
    with tempfile.TemporaryDirectory(prefix='review-',dir=manager.state) as temporary:
        scratch=Path(temporary).resolve()
        if not scratch.is_relative_to(manager.state.resolve()):raise PermissionError('review directory escaped state')
        code,_,_=_git(manager,scratch,['-c','init.templateDir=','init','--quiet'])
        if code:raise RuntimeError('isolated scratch Git context could not be prepared')
        try:_extract(snapshot,scratch)
        except ValueError as error:
            return {'state':'needs_review','reason':str(error),'publication_performed':False,'base_commit':base}
        for item,patch in zip(worktrees,patches):
            record={'worktree_id':item['worktree_id'],'dot_id':item['dot_id'],
                'patch_sha256':hashlib.sha256(patch).hexdigest(),'changed':bool(patch),'state':'compatible'}
            if patch:
                code,_,error=_git(manager,scratch,['apply','--check','--whitespace=nowarn','-'],stdin=patch)
                if code:
                    record.update(state='conflict',reason=error.decode('utf-8','replace'))
                    records.append(record);break
                code,_,_=_git(manager,scratch,['apply','--whitespace=nowarn','-'],stdin=patch)
                if code:raise RuntimeError('scratch application failed after check')
            records.append(record)
    # A concurrent edit or publication invalidates the preview, never triggers retry.
    stable=manager.git('rev-parse','HEAD').strip()==head
    for (own_manager,item),patch in zip(entries,patches):
        try:stable=(_patch(own_manager,item['path'],base)==patch) and stable
        except ValueError:stable=False
    state='stale' if not stable else 'conflict' if any(r['state']=='conflict' for r in records) else 'compatible'
    return {'state':state,'base_commit':base,'target_head':head,'base_diverged':head!=base,
        'worktrees':records,'unchecked_worktrees':len(worktrees)-len(records),
        'publication_performed':False,'automatic_retry':False,
        'scope':'tracked text changes; ordered patch rehearsal, not semantic verification'}
