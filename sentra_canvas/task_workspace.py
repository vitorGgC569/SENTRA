"""Bind real Git worktrees to the existing execution-workspace authority."""
from contextlib import closing
from pathlib import Path


def binding(control,owner,project_id,conversation_id,agent_id=None):
    with closing(control.store.connect('execution_workspace')) as db:
        rows=db.execute("SELECT execution_workspace_id FROM execution_workspaces WHERE owner=? AND backend='worktree' "
            "ORDER BY created_at DESC",(owner,)).fetchall()
    for row in rows:
        item=control.execution_workspaces.info(row['execution_workspace_id'],owner);m=item['metadata']
        if m.get('workspace_id')!=project_id or m.get('conversation_id')!=conversation_id:continue
        if item['state'] in {'DISCARDED','FAILED'}:raise RuntimeError('coding workspace is unavailable; select a new task conversation')
        if agent_id and m.get('agent_id')!=agent_id:raise PermissionError('worktree belongs to another Dot')
        if control.durable.operation_status(m['source_operation_id'],owner)['state']!='SUCCEEDED':
            raise RuntimeError('worktree creation is unconfirmed; inspect the original operation')
        from workspace.worktrees import WorktreeManager
        inspected=WorktreeManager(m['repository'],m['manager_state']).inspect(m['worktree_id'])
        if (inspected['principal_id']!=m['agent_id'] or inspected['work_item_id']!=item['work_item_id']
                or Path(inspected['path']).resolve()!=Path(item['physical_ref']).resolve()):
            raise PermissionError('worktree binding changed')
        return {**inspected,'execution_workspace_id':item['execution_workspace_id'],
            'conversation_id':conversation_id,'project_id':project_id,'space_id':m['space_id'],
            'authority_run_id':item['authority_run_id']}
    return None


def register(control,owner,request,manager,result):
    work=control.work_item_info(request.work_item_id,owner);m=work.get('metadata',{})
    cid=m.get('conversation_id');pid=m.get('workspace_id')
    if not cid or not pid:return result
    with closing(control.store.connect('shell')) as db:
        convo=control.shell._entity(db,owner,pid,'conversation',cid)
        dot=control.shell._entity(db,owner,pid,'dot',convo['dot_id'],space_id=convo['space_id'])
    if dot['agent_id']!=request.principal_id or dot['dot_id']!=result['dot_id']:
        raise PermissionError('worktree execution scope differs from its conversation')
    ident='xws-git-'+result['worktree_id']
    try:existing=control.execution_workspaces.info(ident,owner)
    except FileNotFoundError:existing=None
    if existing:
        if existing['physical_ref']!=result['path'] or existing['work_item_id']!=request.work_item_id:
            raise PermissionError('execution workspace identity changed')
    else:
        control.create_execution_workspace(owner,authority_run_id=work['run_id'],work_item_id=request.work_item_id,
            backend='worktree',execution_workspace_id=ident,physical_ref=result['path'],base_revision=result['base_commit'],
            initial_state='READY',metadata={'workspace_id':pid,'space_id':convo['space_id'],'conversation_id':cid,
                'agent_id':dot['agent_id'],'dot_id':dot['dot_id'],'repository':str(manager.repository),
                'manager_state':str(manager.state),'worktree_id':result['worktree_id'],
                'source_operation_id':request.operation_id})
    return {**result,'execution_workspace_id':ident,'conversation_id':cid}


def for_work_item(control,owner,work_item_id,agent_id):
    work=control.work_item_info(work_item_id,owner)
    if work.get('assignee_agent_id')!=agent_id:raise PermissionError('execution workspace assignee differs')
    m=work.get('metadata',{});cid=m.get('conversation_id')
    if not cid:
        with closing(control.store.connect('shell')) as db:
            row=db.execute('SELECT conversation_id FROM shell_messages WHERE owner=? AND work_item_id=? AND role=\'user\' LIMIT 1',
                (owner,work_item_id)).fetchone()
        cid=row['conversation_id'] if row else None
    selected=binding(control,owner,m['workspace_id'],cid,agent_id) if cid and m.get('workspace_id') else None
    if selected and selected['authority_run_id']!=work['run_id']:
        raise PermissionError('worktree belongs to a previous Run; select a new coding task')
    return selected


