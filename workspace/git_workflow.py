"""Bounded Git review and explicit centrally admitted publication steps.

No path, executable, author, hook or policy override is accepted from callers.
Every physical step uses a distinct capability and an immutable review digest.
"""
from __future__ import annotations
import hashlib
import difflib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from urllib.parse import urlsplit

from sentra_runtime.effect_boundary import CentralEffectContext,current_effect_context
from sentra_canvas.instance_lock import InstanceLock
from sentra_executors._base import EffectRefusedBeforePublication
from .worktree_review import _plain_path,MAX_REVIEW_FILES,MAX_ARCHIVE

CAPABILITIES=('git:commit','git:discard','git:merge','git:publish','git:cleanup')
TEXT_EXT={'.py','.js','.jsx','.ts','.tsx','.json','.md','.txt','.css','.html','.yml','.yaml','.toml','.rs','.go','.ps1','.sh'}
PROTECTED={'.git','.sentra','.sentra-output-locks','.env','.env.local','.npmrc','.pypirc','id_rsa','id_ed25519'}


def _refuse(reason):
    # Host-side proof before any requested ref/file publication. This terminal
    # refusal permits a new reviewed decision; transport/partial effects remain
    # UNCERTAIN and are never automatically submitted again.
    raise EffectRefusedBeforePublication(reason)


def _remote_display(url):
    if any(c in url for c in '\0\r\n'):return None
    if re.match(r'^[A-Za-z]:[\\/]',url) or url.startswith(('/','\\\\')):return url
    if '://' in url:
        try:
            parts=urlsplit(url);port=parts.port
        except ValueError:return None
        if parts.scheme not in {'https','ssh','git','file'}:return None
        if parts.scheme!='file' and not parts.hostname:return None
        return parts.scheme+'://'+(parts.hostname or '')+((':'+str(port)) if port else '')+parts.path
    if '::' in url:return None  # No executable remote helpers.
    if re.fullmatch(r'(?:[^@/:\s]+@)?[^/:\s]+:.+',url):return url.split('@')[-1]
    if ':' not in url:return url
    return None


