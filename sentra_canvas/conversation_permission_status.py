"""Inspect a permission decision after ACK loss without dispatching its effect."""
from contextlib import closing
from .shell_requests import ShellHostRequests
from .store import Denied


def inspect_decision(canvas,pid,params):
    if set(params)!={'space_id','conversation_id','selector'}:raise ValueError('exact decision scope required')
    control=canvas._shell_service();owner=canvas._runtime().owner
    with closing(control.store.connect('shell')) as db:
        control.shell._entity(db,owner,pid,'conversation',params['conversation_id'],space_id=params['space_id'])
    selector=params['selector']
    if not isinstance(selector,dict) or set(selector)-{'action','request_key','fingerprint','conversation_id'}:raise ValueError('invalid decision selector')
    journal=ShellHostRequests(control,owner);stored=journal.intent(pid,selector.get('request_key'),selector.get('fingerprint'))
    if stored is None:return {'found':False,'resolved':False,'request_key':selector.get('request_key'),'automatic_retry':False}
    action=stored['action'];payload=stored['payload']
    if selector.get('action')!=action or action not in {'access_approve','access_reject','coordinator_approval_reply'}:raise Denied('unknown permission decision')
    if action=='coordinator_approval_reply':
        from sentra_runtime.coordinator_approvals import CoordinatorApprovalInbox
        original=CoordinatorApprovalInbox(control,owner).get(pid,payload['approval_id'])
        cid,sid=original['conversation_id'],original['space_id']
    else:cid,sid=payload['conversation_id'],payload['space_id']
    if (cid,sid)!=(params['conversation_id'],params['space_id']):raise Denied('decision belongs to another conversation')
    result=journal.inspect(pid,action,payload,selector['request_key'])
    recorded=result.get('result',{})
    if action=='coordinator_approval_reply' and recorded.get('state') in {'approved','rejected','expired'} and result.get('journal_state')=='committed':
        result['resolved']=True
    if action=='access_approve' and recorded.get('status')!='admission_failed' and recorded.get('result',{}).get('state') not in {'SUCCEEDED','FAILED','CANCELLED'}:
        result['resolved']=False
    return result