def directory(control,owner,request,fallback,*,expected_workspace_id=None):
    assigned=for_work_item(control,owner,request.work_item_id,request.principal_id)
    if expected_workspace_id is not None and expected_workspace_id!=(assigned['execution_workspace_id'] if assigned else 'project'):
        raise PermissionError('file workspace changed; reopen before saving')
    return Path(assigned['path']) if assigned else Path(fallback)


def isolate(actor,message,dot,payload):
    from .full_access import source,prepare_resources
    if payload.get('value','').strip():raise ValueError('isolate_work takes no path or policy override')
    if source(actor.control,actor.owner,message['conversation_id']) is None:
        raise PermissionError('Select Acesso completo in this conversation to prepare coding isolation')
    current=for_work_item(actor.control,actor.owner,message['work_item_id'],dot['agent_id'])
    if current:return {**current,'status':'ready','reused':True,'process_created':False}
    host=actor.canvas._machine_service();repo=actor.canvas.store.workspace(message['project_id'])['path']
    machine=host.configure_worktrees(workspace_id=message['project_id'],workspace_root=repo,
        agent_id=dot['agent_id'],dot_id=dot['dot_id'])
    prepare_resources(actor.runtime,message,dot)
    jobs=host.task_catalog(workspace_id=message['project_id'],agent_ids={dot['agent_id']},conversation_id=message['conversation_id'])
    job=next(w for w in jobs if w['machine_id']==machine['machine_id'] and 'git:worktree' in w['capabilities'])
    from workspace.worktrees import WorktreeManager
    manager=WorktreeManager(repo,actor.control.durable.root/'git-worktrees'/machine['machine_id'])
    base=manager.git('rev-parse','HEAD').strip()
    import hashlib
    key=payload.get('request_key')
    if not isinstance(key,str) or not 8<=len(key)<=128:raise ValueError('persistent isolation identity required')
    oid='isolate-'+hashlib.sha256(key.encode()).hexdigest()[:40]
    value=host.dispatch(workspace_id=message['project_id'],work_item_id=job['work_item_id'],
        machine_id=machine['machine_id'],capability_id='git:worktree',operation_id=oid,idempotency_key=oid,
        arguments={'dot_id':dot['dot_id'],'base_commit':base})
    return {'status':'ready' if value['state']=='SUCCEEDED' else 'uncertain','operation':value,
        'execution_workspace':binding(actor.control,actor.owner,message['project_id'],message['conversation_id'],dot['agent_id']) if value['state']=='SUCCEEDED' else None,
        'automatic_retry':False,'publication_performed':False}


def file_service(canvas,project_id,params):
    """Owner browser reuses the confined project service at the checked task root."""
    control=canvas._shell_service();owner=canvas._runtime().owner
    if not {'space_id','dot_id','conversation_id'}<=set(params):raise ValueError('exact task file scope required')
    with closing(control.store.connect('shell')) as db:
        convo=control.shell._entity(db,owner,project_id,'conversation',params['conversation_id'],space_id=params['space_id'])
        dot=control.shell._entity(db,owner,project_id,'dot',params['dot_id'],space_id=params['space_id'])
    if convo['dot_id']!=dot['dot_id']:raise PermissionError('file pane belongs to another Dot conversation')
    assigned=binding(control,owner,project_id,convo['conversation_id'],dot['agent_id'])
    identity=assigned['execution_workspace_id'] if assigned else 'project'
    if params.get('execution_workspace_id',identity)!=identity:raise PermissionError('file workspace changed; reopen before saving')
    root=assigned['path'] if assigned else canvas.store.workspace(project_id)['path']
    key=(project_id,params['space_id'],dot['dot_id'],convo['conversation_id'],identity)
    with canvas._lock:
        cache=getattr(canvas,'_task_file_services',None)
        if cache is None:cache={};canvas._task_file_services=cache
        if key not in cache:
            if len(cache)>=128:raise RuntimeError('task file-view budget reached; no workspace was substituted')
            from .project_review import ProjectReviewService
            cache[key]=ProjectReviewService(lambda pid:root)
    payload={k:v for k,v in params.items() if k not in {'space_id','dot_id','conversation_id','execution_workspace_id'}}
    return cache[key],payload,{'execution_workspace_id':identity,'branch':assigned['branch'] if assigned else None}