def _run(manager,path,*args,stdin=None,index=None,attr_source=None,limit=MAX_ARCHIVE):
    env={k:v for k,v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update(GIT_TERMINAL_PROMPT='0',GIT_OPTIONAL_LOCKS='0',LC_ALL='C')
    if index is not None:env['GIT_INDEX_FILE']=str(index)
    if attr_source is not None:env.update(GIT_ATTR_SOURCE=attr_source,GIT_ATTR_NOSYSTEM='1')
    with tempfile.TemporaryFile() as output:
        result=subprocess.run(['git','-c','core.hooksPath='+str(manager.hooks),'-c','core.fsmonitor=false','-c','core.longpaths=true',
            *(['-c','core.attributesFile='+str(manager.hooks/'no-global-attributes')] if attr_source else []),
            '-c','core.pager=cat','-c','color.ui=false','-C',str(path),*args],input=stdin,stdout=output,stderr=subprocess.PIPE,
            env=env,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if output.tell()>limit:raise ValueError('Git workflow output exceeds review budget')
        if result.returncode:raise RuntimeError('Git step failed; inspect the central receipt before continuing: '+result.stderr[:2048].decode('utf-8','replace'))
        output.seek(0);return output.read()


def _safe_name(relative):
    if not isinstance(relative,str) or any(c in relative for c in '\n\r\t\0') or len(relative)>512:
        raise ValueError('unsupported review path')
    parts=relative.replace('\\','/').split('/')
    if relative.startswith(('/','\\')) or any(p in {'','.','..'} or ':' in p or p!=p.rstrip(' .') for p in parts):raise ValueError('relative unambiguous review path required')
    if any(p.rstrip(' .').lower() in PROTECTED for p in parts):
        raise PermissionError('protected file requires a separate owner review')


def _file(root,relative):
    _safe_name(relative);path=_plain_path(root,relative)
    if not path.exists():return {'path':relative,'sha256':None,'size_bytes':0,'deleted':True},None
    before=path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size>MAX_ARCHIVE:raise ValueError('regular file within review budget required')
    with path.open('rb') as stream:
        opened=os.fstat(stream.fileno());data=stream.read(MAX_ARCHIVE+1);after=os.fstat(stream.fileno())
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
    if identity(before)!=identity(opened) or identity(opened)!=identity(after) or len(data)>MAX_ARCHIVE:raise ValueError('file changed during review')
    row={'path':relative,'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data),'deleted':False,'mode':'100755' if before.st_mode&stat.S_IXUSR else '100644'}
    try:text=data.decode('utf-8') if b'\0' not in data else None
    except UnicodeDecodeError:text=None
    row['binary']=text is None
    if text is not None and path.suffix.lower() in TEXT_EXT and len(data)<=128*1024:row['preview']=text
    return row,data


def plan(manager,identity):
    item=manager.inspect(identity);root=Path(item['path']).resolve(strict=True)
    head=_run(manager,root,'rev-parse','HEAD',limit=256).decode().strip()
    # NUL records preserve names containing spaces. Renames are reviewed as delete/add.
    names=_run(manager,root,'diff','--name-only','--no-renames','-z','HEAD','--').split(b'\0')
    added=_run(manager,root,'ls-files','--others','--exclude-standard','-z').split(b'\0')
    paths=sorted(set(os.fsdecode(p) for p in names+added if p))
    if len(paths)>MAX_REVIEW_FILES:raise ValueError('Git review file-count budget exceeded')
    rows=[];total=0
    for relative in paths:
        # Persistent atomic-output locks are metadata, never cleanup candidates.
        if '.sentra-output-locks' in relative.replace('\\','/').split('/'):continue
        try:row,_data=_file(root,relative)
        except (ValueError,PermissionError) as error:row={'path':relative,'review_blocked':str(error)}
        row['new']=os.fsencode(relative) in added;total+=row.get('size_bytes',0)
        if 'preview' in row:
            if row['new']:
                diff=''.join(difflib.unified_diff([],row['preview'].splitlines(keepends=True),fromfile='/dev/null',tofile='b/'+relative))
                if len(diff.encode())<=128*1024:row['diff']=diff
                else:row['diff_error']='Diff exceeds the bounded line review; narrow the file before commit'
            else:
                try:row['diff']=_run(manager,root,'diff','--no-ext-diff','--no-textconv','--no-renames','--unified=3','HEAD','--',relative,limit=128*1024).decode('utf-8','replace')
                except ValueError:row['diff_error']='Diff exceeds the bounded line review; use the reviewed content and hashes'
        if total>MAX_ARCHIVE:raise ValueError('Git review total-byte budget exceeded')
        rows.append(row)
    status=_run(manager,root,'status','--porcelain=v1','-z',limit=1024*1024)
    ignored=_run(manager,root,'ls-files','--others','--ignored','--exclude-standard','--directory','-z',limit=1024*1024)
    index=_run(manager,root,'ls-files','--stage','-z',limit=8*1024*1024)
    main_head=_run(manager,manager.repository,'rev-parse','HEAD',limit=256).decode().strip()
    main_status=_run(manager,manager.repository,'status','--porcelain=v1','-z',limit=1024*1024)
    remotes=[]
    for name in _run(manager,root,'remote',limit=8192).decode().splitlines():
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',name):continue
        urls=_run(manager,root,'remote','get-url','--push','--all',name,limit=8192).decode().splitlines()
        # Multiple push URLs can partially publish. They need a separate workflow.
        if len(urls)==1:
            display=_remote_display(urls[0])
            if display is not None:remotes.append({'name':name,'destination':display,'url_sha256':hashlib.sha256(urls[0].encode()).hexdigest()})
    evidence={'worktree_id':identity,'branch':item['branch'],'head':head,'main_head':main_head,
        'main_clean':not main_status,'files':rows,'remotes':remotes,
        'index_sha256':hashlib.sha256(index).hexdigest(),'status_sha256':hashlib.sha256(status).hexdigest(),
        'checkout_clean':not status,'ignored_paths':[os.fsdecode(p) for p in ignored.split(b'\0') if p],
        'main_status_sha256':hashlib.sha256(main_status).hexdigest()}
    evidence['snapshot_sha256']=hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    return {**evidence,'read_only':True,'publication_performed':False,'automatic_retry':False}


def validate_args(capability,args):
    extras={'git:commit':{'files','message'},'git:discard':{'files'},'git:merge':set(),
        'git:publish':{'remote'},'git:cleanup':set()}
    if capability not in extras or set(args)!={'worktree_id','expected_snapshot_sha256'}|extras[capability]:raise ValueError('exact reviewed Git step required')
    if not isinstance(args['worktree_id'],str) or not re.fullmatch('[a-f0-9]{24}',args['worktree_id']):raise ValueError('exact worktree identity required')
    if not isinstance(args['expected_snapshot_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',args['expected_snapshot_sha256']):raise ValueError('exact Git review digest required')
    if 'files' in args:
        files=args['files']
        if not isinstance(files,list) or not 1<=len(files)<=256 or any(not isinstance(p,str) for p in files) or len(set(files))!=len(files):raise ValueError('select one to 256 distinct reviewed files')
        for relative in files:_safe_name(relative)
    if 'message' in args and (not isinstance(args['message'],str) or not args['message'].strip() or len(args['message'])>2000 or '\0' in args['message']):raise ValueError('bounded commit message required')
    if 'remote' in args and (not isinstance(args['remote'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',args['remote']) or args['remote'].startswith('-')):raise ValueError('configured remote name required')
    return args


def execute(manager,request,*,before_cleanup=None):
    context=current_effect_context.get()
    if not isinstance(context,CentralEffectContext) or context.request!=request or request.capability_id not in CAPABILITIES:raise PermissionError('exact central Git effect context required')
    args=validate_args(request.capability_id,dict(request.arguments));context.checkpoint()
    # Shared across Dot machines/instances using the same repository.
    lock=InstanceLock(manager.common/'sentra-worktrees.lock')
    try:
        context.checkpoint();review=plan(manager,args['worktree_id']);item=manager.inspect(args['worktree_id']);root=Path(item['path'])
        if review['snapshot_sha256']!=args['expected_snapshot_sha256']:_refuse('Git review is stale; inspect again before a new decision')
        if any(f.get('review_blocked') for f in review['files']):_refuse('blocked files require owner review')
        selected=[f for f in review['files'] if f['path'] in args.get('files',[])]
        if 'files' in args and len(selected)!=len(args['files']):_refuse('selected file is outside the exact review')
        if request.capability_id=='git:commit':return _commit(manager,root,review,selected,args['message'],context)
        if request.capability_id=='git:discard':
            from sentra_canvas.project_review import save_edit
            results=[];restored=[]
            # Restrict discard to existing UTF-8 tracked files, preserving new/binary files.
            for row in selected:
                if row['new'] or row.get('deleted') or row.get('binary') or 'preview' not in row:_refuse('discard supports reviewed existing UTF-8 source files only')
                original=_run(manager,root,'show',review['head']+':'+row['path'],limit=128*1024).decode('utf-8')
                restored.append((row,original))
            for row,original in restored:
                context.checkpoint();results.append(save_edit(root,row['path'],content=original,expected_sha256=row['sha256'],state_root=manager.state/'file-edits'))
            return {'action':'discard','files':results,'verified':True,'automatic_retry':False}
        if request.capability_id=='git:merge':
            if not review['main_clean']:_refuse('main checkout must be clean before integration')
            if review['files']:_refuse('commit or discard worktree changes before integration')
            _run(manager,manager.repository,'merge-base','--is-ancestor',review['main_head'],review['head'],limit=256)
            context.checkpoint();_run(manager,manager.repository,'merge','--ff-only','--no-edit',review['head'],limit=65536)
            actual=_run(manager,manager.repository,'rev-parse','HEAD',limit=256).decode().strip()
            if actual!=review['head']:raise RuntimeError('integration result changed; reconcile')
            return {'action':'merge','head':actual,'previous_head':review['main_head'],'verified':True,'automatic_retry':False}
        if request.capability_id=='git:publish':
            if review['files']:_refuse('commit or discard worktree changes before publication')
            if not any(r['name']==args['remote'] for r in review['remotes']):_refuse('remote is not in the reviewed configuration')
            context.checkpoint()
            # No force, tags, alternate URL, arbitrary refspec, credential or hook override.
            _run(manager,root,'push','--porcelain','--',args['remote'],review['head']+':refs/heads/'+review['branch'],limit=65536)
            observed=_run(manager,root,'ls-remote','--refs','--',args['remote'],'refs/heads/'+review['branch'],limit=4096).decode().split()
            if not observed or observed[0]!=review['head']:raise RuntimeError('remote publication is unconfirmed; reconcile without replay')
            return {'action':'publish','head':review['head'],'branch':review['branch'],'remote':args['remote'],'verified':True,'automatic_retry':False}
        if not review['checkout_clean'] or review['ignored_paths']:_refuse('cleanup requires no changed, untracked or ignored files; preserve them before removal')
        _run(manager,manager.repository,'merge-base','--is-ancestor',review['head'],review['main_head'],limit=256)
        cleanup_root=_plain_path(manager.state.resolve(),'c-'+args['worktree_id'][:12])
        if cleanup_root.exists():_refuse('cleanup staging identity already exists; reconcile the prior cleanup')
        if before_cleanup is not None:
            context.checkpoint();before_cleanup()
        manifest=manager.state/(args['worktree_id']+'.json')
        record=json.loads(manifest.read_text());record.update(state='archiving',cleanup_path=str(cleanup_root))
        context.checkpoint();manifest.write_text(json.dumps(record))
        # Windows Git's dirty-check subprocess has a shorter absolute GIT_DIR
        # budget than long-path checkout. Move to a short, reserved host path
        # first, then keep Git's normal non-force dirty check during removal.
        # The manifest retains the moved resource if any later step is uncertain.
        context.checkpoint();_run(manager,manager.repository,'worktree','move','--',str(root),str(cleanup_root),limit=65536)
        context.checkpoint();_run(manager,manager.repository,'worktree','remove','--',str(cleanup_root),limit=65536)
        context.checkpoint();record['state']='archived';manifest.write_text(json.dumps(record))
        if root.exists() or cleanup_root.exists():raise RuntimeError('cleanup path identity changed; reconcile without removing new data')
        return {'action':'cleanup','worktree_id':args['worktree_id'],'branch_retained':True,'verified':True,'automatic_retry':False}
    finally:lock.close()


def _commit(manager,root,review,selected,message,context):
    # Build the commit from captured bytes in a private index. A concurrent file
    # edit cannot sneak unreviewed content into the commit.
    if any(Path(row['path']).name=='.gitattributes' for row in review['files']):_refuse('Git attribute changes require separate owner review')
    if _run(manager,root,'diff','--cached','--name-only',limit=1024*1024):_refuse('review or unstage existing index changes before committing')
    with tempfile.TemporaryDirectory(prefix='git-commit-',dir=manager.state) as temporary:
        index=Path(temporary)/'index';context.checkpoint();_run(manager,root,'read-tree',review['head'],index=index)
        for row in selected:
            current,data=_file(root,row['path'])
            if current.get('sha256')!=row.get('sha256'):raise ValueError('selected file changed after review')
            context.checkpoint()
            if data is None:_run(manager,root,'update-index','--force-remove','--',row['path'],index=index)
            else:
                attributes=_run(manager,root,'check-attr','--source='+review['head'],'-z','filter','--',row['path'],attr_source=review['head'],limit=8192).split(b'\0')
                if len(attributes)>=3 and attributes[2] not in {b'unspecified',b'unset'}:
                    raise ValueError('custom Git content filters require separate owner review')
                blob=_run(manager,root,'hash-object','-w','--path='+row['path'],'--stdin',stdin=data,attr_source=review['head'],limit=256).decode().strip()
                _run(manager,root,'update-index','--add','--cacheinfo',row['mode']+','+blob+','+row['path'],index=index)
        context.checkpoint();tree=_run(manager,root,'write-tree',index=index,limit=256).decode().strip()
        commit=_run(manager,root,'commit-tree',tree,'-p',review['head'],stdin=message.encode('utf-8'),limit=256).decode().strip()
        # Reserve the real index before changing HEAD; Git clients honor this lock.
        actual_index=Path(_run(manager,root,'rev-parse','--path-format=absolute','--git-path','index',limit=8192).decode().strip())
        lock_path=Path(str(actual_index)+'.lock');fd=os.open(lock_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'wb') as handle:handle.write(index.read_bytes());handle.flush();os.fsync(handle.fileno())
            if hashlib.sha256(_run(manager,root,'ls-files','--stage','-z',limit=8*1024*1024)).hexdigest()!=review['index_sha256']:raise ValueError('live index changed during review')
            if _run(manager,root,'symbolic-ref','HEAD',limit=512).decode().strip()!='refs/heads/'+review['branch']:raise ValueError('worktree branch changed during commit review')
            context.checkpoint();_run(manager,root,'update-ref','refs/heads/'+review['branch'],commit,review['head'],limit=256)
            context.checkpoint();os.replace(lock_path,actual_index)
        finally:lock_path.unlink(missing_ok=True)
    if _run(manager,root,'rev-parse','HEAD',limit=256).decode().strip()!=commit:raise RuntimeError('commit HEAD changed; reconcile')
    return {'action':'commit','commit':commit,'previous_head':review['head'],'files':[r['path'] for r in selected],'verified':True,'automatic_retry':False}
