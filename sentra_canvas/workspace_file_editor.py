"""Protected owner drafts; physical saves use the existing files machine and CAS.

Drafts are presentation data, never filesystem authority or replayable operations.
Their identity includes the live conversation and exact execution workspace.
"""
from contextlib import closing,nullcontext
import hashlib
import json
import time
from .task_workspace import file_service
from .project_review import MAX_PREVIEW
from sentra_core.conversations import _encode,_decode

ACTIONS=frozenset({'workspace_file_get','workspace_file_draft_save'})
SCOPE={'space_id','dot_id','conversation_id','execution_workspace_id','path'}


def workspace_draft_lock(control,project_id,execution_workspace_id):
    from sentra_remote.product import _exclusive_registry_lock
    directory=control.durable.root/'workspace-editor-locks';directory.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(json.dumps([project_id,execution_workspace_id],separators=(',',':')).encode()).hexdigest()
    return _exclusive_registry_lock(directory/key,timeout_s=3)


def has_protected_workspace_drafts(control,owner,project_id,execution_workspace_id):
    """Cleanup must not orphan private text which has not reached the disk."""
    with closing(control.store.connect('shell')) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='canvas_file_drafts'").fetchone():return False
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='canvas_file_draft_scopes'").fetchone():
            # Old hashes cannot be reverse-mapped safely. Opening each draft
            # under its verified scope migrates its metadata without losing it.
            return bool(db.execute('SELECT 1 FROM canvas_file_drafts WHERE owner=? AND body IS NOT NULL LIMIT 1',(owner,)).fetchone())
        return bool(db.execute('SELECT 1 FROM canvas_file_drafts d LEFT JOIN canvas_file_draft_scopes s '
            'ON s.owner=d.owner AND s.scope=d.scope WHERE d.owner=? AND d.body IS NOT NULL AND '
            '((s.workspace_id=? AND s.execution_workspace_id=?) OR s.scope IS NULL) LIMIT 1',
            (owner,project_id,execution_workspace_id)).fetchone())


