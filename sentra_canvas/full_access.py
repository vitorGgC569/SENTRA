"""Materialize the owner's full-access selection into exact, revocable scopes.

This is host composition, never an actor endpoint. Children receive their own
WorkItems/Grants from a checked central delegation, not the parent's credential.
"""
from contextlib import closing
import hashlib

from .store import Denied


def source(control, owner, conversation_id, _seen=None):
    seen = set() if _seen is None else set(_seen)
    if conversation_id in seen or len(seen) >= 32:
        return None
    seen.add(conversation_id)
    from .shell_access import AccessStore
    store = AccessStore(control, owner)
    profile = store.raw_profile(conversation_id)
    if profile.get('mode') != 'full':
        return None
    anchor = profile.get('full_source') or {
        'conversation_id': conversation_id, 'work_item_id': profile.get('work_item_id')}
    root = store.raw_profile(anchor['conversation_id'])
    via = anchor.get('via_conversation_id')
    if via and (store.raw_profile(via).get('work_item_id') != anchor.get('via_work_item_id')
            or source(control, owner, via, seen) is None):
        return None
    if (root.get('full_source') or root.get('mode') != 'full'
            or root.get('scope') != 'computer' or root.get('approval') != 'never'
            or not anchor.get('work_item_id') or root.get('work_item_id') != anchor['work_item_id']):
        return None
    item = control.work_item_info(anchor['work_item_id'], owner)
    if item['state'] != 'RUNNING':
        return None
    # A revoked access grant also revokes the policy, without requiring a UI change.
    decision = control.authorization.authorize(owner, principal_type='agent',
        principal_id=item['assignee_agent_id'], capability='computer:execute',
        scope_type='work_item', scope_id=item['work_item_id'], local_owner=False)
    return {'conversation_id': anchor['conversation_id'], 'work_item_id': anchor['work_item_id']} if decision['allowed'] else None


def _schema(control):
    with closing(control.store.connect('shell')) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS shell_full_scopes('
            'owner TEXT NOT NULL,source_work_item TEXT NOT NULL,work_item TEXT NOT NULL,'
            'agent_id TEXT NOT NULL,kind TEXT NOT NULL,PRIMARY KEY(owner,work_item))')


def track(control, owner, anchor, wid, agent_id, kind):
    _schema(control)
    with closing(control.store.connect('shell')) as db, db:
        old = db.execute('SELECT * FROM shell_full_scopes WHERE owner=? AND work_item=?',
            (owner, wid)).fetchone()
        if old and (old['source_work_item'] != anchor['work_item_id'] or old['agent_id'] != agent_id):
            raise Denied('full-access derivation changed')
        db.execute('INSERT OR IGNORE INTO shell_full_scopes VALUES(?,?,?,?,?)',
            (owner, anchor['work_item_id'], wid, agent_id, kind))
    return old is not None


def revoke_source(control, owner, source_work_item, conversation_id=None):
    """Invalidate both model/coordination scopes and descendant computer scopes."""
    _schema(control)
    with closing(control.store.connect('shell')) as db:
        if conversation_id:
            scopes = db.execute('SELECT s.* FROM shell_full_scopes s JOIN shell_messages m '
                'ON s.owner=m.owner AND s.work_item=m.work_item_id '
                'WHERE s.owner=? AND m.conversation_id=?', (owner, conversation_id)).fetchall()
        else:
            scopes = db.execute('SELECT * FROM shell_full_scopes WHERE owner=? AND source_work_item=?',
                (owner, source_work_item)).fetchall()
    for row in scopes:
        for grant in control.authorization.list_grants(owner, principal_type='agent',
                principal_id=row['agent_id'])['items']:
            if grant['scope_type'] == 'work_item' and grant['scope_id'] == row['work_item'] and not grant['revoked']:
                control.authorization_revoke(grant['grant_id'], owner)


def inherit(runtime, message, dot):
    from .shell_access import AccessStore, dispatch_access
    from sentra_runtime.effect_boundary import current_effect_context
    context = current_effect_context.get()
    if context is None or context.request.capability_id not in {'canvas.coordinator.delegate', 'canvas.coordinator.handoff'}:
        return
    request = context.request
    parent_cid = request.arguments.get('conversation_id')
    if (context.authority.durable is not runtime.control.durable or context.receipt.owner != runtime.owner
            or context.receipt.run_id != message['run_id']
            or request.arguments.get('project_id') != message['project_id']):
        raise Denied('full-access delegation is outside the admitted parent')
    context.checkpoint()
    item = runtime.control.work_item_info(message['work_item_id'], runtime.owner)
    if item.get('parent_work_item_id') != request.work_item_id:
        raise Denied('full-access child must belong to the admitted parent WorkItem')
    anchor = source(runtime.control, runtime.owner, parent_cid)
    if anchor is None:
        return
    with closing(runtime.control.store.connect('shell')) as db:
        parent = runtime.control.shell._entity(db, runtime.owner, message['project_id'], 'conversation',
            parent_cid, space_id=message['space_id'])
        parent_dot = runtime.control.shell._entity(db, runtime.owner, message['project_id'], 'dot',
            parent['dot_id'], space_id=message['space_id'])
    if ((parent_dot.get('canvas_root_dot_id') or parent_dot['dot_id']) !=
            (dot.get('canvas_root_dot_id') or dot['dot_id'])):
        raise Denied('full-access child is outside the selected Dot canvas')
    store = AccessStore(runtime.control, runtime.owner)
    anchor = {**anchor, 'via_conversation_id':parent_cid,
        'via_work_item_id':store.raw_profile(parent_cid)['work_item_id']}
    old = store.raw_profile(message['conversation_id'])
    # An explicit owner override on the child wins over inherited authority.
    if old.get('work_item_id') and not old.get('full_source') and old.get('owner_selected',True):
        return
    if old.get('full_source') == anchor and source(runtime.control, runtime.owner, message['conversation_id']):
        return
    key = 'full-child:' + hashlib.sha256((anchor['work_item_id'] + message['conversation_id']).encode()).hexdigest()[:40]
    dispatch_access(runtime.canvas, message['project_id'], 'access_set',
        {'space_id': message['space_id'], 'conversation_id': message['conversation_id'], 'mode': 'full'},
        key, inherited_from=anchor)