def review(canvas,project_id,params,*,allowed_dot_ids=None):
    """Select existing bindings by conversation identity, never by caller paths."""
    if set(params)!={'dot_id','space_id','conversation_ids'}:raise ValueError('exact Canvas and conversation selection required')
    ids=params['conversation_ids']
    if (not isinstance(ids,list) or not 1<=len(ids)<=8 or any(not isinstance(cid,str) for cid in ids)
            or len(set(ids))!=len(ids)):
        raise ValueError('select one to eight distinct conversations')
    from .shell_dot_canvas import dots_for_root
    from workspace.worktrees import WorktreeManager
    from workspace.worktree_review import preview
    control=canvas._shell_service();owner=canvas._runtime().owner
    _,members=dots_for_root(control,owner,project_id,params['dot_id'],params['space_id'])
    members={dot['dot_id']:dot for dot in members};entries=[];skipped=[]
    def selected_entry(cid):
        with closing(control.store.connect('shell')) as db:
            convo=control.shell._entity(db,owner,project_id,'conversation',cid,space_id=params['space_id'])
        member=members.get(convo['dot_id'])
        if member is None or allowed_dot_ids is not None and member['dot_id'] not in allowed_dot_ids:
            raise PermissionError('review conversation belongs to another Canvas or unconnected Dot')
        selected=binding(control,owner,project_id,cid,member['agent_id'])
        if selected is None:return None
        record=control.execution_workspaces.info(selected['execution_workspace_id'],owner)
        metadata=record['metadata']
        return WorktreeManager(metadata['repository'],metadata['manager_state']),selected
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(4,len(ids))) as pool:
        for cid,entry in zip(ids,pool.map(selected_entry,ids)):
            if entry is None:skipped.append(cid)
            else:entries.append(entry)
    if not entries:raise ValueError('no isolated coding work exists in the selected conversations')
    value=preview(entries)
    from workspace.git_workflow import plan
    host=canvas._machine_service()
    resources=[]
    for manager,item in entries:
        resource={'dot_id':item['dot_id'],'conversation_id':item['conversation_id'],
            'execution_workspace_id':item['execution_workspace_id'],'branch':item['branch'],'diff_stat':item['diff_stat']}
        # Multi-worktree conflict rehearsal already performs bounded snapshots.
        # Fetch the richer file/remote plan only for the one branch whose next
        # step the owner is reviewing; avoid N full manifests in one HTTP read.
        if len(entries)>1:
            resources.append(resource);continue
        machines=[m for m in host.inventory(project_id) if m['agent_id']==item['principal_id'] and m['kind']=='git-worktrees']
        jobs=host.task_catalog(workspace_id=project_id,agent_ids={item['principal_id']},conversation_id=item['conversation_id'])
        job=next((w for w in jobs if any(m['machine_id']==w['machine_id'] for m in machines) and any(c.startswith('git:') and c not in {'git:worktree','git:worktree.inspect'} for c in w['capabilities'])),None)
        resources.append({**resource,
            'review':plan(manager,item['worktree_id']),
            'workflow':{'machine_id':job['machine_id'],'work_item_id':job['work_item_id'],'capabilities':job['capabilities']} if job else None})
    return {**value,'skipped_conversations':skipped,'resources':resources}