def validate_draft(value):
    if value is None:return True
    if not isinstance(value,dict) or set(value)!={'base_sha256','base_content','content','anchor','head'}:return False
    try:
        if any(not isinstance(value[k],str) or len(value[k].encode('utf-8'))>MAX_PREVIEW for k in ('base_content','content')):return False
        if hashlib.sha256(value['base_content'].encode('utf-8')).hexdigest()!=value['base_sha256']:return False
        return all(type(value[k]) is int and 0<=value[k]<=len(value['content'].encode('utf-16-le'))//2 for k in ('anchor','head'))
    except UnicodeError:return False


def dispatch_editor(canvas,pid,action,params):
    fields=set(params)
    if action not in ACTIONS:raise ValueError('unsupported file editor action')
    if action=='workspace_file_get':
        if fields not in (SCOPE,SCOPE-{'execution_workspace_id'}):raise ValueError('exact file scope required')
    elif fields!=SCOPE|{'expected_revision','draft'}:
        raise ValueError('exact versioned draft scope required')
    if action=='workspace_file_draft_save' and (type(params['expected_revision']) is not int or params['expected_revision']<0 or not validate_draft(params['draft'])):
        raise ValueError('invalid versioned file draft')
    path=params.get('path')
    if (not isinstance(path,str) or not 1<=len(path)<=512 or '\0' in path or ':' in path
            or any(part in {'','.','..','.git','.sentra'} for part in path.replace('\\','/').split('/'))):
        raise ValueError('relative editor file path required')
    params={**params,'path':path.replace('\\','/')}
    service,preview_params,identity=file_service(canvas,pid,{k:v for k,v in params.items() if k in SCOPE})
    file={'path':params['path'],'editable':False,'content':None,'sha256':None}
    if action=='workspace_file_get':
        try:file=service.dispatch('project_file_preview',preview_params,project_id=pid)
        except (OSError,ValueError,PermissionError) as error:
            file['file_error']=str(error)
    control=canvas._shell_service();owner=canvas._runtime().owner
    key=hashlib.sha256(json.dumps([pid,params['space_id'],params['dot_id'],params['conversation_id'],
        identity['execution_workspace_id'],file['path']],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    guard=workspace_draft_lock(control,pid,identity['execution_workspace_id']) if action=='workspace_file_draft_save' else nullcontext()
    with guard,closing(control.store.connect('shell')) as db,db:
        if action=='workspace_file_draft_save':
            # A cleanup may have fenced this workspace after the initial scope
            # read. Never commit a late private draft into a discarded identity.
            file_service(canvas,pid,{k:v for k,v in params.items() if k in SCOPE})
        db.execute('CREATE TABLE IF NOT EXISTS canvas_file_drafts(owner TEXT NOT NULL,scope TEXT NOT NULL,version INTEGER NOT NULL,revision INTEGER NOT NULL,body TEXT,updated_at REAL NOT NULL,PRIMARY KEY(owner,scope))')
        db.execute('BEGIN IMMEDIATE')
        # Keep the original six-column draft table rollback-compatible. New
        # scope metadata lives separately and never contains editor text.
        db.execute('CREATE TABLE IF NOT EXISTS canvas_file_draft_scopes(owner TEXT NOT NULL,scope TEXT NOT NULL,workspace_id TEXT NOT NULL,execution_workspace_id TEXT NOT NULL,conversation_id TEXT NOT NULL,PRIMARY KEY(owner,scope))')
        row=db.execute('SELECT * FROM canvas_file_drafts WHERE owner=? AND scope=?',(owner,key)).fetchone()
        if row and row['version']!=1:raise RuntimeError('file draft schema is newer than this application')
        if row or action=='workspace_file_draft_save' and params['draft'] is not None:
            db.execute('INSERT INTO canvas_file_draft_scopes VALUES(?,?,?,?,?) ON CONFLICT(owner,scope) DO UPDATE SET workspace_id=excluded.workspace_id,execution_workspace_id=excluded.execution_workspace_id,conversation_id=excluded.conversation_id',
                (owner,key,pid,identity['execution_workspace_id'],params['conversation_id']))
        draft=_decode(row['body']) if row and row['body'] is not None else None
        revision=row['revision'] if row else 0
        if action=='workspace_file_draft_save':
            if draft==params['draft']:return {'saved':True,'revision':revision,'scope':key,'execution_started':False}
            if revision!=params['expected_revision']:
                return {'saved':False,'conflict':True,'revision':revision,'scope':key,'draft':draft}
            count=db.execute('SELECT COUNT(*) FROM canvas_file_drafts WHERE owner=?',(owner,)).fetchone()[0]
            if not row and count>=512:raise ValueError('file draft budget reached; no existing draft was replaced')
            revision+=1
            db.execute('INSERT INTO canvas_file_drafts(owner,scope,version,revision,body,updated_at) VALUES(?,?,?,?,?,?) '
                'ON CONFLICT(owner,scope) DO UPDATE SET revision=excluded.revision,body=excluded.body,updated_at=excluded.updated_at',
                (owner,key,1,revision,_encode(params['draft']) if params['draft'] is not None else None,time.time()))
            return {'saved':True,'revision':revision,'scope':key,'execution_started':False}
    # Reading a draft never registers machines, prepares grants or starts work.
    host=canvas._machine_service()
    with closing(control.store.connect('shell')) as db:
        dot=control.shell._entity(db,owner,pid,'dot',params['dot_id'],space_id=params['space_id'])
    machines={m['machine_id'] for m in host.inventory(pid) if m['agent_id']==dot['agent_id'] and m['kind']=='workspace-files'}
    jobs=[w for w in host.task_catalog(workspace_id=pid,agent_ids={dot['agent_id']},conversation_id=params['conversation_id'])
        if w['machine_id'] in machines and 'workspace:file.write' in w['capabilities']]
    root=dot.get('canvas_root_dot_id') or dot['dot_id']
    layout_scope=hashlib.sha256('\0'.join((canvas.store.principal,pid,params['space_id'],root)).encode()).hexdigest()
    return {**file,**identity,'scope':key,'layout_scope':layout_scope,'draft':draft,'revision':revision,
        'editor':{'machine_id':jobs[0]['machine_id'],'work_item_id':jobs[0]['work_item_id']} if jobs and file['editable'] else None,
        'draft_stale':draft is not None and draft['base_sha256']!=file['sha256'],'restoration_creates_resources':False}