def prepare_turn(runtime, message, dot):
    """Called only before a queued turn starts; never repeats an uncertain turn."""
    from sentra_runtime.coordinator_admission import COORDINATOR_CAPABILITIES
    from sentra_mcp.services.shell_coordinator import dot_manages_canvas
    with runtime.canvas._lock:
        anchor = source(runtime.control, runtime.owner, message['conversation_id'])
        if anchor is None:
            return False
        item = runtime.control.work_item_info(message['work_item_id'], runtime.owner)
        op = runtime.control.durable.operation_status(message['operation_id'], runtime.owner)
        if (item['assignee_agent_id'] != dot['agent_id'] or item['run_id'] != message['run_id']
                or item.get('metadata', {}).get('workspace_id') != message['project_id']
                or op['run_id'] != message['run_id'] or op['state'] != 'QUEUED'
                or item['state'] not in {'PENDING', 'QUEUED', 'BLOCKED'}):
            return False
        allowed = {'model:invoke', 'web:send', 'web:attach'}
        if dot_manages_canvas(dot):
            allowed |= set(COORDINATOR_CAPABILITIES.values()) - {
                COORDINATOR_CAPABILITIES[k] for k in ('pause', 'resume', 'cancel')}
        capabilities = set(item.get('required_capabilities', [])) & allowed
        if message.get('coordinator_child'):
            capabilities.add('model:invoke')
        # Register derivation before creating any Grant, so a crash cannot orphan
        # an untracked authorization. Explicit revocation is never auto-undone.
        exists = track(runtime.control, runtime.owner, anchor, item['work_item_id'], dot['agent_id'], 'turn')
        if exists:
            return True
        for capability in sorted(capabilities):
            runtime.control.authorization_grant(runtime.owner, principal_type='agent', principal_id=dot['agent_id'],
                capability=capability, scope_type='work_item', scope_id=item['work_item_id'], ttl_s=3600)
        runtime.control.governance.activity(runtime.owner, 'shell.full_access.derived', 'ok', actor_type='system',
            payload={'source_work_item': anchor['work_item_id'], 'work_item_id': item['work_item_id'],
                'agent_id': dot['agent_id'], 'capabilities': sorted(capabilities)})
        return True


def prepare_resources(runtime, message, dot):
    """Bind configured local services to this conversation; never start a process."""
    with runtime.canvas._lock:
        anchor=source(runtime.control,runtime.owner,message['conversation_id'])
        if anchor is None:return
        host=runtime.canvas._machine_service()
        root=runtime.canvas.store.workspace(message['project_id'])['path']
        if not any(m['agent_id']==dot['agent_id'] and m['kind']=='terminal' for m in host.inventory(message['project_id'])):
            host.configure_terminal(workspace_id=message['project_id'],workspace_root=root,
                agent_id=dot['agent_id'],canvas=runtime.canvas)
        if not any(m['agent_id']==dot['agent_id'] and m['kind']=='workspace-files' for m in host.inventory(message['project_id'])):
            host.configure_workspace_files(workspace_id=message['project_id'],workspace_root=root,agent_id=dot['agent_id'])
        for machine in host.inventory(message['project_id']):
            if machine['agent_id']!=dot['agent_id'] or machine['kind'] not in {
                    'terminal','workspace-files','browser','git-worktrees','acp'}:continue
            caps=machine['capabilities']
            if not caps:continue
            identity=hashlib.sha256((anchor['work_item_id']+message['conversation_id']+machine['machine_id']).encode()).hexdigest()
            wid='full-resource-'+identity[:32]
            exists=track(runtime.control,runtime.owner,anchor,wid,dot['agent_id'],'resource')
            if exists:continue
            item=runtime.control.create_work_item(message['run_id'],runtime.owner,work_item_id=wid,
                parent_work_item_id=message['work_item_id'],assignee_agent_id=dot['agent_id'],
                objective='Recursos autorizados para este trabalho',required_capabilities=caps,
                metadata={'workspace_id':message['project_id'],'space_id':message['space_id'],
                    'conversation_id':message['conversation_id'],'machine_id':machine['machine_id'],
                    'full_source_work_item':anchor['work_item_id']})
            for cap in caps:
                runtime.control.authorization_grant(runtime.owner,principal_type='agent',principal_id=dot['agent_id'],
                    capability=cap,scope_type='work_item',scope_id=wid)
            if item['state']=='PENDING':runtime.control.transition_work_item(wid,runtime.owner,'RUNNING')
