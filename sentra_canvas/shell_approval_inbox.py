"""Authenticated, explicit host responses to durable coordinator requests."""
from sentra_runtime.coordinator_approvals import CoordinatorApprovalInbox
from .shell_permissions import ShellTurnPermissions
from .shell_requests import ShellHostRequests
from .store import Denied


def dispatch_coordinator_approval(canvas, project_id, action, params, request_key):
    control, owner = canvas._shell_service(), canvas._runtime().owner
    inbox = CoordinatorApprovalInbox(control, owner)
    if action == 'coordinator_approval_list':
        if set(params) - {'limit', 'space_id'}:
            raise ValueError('unsupported coordinator inbox fields')
        return inbox.list(project_id, limit=params.get('limit', 30))
    if action != 'coordinator_approval_reply' or set(params) - {'approval_id','answer','space_id'} or not {'approval_id','answer'} <= params.keys():
        raise ValueError('unsupported coordinator approval request')
    approval_id, answer = params['approval_id'], params['answer']
    if answer not in {'approve','reject'}:
        raise ValueError('explicit approve/reject choice required')
    if not isinstance(request_key, str) or not 8 <= len(request_key) <= 128:
        raise ValueError('durable owner response key required')
    row = inbox.get(project_id, approval_id)
    if params.get('space_id') is not None and params['space_id'] != row['space_id']:
        raise Denied('approval belongs to another Space')
    requests=ShellHostRequests(control,owner)
    def decide():
        requests.note_before_admission(project_id,request_key)
        current=inbox.get(project_id,approval_id)
        if current['state']!='pending':return {'approval_id':approval_id,'state':current['state'],'automatic_execution':False}
        if answer=='reject':return inbox.mark(project_id,approval_id,'rejected')
        # Exact protected parent scope; no user-selected capability or replay.
        permissions=ShellTurnPermissions(canvas)
        scope={'space_id':row['space_id'],'conversation_id':row['conversation_id'],'work_item_id':row['work_item_id']}
        dot,item,operation=permissions._scope(project_id,scope)
        if (item is None or dot['agent_id']!=row['agent_id'] or operation['operation_id']!=row['parent_operation_id'] or row['capability'] not in permissions._allowed(dot,item,operation)):
            raise Denied('coordinator request no longer matches its original turn')
        if item['state'] not in {'PENDING','QUEUED','BLOCKED','RUNNING'} or operation['state'] not in {'QUEUED','STARTING','RUNNING','WAITING_EXTERNAL'}:
            return {'approval_id':approval_id,'state':'expired','reason':'Original turn is no longer live; no Grant was created.','automatic_execution':False}
        requests.note_effect_possible(project_id,request_key)
        grant=permissions.dispatch(project_id,'turn_permission_grant',{**scope,'capabilities':[row['capability']],'ttl_seconds':300},'coordinator-grant:'+request_key)
        if grant.get('grant_created') is not True:return {'approval_id':approval_id,'state':'uncertain','automatic_execution':False}
        return {**inbox.mark(project_id,approval_id,'approved'),'grant_created':True,'permission_operation_id':grant.get('permission_operation_id'),'original_intent_replayed':False,'ttl_seconds':300}
    return requests.invoke(project_id,action,params,request_key,decide)
